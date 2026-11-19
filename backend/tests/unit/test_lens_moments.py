"""Moment Calendar rules, offline: the Knowledge Graph relevance rule, name matching, Google event parsing and the reasons a
moment matters. Pure functions; no network, no database."""

from datetime import UTC, date, datetime

from app.schemas import lens as v
from app.services import lens_moments as lm


def kg(name: str, body: str, url: str, *, description: str = "Festival", types: tuple[str, ...] = ("Thing",)) -> dict:
    return {"result": {"name": name, "@type": list(types), "description": description,
                       "detailedDescription": {"articleBody": body, "url": url, "license": "CC BY-SA"}}}


def test_the_knowledge_graph_rule_keeps_the_moment_itself_and_drops_namesakes() -> None:
    onam = kg("Onam", "Onam is a Hindu harvest festival mostly celebrated in the Indian state of Kerala.", "https://en.wikipedia.org/wiki/Onam")
    town = kg("Onamia", "Onamia is a city in Minnesota, United States.", "https://en.wikipedia.org/wiki/Onamia", description="City", types=("City",))
    assert lm.accept_kg("Onam", [town, onam])["url"].endswith("/Onam")
    film = kg("Independence Day", "Independence Day is a 1996 American science fiction film.", "https://en.wikipedia.org/wiki/Independence_Day_(1996_film)",
              description="1996 film", types=("Movie",))
    india = kg("Indian Independence Day", "Independence Day is celebrated annually on 15 August as a public holiday in India.",
               "https://en.wikipedia.org/wiki/Independence_Day_(India)", description="Celebration")
    assert lm.accept_kg("Independence Day", [film, india])["url"].endswith("(India)")  # named in its opening words
    abroad = kg("Statehood Day", "Statehood Day is a national holiday in Ukraine celebrating the Christianization of Kievan Rus.",
                "https://en.wikipedia.org/wiki/Statehood_Day_(Ukraine)", description="Holiday")
    assert lm.accept_kg("Statehood Day", [abroad]) is None  # the page is the same name somewhere else
    parade = kg("East German Republic Day Parade of 1989", "The East German Republic Day Parade of 1989 was a parade of the army.",
                "https://en.wikipedia.org/wiki/East_German_Republic_Day_Parade_of_1989", description="Event")
    assert lm.accept_kg("Republic Day", [parade]) is None
    karva = kg("Karwa Chauth", "Karva Chauth or Karwa Chauth or Karaka Chaturthi is a Hindu festival celebrated by women of Northern India.",
               "https://en.wikipedia.org/wiki/Karva_Chauth")
    assert lm.accept_kg("Karaka Chaturthi", [karva])["entity"] == "Karwa Chauth"
    assert lm.accept_kg("Onam", []) is None and lm.accept_kg("", [onam]) is None


def test_two_lists_name_the_same_moment_only_when_the_names_agree() -> None:
    assert lm.same_moment("Diwali", "Diwali/Deepavali") and lm.same_moment("Ramzan Id", "Id-ul-Fitr")
    assert lm.same_moment("Guru Nanak Jayanti", "Guru Nanak's Jayanti") and lm.same_moment("Janmashtami (Smarta)", "Janmashtami")
    assert not lm.same_moment("Vishu", "Ambedkar Jayanti") and not lm.same_moment("Maha Saptami", "Maha Ashtami")
    assert lm.region_hint("Bahag Bihu (Assam)") == "IN-AS" and lm.region_hint("Vaisakhadi (Bengal)") == "IN-WB"
    assert lm.region_hint("Ramzan Id (tentative)") is None


def test_google_events_keep_googles_kind_and_tentative_flag() -> None:
    items = [
        {"id": "a", "summary": "Ramzan Id (tentative)", "description": "Public holiday\nDate is tentative and may change.", "start": {"date": "2027-03-10"}},
        {"id": "b", "summary": "Vishu", "description": "Observance\nTo hide observances, go to Google Calendar Settings", "start": {"date": "2027-04-14"}},
        {"id": "c", "summary": "No date", "start": {"dateTime": "2027-01-01T10:00:00Z"}},
    ]
    when = datetime(2026, 11, 19, tzinfo=UTC)
    first, second = lm.parse_items(items, when)
    assert (first.name, first.kind, first.tentative, first.day) == ("Ramzan Id", "public_holiday", True, date(2027, 3, 10))
    assert (second.kind, second.tentative, second.retrieved_at) == ("observance", False, when)


def test_entries_merge_the_lists_and_say_why_each_moment_matters() -> None:
    google = lm.parse_items([
        {"id": "x", "summary": "Onam", "description": "Observance", "start": {"date": "2027-09-12"}},
        {"id": "y", "summary": "Bahag Bihu (Assam)", "description": "Observance", "start": {"date": "2027-04-15"}},
        {"id": "z", "summary": "Gandhi Jayanti", "description": "Public holiday", "start": {"date": "2027-10-01"}},
    ], datetime(2026, 11, 19, tzinfo=UTC))
    window = v.LensWindow(date_from=date(2027, 9, 1), date_to=date(2027, 9, 30))
    searches = [v.LensSearchTerm(term="onam wishes", kind="rising", score=80, percent_gain=500)]
    entries = lm.build_entries(
        state="Kerala", year=2027, window=window, dated=[], festivals=[("Onam", 7)],
        state_list=((date(2027, 9, 12), "Onam"), (date(2027, 10, 1), "Gandhi Jayanti")), google=google, region_code="IN-KL",
        searches=searches)
    names = [e.name for e in entries]
    assert "Bahag Bihu (Assam)" not in names  # another state's moment stays off Kerala's calendar
    onam = next(e for e in entries if e.name == "Onam")
    assert onam.kind == "public_holiday" and len(onam.sources) == 2 and onam.in_window is True  # two lists, one moment
    assert "On Kerala's public-holiday list for 2027." in onam.why and "Inside the campaign window." in onam.why
    assert "7 cited sources describe it as a festival of Kerala." in onam.why
    assert any("onam wishes" in reason and "rising" in reason for reason in onam.why)
    gandhi = next(e for e in entries if e.name == "Gandhi Jayanti")  # Friday 1 October 2027
    assert "Falls on a Friday, next to a weekend." in gandhi.why and "1 day after the campaign window closes." in gandhi.why
    assert [e.date for e in entries] == sorted(e.date for e in entries)
