import logging
from typing import Any

from app.platform.llm.model_json import extract_json as _extract_json
from app.platform.llm.guardrails import delimit_untrusted
from app.platform.llm.model_router import ModelTier
from app.platform.llm.prompts.loader import PromptLoader
from app.platform.llm.model_json import field, list_items

logger = logging.getLogger(__name__)

NOTE_FIELDS = ("summary", "key_contributions", "methodology", "results", "limitations", "relevance")


class NotesAgent:
    name = "notes_agent"

    def __init__(self, llm=None, router=None, prompts: PromptLoader | None = None):
        self.llm = llm
        self.router = router
        self.prompts = prompts or PromptLoader()

    async def generate(self, paper_title: str, chunks: list[Any]) -> dict:
        if self.llm and self.router:
            evidence = [
                {"chunk_id": getattr(chunk, "chunk_id", str(i)), "text": delimit_untrusted(getattr(chunk, "text", str(chunk)))}
                for i, chunk in enumerate(chunks)
            ]
            messages = [
                {"role": "system", "content": self.prompts.render("notes_agent/system.jinja")},
                {"role": "user", "content": self.prompts.render("notes_agent/user.jinja", paper_title=paper_title, chunks=evidence)},
            ]
            for model_tier, json_format in ((ModelTier.LARGE, False), (ModelTier.MEDIUM, True)):
                try:
                    raw = await self.llm.chat(messages, self.router.model_for(model_tier), temperature=0.1, json_format=json_format)
                    note = self._parse(raw)
                except Exception:
                    logger.warning("Notes generation failed on tier %s", model_tier, exc_info=True)
                    continue
                if self._has_content(note):
                    return note
                logger.warning("Notes generation returned thin content on tier %s", model_tier)
        return self._fallback(paper_title, chunks)

    def _parse(self, raw: str) -> dict:
        obj = _extract_json(raw)
        if not isinstance(obj, dict):
            raise ValueError("notes JSON must be an object")
        contributions = list_items(obj, "key_contributions", aliases=("key_contribution",), text_key="text")
        def narrative(name: str) -> str:
            value = field(obj, name)
            return str(value or "").strip() if not isinstance(value, (dict, list)) else ""
        return {
            "summary": narrative("summary"),
            "key_contributions": [text.strip() for item in contributions
                                  if isinstance(text := field(item, "text", "name"), str) and text.strip()],
            "methodology": narrative("methodology"),
            "results": narrative("results"),
            "limitations": narrative("limitations"),
            "relevance": narrative("relevance"),
        }

    def _has_content(self, note: dict) -> bool:
        # A single short field (often just the echoed title) is not a usable note:
        # require real substance before accepting a tier's output.
        populated = [field for field in NOTE_FIELDS if note.get(field)]
        if len(populated) < 2:
            return False
        narrative = " ".join(str(note.get(field) or "") for field in ("summary", "methodology", "results"))
        return len(narrative.split()) >= 15

    def _fallback(self, paper_title: str, chunks: list[Any]) -> dict:
        text = " ".join(getattr(chunk, "text", str(chunk)) for chunk in chunks).strip()
        words = text.split()
        summary = " ".join(words[:80])
        if len(words) > 80:
            summary += "..."
        return {
            "summary": summary or f"No source text was available for {paper_title}.",
            "key_contributions": [],
            "methodology": "",
            "results": "",
            "limitations": "",
            "relevance": "",
        }
