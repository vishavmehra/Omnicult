"""Market Lens helpers: month and date reading, calendar entries, language names, comparison rows, source summaries.
Pure functions over ClaimViews: no database, no network."""

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from app.analytics import lens
from app.schemas import lens as v
from app.schemas.claims import ClaimScope
from app.schemas.regions import ClaimView, SourceView

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def source(source_type: str = "curated_reference", identifier: str = "s1", published: date | None = None) -> SourceView:
    return SourceView(
        id=uuid4(), source_type=source_type, source_identifier=identifier, url=None, title=None, publisher=None, published_at=published,
        retrieved_at=NOW, excerpt=None, independence_group=source_type)


def claim(subject: str, attribute: str, category: str, value: Any, *, region: str = "IN-MH", period: str | None = None,
          text: str = "x", sources: list[SourceView] | None = None, conflicts: list | None = None, language: str | None = None,
          confidence: str = "low") -> ClaimView:
    return ClaimView(
        id=uuid4(), shared=False, subject=subject, attribute=attribute, category=category, value=value, value_text=text,  # type: ignore[arg-type]
        scope=ClaimScope(region_code=region, period=period, language=language), kind="observed", confidence=confidence,  # type: ignore[arg-type]
        effective_confidence=confidence,  # type: ignore[arg-type]
        confidence_reason="r", sources=sources if sources is not None else [source()], published_at=None, retrieved_at=NOW,
        expires_at=None, status="active", stale=False, conflict_ids=conflicts or [])


def holiday(name: str, day: str, *, festival: str | None = None, year: int = 2027) -> ClaimView:
    value = {"date": day, "name": name, "subdivision": "MH", "year": year}
    if festival:
        value["curated_festival"] = festival
    return claim(f"moment:{name.lower().replace(' ', '_')}", "public_holiday_date", "moment", value, period=str(year),
                 sources=[source("holidays_package", f"h:{name}")])


def test_months_named_reads_names_in_calendar_order_and_ignores_text_with_a_year() -> None:
    assert lens.months_named("August or September") == [8, 9]
    assert lens.months_named("between around mid-October and mid-November") == [10, 11]
    assert lens.months_named("December to January") == [1, 12]
    assert lens.months_named("around Aug-Sep") == [8, 9]
    assert lens.months_named("early May, on the 25th day of the Bengali month of Boishakh") == [5]
    assert lens.months_named("Margazhi in the Tamil calendar") == []  # Mar inside a word is not March
    assert lens.months_named("14 January 1969") == []  # a past event names no recurring months
    assert lens.months_named("the first full moon day of the Tamil calendar month of Karthigai") == []


def test_parse_fixed_date_accepts_only_a_plain_day_and_month() -> None:
    assert lens.parse_fixed_date("1 May", 2027) == date(2027, 5, 1)
    assert lens.parse_fixed_date("February 19", 2027) == date(2027, 2, 19)
    assert lens.parse_fixed_date("14th January", 2027) == date(2027, 1, 14)
    for text in ("14 or 15 April", "14 January 1969", "20 June (announced 2022)", "generally 14 April; first day of Chithirai", "mid-January", "30 February"):
        assert lens.parse_fixed_date(text, 2027) is None, text


def test_a_public_holiday_is_dated_and_linked_to_its_festival_and_other_years_are_left_out() -> None:
    views = [holiday("Diwali (Deepavali)", "2027-10-29", festival="festival:diwali"), holiday("Old", "2026-01-01", year=2026)]
    dated, timed = lens.calendar_entries(views, year=2027, window=None)
    assert [(d.name, d.date, d.date_basis, d.festival_subject, d.in_window) for d in dated] == [
        ("Diwali (Deepavali)", date(2027, 10, 29), "public_holiday_list", "festival:diwali", None)]
    assert timed == []


def test_a_window_flags_dated_moments_inside_it() -> None:
    window = v.LensWindow(date_from=date(2027, 10, 4), date_to=date(2027, 11, 1))
    dated, _ = lens.calendar_entries([holiday("Diwali", "2027-10-29"), holiday("Later", "2027-12-25")], year=2027, window=window)
    assert {d.name: d.in_window for d in dated} == {"Diwali": True, "Later": False}
    assert lens.window_months(window) == {10, 11}
    assert lens.window_months(v.LensWindow(date_from=date(2027, 12, 20), date_to=date(2028, 1, 5))) == {12, 1}


