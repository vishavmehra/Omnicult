"""Wikidata: entity resolution (wbsearchentities) and statement-backed related signals.

Resolution searches the query in English and the regional language and keeps every plausible candidate: an alias
collision (for example "Pongal", which is both a festival's label and another item's alias) stays ambiguous.
Related signals are retrieved statements only (kind "observed"): a seed entity's whitelisted statements, or, for a
`region:IN-XX` seed, the region's official languages and scripts plus festivals, dishes and tourist attractions
that Wikidata links to the region. Coverage is uneven: an empty result means "no statement found", not "no such link".
Wikidata data is CC0.
"""

import re
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from app.integrations.culture.base import (
    EntityCandidate,
    EntityResolution,
    SourceBase,
    SourceDescriptor,
    SourceValidationError,
    decide_resolution,
    now_utc,
)
from app.integrations.culture.http import HttpFetcher
from app.integrations.culture.regions import LANGUAGE_NAMES, REGIONS, region_for
from app.schemas.claims import ClaimDraft, ClaimScope, SourceRef

API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
ENTITY_URL = "https://www.wikidata.org/wiki/{}"
QID = re.compile(r"^Q[1-9]\d{0,12}$")
REGION_CODE = re.compile(r"^IN-[A-Z]{2}$")
LANGUAGE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})?$")

# Statements read for a seed entity: property id -> attribute name. Lookup data, not evidence.
PROPERTIES = {
    "P31": "instance_of", "P279": "subclass_of", "P361": "part_of", "P17": "country", "P131": "located_in",
    "P495": "country_of_origin", "P276": "location", "P1269": "facet_of",
}
# Classes whose region-linked members are listed for a region seed -> claim category.
# Scripts reported for a language: the ISO 15924 codes the product handles (contract section 2). Wikidata's P282 also
# lists historical and constructed scripts (Vatteluttu, Deseret, Braille), which would mislead a campaign team.
SCRIPT_CODES = frozenset({"Deva", "Taml", "Mlym", "Beng", "Latn"})
REGION_CLASSES = {"Q132241": "festival", "Q746549": "food", "Q570116": "custom"}
CLASS_LABEL = {"Q132241": "festival", "Q746549": "dish", "Q570116": "tourist attraction"}


