"""Census of India 2011, table C-16 (population by mother tongue): language mix for the four demo states.

Data comes from the official state workbooks in the Census Digital Library, reduced to a small JSON file by
`scripts/culture_build_census.py`. It is a 2011 snapshot: every claim carries scope period "2011" and says so in its
text, and it must never be presented as the current language mix. Mother tongue is the language a person reports as
spoken in childhood; it is not proficiency, media consumption or language preference today.
"""

import json
import re
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.integrations.culture.base import SourceBase, SourceDescriptor
from app.integrations.culture.regions import region_for
from app.schemas.claims import ClaimDraft, ClaimScope, SourceRef

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "census_2011_languages.json"


@lru_cache(maxsize=1)
def load_census() -> dict[str, Any]:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


class CensusSource(SourceBase):
    name = "census_2011"
    descriptor = SourceDescriptor(
        name="census_2011", source_type="public_dataset", supported_operations=frozenset({"audience_facts"}),
        scope="IN-MH, IN-TN, IN-KL, IN-WB; mother-tongue shares; Census of India 2011 (table C-16).",
        coverage_limitations=[
            "2011 data: more than a decade old, never current; migration and urbanisation have changed language use since.",
            "Mother tongue, not proficiency, media language or purchase language.",
            "State level only; no city tier or age split.",
            "Languages below 0.5% of a state are folded into other_speakers unless they are one of mr, ta, ml, bn, hi, en.",
        ],
        cache_policy={"audience_facts": timedelta(days=30)},
    )

    async def audience_facts(self, region_code: str) -> list[ClaimDraft]:
        region = region_for(region_code)
        data = load_census()
        state = data["states"].get(region.code) if region else None
        if state is None:
            return []
        retrieved = datetime.combine(date.fromisoformat(data["retrieved_on"]), time.min, tzinfo=UTC)
        population = state["population"]
        languages = state["languages"]
        scope = lambda iso: ClaimScope(region_code=region.code, language=iso, period="2011")  # noqa: E731
        out: list[ClaimDraft] = []
        # A language without an ISO 639-1 code cannot be told apart by scope.language, so its claims are about
        # `language:<name>` instead of the region: otherwise two languages would look like one claim with two values.
        subject = lambda iso, name: f"region:{region.code}" if iso else f"language:{re.sub('[^a-z0-9]+', '_', name.casefold()).strip('_')}"  # noqa: E731
        row_sources: dict[str, SourceRef] = {}
        for lang in languages:
            speakers, name, iso = lang["speakers"], lang["name"], lang["iso639_1"]
            source = SourceRef(
                source_type="census_2011", source_identifier=f"{state['reference_id']}:{lang['mother_tongue_code']}",
                url=state["catalog_url"], title=state["citation"], publisher=data["publisher"],
                published_at=date.fromisoformat(state["catalog_created"]),  # the library entry date; the data year is in scope.period
                retrieved_at=retrieved, independence_group="census_2011",
                excerpt=(f"Table C0116, state {region.census_state_code} {state['state_name'].upper()}, mother tongue "
                         f"{lang['mother_tongue_code']} {name.upper()}: total persons {speakers}"))
            row_sources[lang["mother_tongue_code"]] = source
            out.append(ClaimDraft(
                subject=subject(iso, name), attribute="mother_tongue_speakers", category="language", value=speakers,
                value_text=f"In the 2011 census, {speakers:,} people in {region.name} reported {name} as their mother tongue.",
                scope=scope(iso), kind="observed", sources=[source], retrieved_at=retrieved))
            share = round(100 * speakers / population, 2)
            out.append(ClaimDraft(
                subject=subject(iso, name), attribute="language_share", category="language", value=share,
                value_text=(f"In the 2011 census, {name} was the mother tongue of {share}% of {region.name}'s population "
                            f"({speakers:,} of {population:,}). A 2011 snapshot, not a current figure."),
                scope=scope(iso), kind="calculated", sources=[source], retrieved_at=retrieved))
        top = max(languages, key=lambda lang: lang["speakers"])
        out.append(ClaimDraft(
            subject=f"region:{region.code}", attribute="principal_language", category="language", value=top["name"],
            value_text=(f"{top['name']} was the largest mother tongue in {region.name} in the 2011 census "
                        f"({round(100 * top['speakers'] / population, 2)}%)."),
            scope=scope(top["iso639_1"]), kind="calculated", retrieved_at=retrieved,
            sources=[row_sources[top["mother_tongue_code"]]]))
        return out