def test_timing_text_stays_verbatim_and_names_months_without_inventing_a_date() -> None:
    festival = claim("festival:ganesh_chaturthi", "major_festival", "festival", {"name": "Ganesh Chaturthi", "month_text": "around August-September"})
    lunar = claim("festival:ganesh_chaturthi", "festival_timing", "festival",
                  {"name": "Ganesh Chaturthi", "month_text": "Chaturthi of the waxing moon in Bhadrapada"})
    plain = claim("festival:pola", "major_festival", "festival", {"name": "Pola"})
    window = v.LensWindow(date_from=date(2027, 9, 1), date_to=date(2027, 9, 30))
    dated, timed = lens.calendar_entries([festival, lunar, plain], year=2027, window=window)
    assert dated == []
    by_name = {t.name: t for t in timed}
    ganesh = by_name["Ganesh Chaturthi"]
    assert [t.text for t in ganesh.timings] == ["around August-September", "Chaturthi of the waxing moon in Bhadrapada"]
    assert ganesh.months_named == [8, 9] and ganesh.may_overlap_window is True and ganesh.dated_for_year == []
    assert by_name["Pola"].timings == [] and by_name["Pola"].may_overlap_window is False  # listed, with no timing stated
    assert [t.name for t in timed] == ["Ganesh Chaturthi", "Pola"]  # named months first, then entries with none


def test_a_curated_moment_with_a_plain_date_goes_on_the_calendar_not_the_timed_list() -> None:
    day = claim("moment:maharashtra_day", "moment_date", "moment", {"name": "Maharashtra Day", "date_text": "1 May"})
    named = claim("moment:maharashtra_day", "cultural_moment", "moment", {"name": "Maharashtra Day"})
    dated, timed = lens.calendar_entries([day, named], year=2027, window=None)
    assert [(d.name, d.date, d.date_basis) for d in dated] == [("Maharashtra Day", date(2027, 5, 1), "source_text")]
    assert timed == []


def test_a_source_text_date_that_matches_a_public_holiday_is_kept_as_a_second_claim() -> None:
    text = claim("moment:maharashtra_day", "moment_date", "moment", {"name": "Maharashtra Day", "date_text": "1 May"})
    dated, timed = lens.calendar_entries([holiday("Maharashtra Day", "2027-05-01"), text], year=2027, window=None)
    (entry,) = dated
    assert entry.date_basis == "public_holiday_list" and [c.id for c in entry.also_stated_by] == [text.id] and timed == []


def test_conflicting_relative_day_claims_mark_the_festival_instead_of_choosing() -> None:
    cid = uuid4()
    named = claim("festival:dahi_handi", "major_festival", "festival", {"name": "Dahi Handi", "month_text": "August or September"})
    a = claim("festival:dahi_handi", "festival_day_relative_to_janmashtami", "festival", "same day as Krishna Janmashtami", conflicts=[cid])
    b = claim("festival:dahi_handi", "festival_day_relative_to_janmashtami", "festival", "day after Krishna Janmashtami", conflicts=[cid])
    _, timed = lens.calendar_entries([named, a, b], year=2027, window=None)
    (entry,) = timed
    assert entry.name == "Dahi Handi" and entry.conflict_ids == [cid] and entry.months_named == [8, 9]


def test_linked_public_holidays_appear_on_the_festival_and_count_for_the_window() -> None:
    festival = claim("festival:diwali", "festival_timing", "festival", {"name": "Diwali", "month_text": "between mid-October and mid-November"})
    named = claim("festival:diwali", "major_festival", "festival", {"name": "Diwali"})
    window = v.LensWindow(date_from=date(2027, 10, 20), date_to=date(2027, 10, 31))
    _, timed = lens.calendar_entries([festival, named, holiday("Diwali (Deepavali)", "2027-10-29", festival="festival:diwali")], year=2027, window=window)
    (entry,) = timed
    assert entry.dated_for_year == [date(2027, 10, 29)] and entry.may_overlap_window is True


