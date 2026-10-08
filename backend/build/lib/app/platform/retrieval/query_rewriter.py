import logging
import re

from app.core.exceptions import LLMUnavailableError
from app.platform.llm.model_router import ModelTier
from app.platform.llm.prompts.loader import PromptLoader
from app.modules.chat.schemas.chat import ConversationContext
from app.platform.llm.model_json import extract_json as _extract_json
from app.platform.llm.model_json import field

logger = logging.getLogger(__name__)

MAX_REWRITE_CHARS = 200
REFERENTIAL = re.compile(r"\b(it|its|they|them|their|this|that|these|those|the paper|the authors|the study|the framework|the model|the approach)\b", re.I)


class QueryRewriter:
    """Resolves follow-up references into a standalone retrieval query.

    Retrieval quality collapses if the raw conversation is used as the query: a long
    context blob embeds to the *previous* topic and floods sparse search with stale
    terms. So we ask a small model for one short self-contained question instead, and
    always keep the original question as a second query for fusion.
    """

    def __init__(self, llm=None, router=None, prompts: PromptLoader | None = None):
        self.llm = llm
        self.router = router
        self.prompts = prompts or PromptLoader()

    async def rewrite(self, question: str, conversation_context: ConversationContext | str | None = None) -> list[str]:
        referenced = list(getattr(conversation_context, "referenced_sessions", None) or [])
        # An @-mentioned conversation is an explicit reference, even without pronouns.
        if not conversation_context or not (referenced or self._needs_rewrite(question)):
            return [question]
        recent = self._recent_exchange(conversation_context)
        if not recent:
            return [question]
        if not (self.llm and self.router):
            return [question]
        try:
            system = self.prompts.render("query_rewriter/system.jinja")
            user = self.prompts.render("query_rewriter/user.jinja", recent=recent, question=question)
            raw = await self.llm.chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                self.router.model_for(ModelTier.SMALL),
                temperature=0.0,
            )
        except (LLMUnavailableError, Exception):
            logger.warning("Query rewrite unavailable; using the original question", exc_info=True)
            return [question]
        standalone = self._clean(raw)
        if not standalone or standalone.lower() == question.lower():
            return [question]
        return [standalone, question]

    def _needs_rewrite(self, question: str) -> bool:
        return bool(REFERENTIAL.search(question))

    def _recent_exchange(self, context) -> str:
        """Only the last couple of turns, truncated — never the whole memory blob."""
        parts = []
        for ref in list(getattr(context, "referenced_sessions", None) or [])[:3]:
            ref_turns = list(getattr(ref, "recent_turns", None) or [])
            gist = getattr(ref, "summary", None) or " ".join(
                f"{getattr(turn, 'role', 'user')}: {getattr(turn, 'content', turn)}" for turn in ref_turns[-2:]
            )
            if gist:
                parts.append(f'referenced conversation "{getattr(ref, "title", "")}": {str(gist)[:MAX_REWRITE_CHARS]}')
        turns = list(getattr(context, "recent_turns", None) or [])
        if not turns and not parts:
            text = context if isinstance(context, str) else ""
            return text[-MAX_REWRITE_CHARS:].strip()
        for turn in turns[-2:]:
            role = getattr(turn, "role", "user")
            content = str(getattr(turn, "content", turn))[:MAX_REWRITE_CHARS]
            parts.append(f"{role}: {content}")
        return "\n".join(parts).strip()

    def _clean(self, raw: str) -> str:
        text = (raw or "").strip().strip("`").strip()
        if text.startswith("{") or (raw or "").lstrip().startswith("```json"):
            try:
                payload = _extract_json(raw)
                if isinstance(payload, dict):
                    value = field(payload, "question", "standalone", "rewritten", "query")
                    if isinstance(value, str):
                        text = value.strip()
                    else:
                        return ""
            except ValueError:
                return ""
        text = text.splitlines()[0] if text else ""
        text = re.sub(r"^(rewritten|standalone|question)\s*[:\-]\s*", "", text, flags=re.I).strip().strip('"')
        return text[:MAX_REWRITE_CHARS]
