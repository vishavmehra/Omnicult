"""Builders for Launch Room observations. `good()` is a version that no readiness rule objects to."""

from typing import Any
from uuid import UUID, uuid4

from app.schemas import launch as v


def quick_read(**changes: Any) -> v.QuickReadObservation:
    base = {"respondents": 10, "understood": 8, "confused": 1, "positive": 6, "negative": 2, "relevant": 7, "concerned": 1}
    return v.QuickReadObservation(**(base | changes))


def finding(fid: str = "f1", severity: str = "medium", status: str = "open", blocks_go: bool = False,
            claims: list[UUID] | None = None) -> v.RiskFindingInput:
    return v.RiskFindingInput(
        id=fid, severity=severity, status=status, blocks_go=blocks_go, summary=f"Finding {fid}",  # type: ignore[arg-type]
        claim_ids=claims or [],
    )


def risk(*findings: v.RiskFindingInput) -> v.RiskCheckObservation:
    return v.RiskCheckObservation(findings=list(findings))


def transcreation(**changes: Any) -> v.TranscreationObservation:
    base = {"lines_checked": 10, "glossary_violation_lines": 0, "meaning_preserved_lines": 9}
    return v.TranscreationObservation(**(base | changes))


def objective(status: str = "met", primary: bool = True, oid: str = "o1") -> v.ObjectiveCheck:
    return v.ObjectiveCheck(id=oid, statement=f"Objective {oid}", status=status, primary=primary)  # type: ignore[arg-type]


def meter(strength: str = "solid") -> v.EvidenceMeterObservation:
    return v.EvidenceMeterObservation(strength=strength, claims=40, supported_claims=30)  # type: ignore[arg-type]


def conflict(relied_on: bool = True, status: str = "open", claims: list[UUID] | None = None) -> v.OpenConflictInput:
    return v.OpenConflictInput(
        conflict_id=uuid4(), claim_ids=claims or [], relied_on=relied_on, status=status,  # type: ignore[arg-type]
        summary="Sources disagree on the harvest festival date.",
    )


def good(**changes: Any) -> v.VersionObservations:
    """Every observation present and clean: verdict go, overall 88.2."""
    base: dict[str, Any] = {
        "quick_read": quick_read(), "risk_check": risk(), "transcreation": transcreation(),
        "references": v.ReferenceObservation(references_checked=4, references_supported=3),
        "objective_checks": [objective()], "evidence_meter": meter(),
    }
    return v.VersionObservations(**(base | changes))


def observations_json(**changes: Any) -> dict[str, Any]:
    return good(**changes).model_dump(mode="json")