def test_months_group_dated_entries_in_calendar_order() -> None:
    dated, _ = lens.calendar_entries([holiday("A", "2027-10-29"), holiday("B", "2027-01-26")], year=2027, window=None)
    months = lens.months_of(dated)
    assert [m.name for m in months][:2] == ["January", "February"] and len(months) == 12
    assert [d.name for d in months[0].dated] == ["B"] and [d.name for d in months[9].dated] == ["A"]


def test_language_names_come_from_the_statement_and_fall_back_to_the_subject() -> None:
    marathi = claim("region:IN-MH", "language_share", "language", 68.93, language="mr",
                    text="In the 2011 census, Marathi was the mother tongue of 68.93% of Maharashtra's population (x of y).")
    bhili = claim("language:bhili_bhilodi", "language_share", "language", 2.0,
                  text="In the 2011 census, Bhili/Bhilodi was the mother tongue of 2.0% of Maharashtra's population.")
    odd = claim("language:khandeshi", "language_share", "language", 1.44, text="something else")
    assert [lens.share_language_name(c) for c in (marathi, bhili, odd)] == ["Marathi", "Bhili/Bhilodi", "Khandeshi"]
    assert [lens.language_key(c) for c in (marathi, bhili)] == ["mr", "language:bhili_bhilodi"]


def test_compare_shows_missing_evidence_as_missing_and_counts_only_sourced_overlap() -> None:
    mh = [claim("festival:diwali", "major_festival", "festival", {"name": "Diwali"}),
          claim("festival:holi", "major_festival", "festival", {"name": "Holi"}),
          claim("topic:tamasha", "humour_style", "humour", {"name": "tamasha"})]
    tn = [claim("festival:diwali", "major_festival", "festival", {"name": "Deepavali"}, region="IN-TN")]
    rows = {r.key: r for r in lens.compare_rows({"IN-MH": mh, "IN-TN": tn})}
    festivals = rows["festivals"]
    assert festivals.shared_subjects == 1
    assert [i.label for i in festivals.cells[0].items] == ["Diwali", "Holi"] and festivals.cells[0].items[0].also_in == ["IN-TN"]
    assert festivals.cells[0].items[1].also_in == []  # no claim found in the other column: absence of evidence only
    humour = rows["humour"]
    assert humour.cells[1].missing is True and humour.cells[1].total == 0 and humour.cells[0].missing is False
    assert len(lens.COMPARE_ROWS) == len(rows) == 8


def test_compare_keeps_the_top_language_shares_and_the_principal_language_only() -> None:
    shares = [claim("region:IN-MH", "language_share", "language", pct, language=code,
                    text=f"In the 2011 census, {name} was the mother tongue of {pct}% of x")
              for code, name, pct in (("mr", "Marathi", 68.93), ("hi", "Hindi", 12.89), ("ur", "Urdu", 6.71), ("gu", "Gujarati", 2.11))]
    rows = {r.key: r for r in lens.compare_rows({"IN-MH": shares, "IN-TN": []})}
    labels = [i.label for i in rows["languages"].cells[0].items]
    assert len(labels) == lens.TOP_SHARES and not any("Gujarati" in label for label in labels)
    assert all("(2011)" in label for label in labels)


def test_a_compare_cell_is_capped_and_reports_the_total() -> None:
    many = [claim(f"festival:f{i}", "major_festival", "festival", {"name": f"F{i:02d}"}) for i in range(lens.CELL_LIMIT + 5)]
    cell = {r.key: r for r in lens.compare_rows({"IN-MH": many, "IN-TN": []})}["festivals"].cells[0]
    assert cell.total == lens.CELL_LIMIT + 5 and len(cell.items) == lens.CELL_LIMIT


def test_source_summary_gives_dates_limits_and_distinct_counts() -> None:
    census = source("census_2011", "t1", date(2022, 7, 4))
    views = [claim("a", "language_share", "language", 1.0, sources=[census]), claim("b", "language_share", "language", 2.0, sources=[census, source("wikipedia", "p1")])]
    summary = {s.source_type: s for s in lens.summarise_sources(views)}
    assert summary["census_2011"].claims == 2 and summary["census_2011"].sources == 1
    assert summary["census_2011"].newest_published_at == date(2022, 7, 4) and any("2011" in x for x in summary["census_2011"].limitations)
    assert summary["wikipedia"].newest_published_at is None and summary["wikipedia"].newest_retrieved_at == NOW
