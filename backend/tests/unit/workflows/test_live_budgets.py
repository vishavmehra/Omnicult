"""Output budgets that keep live runs inside their deadlines. No network."""

import json

from app.agents import transcreate as agent
from app.llm.gateway import Completion, LLMGateway
from app.llm.registry import spec_for
from app.schemas.versions import Tone
from tests.unit.workflows.scenario import offline_settings


class Recording:
    """Answers a Transcreate request with one valid line per handle and remembers the request."""

    name = "recording"

    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        count = max(1, sum(1 for h in range(1, 40) if f'"L{h}"' in request.messages[1]["content"]))
        lines = [{"line": f"L{n}", "regional_copy": "x", "back_translation": "y", "explanation": "z"} for n in range(1, count + 1)]
        return Completion(text=json.dumps({"lines": lines}))


async def generate(count: int) -> int:
    provider = Recording()
    lines = {f"L{n}": {"element_id": f"e{n}", "kind": "headline", "text": "t"} for n in range(1, count + 1)}
    drafts, _, _ = await agent.generate_lines(
        LLMGateway(offline_settings(), provider=provider, backoff_seconds=0), stage="transcreating_lines", lines=lines,
        region_name="Maharashtra", region_code="IN-MH", language="mr", language_name="Marathi", script="Devanagari",
        tone=Tone().model_dump(), claims=[], glossary=[], brand="")
    assert len(drafts) == count
    (request,) = provider.requests
    headroom = spec_for(request.model).thinking_headroom if spec_for(request.model) else 0
    return request.max_tokens - headroom


async def test_transcreate_keeps_the_default_output_budget_for_a_few_lines_and_scales_it_for_many():
    assert await generate(1) == 4096 and await generate(4) == 4096  # never below the gateway default
    assert await generate(12) == agent.LINE_TOKENS * 12 + 400  # 12 Indic lines no longer share a 4096-token answer