class WikidataSource(SourceBase):
    name = "wikidata"
    descriptor = SourceDescriptor(
        name="wikidata", source_type="knowledge_graph",
        supported_operations=frozenset({"resolve_entity", "related_signals"}),
        scope="Global; queried for India and four states (ISO 3166-2:IN). Multilingual labels.",
        coverage_limitations=[
            "Coverage is uneven: many Indian festivals and foods carry no link to a state.",
            "A relationship is a statement someone entered; it does not show current popularity or demand.",
            "Descriptions and labels can be edited at any time; each claim records the retrieval time.",
        ],
        cache_policy={"resolve_entity": timedelta(days=7), "related_signals": timedelta(hours=24)},
    )

    def __init__(self, *, user_agent: str, timeout: float = 15.0, client: httpx.AsyncClient | None = None,
                 max_retries: int = 2, backoff_seconds: float = 0.5, sleep: Any = None) -> None:
        extra = {"sleep": sleep} if sleep is not None else {}
        self._qids: dict[str, str | None] = {}
        self.http = HttpFetcher("wikidata", user_agent=user_agent, timeout=timeout, client=client,
                                max_retries=max_retries, backoff_seconds=backoff_seconds, **extra)

    # ---- resolve_entity ----

    async def resolve_entity(self, query: str, *, language: str | None = None,
                             region_code: str | None = None) -> EntityResolution:
        query = query.strip()
        if not query:
            return EntityResolution(status="unresolved", query=query, language=language, region_code=region_code,
                                    retrieved_at=now_utc(), note="Empty query.")
        region = region_for(region_code) if region_code else None
        language = language if language and LANGUAGE.match(language) else None  # the value goes into the API request
        languages = list(dict.fromkeys([language or "en", *( [region.language] if region else [] ), "en"]))
        candidates: dict[str, EntityCandidate] = {}
        for lang in languages:
            data = await self.http.get_json(API, {
                "action": "wbsearchentities", "search": query, "language": lang, "uselang": lang, "type": "item",
                "limit": 7, "format": "json"}, operation="resolve_entity")
            for item in _results(data):
                candidates.setdefault(item["id"], _candidate(item, lang))
        return decide_resolution(query, list(candidates.values()), language=language, region_code=region_code,
                                 sources=[self.name], retrieved_at=now_utc())

    # ---- related_signals ----

    async def related_signals(self, entity_id: str, *, region_code: str, limit: int = 10) -> list[ClaimDraft]:
        if entity_id.startswith("region:"):
            code = entity_id.split(":", 1)[1].upper()
            if not REGION_CODE.match(code):
                return []
            return (await self._region_languages(code) + await self._region_links(code))[: max(limit, 0)]
        if not QID.match(entity_id):
            return []
        return await self._entity_statements(entity_id, region_code, limit)

    async def _entity_statements(self, qid: str, region_code: str, limit: int) -> list[ClaimDraft]:
        region = region_for(region_code)
        entity = (await self._entities([qid], "claims|labels|descriptions|info")).get(qid)
        if entity is None or "missing" in entity:
            return []
        claims = entity.get("claims", {})
        targets: list[tuple[str, str]] = []  # (property, target qid)
        for pid in PROPERTIES:
            for statement in claims.get(pid, []):
                value = (statement.get("mainsnak", {}).get("datavalue") or {}).get("value")
                if isinstance(value, dict) and QID.match(str(value.get("id", ""))):
                    targets.append((pid, value["id"]))
        if not targets:
            return []
        labels = await self._entities(sorted({t for _, t in targets}), "labels|descriptions")
        seed_label = _label(entity, qid)
        source = self._source(qid, seed_label, entity)
        out: list[ClaimDraft] = []
        for pid, target in targets:
            target_label = _label(labels.get(target, {}), target)
            linked = region is not None and target == region.wikidata_id
            out.append(ClaimDraft(
                # one attribute per (property, target): a multi-valued property is several facts, not one fact with two values
                subject=f"entity:{qid}", attribute=f"wikidata_{PROPERTIES[pid]}_{target.lower()}", category="custom",
                value={"property": pid, "target_id": target, "target_label": target_label, "region_link": linked},
                value_text=f"Wikidata: {seed_label} ({qid}) {PROPERTIES[pid].replace('_', ' ')} {target_label} ({target}).",
                scope=ClaimScope(region_code=region_code if linked else None),
                kind="observed", sources=[source], published_at=source.published_at, retrieved_at=source.retrieved_at))
        out.sort(key=lambda c: not c.value["region_link"])  # statements that name the region first
        return out[: max(limit, 0)]

    async def _region_languages(self, code: str) -> list[ClaimDraft]:
        query = (
            'SELECT ?region ?regionLabel ?lang ?langLabel ?iso ?script ?scriptLabel ?scriptCode ?mod WHERE { '
            f'?region wdt:P300 "{code}" . ?region wdt:P37 ?lang . OPTIONAL {{ ?lang wdt:P218 ?iso }} '
            'OPTIONAL { ?lang wdt:P282 ?script . OPTIONAL { ?script wdt:P506 ?scriptCode } } '
            'OPTIONAL { ?region schema:dateModified ?mod } '
            'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }')
        rows = await self._sparql(query, "related_signals")
        out: list[ClaimDraft] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            region_id, lang_id = _qid(row, "region"), _qid(row, "lang")
            region_label = _val(row, "regionLabel") or code
            lang_label, iso = _val(row, "langLabel") or lang_id, _val(row, "iso")
            retrieved = now_utc()
            region_source = SourceRef(
                source_type="wikidata", source_identifier=region_id, url=ENTITY_URL.format(region_id), title=region_label,
                publisher="Wikidata", published_at=_date(_val(row, "mod")), retrieved_at=retrieved, independence_group="wikimedia")
            if ("lang", lang_id) not in seen:
                seen.add(("lang", lang_id))
                out.append(ClaimDraft(
                    # no ISO 639-1 code to tell languages apart by scope: the language becomes the subject
                    subject=f"region:{code}" if iso else f"language:{lang_id}", attribute="official_language", category="language",
                    value=lang_label,  # a plain name, so the same fact from another source compares equal
                    value_text=f"Wikidata lists {lang_label} ({lang_id}) as an official language of {region_label} (property P37).",
                    scope=ClaimScope(region_code=code, language=iso), kind="observed", sources=[region_source],
                    published_at=region_source.published_at, retrieved_at=retrieved))
            script_id = _qid(row, "script") if "script" in row else None
            if script_id and _val(row, "scriptCode") in SCRIPT_CODES and ("script", f"{lang_id}:{script_id}") not in seen:
                seen.add(("script", f"{lang_id}:{script_id}"))
                script_label, script_code = _val(row, "scriptLabel") or script_id, _val(row, "scriptCode")
                lang_source = SourceRef(
                    source_type="wikidata", source_identifier=lang_id, url=ENTITY_URL.format(lang_id), title=lang_label,
                    publisher="Wikidata", retrieved_at=retrieved, independence_group="wikimedia")
                out.append(ClaimDraft(
                    subject=f"language:{iso or lang_id}", attribute=f"writing_system_{script_code.lower()}", category="script",
                    value={"script": script_label, "iso15924": script_code, "wikidata_id": script_id},
                    value_text=f"Wikidata lists {script_label} as a writing system of {lang_label} (property P282).",
                    scope=ClaimScope(region_code=code, language=iso), kind="observed", sources=[lang_source],
                    retrieved_at=retrieved))
        return out

    async def _region_links(self, code: str) -> list[ClaimDraft]:
        qid = await self._region_qid(code)
        if qid is None:
            return []
        classes = " ".join(f"wd:{c}" for c in REGION_CLASSES)
        # The region is a constant in every pattern and there is no BIND or VALUES on the property: both made WDQS time out.
        query = (
            'SELECT DISTINCT ?item ?itemLabel ?itemDescription ?cls WHERE { '
            f'VALUES ?cls {{ {classes} }} ?item wdt:P31/wdt:P279* ?cls . '
            f'{{ ?item wdt:P131 wd:{qid} }} UNION {{ ?item wdt:P495 wd:{qid} }} UNION {{ ?item wdt:P276 wd:{qid} }} '
            'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } } LIMIT 60')
        rows = await self._sparql(query, "related_signals")
        retrieved, out, seen = now_utc(), [], set()
        for row in rows:
            qid, label = _qid(row, "item"), _val(row, "itemLabel")
            if not label or QID.match(label) or qid in seen:  # an unlabelled item cannot be shown to a reader
                continue
            seen.add(qid)
            cls = _qid(row, "cls")
            description = _val(row, "itemDescription")
            source = SourceRef(
                source_type="wikidata", source_identifier=qid, url=ENTITY_URL.format(qid), title=label, publisher="Wikidata",
                retrieved_at=retrieved, independence_group="wikimedia")
            out.append(ClaimDraft(
                subject=f"entity:{qid}", attribute="linked_to_region", category=REGION_CLASSES[cls],
                value={"entity_id": qid, "label": label, "description": description, "class": CLASS_LABEL[cls], "via_properties": "P131, P495 or P276"},
                value_text=(f"Wikidata links the {CLASS_LABEL[cls]} {label} ({qid}) to {REGIONS[code].name if code in REGIONS else code} "
                            f"(located in, country of origin or location statement)."),
                scope=ClaimScope(region_code=code), kind="observed", sources=[source], retrieved_at=retrieved))
        return out

    async def _region_qid(self, code: str) -> str | None:
        """The item whose P300 (ISO 3166-2 code) is `code`: known for the demo states, looked up (and kept) otherwise."""
        if code in REGIONS:
            return REGIONS[code].wikidata_id
        if code not in self._qids:
            rows = await self._sparql(f'SELECT ?r WHERE {{ ?r wdt:P300 "{code}" }} LIMIT 2', "related_signals")
            ids = {_qid(r, "r") for r in rows}
            self._qids[code] = ids.pop() if len(ids) == 1 else None  # two items for one code: do not guess
        return self._qids[code]

    # ---- shared ----

    async def _entities(self, ids: list[str], props: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for i in range(0, len(ids), 50):  # the API accepts at most 50 ids per request
            data = await self.http.get_json(API, {
                "action": "wbgetentities", "ids": "|".join(ids[i:i + 50]), "props": props,
                "languages": "|".join(LANGUAGE_NAMES), "format": "json"}, operation="related_signals")
            if not isinstance(data, dict) or not isinstance(data.get("entities"), dict):
                raise SourceValidationError(self.name, "related_signals", "wbgetentities returned no entities object")
            out.update(data["entities"])
        return out

    async def _sparql(self, query: str, operation: str) -> list[dict[str, Any]]:
        # WDQS answers in a few seconds but can take longer under load; its own limit is 60 s.
        data = await self.http.get_json(SPARQL, {"query": query, "format": "json"}, operation=operation, timeout=max(self.http.timeout, 30.0),
                                        headers={"Accept": "application/sparql-results+json"})
        try:
            return data["results"]["bindings"]
        except (KeyError, TypeError) as exc:
            raise SourceValidationError(self.name, operation, "SPARQL response has no results.bindings") from exc

    def _source(self, qid: str, label: str, entity: dict[str, Any]) -> SourceRef:
        return SourceRef(
            source_type="wikidata", source_identifier=qid, url=ENTITY_URL.format(qid), title=label, publisher="Wikidata",
            published_at=_date(entity.get("modified")), retrieved_at=now_utc(), independence_group="wikimedia")


# ---- parsing helpers (raise SourceValidationError on a malformed response) ----


def _results(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or not isinstance(data.get("search"), list):
        raise SourceValidationError("wikidata", "resolve_entity", "wbsearchentities returned no search list")
    return [item for item in data["search"] if isinstance(item, dict) and QID.match(str(item.get("id", "")))]


def _candidate(item: dict[str, Any], language: str) -> EntityCandidate:
    match = item.get("match") or {}
    kind = match.get("type")
    return EntityCandidate(
        entity_id=item["id"], label=item.get("label") or item["id"], description=item.get("description"),
        language=match.get("language") or language, match_type=kind if kind in ("label", "alias") else "other",
        matched_text=match.get("text"), url=ENTITY_URL.format(item["id"]), source="wikidata")


def _label(entity: dict[str, Any], default: str) -> str:
    labels = entity.get("labels") or {}
    pick = labels.get("en") or next(iter(labels.values()), None)
    return pick["value"] if pick else default


def _val(row: dict[str, Any], key: str) -> str | None:
    return (row.get(key) or {}).get("value")


def _qid(row: dict[str, Any], key: str) -> str:
    value = _val(row, key) or ""
    return value.rsplit("/", 1)[-1]


def _date(value: str | None) -> date | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date() if value else None
    except ValueError:
        return None
