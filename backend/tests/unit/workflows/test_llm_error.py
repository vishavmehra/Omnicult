"""A failed model call reports one thing: the message and the retryable flag never disagree."""

from app.llm.gateway import LLMError
from app.schemas.common import StepTrace
from app.workflows._common import llm_error

SAVED = "No reactions were saved; retrying is safe."


def failure(code: str, retryable: bool) -> LLMError:
    return LLMError(code, "The model provider rejected the request." if not retryable else "The model provider timed out.",
                    retryable=retryable, trace=StepTrace(stage="s", agent="a", status="failed", error_code=code))


def test_a_retryable_failure_keeps_the_retry_note():
    error = llm_error(failure("PROVIDER_TIMEOUT", True), "generating_reactions", SAVED)
    assert error.retryable and error.message.endswith("No reactions were saved; retrying is safe.")


def test_a_failure_that_will_repeat_does_not_say_retrying_is_safe():
    for code in ("PROVIDER_ERROR", "CONTENT_BLOCKED", "BUDGET_EXCEEDED"):
        error = llm_error(failure(code, False), "generating_reactions", SAVED)
        assert not error.retryable and "retrying is safe" not in error.message.lower()
        assert error.message == "The model provider rejected the request. No reactions were saved."
    assert llm_error(failure("PROVIDER_ERROR", False), "s", "Nothing was saved; retrying is safe.").message.endswith("Nothing was saved.")
