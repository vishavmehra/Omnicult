"""Category Shelf discovery: which brands and products Wikidata records in a category, and which state it links them to.

Everything returned is a Wikidata statement or a count of them: a label, a description, an inception year, a headquarters
or origin place, the number of Wikipedia language editions. Nothing is estimated and nothing is filled in. A field Wikidata
does not hold stays `None` and the reader sees "not recorded". Wikidata does not record prices, sales, share or advertising,
so none of those is ever produced here.

Discovery uses the free Wikidata API only (no SPARQL, which times out on the place hierarchy): a full-text search per pack
term restricted to India, one batch fetch of the items, one for the labels of their classes, and a walk up the
located-in chain of their places. About a dozen requests, through `HttpFetcher` (User-Agent, retries, cool-down).
An item is kept only if its class says it is a business or a product and its label and description name the category; the
rest are returned in `excluded` with the reason, so a reader can see what was left out and why.
"""

import asyncio
import json
import re
import time
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from app.integrations.culture.base import (
    CallLogRecord,
    CultureSourceError,
    now_utc,
    request_hash,
)
from app.integrations.culture.http import HttpFetcher
from app.integrations.culture.regions import REGIONS

API = "https://www.wikidata.org/w/api.php"
ENTITY_URL = "https://www.wikidata.org/wiki/{}"
INDIA = "Q668"
QID = re.compile(r"^Q[1-9]\d{0,12}$")
PACKS_FILE = Path(__file__).resolve().parent / "data" / "category_packs.json"
SEARCH_LIMIT = 25  # per search term; the API allows 50 but a shelf is a short list
MAX_CANDIDATES = 60
MAX_PLACE_DEPTH = 4
NOT_A_WIKIPEDIA = frozenset({"commonswiki", "specieswiki", "metawiki", "wikidatawiki", "mediawikiwiki", "outreachwiki"})
CACHE_TTL = timedelta(hours=24)

# What an item's class (instance of) must say for it to count as a business or a product. Words, not ids: Wikidata has
# hundreds of company subclasses and a fixed id list would silently miss most of them.
BRAND_CLASS_WORDS = ("company", "business", "brand", "chain", "enterprise", "manufactur", "retail", "shop", "store", "restaurant",
                     "corporation", "firm", "franchise", "startup", "producer", "dairy", "bakery", "plantation", "jeweller")
PRODUCT_CLASS_WORDS = ("dish", "dessert", "sweet", "snack", "confection", "food", "beverage", "drink", "garment", "clothing",
                       "jewel", "textile", "dress", "tea", "coffee", "ornament")


class CategoryTopic(BaseModel):
    entity_id: str
    label: str


class CategoryPack(BaseModel):
    key: str
    label: str
    keywords: list[str]
    search_terms: list[str]
    include_terms: list[str]
    exclude_terms: list[str]
    topics: list[CategoryTopic]


@lru_cache(maxsize=1)
def packs() -> tuple[CategoryPack, ...]:
    return tuple(CategoryPack.model_validate(p) for p in json.loads(PACKS_FILE.read_text(encoding="utf-8"))["packs"])


def pack_by_key(key: str | None) -> CategoryPack | None:
    return next((p for p in packs() if p.key == key), None)


def match_pack(text: str | None) -> CategoryPack | None:
    """The pack whose keywords the category text names most often; None when none is named (nothing is guessed)."""
    lowered = (text or "").casefold()
    # a keyword matches at the start of a word ("sweet" in "sweets"), never inside one ("tea" in "instead")
    scored = [(sum(1 for k in p.keywords if re.search(r"\b" + rf"{re.escape(k.casefold())}", lowered)), -i, p) for i, p in enumerate(packs())]
    best = max(scored, default=(0, 0, None))
    return best[2] if best[0] > 0 else None


class ShelfPlace(BaseModel):
    entity_id: str
    label: str


class ShelfEntity(BaseModel):
    """One brand or product as Wikidata records it. Every value is a statement or a count of statements."""

    entity_id: str
    label: str
    description: str | None
    kind: str  # brand | product
    classes: list[str]  # labels of "instance of", as Wikidata words them
    website: str | None
    founded_year: int | None
    places: list[ShelfPlace]  # headquarters (brand) or location and origin (product), as recorded
    region_codes: list[str]  # the mapped states those places sit in, by Wikidata's located-in chain
    region_basis: str | None  # for example "headquarters Nagpur, which Wikidata places in Maharashtra"
    wikipedia_languages: int
    sitelinks: dict[str, str]  # language -> article title, for the editions the product reads
    wikidata_url: str


class ShelfExcluded(BaseModel):
    entity_id: str
    label: str
    reason: str


class ShelfDiscovery(BaseModel):
    pack_key: str
    entities: list[ShelfEntity]
    excluded: list[ShelfExcluded]
    gaps: list[str]
    calls: list[CallLogRecord]
    retrieved_at: datetime


