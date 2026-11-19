"""Audience Lab sessions (lab-t3): Live Focus Group, Buzz Simulator and Message Check end to end on the fixture provider (demo
projects) and on a scripted provider (live projects). Persistence, streaming, interjection, validation of every model reference,
code-computed counts, access and roles. No network, no paid call."""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.analytics.lab_text import content_words
from app.core.config import get_settings
from app.db import models as m
from app.db.base import utcnow
from app.db.session import read_session, session
from app.fixtures.audience_llm import AUDIENCE_RESPONDERS
from app.fixtures.lab_t3_llm import RESPONDERS as SESSION_RESPONDERS
from app.services import audience as service
from tests.api.omnicult_support import add_member, client_for, seeded, workspace_of  # noqa: F401
from tests.api.test_audience_api import (  # noqa: F401
    demo_campaign,
    finish,
    live,
    live_campaign,
    post_run,
    run_and_read,
)
from tests.conftest import BOB

API = "/api/v1"
GUIDE = ["What is your first impression of this ad?", "In your own words, what is this ad telling you?",
         "Is there anything here that feels out of place where you live?"]
MESSAGE = "Home-style festive sweets, ready to gift and delivered before the festival day."


@pytest.fixture(autouse=True)
def no_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    """Demo sessions replay their fixtures with a pause between turns; tests do not wait for it."""
    monkeypatch.setenv("LAB_T3_DEMO_TURN_DELAY_SECONDS", "0")
    get_settings.cache_clear()


async def panel_of(client: httpx.AsyncClient, campaign_id: str, region: str = "IN-TN", size: int = 8) -> dict[str, Any]:
    return await run_and_read(client, campaign_id, "quick-reads", {"region_code": region, "size": size, "intended_message": MESSAGE})


async def focus(client: httpx.AsyncClient, campaign_id: str, panel_id: str, **body: Any) -> dict[str, Any]:
    return await run_and_read(client, campaign_id, "focus-groups", {"panel_run_id": panel_id, "speakers": 5, "guide": GUIDE, **body})


# --- Live Focus Group -----------------------------------------------------------------------------------------------------


