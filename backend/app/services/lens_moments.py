"""Moment Calendar sources that are data, not claims.

- Each state's public-holiday list: python-holidays, computed offline for any state and year (the same package the builds use).
- Google Calendar's public "Holidays in India" calendar, read through the Calendar API with an API key: national public
  holidays and observances (festivals, birthdays, new years) with Google's own tentative flag. Stored in
  `lens_calendar_events`, refreshed by the daily signals job; a live read pulls a year only when none is stored or the stored
  copy is older than a week. Demo campaigns read a recording and make no call.
- What a moment is: a short description from the Google Knowledge Graph Search API, recorded by
  `scripts/record_lens_calendar.py` (Wikipedia text, CC BY-SA). A result is kept only when it names the moment itself, so a
  query such as "Republic Day" that returns another country's republic is dropped, never shown.

Nothing here is estimated. A date, a name, a kind and a description are copied from their source with the source named.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.integrations.culture.adapters.holidays_calendar import PACKAGE_SUBDIVISION, PYPI_URL
from app.integrations.culture.regions import subdivision
from app.reference import india
from app.schemas import lens as v

logger = logging.getLogger(__name__)

CALENDAR_ID = "en.indian#holiday@group.v.calendar.google.com"
CALENDAR_NAME = "Holidays in India"
CALENDAR_PAGE = "https://calendar.google.com/calendar/embed?src=en.indian%23holiday%40group.v.calendar.google.com"
API = "https://www.googleapis.com/calendar/v3/calendars/{}/events"
KG_API = "https://kgsearch.googleapis.com/v1/entities:search"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "lens_calendar"
RECORDED_FILE = FIXTURES / "google_holidays.json"
NOTES_FILE = Path(__file__).resolve().parents[1] / "integrations" / "culture" / "data" / "moment_notes.json"
MAX_AGE = timedelta(days=7)
RETRY_AFTER_FAILURE = 600.0  # seconds a live read leaves the Calendar API alone after a failed pull
TIMEOUT = 15.0
_LOCK = asyncio.Lock()
_BACKOFF: dict[int, float] = {}  # year -> monotonic time before which a live read does not pull it again


class CalendarSourceError(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Event:
    """One Google Calendar event as the moment calendar uses it."""

    event_id: str
    day: date
    name: str
    kind: str  # public_holiday | observance
    tentative: bool
    url: str | None
    region_code: str | None  # a state the event name points to, e.g. "Bahag Bihu (Assam)"
    retrieved_at: datetime | None


# --- names --------------------------------------------------------------------------------------------------------


def name_key(name: str) -> str:
    """Comparable form of a moment name: lower case, no parenthetical, letters and digits only."""
    text = re.sub(r"\([^)]*\)", " ", name.casefold())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


_STATE_WORDS = {name_key(r.name): r.code for r in india.REGIONS} | {"bengal": "IN-WB", "orissa": "IN-OD"}


def region_hint(name: str) -> str | None:
    """The state a name's parenthetical points to ("Vaisakhadi (Bengal)" -> IN-WB), or None."""
    for inner in re.findall(r"\(([^)]*)\)", name):
        code = _STATE_WORDS.get(name_key(inner))
        if code:
            return code
    return None


# --- python-holidays ------------------------------------------------------------------------------------------------


@lru_cache(maxsize=512)
def state_holidays(code: str, year: int) -> tuple[tuple[date, str], ...]:
    """(date, name) for every public holiday on the state's list in python-holidays; empty where the package has no list."""
    if not 1950 <= year <= 2100:
        return ()
    import holidays

    sub = PACKAGE_SUBDIVISION.get(subdivision(code), subdivision(code))
    if sub not in holidays.India.subdivisions:
        return ()
    calendar = holidays.India(subdiv=sub, years=year)
    return tuple((day, name) for day, joined in sorted(calendar.items()) for name in joined.split("; "))


def holidays_version() -> str:
    return metadata.version("holidays")


def holidays_source() -> v.LensMomentSource:
    version = holidays_version()
    return v.LensMomentSource(label=f"python-holidays {version}, the state's public-holiday list", url=PYPI_URL,
                              publisher="python-holidays contributors", retrieved_at=None)


# --- Google Calendar ------------------------------------------------------------------------------------------------