def _ids(entity: dict[str, Any], prop: str) -> list[str]:
    out = []
    for statement in (entity.get("claims") or {}).get(prop, []):
        value = (statement.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and QID.match(str(value.get("id", ""))):
            out.append(value["id"])
    return list(dict.fromkeys(out))


def _classes_of(entity: dict[str, Any]) -> list[str]:
    """What the item is, by Wikidata: its classes (instance of), then the classes it specialises (subclass of). Indian dishes
    are mostly entered with the second."""
    return list(dict.fromkeys([*_ids(entity, "P31"), *_ids(entity, "P279")]))


def _text(entity: dict[str, Any], prop: str) -> str | None:
    for statement in (entity.get("claims") or {}).get(prop, []):
        value = (statement.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _year(entity: dict[str, Any], prop: str) -> int | None:
    for statement in (entity.get("claims") or {}).get(prop, []):
        value = (statement.get("mainsnak") or {}).get("datavalue", {}).get("value")
        stamp = value.get("time") if isinstance(value, dict) else None
        match = re.match(r"^[+-]?(\d{4})-", stamp or "")
        if match:
            return int(match.group(1))
    return None


def _label(entity: dict[str, Any], fallback: str = "") -> str:
    return ((entity.get("labels") or {}).get("en") or {}).get("value") or fallback


def _description(entity: dict[str, Any]) -> str | None:
    return ((entity.get("descriptions") or {}).get("en") or {}).get("value") or None


def wikipedia_sitelinks(entity: dict[str, Any]) -> dict[str, str]:
    """language -> article title for every Wikipedia edition (not Commons, Species or Wikidata itself)."""
    out: dict[str, str] = {}
    for site, link in (entity.get("sitelinks") or {}).items():
        if site.endswith("wiki") and site not in NOT_A_WIKIPEDIA and isinstance(link, dict) and link.get("title"):
            out[site[: -len("wiki")].replace("_", "-")] = link["title"]
    return out


def relevance(pack: CategoryPack, label: str, description: str | None, classes: list[str]) -> tuple[str | None, str]:
    """(kind, reason). kind is brand, product or None; the reason says why an item is kept or left out."""
    text = f"{label} {description or ''}".casefold()
    if any(term in text for term in pack.exclude_terms):
        return None, "Its description names something other than a business or a product."
    class_text = " ".join(classes).casefold()
    kind = ("brand" if any(w in class_text for w in BRAND_CLASS_WORDS)
            else "product" if any(w in class_text for w in PRODUCT_CLASS_WORDS) else None)
    if kind is None:
        return None, f"Its class ({', '.join(classes) or 'none recorded'}) is not a business or a product."
    if not description:
        return None, "It has no description, so its relevance to the category cannot be checked."
    if not any(term in text for term in pack.include_terms):
        return None, "Its label and description do not name the category."
    return kind, "A business or product whose description names the category."


class WikidataShelfSource:
    name = "wikidata"
    operation = "category_shelf"

    def __init__(self, *, user_agent: str, timeout: float = 15.0, client: httpx.AsyncClient | None = None,
                 max_retries: int = 2, backoff_seconds: float = 0.5, sleep: Any = None, gap_seconds: float = 1.0) -> None:
        extra = {"sleep": sleep} if sleep is not None else {}
        self.gap, self._asked = gap_seconds, False  # Wikidata answers 429 to a burst: a short gap between requests keeps us under it
        self.http = HttpFetcher("wikidata", user_agent=user_agent, timeout=timeout, client=client,
                                max_retries=max_retries, backoff_seconds=backoff_seconds, **extra)

    async def discover(self, pack: CategoryPack) -> ShelfDiscovery:
        calls: list[CallLogRecord] = []
        gaps: list[str] = []

        async def get(params: dict[str, Any], what: str) -> dict[str, Any] | None:
            if self._asked and self.gap > 0:
                await asyncio.sleep(self.gap)
            self._asked = True
            started = time.perf_counter()
            digest = request_hash(self.name, self.operation, params)
            try:
                data = await self.http.get_json(API, {**params, "format": "json"}, operation=self.operation)
                if not isinstance(data, dict):
                    raise CultureSourceError(self.name, self.operation, "response is not a JSON object")
            except CultureSourceError as exc:
                calls.append(_record(digest, started, "error", error=exc))
                gaps.append(f"Wikidata {what} failed ({exc.kind}); what it would have added is missing.")
                return None
            calls.append(_record(digest, started, "ok"))
            return data

        found: dict[str, None] = {}
        for term in pack.search_terms:
            # a business has a country (P17); a product has a country of origin (P495): one search covers both
            data = await get({"action": "query", "list": "search", "srsearch": f"{term} haswbstatement:P17={INDIA}|P495={INDIA}",
                              "srnamespace": 0, "srlimit": SEARCH_LIMIT, "srprop": ""}, f"search for '{term}'")
            for hit in ((data or {}).get("query") or {}).get("search", []):
                if isinstance(hit, dict) and QID.match(str(hit.get("title", ""))):
                    found.setdefault(hit["title"])
        candidates = list(found)[:MAX_CANDIDATES]
        if len(found) > MAX_CANDIDATES:
            gaps.append(f"Wikidata returned {len(found)} candidates; the first {MAX_CANDIDATES} were read.")
        entities = await self._entities(candidates, "claims|labels|descriptions|sitelinks", get)
        class_ids = sorted({c for e in entities.values() for c in _classes_of(e)})
        class_labels = {k: _label(v, k) for k, v in (await self._entities(class_ids, "labels", get)).items()}

        kept: list[tuple[dict[str, Any], str, list[str]]] = []
        excluded: list[ShelfExcluded] = []
        for qid in candidates:
            entity = entities.get(qid)
            if entity is None or "missing" in entity:
                continue
            classes = [class_labels.get(c, c) for c in _classes_of(entity)]
            kind, reason = relevance(pack, _label(entity, qid), _description(entity), classes)
            if kind is None:
                excluded.append(ShelfExcluded(entity_id=qid, label=_label(entity, qid), reason=reason))
            else:
                kept.append((entity, kind, classes))

        place_ids = {p for e, kind, _ in kept for p in _place_ids(e, kind)}
        places = await self._places(place_ids, get)
        out = [self._shape(e, kind, classes, places) for e, kind, classes in kept]
        out.sort(key=lambda x: (-x.wikipedia_languages, x.label.casefold(), x.entity_id))
        return ShelfDiscovery(pack_key=pack.key, entities=out, excluded=excluded, gaps=gaps, calls=calls, retrieved_at=now_utc())

    async def _entities(self, ids: list[str], props: str, get: Any) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for i in range(0, len(ids), 50):
            data = await get({"action": "wbgetentities", "ids": "|".join(ids[i:i + 50]), "props": props, "languages": "en"},
                             "entity read")
            found = (data or {}).get("entities")
            if isinstance(found, dict):
                out.update({k: v for k, v in found.items() if isinstance(v, dict)})
        return out

    async def _places(self, first: set[str], get: Any) -> dict[str, dict[str, Any]]:
        """Each place and its located-in ancestors, a level per request, up to MAX_PLACE_DEPTH levels."""
        seen: dict[str, dict[str, Any]] = {}
        todo = sorted(first)
        for _ in range(MAX_PLACE_DEPTH):
            if not todo:
                break
            got = await self._entities(todo, "claims|labels", get)
            seen.update(got)
            todo = sorted({p for e in got.values() for p in _ids(e, "P131")} - set(seen))
        return seen

    def _shape(self, entity: dict[str, Any], kind: str, classes: list[str], places: dict[str, dict[str, Any]]) -> ShelfEntity:
        qid = entity.get("id", "")
        links = wikipedia_sitelinks(entity)
        mapped = {r.wikidata_id: code for code, r in REGIONS.items()}
        placed = [ShelfPlace(entity_id=p, label=_label(places.get(p, {}), p)) for p in _place_ids(entity, kind)]
        regions: list[str] = []
        basis: list[str] = []
        for place in placed:
            hit = _ancestor_region(place.entity_id, places, mapped)
            if hit:
                regions.append(hit[0])
                basis.append(f"{'headquarters' if kind == 'brand' else 'recorded place'} {place.label}"
                             f"{'' if hit[1] == place.entity_id else ', which Wikidata places in ' + REGIONS[hit[0]].name}")
        return ShelfEntity(
            entity_id=qid, label=_label(entity, qid), description=_description(entity), kind=kind, classes=classes,
            website=_text(entity, "P856"), founded_year=_year(entity, "P571"), places=placed,
            region_codes=list(dict.fromkeys(regions)), region_basis="; ".join(dict.fromkeys(basis)) or None,
            wikipedia_languages=len(links), sitelinks={k: v for k, v in links.items() if k in {"en", "hi", "mr", "ta", "ml", "bn"}},
            wikidata_url=ENTITY_URL.format(qid))


def _place_ids(entity: dict[str, Any], kind: str) -> list[str]:
    ids = _ids(entity, "P159") if kind == "brand" else [*_ids(entity, "P131"), *_ids(entity, "P276"), *_ids(entity, "P495")]
    return [p for p in dict.fromkeys(ids) if p != INDIA]


def _ancestor_region(start: str, places: dict[str, dict[str, Any]], mapped: dict[str, str]) -> tuple[str, str] | None:
    """The mapped state a place sits in (itself or an ancestor by located-in), with the place that matched."""
    frontier, seen = [start], set()
    for _ in range(MAX_PLACE_DEPTH + 1):
        nxt: list[str] = []
        for pid in frontier:
            if pid in mapped:
                return mapped[pid], pid
            if pid in seen:
                continue
            seen.add(pid)
            nxt.extend(_ids(places.get(pid, {}), "P131"))
        frontier = nxt
    return None


def _record(digest: str, started: float, status: str, *, error: CultureSourceError | None = None) -> CallLogRecord:
    return CallLogRecord(
        source="wikidata", operation="category_shelf", request_hash=digest, retrieved_at=now_utc(), status=status,  # type: ignore[arg-type]
        cached=False, result_count=0, duration_ms=int((time.perf_counter() - started) * 1000),
        error_type=error.kind if error else None, error=str(error)[:300] if error else None)