async def test_a_demo_focus_group_saves_a_transcript_of_the_moderator_and_replying_participants(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    panel = await panel_of(client, campaign["id"])
    result = await focus(client, campaign["id"], panel["id"])
    assert result["status"] == "completed" and result["mode"] == "demo" and result["panel_run_id"] == panel["id"]
    assert result["panel_kind"] == "quick_read" and result["regions"] == [{"code": "IN-TN", "name": "Tamil Nadu"}]
    assert result["guide"] == GUIDE and result["progress"]["stage"] == "completed" and result["interjections_open"] is False

    speakers, turns = result["speakers"], result["turns"]
    panel_people = {p["id"]: p for p in panel["participants"]}
    assert len(speakers) == 5 and all(s["id"] in panel_people for s in speakers)  # the panel's own participants, not new personas
    for s in speakers:
        stored = panel_people[s["id"]]
        assert s["persona"] == stored["persona"] and s["stored_stance"] == stored["response"]["sentiment"]
    assert [t["turn_index"] for t in turns] == list(range(len(turns)))
    moderator = [t for t in turns if t["kind"] == "moderator"]
    assert [t["text"] for t in moderator] == [GUIDE[0], *[t["text"] for t in moderator[1:]]]  # the guide drives it; later turns may add a probe
    assert all(g in t["text"] for g, t in zip(GUIDE, moderator))
    spoken = [t for t in turns if t["kind"] == "participant"]
    assert len(spoken) == 5 * 3 and {t["participant_id"] for t in spoken} == {s["id"] for s in speakers}
    by_index = {t["turn_index"]: t for t in turns}
    replies = [t for t in spoken if t["reply_to_turn_index"] is not None]
    assert replies, "participants answer each other"
    for t in spoken:
        assert t["stance"] in ("positive", "mixed", "neutral", "negative", "confused") and t["themes"] and t["text"]
        assert (t["reply_to_turn_index"] is None) == (t["relation"] == "new_point")
        if t["reply_to_turn_index"] is not None:
            target = by_index[t["reply_to_turn_index"]]
            assert target["turn_index"] < t["turn_index"] and target["kind"] == "participant" and target["participant_id"] != t["participant_id"]
    # the speaking order rotates, so a different participant opens each round
    openers = [next(t["participant_id"] for t in spoken if t["round_index"] == r) for r in range(3)]
    assert len(set(openers)) == 3

    summary = result["summary"]
    assert (summary["turn_count"], summary["participant_turns"], summary["speakers_heard"]) == (len(turns), 15, 5)
    assert [r["question"] for r in summary["rounds"]] == GUIDE and [r["answered"] for r in summary["rounds"]] == [5, 5, 5]
    for r in summary["rounds"]:  # the round's stance counts are the saved turns' stances, counted
        stances = [t["stance"] for t in spoken if t["round_index"] == r["round_index"]]
        assert r["stance"]["denominator"] == 5 and all(r["stance"]["counts"][k] == stances.count(k) for k in r["stance"]["counts"])
    for theme in summary["themes"]:
        who = {by_index[i]["participant_id"] for i in theme["turn_indices"]}
        assert theme["participants"] >= len(who) >= 1 and theme["basis"] == "interpretation"
    for shift in summary["shifts"]:
        mine = [t for t in spoken if t["participant_id"] == shift["participant_id"]]
        assert (shift["from_stance"], shift["to_stance"]) == (mine[0]["stance"], mine[-1]["stance"]) and shift["from_stance"] != shift["to_stance"]
    assert all(d["kind"] in ("stance_split", "direct_challenge") and d["description"] for d in summary["disagreements"])
    assert "counted from the saved transcript" in summary["method"]

    meta = result["run_metadata"]
    assert meta["providers"] == ["fixture"] and meta["model_ids"] == [] and meta["prompt_versions"] == ["focus-round-v1"]
    assert meta["usage"]["model_stages"] == 0 and [s["stage"] for s in meta["steps"]] == ["loading_context", "moderated_discussion", "analysing_themes"]
    assert not any("fixture" in lim.lower() for lim in result["limitations"]) and any("real people" in lim for lim in result["limitations"])
    assert result["disclosure"]["is_synthetic"] is True and result["disclosure"]["independent_human_sample"] is False

    async with read_session() as s:
        rows = (await s.execute(select(m.FocusGroupTurn).where(m.FocusGroupTurn.run_id == UUID(result["id"])))).scalars().all()
        run = await s.get(m.AudienceRun, UUID(result["id"]))
    assert len(rows) == len(turns) and run.kind == "focus_group" and run.inputs["panel"]["run_id"] == panel["id"]


async def test_the_default_guide_and_speakers_come_from_the_server(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    defaults = (await client.get(f"{API}/campaigns/{campaign['id']}/lab-session-defaults")).json()
    assert len(defaults["guide"]) == 4 and defaults["limits"]["focus_max_speakers"] == 8 and defaults["primary_message"] is None
    assert [p["value"] for p in defaults["platforms"]] == ["instagram", "facebook", "youtube", "x", "whatsapp"]
    panel = await panel_of(client, campaign["id"], size=10)
    result = await run_and_read(client, campaign["id"], "focus-groups", {"panel_run_id": panel["id"]})
    assert result["guide"] == defaults["guide"] and len(result["speakers"]) == 6
    ordinals = [s["ordinal"] for s in result["speakers"]]
    assert ordinals == sorted(ordinals)
    again = await run_and_read(client, campaign["id"], "focus-groups", {"panel_run_id": panel["id"]})
    assert [s["id"] for s in again["speakers"]] == [s["id"] for s in result["speakers"]]  # same panel and seed, same speakers


async def test_a_question_typed_mid_session_is_relayed_at_the_next_turn_boundary(
    seeded, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAB_T3_DEMO_TURN_DELAY_SECONDS", "0.05")
    get_settings.cache_clear()
    _, campaign, _ = await demo_campaign(client)
    panel = await panel_of(client, campaign["id"])
    accepted = await post_run(client, campaign["id"], "focus-groups", {"panel_run_id": panel["id"], "speakers": 4, "guide": GUIDE})
    url = accepted["status_url"]
    async with asyncio.timeout(10):
        while True:  # the transcript streams: read it while the session is still running
            partial = (await client.get(url)).json()
            if len(partial["turns"]) >= 3:
                break
            await asyncio.sleep(0.02)
    assert partial["status"] in ("queued", "running") and partial["interjections_open"] is True
    at = len(partial["turns"])
    sent = await client.post(f"{url}/interjections", json={"text": "  Would the delivery date change your mind?  "})
    assert sent.status_code == 201 and sent.json()["status"] == "pending" and sent.json()["text"] == "Would the delivery date change your mind?"
    result = await finish(client, url)
    assert result["status"] == "completed" and result["interjections"][0]["status"] == "taken" and result["interjections"][0]["taken_at"]
    researcher = [t for t in result["turns"] if t["kind"] == "researcher"]
    assert len(researcher) == 1 and researcher[0]["interjection_id"] == sent.json()["id"] and researcher[0]["turn_index"] >= at
    answers = [t for t in result["turns"] if t["kind"] == "participant" and t["round_index"] == researcher[0]["round_index"]]
    assert len(answers) == 4  # the whole group answered the researcher
    rounds = result["summary"]["rounds"]
    assert [r["kind"] for r in rounds].count("interjection") == 1 and len(rounds) == 4
    assert (await client.post(f"{url}/interjections", json={"text": "Too late?"})).status_code == 409  # finished: refused, not queued
    async with read_session() as s:
        pending = (await s.execute(select(m.FocusGroupInterjection).where(m.FocusGroupInterjection.status == "pending"))).scalars().all()
    assert pending == []


async def test_a_focus_group_needs_a_finished_panel_with_responses_and_valid_speakers(
    seeded, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAB_T3_FOCUS_MAX_SPEAKERS", "3")
    get_settings.cache_clear()
    project, campaign, _ = await demo_campaign(client)
    panel = await panel_of(client, campaign["id"])
    url = f"{API}/campaigns/{campaign['id']}/focus-groups"
    risk = await run_and_read(client, campaign["id"], "risk-checks", {"region_code": "IN-TN", "elements": [{"id": "h", "kind": "headline", "value": "Hello"}]})

    async def reject(body: dict[str, Any], status: int, field: str) -> None:
        response = await client.post(url, json=body)
        assert response.status_code == status, (body, response.text)
        assert not field or any(d["field"] and d["field"].startswith(field) for d in response.json()["error"]["details"]), response.text

    await reject({"panel_run_id": risk["id"]}, 404, "")  # a Risk Check is not a panel
    await reject({"panel_run_id": str(uuid4())}, 404, "")
    other = await run_and_read(client, (await live_campaign_demo(client))["id"], "quick-reads", {"region_code": "IN-TN", "size": 6})
    await reject({"panel_run_id": other["id"]}, 404, "")  # another campaign's panel is not found
    await reject({"panel_run_id": panel["id"], "participant_ids": [str(uuid4()), str(uuid4())]}, 422, "participant_ids")
    await reject({"panel_run_id": panel["id"], "participant_ids": [panel["participants"][0]["id"]]}, 422, "participant_ids")  # at least two
    await reject({"panel_run_id": panel["id"], "participant_ids": [p["id"] for p in panel["participants"][:4]]}, 422, "participant_ids")  # over the seat limit
    await reject({"panel_run_id": panel["id"], "guide": [f"q{n}" for n in range(7)]}, 422, "guide")
    await reject({"panel_run_id": panel["id"], "guide": ["  "]}, 422, "guide")
    await reject({"panel_run_id": panel["id"], "speakers": 1}, 422, "speakers")
    await reject({"panel_run_id": panel["id"], "unknown": 1}, 422, "unknown")
    assert (await client.get(f"{url}/{panel['id']}")).status_code == 404  # a Quick Read is not a focus group
    assert (await client.get(url)).json()["total"] == 0


async def live_campaign_demo(client: httpx.AsyncClient) -> dict[str, Any]:
    _, campaign, _ = await demo_campaign(client)
    return campaign


async def test_the_chosen_speakers_are_the_ones_named_and_roles_gate_a_session(seeded, client: httpx.AsyncClient, client_for) -> None:
    _, campaign, ws = await demo_campaign(client)
    panel = await panel_of(client, campaign["id"])
    wanted = [panel["participants"][i]["id"] for i in (6, 1, 3)]
    result = await focus(client, campaign["id"], panel["id"], participant_ids=wanted)
    assert [s["id"] for s in result["speakers"]] == [panel["participants"][i]["id"] for i in (1, 3, 6)]  # panel order, exactly these three
    base = f"{API}/campaigns/{campaign['id']}"
    await add_member(ws, "bob", "viewer")
    bob = client_for(BOB)
    assert (await bob.get(f"{base}/focus-groups/{result['id']}")).status_code == 200
    body = {"panel_run_id": panel["id"], "guide": GUIDE}
    assert (await bob.post(f"{base}/focus-groups", json=body)).status_code == 403
    assert (await bob.post(f"{base}/focus-groups/{result['id']}/interjections", json={"text": "hi"})).status_code == 403
    await add_member(ws, "bob", "editor")
    assert (await bob.post(f"{base}/focus-groups", json=body)).status_code == 202
    await service.wait_idle()


async def test_other_workspaces_and_a_retried_start_with_the_same_key(seeded, client: httpx.AsyncClient, client_for) -> None:
    _, campaign, _ = await demo_campaign(client)
    panel = await panel_of(client, campaign["id"])
    body = {"panel_run_id": panel["id"], "speakers": 4, "guide": GUIDE[:1]}
    first = await post_run(client, campaign["id"], "focus-groups", body, headers={"Idempotency-Key": "fg-1"})
    retried = await client.post(f"{API}/campaigns/{campaign['id']}/focus-groups", json=body, headers={"Idempotency-Key": "fg-1"})
    assert retried.status_code == 202, retried.text
    again = retried.json()  # the same run; on a fast machine it may already be running
    assert again["run_id"] == first["run_id"] and again["status"] in ("queued", "running")
    await service.wait_idle()
    assert (await client.get(f"{API}/campaigns/{campaign['id']}/focus-groups")).json()["total"] == 1
    bob = client_for(BOB)
    assert (await bob.get(first["status_url"])).status_code == 404
    assert (await bob.post(f"{first['status_url']}/interjections", json={"text": "hi"})).status_code == 404


def scripted_focus(ctx: dict[str, Any], *, reply_to: str | None = "T1", relation: str = "agrees", claims: list[str] | None = None,
                   skip_last: bool = False) -> dict[str, Any]:
    rows = ctx["speakers"][:-1] if skip_last else ctx["speakers"]
    return {"turns": [{"participant": r["participant"], "text": f"{r['participant']} says something.", "reply_to": reply_to,
                       "relation": relation, "stance": "mixed", "themes": ["a theme"], "claims": claims or []} for r in rows]}


async def live_panel(client: httpx.AsyncClient, live) -> tuple[dict, dict]:
    live.responders.update(AUDIENCE_RESPONDERS)
    live.responders.update(SESSION_RESPONDERS)
    _, campaign = await live_campaign(client)
    panel = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 6})
    assert panel["status"] == "completed" and panel["mode"] == "live"
    return campaign, panel


async def test_a_live_focus_group_validates_every_reference_the_model_makes(seeded, client: httpx.AsyncClient, live) -> None:
    campaign, panel = await live_panel(client, live)
    seen: list[dict[str, Any]] = []

    def respond(ctx: dict[str, Any]) -> dict[str, Any]:
        seen.append(ctx)
        # T1 is the moderator in round 0 and a participant turn afterwards; T99 never exists; each speaker answers itself once.
        out = scripted_focus(ctx, reply_to="T99", relation="disagrees", claims=["C99"], skip_last=len(seen) == 1)
        out["turns"][1]["reply_to"] = f"T{ctx['first_turn']}"  # a valid reply to the speaker just before
        out["turns"][2]["reply_to"] = f"T{ctx['first_turn'] + 2}"  # its own turn: invalid
        out["turns"][2]["relation"] = "disagrees"
        return out

    live.responders["focus-round-v1"] = respond
    result = await focus(client, campaign["id"], panel["id"], speakers=4, guide=GUIDE[:2])
    assert result["status"] == "partial"  # a participant the model left out is reported, so the run is not "completed"
    spoken = [t for t in result["turns"] if t["kind"] == "participant"]
    first_round = [t for t in spoken if t["round_index"] == 0]
    assert len(first_round) == 3  # the model skipped the last speaker: not guessed
    assert any("gave no turn for 1 of 4" in lim for lim in result["limitations"])
    assert first_round[0]["reply_to_turn_index"] is None and first_round[0]["relation"] == "new_point"  # T99: dropped, and a disagreement with nothing is a new point
    assert first_round[1]["reply_to_turn_index"] == first_round[0]["turn_index"] and first_round[1]["relation"] == "disagrees"
    assert first_round[2]["reply_to_turn_index"] is None and first_round[2]["relation"] == "new_point"  # its own turn
    assert all(t["claim_ids"] == [] and t["basis"] == "interpretation" for t in spoken)  # C99 never existed
    assert any("did not match" in lim for lim in result["limitations"])
    meta = result["run_metadata"]
    assert meta["providers"] == ["metered"] and meta["usage"]["model_stages"] >= 1 and meta["usage"]["input_tokens"] is not None
    # the model was told exactly which T numbers the speakers would have, and was given the guide as untrusted data
    assert seen[0]["first_turn"] == 2 and seen[0]["round_index"] == 0 and seen[1]["round_index"] == 1
    async with read_session() as s:
        events = (await s.execute(select(m.AiUsageEvent).where(m.AiUsageEvent.campaign_id == UUID(campaign["id"])))).scalars().all()
    assert len(events) >= 3 and {e.project_id for e in events} == {UUID(result["project_id"])}


async def test_claims_cited_by_a_participant_are_checked_against_the_stored_claims(seeded, client: httpx.AsyncClient, live) -> None:
    from tests.api.test_audience_api import add_region_claims

    _, campaign = await live_campaign(client)
    live.responders.update(AUDIENCE_RESPONDERS | SESSION_RESPONDERS)
    ws = await workspace_of("alice")
    # live claims are stored for the workspace, in live mode
    await add_region_claims(ws, mode="live")
    panel = await run_and_read(client, campaign["id"], "quick-reads", {"region_code": "IN-MH", "size": 6})
    assert panel["grounding"]["claims_supplied"] == 3
    live.responders["focus-round-v1"] = lambda ctx: scripted_focus(ctx, reply_to=None, relation="new_point", claims=[ctx["claims"][0]["handle"], "C77"])
    result = await focus(client, campaign["id"], panel["id"], speakers=2, guide=GUIDE[:1])
    spoken = [t for t in result["turns"] if t["kind"] == "participant"]
    assert spoken and all(len(t["claim_ids"]) == 1 for t in spoken)
    known = {c["id"]: c["kind"] for c in result["grounding"]["claims"]}
    assert all(t["claim_ids"][0] in known for t in spoken)
    expected = "claim_supported" if known[spoken[0]["claim_ids"][0]] in ("observed", "calculated") else "interpretation"
    assert all(t["basis"] == expected for t in spoken)
    assert result["grounding"]["cited_claim_ids"] == [spoken[0]["claim_ids"][0]]


async def test_a_focus_group_whose_model_fails_keeps_the_turns_already_saved(seeded, client: httpx.AsyncClient, live) -> None:
    campaign, panel = await live_panel(client, live)
    calls: list[int] = []

    def respond(ctx: dict[str, Any]) -> dict[str, Any] | None:
        calls.append(ctx["round_index"])
        return scripted_focus(ctx, reply_to=None, relation="new_point") if len(calls) == 1 else None

    live.responders["focus-round-v1"] = respond
    result = await focus(client, campaign["id"], panel["id"], speakers=3, guide=GUIDE)
    assert result["status"] == "partial" and result["error"]["stage"] == "moderated_discussion"
    assert "already saved are kept" in result["error"]["message"]
    kinds = [t["kind"] for t in result["turns"]]
    assert kinds.count("participant") == 3 and kinds.count("moderator") == 2  # round 2's question stands unanswered
    assert result["summary"]["participant_turns"] == 3


async def test_a_focus_group_whose_first_round_fails_is_a_failed_run_with_nothing_to_keep(seeded, client: httpx.AsyncClient, live) -> None:
    campaign, panel = await live_panel(client, live)
    live.responders["focus-round-v1"] = lambda ctx: None
    result = await focus(client, campaign["id"], panel["id"], speakers=3, guide=GUIDE[:1])
    error = result["error"]  # a rejected request fails the same way again, so the message must not call a retry safe
    assert result["status"] == "failed" and error["code"] == "PROVIDER_ERROR" and error["retryable"] is False
    assert error["message"].endswith("No participant turn was saved.") and "retrying is safe" not in error["message"]
    assert [t["kind"] for t in result["turns"]] == ["moderator"] and result["summary"]["participant_turns"] == 0


async def test_a_live_focus_group_refuses_a_panel_whose_run_did_not_finish_and_a_missing_provider(seeded, client: httpx.AsyncClient) -> None:
    _, campaign = await live_campaign(client)
    response = await client.post(f"{API}/campaigns/{campaign['id']}/focus-groups", json={"panel_run_id": str(uuid4())})
    assert response.status_code == 503 and response.json()["error"]["code"] == "PROVIDER_NOT_CONFIGURED"


# --- Buzz Simulator --------------------------------------------------------------------------------------------------------


BUZZ = {"sampling": {"states": ["IN-TN", "IN-KL", "IN-WB"]}, "size": 18, "rounds": 3, "seed": 7, "intended_message": MESSAGE}


async def test_a_demo_buzz_simulation_counts_spread_sentiment_and_cohorts_from_the_saved_acts(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    result = await run_and_read(client, campaign["id"], "buzz-simulations", BUZZ)
    assert result["status"] == "completed" and result["mode"] == "demo" and result["platform"] == "instagram"
    assert result["regions"] == [{"code": c, "name": n} for c, n in (("IN-TN", "Tamil Nadu"), ("IN-KL", "Kerala"), ("IN-WB", "West Bengal"))]
    people = {p["id"]: p for p in result["participants"]}
    assert len(people) == 18 and {p["state_code"] for p in people.values()} == {"IN-TN", "IN-KL", "IN-WB"}
    assert all(p["language"] in service._region_languages(p["state_code"]) for p in people.values())  # a language of the account's own state
    assert result["panel"]["generated_size"] == 18 and result["panel"]["seed"] == 7

    acts = result["acts"]
    assert len({a["participant_id"] for a in acts}) == len(acts)  # each account acts once
    first = [a for a in acts if a["round_index"] == 1]
    seeds = round(18 * 0.25)
    assert len(first) == seeds and all(a["exposed_by_participant_id"] is None for a in first)  # a quarter of the accounts see the creative first
    by_id = {a["participant_id"]: a for a in acts}
    for a in acts:
        if a["round_index"] > 1:
            source = by_id[a["exposed_by_participant_id"]]
            assert source["round_index"] == a["round_index"] - 1 and source["action"] in ("post", "share")  # only a post or reshare shows it on
        if a["action"] == "ignore":
            assert a["text"] is None and a["message_gloss"] is None
        else:
            assert a["text"] and a["text_en"]
        if a["action"] in ("reply", "share") and a["parent_act_id"]:
            assert a["parent_act_id"] in {x["id"] for x in acts}

    s = result["summary"]
    expressed = [a for a in acts if a["action"] != "ignore"]
    reach = s["reach"]
    assert reach["population"] == 18 and reach["seed_exposed"] == seeds and reach["acted"] == len(acts)
    exposed = {a["participant_id"] for a in acts}
    assert reach["exposed"] >= len(exposed) and reach["exposed_share"] == round(reach["exposed"] / 18, 4)
    assert reach["resharers"] == sum(a["action"] in ("post", "share") for a in acts) and 0 <= reach["cascade_depth"] <= 2
    assert reach["rounds_run"] == len(s["rounds"]) and reach["ended"] in ("rounds_used", "no_new_exposure")
    assert s["sentiment"]["denominator"] == len(expressed)
    assert all(s["sentiment"]["counts"][k] == sum(a["stance"] == k for a in expressed) for k in s["sentiment"]["counts"])
    assert sum(r["exposed"] for r in s["rounds"]) == len(acts)
    assert {c["value"] for c in s["by_state"]} == {"IN-TN", "IN-KL", "IN-WB"} and sum(c["participants"] for c in s["by_state"]) == 18
    assert sum(c["expressed"] for c in s["by_language"]) == len(expressed) == sum(c["posts"] + c["replies"] + c["shares"] for c in s["by_state"])
    assert s["mutation"]["reference_source"] == "intended_message" and s["mutation"]["reference"] == MESSAGE
    assert s["mutation"]["compared"] == sum(1 for a in expressed if a["message_gloss"]) and s["mutation"]["threshold"] == 0.34
    assert all(a["changed_message"] == (a["wording_overlap"] < 0.34) for a in acts if a["wording_overlap"] is not None)
    assert s["confusion"]["count"] == sum(a["stance"] == "confused" for a in expressed)
    assert all(e["from_participant_id"] in by_id for e in s["influence"]) and s["network_method"].startswith("Each account sees posts from 4")
    assert any("not a forecast" in lim for lim in result["limitations"]) and not any("fixture" in lim.lower() for lim in result["limitations"])
    meta = result["run_metadata"]
    assert meta["providers"] == ["fixture"] and meta["prompt_versions"] == ["buzz-round-v1"] and meta["usage"]["model_stages"] == 0

    async with read_session() as s2:
        run = await s2.get(m.AudienceRun, UUID(result["id"]))
    assert run.kind == "buzz_sim" and set(run.result) == {"network", "seed_exposed", "exposed_by", "rounds_run", "ended"}
    assert len(run.result["seed_exposed"]) == seeds and all(len(v) == 4 for v in run.result["network"].values())


async def test_buzz_is_reproducible_for_a_seed_and_changes_with_it(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    a = await run_and_read(client, campaign["id"], "buzz-simulations", BUZZ)
    b = await run_and_read(client, campaign["id"], "buzz-simulations", BUZZ)
    c = await run_and_read(client, campaign["id"], "buzz-simulations", BUZZ | {"seed": 8})
    key = lambda r: [(x["ordinal"], x["round_index"], x["action"], x["stance"]) for x in r["acts"]]  # noqa: E731
    assert key(a) == key(b) and key(a) != key(c)
    assert a["summary"]["reach"] == b["summary"]["reach"]


async def test_buzz_requests_are_validated_and_bounded_by_the_server(seeded, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _, campaign, _ = await demo_campaign(client)
    url = f"{API}/campaigns/{campaign['id']}/buzz-simulations"

    async def reject(body: dict[str, Any], field: str, text: str = "") -> None:
        response = await client.post(url, json=body)
        assert response.status_code == 422, (body, response.text)
        assert any(d["field"] and d["field"].startswith(field) and text in d["message"] for d in response.json()["error"]["details"]), response.text

    await reject({"sampling": {}}, "sampling.states", "at least one state")
    await reject({"sampling": {"states": ["IN-ZZ"]}}, "sampling.states", "Unknown")
    await reject({"sampling": {"states": ["IN-TN"], "religion": ["x"]}}, "sampling", "protected trait")
    await reject({"sampling": {"states": ["IN-TN"]}, "size": 11}, "size")
    await reject({"sampling": {"states": ["IN-TN"]}, "size": 41}, "size", "12 to 40")
    await reject({"sampling": {"states": ["IN-TN"]}, "rounds": 5}, "rounds", "at most 4")
    await reject({"sampling": {"states": ["IN-TN"]}, "platform": "myspace"}, "platform")
    await reject({"sampling": {"states": ["IN-TN"]}, "initial_exposure": 0.9}, "initial_exposure")
    await reject({"sampling": {"states": ["IN-TN"]}, "degree": 1}, "degree")
    assert (await client.get(url)).json()["total"] == 0
    monkeypatch.setenv("LAB_T3_BUZZ_MAX_PARTICIPANTS", "20")
    get_settings.cache_clear()
    await reject({"sampling": {"states": ["IN-TN"]}, "size": 24}, "size", "12 to 20")


async def test_buzz_runs_on_an_inline_creative_and_a_stored_version_and_voices_the_platform(seeded, client: httpx.AsyncClient, live) -> None:
    campaign, _ = await live_panel(client, live)
    seen: list[dict[str, Any]] = []

    def respond(ctx: dict[str, Any]) -> dict[str, Any]:
        seen.append(ctx)
        return SESSION_RESPONDERS["buzz-round-v1"](ctx)

    live.responders["buzz-round-v1"] = respond
    body = {"sampling": {"states": ["IN-MH"], "languages": ["mr"]}, "size": 12, "platform": "whatsapp", "rounds": 2,
            "creative": {"headline": "Inline headline", "body": "Inline body"}, "version_ref": "node-9"}
    result = await run_and_read(client, campaign["id"], "buzz-simulations", body)
    assert result["status"] in ("completed", "partial") and result["platform"] == "whatsapp" and result["creative"]["headline"] == "Inline headline"
    assert {p["language"] for p in result["participants"]} == {"mr"} and seen and seen[0]["platform"] == "whatsapp"
    assert result["summary"]["mutation"]["reference_source"] == "creative"  # no intended message: compared with the creative's own copy
    async with read_session() as s:
        run = await s.get(m.AudienceRun, UUID(result["id"]))
    assert run.version_ref == "node-9" and run.content_version_id is None
    stored = await run_and_read(client, campaign["id"], "buzz-simulations", {"sampling": {"states": ["IN-MH"]}, "size": 12, "rounds": 1})
    assert stored["creative"]["headline"] == campaign["current_version"]["content"]["headline"]


async def test_buzz_drops_replies_to_posts_the_account_never_saw_and_empty_posts(seeded, client: httpx.AsyncClient, live) -> None:
    campaign, _ = await live_panel(client, live)

    def respond(ctx: dict[str, Any]) -> dict[str, Any]:
        acts = []
        for i, row in enumerate(ctx["accounts"]):
            n = i % 3
            acts.append({"participant": row["participant"], "action": ["reply", "post", "share"][n], "reply_to": "F9" if n != 1 else None,
                         "text": None if n == 1 else "A reply", "text_en": None if n == 1 else "A reply", "message_gloss": "festive sweets as gifts",
                         "stance": "positive", "topics": ["gifting"]})
        return {"acts": acts}

    live.responders["buzz-round-v1"] = respond
    result = await run_and_read(client, campaign["id"], "buzz-simulations", {"sampling": {"states": ["IN-MH"]}, "size": 12, "rounds": 1})
    acts = result["acts"]
    assert {a["action"] for a in acts} == {"reply", "share", "ignore"}  # a post with no words is a scroll past, not a guess
    assert all(a["parent_act_id"] is None for a in acts)  # F9 is not in the feed: attached to the brand's own post instead
    assert any("did not match" in lim for lim in result["limitations"])
    assert all(a["text"] is None for a in acts if a["action"] == "ignore")


async def test_a_buzz_run_whose_later_round_fails_keeps_the_rounds_it_saved(seeded, client: httpx.AsyncClient, live) -> None:
    campaign, _ = await live_panel(client, live)
    calls: list[int] = []

    def respond(ctx: dict[str, Any]) -> dict[str, Any] | None:
        calls.append(ctx["round_index"])
        if ctx["round_index"] > 1:
            return None
        return {"acts": [{"participant": r["participant"], "action": "share", "reply_to": "F1", "text": "Sharing", "text_en": "Sharing",
                          "message_gloss": "festive sweets", "stance": "positive", "topics": []} for r in ctx["accounts"]]}

    live.responders["buzz-round-v1"] = respond
    result = await run_and_read(client, campaign["id"], "buzz-simulations", {"sampling": {"states": ["IN-MH"]}, "size": 12, "rounds": 3})
    assert result["status"] == "partial" and result["error"]["stage"] == "simulating_rounds" and "already saved are kept" in result["error"]["message"]
    assert {a["round_index"] for a in result["acts"]} == {1} and result["summary"]["reach"]["ended"] == "stopped_early"
    assert result["summary"]["reach"]["exposed"] > result["summary"]["reach"]["acted"]  # those the shares reached are counted as exposed


# --- Message Check ---------------------------------------------------------------------------------------------------------


CHECK = {"targets": [{"region_code": "IN-TN"}, {"region_code": "IN-KL", "creative": {"headline": "Kerala copy", "body": "Festive snacks"}}],
         "intended_message": MESSAGE, "size_per_region": 7, "seed": 3}


async def test_a_demo_message_check_scores_restatements_by_published_rules_and_counts_them_per_region(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    result = await run_and_read(client, campaign["id"], "message-checks", CHECK)
    assert result["status"] == "completed" and result["mode"] == "demo" and result["intended_message"] == MESSAGE
    assert result["intended_message_source"] == "request" and result["key_points_source"] == "split_by_code"
    assert [k["text"] for k in result["key_points"]] == ["Home-style festive sweets", "ready to gift", "delivered before the festival day"]
    assert [k["id"] for k in result["key_points"]] == ["K1", "K2", "K3"]
    people = result["participants"]
    assert len(people) == 14 and {p["state_code"] for p in people} == {"IN-TN", "IN-KL"}
    assert sum(p["state_code"] == "IN-TN" for p in people) == 7 and [p["ordinal"] for p in people] == list(range(14))

    verdicts = {}
    for p in people:
        r = p["response"]
        assert r["is_synthetic"] is True and r["restated"] and r["restated_en"] and [x["point_id"] for x in r["points"]] == ["K1", "K2", "K3"]
        expected = sum({"yes": 1, "partly": 0.5, "no": 0}[x["restated"]] for x in r["points"]) / 3
        assert r["score"] == pytest.approx(expected, abs=1e-3)
        want = "misread" if r["misreading"] else "understood" if expected >= 0.8 else "partly" if expected >= 0.4 else "missed"
        assert r["verdict"] == want
        assert r["wording_overlap"] == (round(len(content_words(r["restated_en"]) & content_words(MESSAGE)) / min(
            len(content_words(r["restated_en"])), len(content_words(MESSAGE))), 4))
        verdicts[p["ordinal"] % 7] = r["verdict"]
    # the demo fixture's seven readers (positive, mixed, positive, neutral, confused, mixed, negative) land on these verdicts
    assert [verdicts[i] for i in range(7)] == ["understood", "partly", "understood", "missed", "misread", "partly", "misread"]

    s = result["summary"]
    assert s["rules_version"] == "message-check-rules-v1" and len(s["rules"]) == 5
    assert [r["region"]["code"] for r in s["regions"]] == ["IN-TN", "IN-KL"]  # request order
    tn, kl = s["regions"]
    for region in (tn, kl):
        rates = region["rates"]
        assert (rates["denominator"], rates["failed"]) == (7, 0)
        assert (rates["understood"], rates["partly"], rates["missed"], rates["misread"]) == (2, 2, 1, 2) and rates["understood_rate"] == round(2 / 7, 4)
        assert sum(x["rates"]["denominator"] for x in region["by_language"]) == 7
        assert [p["point_id"] for p in region["points"]] == ["K1", "K2", "K3"] and all(p["denominator"] == 7 for p in region["points"])
        assert region["misreadings"] and {g["label"] for g in region["misreadings"]} == {"Reads as a greeting, not an offer", "Reads as an announcement"}
        assert region["recommendations"] and any("misreading" in x for x in region["recommendations"])
    assert kl["creative"]["headline"] == "Kerala copy" and tn["creative"]["headline"] == campaign["current_version"]["content"]["headline"]
    assert s["overall"]["denominator"] == 14 and s["overall"]["understood"] == 4
    assert "similar words do not show" in " ".join(s["rules"]).lower()

    meta = result["run_metadata"]
    assert meta["providers"] == ["fixture"] and set(meta["prompt_versions"]) == {"message-check-read-v1", "message-check-compare-v1"}
    assert [s["stage"] for s in meta["steps"]] == ["loading_context", "reading_message", "comparing_restatements", "aggregating_results"]


async def test_the_message_defaults_to_the_briefs_primary_message_and_a_missing_one_is_refused(seeded, client: httpx.AsyncClient) -> None:
    project, campaign, _ = await demo_campaign(client)
    url = f"{API}/campaigns/{campaign['id']}/message-checks"
    body = {"targets": [{"region_code": "IN-TN"}], "size_per_region": 4}
    refused = await client.post(url, json=body)
    assert refused.status_code == 422 and any(d["field"] == "intended_message" for d in refused.json()["error"]["details"])
    async with session() as s, s.begin():
        s.add(m.CampaignBriefRow(id=uuid4(), campaign_id=UUID(campaign["id"]), project_id=UUID(project["id"]), version_number=1,
                                 content={"primary_message": MESSAGE}, change_note=None, provenance={}, created_by=None, created_at=utcnow()))
    defaults = (await client.get(f"{API}/campaigns/{campaign['id']}/lab-session-defaults")).json()
    assert defaults["primary_message"] == MESSAGE and defaults["primary_message_source"] == "brief" and len(defaults["key_points"]) == 3
    result = await run_and_read(client, campaign["id"], "message-checks", body)
    assert result["intended_message"] == MESSAGE and result["intended_message_source"] == "brief"
    edited = await run_and_read(client, campaign["id"], "message-checks", body | {"key_points": ["festive sweets", "delivered in time"]})
    assert edited["key_points_source"] == "request" and [k["id"] for k in edited["key_points"]] == ["K1", "K2"]
    assert edited["participants"][0]["response"]["points"][0]["point_id"] == "K1"


async def test_message_check_requests_are_validated_and_bounded(seeded, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _, campaign, _ = await demo_campaign(client)
    url = f"{API}/campaigns/{campaign['id']}/message-checks"
    ok = {"targets": [{"region_code": "IN-TN"}], "intended_message": MESSAGE}

    async def reject(body: dict[str, Any], field: str, text: str = "") -> None:
        response = await client.post(url, json=body)
        assert response.status_code == 422, (body, response.text)
        assert any(d["field"] and d["field"].startswith(field) and text in d["message"] for d in response.json()["error"]["details"]), response.text

    await reject(ok | {"targets": []}, "targets")
    await reject(ok | {"targets": [{"region_code": "IN-TN"}, {"region_code": "IN-TN"}]}, "targets", "once")
    await reject(ok | {"targets": [{"region_code": "IN-ZZ"}]}, "targets")
    await reject(ok | {"targets": [{"region_code": f"IN-{c}"} for c in ("TN", "KL", "WB", "MH", "KA")]}, "targets", "at most 4")
    await reject(ok | {"size_per_region": 13}, "size_per_region", "3 to 12")
    await reject(ok | {"size_per_region": 2}, "size_per_region")
    await reject(ok | {"key_points": []}, "key_points")
    await reject(ok | {"key_points": ["a point"] * 6}, "key_points")
    await reject(ok | {"sampling": {"states": ["IN-KL"]}}, "sampling.states", "target regions")
    await reject(ok | {"sampling": {"gender": ["x"]}}, "sampling", "protected trait")
    other = await live_campaign_demo(client)
    conflict = await client.post(url, json=ok | {"targets": [{"region_code": "IN-TN", "content_version_id": other["current_version"]["id"]}]})
    assert conflict.status_code == 409
    assert (await client.get(url)).json()["total"] == 0


async def test_a_live_message_check_keeps_the_intended_message_from_the_participants_and_leaves_out_unmarked_ones(seeded, client: httpx.AsyncClient, live) -> None:
    campaign, _ = await live_panel(client, live)
    reads: list[dict[str, Any]] = []
    compares: list[dict[str, Any]] = []

    def read(ctx: dict[str, Any]) -> dict[str, Any]:
        reads.append(ctx)
        return SESSION_RESPONDERS["message-check-read-v1"](ctx)

    def compare(ctx: dict[str, Any]) -> dict[str, Any]:
        compares.append(ctx)
        out = SESSION_RESPONDERS["message-check-compare-v1"](ctx)
        out["participants"][0]["points"].pop()  # not marked on every key point: left out, not marked "no"
        out["participants"][1]["points"].append({"point": "K9", "restated": "yes", "recalled": True})  # unknown handle: dropped
        return out

    live.responders["message-check-read-v1"], live.responders["message-check-compare-v1"] = read, compare
    result = await run_and_read(client, campaign["id"], "message-checks", {"targets": [{"region_code": "IN-MH"}], "intended_message": MESSAGE, "size_per_region": 6})
    assert result["status"] == "partial"
    people = result["participants"]
    assert people[0]["response"]["verdict"] is None and people[0]["response"]["points"] == [] and people[0]["response"]["restated"]  # kept, not scored
    assert people[1]["response"]["verdict"] is not None and len(people[1]["response"]["points"]) == 3
    assert result["summary"]["overall"]["denominator"] == 5 and result["summary"]["overall"]["failed"] == 1
    assert any("not fully compared" in lim for lim in result["limitations"]) and any("did not match" in lim for lim in result["limitations"])
    assert result["run_metadata"]["usage"]["model_stages"] == 2 and result["run_metadata"]["providers"] == ["metered"]


async def test_the_participants_prompt_never_contains_the_intended_message(seeded, client: httpx.AsyncClient, live) -> None:
    campaign, _ = await live_panel(client, live)
    prompts: list[str] = []
    original = live.provider.complete

    async def spy(request):
        text = " ".join(str(msg["content"]) for msg in request.messages)
        prompts.append(request.prompt_version + " " + text)
        return await original(request)

    live.provider.complete = spy  # type: ignore[method-assign]
    live.responders["message-check-read-v1"] = SESSION_RESPONDERS["message-check-read-v1"]
    live.responders["message-check-compare-v1"] = SESSION_RESPONDERS["message-check-compare-v1"]
    await run_and_read(client, campaign["id"], "message-checks", {"targets": [{"region_code": "IN-MH"}], "intended_message": MESSAGE, "size_per_region": 4})
    reading = [p for p in prompts if p.startswith("message-check-read-v1")]
    comparing = [p for p in prompts if p.startswith("message-check-compare-v1")]
    assert reading and comparing
    assert all(MESSAGE not in p and "ready to gift" not in p for p in reading)  # readers see only the regional copy
    assert all(MESSAGE in p and "ready to gift" in p for p in comparing)  # the comparison sees the intended message and its key points


async def test_a_message_check_with_no_usable_restatement_fails_without_inventing_a_result(seeded, client: httpx.AsyncClient, live) -> None:
    campaign, _ = await live_panel(client, live)
    live.responders["message-check-read-v1"] = lambda ctx: None
    result = await run_and_read(client, campaign["id"], "message-checks", {"targets": [{"region_code": "IN-MH"}], "intended_message": MESSAGE, "size_per_region": 4})
    assert result["status"] == "failed" and result["error"]["stage"] == "reading_message" and result["summary"] is None
    assert all(p["response"] is None for p in result["participants"])


# --- the run lists, the desk and the migration -----------------------------------------------------------------------------


async def test_session_runs_list_by_kind_and_reach_the_campaign_activity(seeded, client: httpx.AsyncClient) -> None:
    _, campaign, _ = await demo_campaign(client)
    panel = await panel_of(client, campaign["id"])
    fg = await focus(client, campaign["id"], panel["id"], speakers=3, guide=GUIDE[:1])
    buzz = await run_and_read(client, campaign["id"], "buzz-simulations", BUZZ | {"size": 12})
    check = await run_and_read(client, campaign["id"], "message-checks", CHECK)
    base = f"{API}/campaigns/{campaign['id']}"
    for path, run, kind, count in (("focus-groups", fg, "focus_group", 3), ("buzz-simulations", buzz, "buzz_sim", 12), ("message-checks", check, "message_check", 14)):
        page = (await client.get(f"{base}/{path}")).json()
        assert page["total"] == 1 and page["items"][0]["id"] == run["id"] and page["items"][0]["kind"] == kind
        assert page["items"][0]["participant_count"] == count and page["items"][0]["status"] == "completed"
        others = [p for p in ("quick-reads", "audience-studies", "risk-checks") if p != path]
        for other in others:
            assert run["id"] not in [i["id"] for i in (await client.get(f"{base}/{other}")).json()["items"]]
        assert (await client.get(f"{base}/risk-checks/{run['id']}")).status_code == 404  # each kind is read through its own resource
    assert (await client.get(f"{base}/focus-groups/{buzz['id']}")).status_code == 404
    assert (await client.get(f"{base}/message-checks/{buzz['id']}")).status_code == 404


async def test_the_aamod_demo_journey_carries_one_finished_session_of_each_kind_from_fixtures(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.fixtures import demo_aamod as fx
    from tests.api.test_demo_aamod import no_network

    monkeypatch.setenv("DEMO_SEED", "aamod")
    get_settings.cache_clear()
    with no_network():  # the seed reaches no host: the sessions replay fixtures
        created = await client.post(f"{API}/projects/demo")
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    campaign = (await client.get(f"{API}/projects/{pid}/campaigns")).json()["items"][0]
    base = f"{API}/campaigns/{campaign['id']}"
    assert len(campaign["versions"]) == 1  # no scratch version is left behind

    async def only(path: str) -> dict[str, Any]:
        page = (await client.get(f"{base}/{path}")).json()
        assert page["total"] == 1 and page["items"][0]["status"] == "completed" and page["items"][0]["mode"] == "demo"
        return (await client.get(f"{base}/{path}/{page['items'][0]['id']}")).json()

    talk, buzz, check = await only("focus-groups"), await only("buzz-simulations"), await only("message-checks")
    assert talk["regions"] == [{"code": "IN-KL", "name": "Kerala"}] and len(talk["speakers"]) == 5 and len(talk["guide"]) == 3
    kinds = {d["kind"] for d in talk["summary"]["disagreements"]}
    assert kinds == {"stance_split", "direct_challenge"} and talk["summary"]["shifts"] and talk["summary"]["themes"]
    panels = (await client.get(f"{base}/quick-reads")).json()["items"]
    assert talk["panel_run_id"] in {p["id"] for p in panels}
    assert [r["code"] for r in buzz["regions"]] == ["IN-MH", "IN-TN", "IN-KL", "IN-WB"] and buzz["panel"]["generated_size"] == 24
    assert buzz["creative"]["headline"] == "दिवाळी म्हणजे फराळ!" and buzz["intended_message"] == fx.BRIEF_PRIMARY_MESSAGE
    assert 0 < buzz["summary"]["reach"]["exposed"] <= 24 and buzz["summary"]["reach"]["resharers"] >= 1
    assert [r["region"]["code"] for r in check["summary"]["regions"]] == ["IN-TN", "IN-KL", "IN-WB"]
    assert check["intended_message"] == fx.BRIEF_PRIMARY_MESSAGE and len(check["key_points"]) == 3 and len(check["participants"]) == 24
    assert all(r["version_ref"] for r in check["summary"]["regions"])  # each region's copy is a Studio version of the journey
    kl = next(r for r in check["summary"]["regions"] if r["region"]["code"] == "IN-KL")
    tn = next(r for r in check["summary"]["regions"] if r["region"]["code"] == "IN-TN")
    assert kl["rates"]["understood"] < tn["rates"]["understood"]  # the festival-neutral Kerala copy lands less well than Tamil Nadu's
    for run in (talk, buzz, check):
        assert run["run_metadata"]["providers"] == ["fixture"] and run["run_metadata"]["model_ids"] == []
