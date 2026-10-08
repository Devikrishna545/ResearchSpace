"""Single gateway for grounded LLM calls: pinned model, fixed seed, raw-output retention."""

import asyncio
import logging
from time import perf_counter
from uuid import uuid4

from app.db.session import SessionLocal
from app.modules.compare.grounded import normalizer as norm
from app.modules.compare.grounded.tiers import TierConfig
from app.modules.compare.orm.grounded import LLMCallLog
from app.db.retry import retry_sqlite_locked

logger = logging.getLogger(__name__)
RAW_LIMIT = 50000


class GroundedLLM:
    def __init__(self, client, tier: TierConfig, *, job_id: str | None = None, timeout_s: float = 300.0,
                 persist_logs: bool = True, concurrency: int = 1):
        self.client = client
        self.tier = tier
        self.job_id = job_id
        self.timeout_s = timeout_s
        self.persist_logs = persist_logs
        self._digests: dict[str, str] | None = None
        self._slot = asyncio.Semaphore(concurrency)
        self.stats: dict[str, int] = {}

    async def digests(self) -> dict[str, str]:
        if self._digests is None:
            getter = getattr(self.client, "model_digests", None)
            self._digests = await getter() if getter else {}
        return self._digests

    async def call(self, *, purpose: str, prompt_version: str, system: str, user: str, list_names=(),
                   text_key: str = "value", schema: dict | None = None, single_object: bool = False,
                   allow_paper_labels: bool = False, paper_id: str | None = None, images: list[str] | None = None,
                   vision: bool = False, max_tokens: int = 2048) -> tuple[norm.NormalizedResult, str]:
        model = self.tier.vision_model if vision else self.tier.text_model
        user_message = {"role": "user", "content": user}
        if images:
            user_message["images"] = images
        messages = [{"role": "system", "content": system}, user_message]
        raw, error = "", None
        start = perf_counter()
        async with self._slot:
            try:
                raw = await self.client.chat(
                    messages, model, temperature=0.0, json_format=schema is None, schema=schema,
                    seed=self.tier.seed, think=self.tier.think, num_ctx=self.tier.num_ctx, timeout=self.timeout_s,
                    # A cap turns a runaway generation into a fast, logged model failure instead of a timeout.
                    num_predict=max_tokens * (4 if self.tier.think else 1),
                )
            except Exception as exc:  # recorded as a model failure, never as a parser defect
                error = f"{type(exc).__name__}: {exc}"[:2000]
        latency = int((perf_counter() - start) * 1000)
        if error:
            result = norm.NormalizedResult(status=norm.MODEL_ERROR, notes=[error])
        elif single_object:
            result = norm.normalize_object(raw)
        else:
            result = norm.normalize(raw, list_names, text_key=text_key, allow_paper_labels=allow_paper_labels)
        self.stats[result.status] = self.stats.get(result.status, 0) + 1
        await self._log(purpose, prompt_version, model, paper_id, raw, result, error, latency)
        return result, model

    async def _log(self, purpose, prompt_version, model, paper_id, raw, result, error, latency):
        if not self.persist_logs:
            return
        digest = (await self.digests()).get(model)

        async def op():
            async with SessionLocal() as session:
                session.add(LLMCallLog(
                    id=str(uuid4()), job_id=self.job_id, paper_id=paper_id, purpose=purpose, model=model,
                    model_digest=digest, prompt_version=prompt_version, seed=self.tier.seed,
                    raw_output=str(raw or "")[:RAW_LIMIT], parse_status=result.status,
                    error=error or (";".join(result.notes)[:2000] if result.status == norm.PARSER_DEFECT else None),
                    latency_ms=latency,
                ))
                await session.commit()
        try:
            await retry_sqlite_locked(op)
        except Exception:
            logger.warning("Could not persist LLM call log", exc_info=True)

    def model_version(self, model: str) -> str:
        digest = (self._digests or {}).get(model)
        return f"{model}@{digest[:12]}" if digest else model