def _iso(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def parse_items(items: list[dict[str, Any]], retrieved_at: datetime | None) -> list[Event]:
    """Calendar API items -> events. An item without an all-day date or a name is skipped; the kind is Google's own first
    description line ("Public holiday" or "Observance")."""
    out: list[Event] = []
    for item in items:
        raw_day, summary = (item.get("start") or {}).get("date"), str(item.get("summary") or "").strip()
        if not raw_day or not summary or item.get("status") == "cancelled":
            continue
        description = str(item.get("description") or "")
        first = description.split("\n", 1)[0].strip().casefold()
        tentative = "tentative" in summary.casefold() or "tentative" in description.casefold()
        name = re.sub(r"\s*\(tentative\)\s*", " ", summary, flags=re.I).strip()
        out.append(Event(
            event_id=str(item.get("id") or f"{raw_day}:{name}"), day=date.fromisoformat(raw_day), name=name,
            kind="public_holiday" if first.startswith("public holiday") else "observance", tentative=tentative,
            url=item.get("htmlLink"), region_code=region_hint(summary), retrieved_at=retrieved_at))
    return out


async def fetch_year(year: int, key: SecretStr | str | None, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    """Every event of the calendar in `year`: one request (single events, at most 2,500). The key goes only in the query."""
    secret = key.get_secret_value() if isinstance(key, SecretStr) else key
    if not secret:
        raise CalendarSourceError("not_configured", "GOOGLE_PUBLIC_API_KEY is not set.")
    params = {"key": secret, "timeMin": f"{year}-01-01T00:00:00Z", "timeMax": f"{year + 1}-01-01T00:00:00Z", "singleEvents": "true",
              "orderBy": "startTime", "maxResults": 2500}
    own = client is None
    http = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        response = await http.get(API.format(quote(CALENDAR_ID, safe="")), params=params)
    except httpx.TimeoutException:
        raise CalendarSourceError("timeout", "Google Calendar did not answer in time.") from None
    except httpx.HTTPError:
        raise CalendarSourceError("network", "Google Calendar could not be reached.") from None
    finally:
        if own:
            await http.aclose()
    if response.status_code in (401, 403):
        raise CalendarSourceError("auth", f"Google Calendar refused the key ({response.status_code}).")
    if response.status_code == 429:
        raise CalendarSourceError("rate_limited", "Google Calendar's quota is used up.")
    if response.status_code != 200:
        raise CalendarSourceError("http", f"Google Calendar answered {response.status_code}.")
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise CalendarSourceError("validation", "The answer is not a Calendar event list.")
    return [i for i in data["items"] if isinstance(i, dict)]


async def refresh_google(s: AsyncSession, years: list[int], *, key: SecretStr | str | None = None,
                         client: httpx.AsyncClient | None = None, now: datetime | None = None) -> dict[str, int]:
    """Replace the stored events of each year with the calendar's current list. The caller commits. Raises
    CalendarSourceError; a year that failed keeps its stored rows."""
    key = key if key is not None else get_settings().google_public_api_key
    now = now or utcnow()
    stored: dict[str, int] = {}
    for year in years:
        events = parse_items(await fetch_year(year, key, client), now)
        await s.execute(delete(m.LensCalendarEvent).where(m.LensCalendarEvent.calendar_id == CALENDAR_ID, m.LensCalendarEvent.year == year))
        s.add_all(m.LensCalendarEvent(
            calendar_id=CALENDAR_ID, event_id=e.event_id, year=year, day=e.day, name=e.name, kind=e.kind, tentative=e.tentative,
            url=e.url, source_updated_at=None, retrieved_at=now) for e in events)
        stored[str(year)] = len(events)
    return stored


async def refresh_scheduled() -> dict[str, int]:
    """The daily signals job: this year and the next, in its own transaction."""
    year = utcnow().year
    async with _LOCK, session() as s, s.begin():
        return await refresh_google(s, [year, year + 1])


@lru_cache(maxsize=1)
def recorded() -> dict[str, Any]:
    return json.loads(RECORDED_FILE.read_text(encoding="utf-8"))


def recorded_at() -> datetime:
    return datetime.combine(date.fromisoformat(recorded()["recorded_on"]), datetime.min.time(), tzinfo=UTC)


def _stored_events(rows: list[m.LensCalendarEvent]) -> list[Event]:
    return [Event(event_id=r.event_id, day=r.day, name=r.name, kind=r.kind, tentative=r.tentative, url=r.url,
                  region_code=region_hint(r.name), retrieved_at=r.retrieved_at) for r in rows]


async def _rows(year: int) -> list[m.LensCalendarEvent]:
    async with read_session() as s:
        return list((await s.execute(select(m.LensCalendarEvent).where(
            m.LensCalendarEvent.calendar_id == CALENDAR_ID, m.LensCalendarEvent.year == year).order_by(m.LensCalendarEvent.day))).scalars())


async def google_events(mode: str, year: int) -> list[Event]:
    """The calendar's events of `year`. Demo: the recording. Live: the stored copy, pulled first when none is stored or it is
    older than a week (and a key is configured); a failed pull serves what is stored and is not retried for ten minutes."""
    if mode == "demo":
        return parse_items(recorded()["years"].get(str(year), []), recorded_at())
    rows = await _rows(year)
    stale = not rows or utcnow() - max(r.retrieved_at for r in rows) > MAX_AGE
    if stale and get_settings().google_public_api_key and _BACKOFF.get(year, 0.0) <= time.monotonic():
        try:
            async with _LOCK:
                rows = await _rows(year)  # another request may have pulled it while this one waited
                if not rows or utcnow() - max(r.retrieved_at for r in rows) > MAX_AGE:
                    async with session() as s, s.begin():
                        await refresh_google(s, [year])
                    rows = await _rows(year)
        except CalendarSourceError as error:
            logger.warning("moment calendar: Google Calendar pull for %s failed (%s)", year, error.kind)
            _BACKOFF[year] = time.monotonic() + RETRY_AFTER_FAILURE
    return _stored_events(rows)


def calendar_source(retrieved_at: datetime | None, url: str | None = None) -> v.LensMomentSource:
    return v.LensMomentSource(label=f"Google Calendar, {CALENDAR_NAME}", url=url or CALENDAR_PAGE, publisher="Google",
                              retrieved_at=retrieved_at)


# --- what a moment is (Knowledge Graph, recorded) -------------------------------------------------------------------

NOTE_ATTRIBUTION = "Wikipedia text (CC BY-SA), found through the Google Knowledge Graph"


@lru_cache(maxsize=1)
def _notes() -> dict[str, Any]:
    if not NOTES_FILE.exists():
        return {"notes": {}}
    return json.loads(NOTES_FILE.read_text(encoding="utf-8"))


def notes_recorded_on() -> date | None:
    raw = _notes().get("recorded_on")
    return date.fromisoformat(raw) if raw else None


def _clip(text: str, limit: int = 320) -> str:
    """The first sentences of a description, up to `limit` characters, cut at a sentence end where there is one."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return cut[: end + 1] if end > 80 else cut.rstrip() + "…"


AMBIGUOUS = {"statehood day", "state day", "foundation day", "formation day"}  # several states share these names


def note_for(name: str) -> v.LensMomentAbout | None:
    key = name_key(name)
    note = None if key in AMBIGUOUS else _notes()["notes"].get(key)
    if not note:
        return None
    return v.LensMomentAbout(text=_clip(note["text"]), url=note.get("url"), attribution=NOTE_ATTRIBUTION)


def accept_kg(query: str, elements: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The Knowledge Graph result that is about the moment itself, or None. A result qualifies when it has a description with a
    page; its name is the query, or its description names the query in its opening words ("X or Y is ..."); the description
    reads as a festival, holiday or observance; and it ties the moment to India or to a faith observed there. Films, paintings,
    people, places and events such as parades or attacks that share the name are dropped. Among those that qualify, a result
    Google itself describes as a festival or holiday, then one with the same name, comes first. Pure: tested on its own."""
    wanted = name_key(query)
    if not wanted:
        return None
    ranked = []
    for element in elements:
        result = element.get("result") or {}
        detail = result.get("detailedDescription") or {}
        body, url = str(detail.get("articleBody") or ""), str(detail.get("url") or "")
        short = str(result.get("description") or "").casefold()
        if not body or not url or set(result.get("@type") or []) & _NOT_A_MOMENT:
            continue
        if any(word in f"{short} {url.casefold()} {body[:160].casefold()}" for word in _NOT_A_MOMENT_WORDS):
            continue  # a film, a painting, a parade or an attack that shares the name
        qualifier = re.search(r"_\(([^)/]*)\)$", url)
        if qualifier and not any(w in qualifier.group(1).casefold().replace("_", " ") for w in (*_INDIAN, *_FESTIVE)):
            continue  # "Statehood_Day_(Ukraine)": the page is about the same name somewhere else
        named = name_key(str(result.get("name") or "")) == wanted
        if not (named or f" {wanted} " in f" {name_key(body[:200])} "):
            continue
        opening = body[:400].casefold()
        festive_short = any(word in short for word in _FESTIVE)
        if not (festive_short or any(word in opening[:300] for word in _FESTIVE)) or not any(word in opening for word in _INDIAN):
            continue
        ranked.append((not festive_short, not named, len(ranked), result, detail))
    if not ranked:
        return None
    *_, result, detail = min(ranked, key=lambda r: r[:3])
    return {"entity": result.get("name"), "kg_id": result.get("@id"), "description": result.get("description"),
            "text": str(detail["articleBody"]), "url": detail["url"], "license": detail.get("license")}


# --- the year's entries ---------------------------------------------------------------------------------------------

# Words too common to say two names are the same moment, and the few names the lists spell differently for one holiday.
_GENERIC = {"day", "jayanti", "festival", "puja", "first", "year", "birthday", "shri", "maha", "diwas", "holiday", "eve", "sant",
            "guru", "saint", "start", "festivities"}
_ALIASES = {"ramzan id": "id ul fitr", "eid al fitr": "id ul fitr", "bakrid": "id ul zuha", "eid al adha": "id ul zuha",
            "muharram ashura": "muharram", "dussehra": "vijaya dashami", "vijayadashami": "vijaya dashami"}
_KIND_ORDER = {"public_holiday": 0, "festival": 1, "observance": 2}
NEAR_DAYS = 45  # a moment this close before or after the campaign window is said to be near it


def _tokens(key: str) -> set[str]:
    return {t for t in key.split() if len(t) >= 4 and t not in _GENERIC}


def same_moment(a: str, b: str) -> bool:
    """Two names on the same day name the same moment: equal, one inside the other, a listed alias or a shared distinctive word."""
    ka, kb = name_key(a), name_key(b)
    ka, kb = _ALIASES.get(ka, ka), _ALIASES.get(kb, kb)
    return bool(ka and kb) and (ka == kb or f" {ka} " in f" {kb} " or f" {kb} " in f" {ka} " or bool(_tokens(ka) & _tokens(kb)))


@dataclass
class _Draft:
    day: date
    name: str
    kind: str
    names: list[str]
    sources: list[v.LensMomentSource]
    reasons: list[str]
    claim_id: Any = None
    tentative: bool = False


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def build_entries(
    *, state: str, year: int, window: v.LensWindow | None, dated: list[v.LensDatedMoment], festivals: list[tuple[str, int]],
    state_list: tuple[tuple[date, str], ...], google: list[Event], region_code: str, searches: list[v.LensSearchTerm],
) -> list[v.LensCalendarEntry]:
    """Every dated moment of the year for one state, merged across the lists that give it, with the reasons it matters.

    `dated`: the claim-backed dates (`analytics.lens.calendar_entries`); `festivals`: (festival name, distinct cited sources)
    from the state's festival claims; `state_list`: the state's public-holiday list; `google`: Google's Holidays in India
    events of the year (an event whose name points to another state is left out); `searches`: the state's newest-week
    searches. Pure: no I/O, no clock. Every reason is a fact the inputs state or a count or date difference computed here."""
    drafts: list[_Draft] = []

    def add(day: date, name: str, kind: str, source: v.LensMomentSource, reason: str, *, claim_id: Any = None, tentative: bool = False) -> None:
        if day.year != year:
            return
        for d in drafts:
            if d.day == day and any(same_moment(n, name) for n in d.names):
                d.kind = min(d.kind, kind, key=_KIND_ORDER.__getitem__)
                if name not in d.names:
                    d.names.append(name)
                if all(s.label != source.label for s in d.sources):
                    d.sources.append(source)
                if reason not in d.reasons:
                    d.reasons.append(reason)
                d.claim_id = d.claim_id or claim_id
                d.tentative = d.tentative or tentative
                return
        drafts.append(_Draft(day, name, kind, [name], [source], [reason], claim_id, tentative))

    on_list = f"On {state}'s public-holiday list for {year}."
    for moment in dated:
        src = moment.claim.sources[0] if moment.claim.sources else None
        source = v.LensMomentSource(label=(src.title or src.source_type) if src else "Cited claim", url=src.url if src else None,
                                    publisher=(src.publisher or "") if src else "", retrieved_at=src.retrieved_at if src else None)
        holiday = moment.date_basis == "public_holiday_list"
        add(moment.date, moment.name, "public_holiday" if holiday else "festival", source,
            on_list if holiday else "A cited source gives this date.", claim_id=moment.claim.id)
    listed = holidays_source()
    claimed = [(m.date, m.name) for m in dated if m.date_basis == "public_holiday_list"]  # a build stored these from the same list
    for day, name in state_list:
        if not any(d == day and same_moment(n, name) for d, n in claimed):
            add(day, name, "public_holiday", listed, on_list)
    for event in google:
        if event.region_code and event.region_code != region_code:
            continue
        reason = ("On Google's Holidays in India calendar as a public holiday." if event.kind == "public_holiday"
                  else "Marked in Google's Holidays in India calendar.")
        add(event.day, event.name, event.kind, calendar_source(event.retrieved_at, event.url), reason, tentative=event.tentative)

    entries: list[v.LensCalendarEntry] = []
    for d in sorted(drafts, key=lambda x: (x.day, _KIND_ORDER[x.kind], x.name)):
        why = list(d.reasons)
        cited = max((n for festival, n in festivals if any(same_moment(festival, name) for name in d.names)), default=0)
        if cited:
            why.append(f"{_plural(cited, 'cited source describes', 'cited sources describe')} it as a festival of {state}.")
        if window is not None:
            if window.date_from <= d.day <= window.date_to:
                why.append("Inside the campaign window.")
            elif 0 < (window.date_from - d.day).days <= NEAR_DAYS:
                why.append(f"{_plural((window.date_from - d.day).days, 'day', 'days')} before the campaign window opens.")
            elif 0 < (d.day - window.date_to).days <= NEAR_DAYS:
                why.append(f"{_plural((d.day - window.date_to).days, 'day', 'days')} after the campaign window closes.")
        if d.kind == "public_holiday" and d.day.weekday() in (0, 4):
            why.append(f"Falls on a {d.day:%A}, next to a weekend.")
        for term in searches:
            words = _tokens(name_key(term.term))
            if any(words & _tokens(name_key(name)) for name in d.names):
                why.append(f"“{term.term}” is among this week's {'rising' if term.kind == 'rising' else 'top'} searches in {state}.")
                break
        about = next((note for name in d.names if (note := note_for(name)) is not None), None)
        entries.append(v.LensCalendarEntry(
            key=f"{d.day.isoformat()}:{name_key(d.name) or d.name}", date=d.day, name=d.name, kind=d.kind,  # type: ignore[arg-type]
            about=about, why=why, sources=d.sources, claim_id=d.claim_id, tentative=d.tentative,
            in_window=None if window is None else window.date_from <= d.day <= window.date_to))
    return entries


def typical_moments(region_code: str, entries: list[v.LensCalendarEntry]) -> list[v.LensTypicalMoment]:
    """The reference moments of the state (and the national ones) with their typical months, marked when the year has a date."""
    return [v.LensTypicalMoment(name=row.name, kind=row.kind, months=list(row.months), calendar=row.calendar, note=row.notes,
                                dated=any(same_moment(row.name, e.name) for e in entries))
            for row in india.MOMENTS if row.region in (None, region_code)]


_NOT_A_MOMENT = {"Movie", "CreativeWork", "Book", "TVSeries", "TVEpisode", "MusicAlbum", "MusicRecording", "MusicComposition",
                 "VideoGame", "Person", "Organization", "Corporation", "Place", "City", "AdministrativeArea", "Country", "Painting",
                 "VisualArtwork"}
_NOT_A_MOMENT_WORDS = ("film", "album", "song", "novel", "television", "video game", "painting", "parade of", "bombing", "attack",
                       "massacre", "magazine", "(dish)")
_FESTIVE = ("festival", "holiday", "observance", "observed", "celebrat", "commemorat", "anniversary", "feast", "worship", "new year",
            "puja", "jayanti", "month of the islamic")
_INDIAN = ("india", "hindu", "sikh", "jain", "buddhis", "islam", "muslim", "christian", "jesus", "parsi", "zoroastrian", "bengal",
           "tamil", "kerala", "malayal", "maharashtra", "marathi", "gujarat", "punjab", "assam", "odisha", "odia", "bihar", "kashmir",
           "goa", "sikkim", "mizo", "manipur", "tripura", "nagaland", "meghalaya", "karnataka", "kannada", "telugu", "andhra",
           "telangana", "rajasthan", "haryana", "himachal", "uttarakhand", "jharkhand", "chhattisgarh", "puducherry", "ladakh",
           "lakshadweep", "andaman", "delhi", "uttar pradesh", "madhya pradesh", "nepal")
