"""Run the faculty-reviewed grounded-compare evaluation set and report separate metrics.

Usage (from backend/):
    python -m scripts.eval_grounded_compare --gold evaluations/compare/grounded/gold.json --owner-id <user id> [--run] [--tier student]

With --run each pair is compared by a fresh background job (refresh=True);
without it, each pair must name an existing grounded "report_id".
"""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.auth import _active_user_id
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.modules.compare.grounded.evaluation import aggregate, evaluate_pair, release_gate
from app.modules.compare.grounded.jobs import CompareJobService
from app.modules.compare.orm.grounded import AnalysisJob, LLMCallLog
from app.modules.compare.schemas.grounded import TERMINAL_STATES, CompareJobRequest
from app.modules.compare.service import CompareService

BACKEND = Path(__file__).resolve().parents[1]


async def run_pair(service: CompareJobService, pair: dict, tier: str | None) -> tuple[str | None, str | None]:
    job = await service.start(pair["space_id"], CompareJobRequest(paper_ids=pair["paper_ids"], refresh=True, tier=tier,
                                                                  check_novelty=bool(pair.get("check_novelty"))))
    while job.state not in TERMINAL_STATES:
        await asyncio.sleep(5)
        job = await service.get(job.id)
        print(f"  {pair['pair_id']}: {job.state} {round(job.progress * 100)}%", flush=True)
    return job.report_id, job.id


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", required=True)
    parser.add_argument("--owner-id", required=True)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--tier", choices=("weak", "student", "deep"))
    parser.add_argument("--thresholds", default=str(BACKEND / "evaluations" / "compare" / "grounded" / "thresholds.json"))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    _active_user_id.set(args.owner_id)
    settings = get_settings()
    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    if not gold.get("faculty_approved"):
        print("WARNING: this gold set is not marked faculty_approved; results cannot support a release decision.")
    jobs = CompareJobService(settings)
    reports = CompareService(settings)
    results = []
    for pair in gold["pairs"]:
        report_id, job_id = (await run_pair(jobs, pair, args.tier)) if args.run else (pair.get("report_id"), None)
        if not report_id:
            print(f"{pair['pair_id']}: no report (job failed or report_id missing)")
            continue
        report = await reports.get_report(report_id)
        job_id = job_id or report.get("job_id")
        async with SessionLocal() as session:
            statuses = list((await session.execute(select(LLMCallLog.parse_status).where(LLMCallLog.job_id == job_id))).scalars().all())
            job = await session.get(AnalysisJob, job_id) if job_id else None
        latency = (job.finished_at - job.created_at).total_seconds() if job and job.finished_at and job.created_at else None
        results.append(evaluate_pair(pair["pair_id"], report, pair, statuses, latency))
        print(pair["pair_id"], json.dumps(results[-1].metrics))
    summary = aggregate(results)
    thresholds = json.loads(Path(args.thresholds).read_text(encoding="utf-8"))
    output = {"generated_at": datetime.now(timezone.utc).isoformat(), "tier": args.tier or settings.grounded_tier,
              "gold": args.gold, "faculty_approved": bool(gold.get("faculty_approved")), "summary": summary,
              "release_gate": release_gate(summary, thresholds),
              "pairs": [{"pair_id": r.pair_id, "metrics": r.metrics, "counts": r.counts, "notes": r.notes} for r in results]}
    text = json.dumps(output, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
