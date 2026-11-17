"""The Idempotency-Key request header, carried to `services.runs._create_run` through a context variable.

A client that retries a run-creating POST with the same key gets the run it already created instead of a second one.
Keys are unique per user (a unique index on agent_runs(created_by, idempotency_key)).
"""

import re
from contextvars import ContextVar

IDEMPOTENCY_HEADER = "Idempotency-Key"
VALID_KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

idempotency_key_var: ContextVar[str | None] = ContextVar("idempotency_key", default=None)
