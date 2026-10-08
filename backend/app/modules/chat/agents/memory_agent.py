import logging
from typing import Any

from app.platform.llm.model_json import extract_json as _extract_json
from app.core.exceptions import LLMUnavailableError
from app.platform.llm.model_router import ModelTier
from app.platform.llm.prompts.loader import PromptLoader
from app.platform.llm.model_json import field, list_items

logger = logging.getLogger(__name__)


class MemoryAgent:
    name = "memory_agent"

    def __init__(self, llm=None, router=None, prompts: PromptLoader | None = None):
        self.llm = llm
        self.router = router
        self.prompts = prompts or PromptLoader()

    async def summarize(self, turns: list[Any], prior_summary: str | None = None) -> str:
        if not (self.llm and self.router):
            return self._fallback_summary(turns, prior_summary)
        messages = [
            {"role": "system", "content": self.prompts.render("memory_agent/system.jinja", task="summary")},
            {"role": "user", "content": self.prompts.render("memory_agent/user.jinja", turns=self._turn_payloads(turns), prior_summary=prior_summary or "", mode="summary")},
        ]
        try:
            raw = await self.llm.chat(messages, self.router.model_for(ModelTier.SMALL), temperature=0.1)
            return raw.strip() or self._fallback_summary(turns, prior_summary)
        except LLMUnavailableError:
            raise
        except Exception:
            logger.warning("Memory summarization failed", exc_info=True)
            return self._fallback_summary(turns, prior_summary)

    async def extract_findings(self, turns: list[Any], prior_findings: dict | None = None) -> dict:
        prior_findings = prior_findings or {"findings": [], "open_questions": []}
        if not (self.llm and self.router):
            return prior_findings
        messages = [
            {"role": "system", "content": self.prompts.render("memory_agent/system.jinja", task="findings")},
            {"role": "user", "content": self.prompts.render("memory_agent/user.jinja", turns=self._turn_payloads(turns), prior_summary="", prior_findings=prior_findings, mode="findings")},
        ]
        for model_tier, json_format in ((ModelTier.SMALL, True), (ModelTier.MEDIUM, False)):
            try:
                raw = await self.llm.chat(messages, self.router.model_for(model_tier), temperature=0.1, json_format=json_format)
                parsed = self._parse_findings(raw)
            except LLMUnavailableError:
                raise
            except Exception:
                logger.warning("Memory findings extraction failed on tier %s", model_tier, exc_info=True)
                continue
            if parsed["findings"] or parsed["open_questions"]:
                return parsed
        return prior_findings

    def _parse_findings(self, raw: str) -> dict:
        obj = _extract_json(raw)
        if not isinstance(obj, dict):
            raise ValueError("findings JSON must be an object")
        findings = list_items(obj, "findings", aliases=("finding",), text_key="text")
        questions = list_items(obj, "open_questions", aliases=("open_question",), text_key="text")
        return {
            "findings": [text.strip() for item in findings
                         if isinstance(text := field(item, "text"), str) and text.strip()],
            "open_questions": [text.strip() for item in questions
                               if isinstance(text := field(item, "text", "question"), str) and text.strip()],
        }

    def _turn_payloads(self, turns: list[Any]) -> list[dict]:
        return [{"role": getattr(turn, "role", "unknown"), "content": getattr(turn, "content", str(turn))} for turn in turns]

    def _fallback_summary(self, turns: list[Any], prior_summary: str | None = None) -> str:
        snippets = []
        if prior_summary:
            snippets.append(prior_summary.strip())
        for turn in turns[-6:]:
            content = getattr(turn, "content", str(turn)).strip()
            if content:
                snippets.append(f"{getattr(turn, 'role', 'turn')}: {content[:180]}")
        return "\n".join(snippets)[-2000:]
