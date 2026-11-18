"""Demo-mode fixtures for the Launch Room delivery features on the fictional Aamod journey.

Two stakeholder responses on a review link, written by hand and labelled as samples. They are advice to the approvers, never
approvals, and nothing here is research or a native speaker's judgement.
"""

LINK_LABEL = "Regional heads: Tamil Nadu and Kerala (sample)"
LINK_NOTE = "Please read the regional lines and tell us if anything sounds wrong for your state. Sample link of the demonstration."
APPROVAL_REASON = "Approved on a Go recommendation. Demonstration decision on a fictional brand."

# (region code, decision, reviewer name or None, comment or None)
RESPONSES: tuple[tuple[str, str, str | None, str | None], ...] = (
    ("IN-TN", "approve", "Regional head, Tamil Nadu (sample)", None),
    ("IN-KL", "request_changes", None, "The delivery promise should name a festival day the Kerala team can actually ship by. Sample comment."),
)
