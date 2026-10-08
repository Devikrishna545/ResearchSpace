"""Explicit CLI; no application entrypoints, database writes, or import-time runs."""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import os
import platform
import random
import re
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import numpy as np

from .chunking import STRATEGIES, Chunk, ChunkSet, chunk_documents, recursive_spans, tokens
from .corpus import LOCAL, ROOT, digest, load_corpus, read_json, snapshot, write_json
from .evaluation import (answer_metrics, bind_cases, passes, relevance_metrics,
                         review_metrics, summary, threshold_sweep, validate_answer)
from .local_models import (ANSWER_SYSTEM, REVIEW_SYSTEM, LocalModels, answer_schema,
                           review_schema)
from .retrieval import CONTEXT_BUDGET, retrieve, serialized

CONFIG = {"seed": 42, "answer_model": "llama3.2:3b", "reviewer_model": "gemma4:latest",
          "embedding_model": "nomic-embed-text:latest", "tokenizer": "cl100k_base",
          "context_budget": CONTEXT_BUDGET, "top_k": 8, "num_ctx": 8192,
          "generation_temperature": 0, "baseline_size": 650, "baseline_overlap": 81,
          "structured_max": 800, "recursive_child": 320, "semantic_boundary": 0.65,
          "review_reference_threshold": 0.9, "similarity_reference_threshold": 0.65}


def source_hash() -> str:
    return digest({p.name: p.read_text(encoding="utf-8")
                   for p in sorted(ROOT.glob("*.py"))})


def models(run: Path) -> LocalModels:
    return LocalModels(run, answer=CONFIG["answer_model"], reviewer=CONFIG["reviewer_model"],
                       embedding=CONFIG["embedding_model"])


def safe_run(name: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        raise ValueError("Run name must contain only letters, numbers, underscores, and hyphens.")
    return LOCAL / "runs" / name


def input_paths(run: Path, manifest: dict) -> tuple[Path, Path]:
    if "corpus_file" in manifest:
        corpus = (run / manifest["corpus_file"]).resolve()
        cases = (run / manifest["case_spec_file"]).resolve()
        if not corpus.is_relative_to(run.resolve()) or not cases.is_relative_to(run.resolve()):
            raise ValueError("Run input paths must stay within the run.")
        return corpus, cases
    return LOCAL / "corpus.json", ROOT / "cases.json"


def verify_manifest(run: Path) -> dict:
    manifest = read_json(run / "manifest.json")
    if manifest["code_sha256"] != source_hash() or manifest["config"] != CONFIG:
        raise ValueError("Experiment code/config changed; use a new run instead of mixing results.")
    corpus_path, case_path = input_paths(run, manifest)
    if digest(read_json(corpus_path)) != manifest["corpus_file_sha256"]:
        raise ValueError("Corpus changed after run registration.")
    if digest(read_json(case_path)) != manifest["case_spec_sha256"]:
        raise ValueError("Questions/rubrics changed after run registration.")
    if digest(read_json(run / "cases.json")) != manifest["cases_sha256"]:
        raise ValueError("Bound source labels changed after run registration.")
    return manifest


def check_model_identity(client: LocalModels, manifest: dict) -> None:
    if client.identities != manifest["models"]:
        raise ValueError("Installed model digests changed; refusing mixed-model evaluation.")


def freeze_input(path: Path, data: dict) -> None:
    if path.exists():
        if digest(read_json(path)) != digest(data):
            raise ValueError(f"Refusing to replace a frozen run input: {path}")
    else:
        write_json(path, data)


def prepare(name: str, corpus_path: Path | None = None, case_path: Path | None = None) -> None:
    run = safe_run(name)
    if (run / "manifest.json").exists():
        manifest = verify_manifest(run)
        frozen_corpus, frozen_cases = input_paths(run, manifest)
        for supplied, frozen in ((corpus_path, frozen_corpus), (case_path, frozen_cases)):
            if supplied is not None and digest(read_json(supplied)) != digest(read_json(frozen)):
                raise ValueError("Supplied inputs differ from the already registered run.")
        corpus_path, case_path = frozen_corpus, frozen_cases
    else:
        corpus_path = corpus_path or LOCAL / "corpus.json"
        case_path = case_path or ROOT / "cases.json"
    docs = load_corpus(corpus_path)
    specification = read_json(case_path)
    cases = bind_cases(docs, specification)
    if len(cases) != 24 or sum(c["split"] == "calibration" for c in cases) != 8:
        raise ValueError("Expected 24 preregistered questions, including eight calibration questions.")
    client = models(run)
    try:
        if (run / "manifest.json").exists():
            manifest = verify_manifest(run)
            check_model_identity(client, manifest)
        else:
            freeze_input(run / "inputs" / "corpus.json", read_json(corpus_path))
            freeze_input(run / "inputs" / "case_spec.json", specification)
            warm_schema = {"type": "object", "properties": {"ready": {"type": "boolean"}},
                           "required": ["ready"], "additionalProperties": False}
            for role in ("answer", "reviewer"):
                record = client.chat(role, [{"role": "user", "content": 'Return {"ready":true}.'}],
                                     warm_schema, "warmup-" + role)
                if record.get("error") or record.get("parsed") != {"ready": True}:
                    raise ValueError(f"Required {role} model failed structured-output preflight: {record}")
            client.embed(["Research benchmark embedding warmup."])
            manifest = {
                "created_at": datetime.now(timezone.utc).isoformat(), "config": CONFIG,
                "models": client.identities, "ollama_version": client.version,
                "code_sha256": source_hash(), "corpus_file_sha256": digest(read_json(corpus_path)),
                "case_spec_sha256": digest(specification), "cases_sha256": digest(cases),
                "corpus_file": "inputs/corpus.json", "case_spec_file": "inputs/case_spec.json",
                "source_checks": read_json(corpus_path).get("source_checks", []),
                "python": sys.version, "platform": platform.platform(),
                "packages": {p: importlib.metadata.version(p) for p in
                             ("httpx", "numpy", "pypdf", "pdfplumber", "fonttools", "tiktoken")},
                "source_limitations": [{"title": d.title, "source_kind": d.source_kind, "flags": d.flags,
                                       "blocks": len(d.blocks), "tokens": tokens(d.text),
                                       "kinds": {k: sum(b.kind == k for b in d.blocks) for k in ("text", "table", "figure")}}
                                      for d in docs],
                "design": "first-pass controlled hybrid RAG; same-source representations, not production integration",
            }
            write_json(run / "manifest.json", manifest)
            write_json(run / "cases.json", cases)
        query_started = perf_counter()
        query_vectors = client.embed([case["question"] for case in cases])
        query_seconds = perf_counter() - query_started
        order = list(STRATEGIES)
        random.Random(CONFIG["seed"]).shuffle(order)
        for strategy in order:
            index_path = run / "indexes" / f"{strategy}.json"
            if index_path.exists():
                print(f"RESUME index {strategy}", flush=True)
                continue
            print(f"INDEX {strategy}", flush=True)
            before_hits, before_misses = client.embed_hits, client.embed_misses
            chunk_set = chunk_documents(docs, strategy, client.embed)
            started = perf_counter()
            vectors = client.embed([c.text for c in chunk_set.children])
            indexing_seconds = perf_counter() - started
            sizes = [tokens(c.text) for c in chunk_set.children]
            report = chunk_set.payload()
            report["metrics"] = {
                "children": len(chunk_set.children), "parents": len(chunk_set.parents),
                "chunk_tokens_min": min(sizes), "chunk_tokens_median": float(np.median(sizes)),
                "chunk_tokens_max": max(sizes), "indexed_tokens": sum(sizes),
                "embedding_seconds": indexing_seconds, "build_seconds": chunk_set.build_seconds,
                "semantic_embedding_seconds": chunk_set.semantic_embedding_seconds,
                "embedding_cache_hits": client.embed_hits - before_hits,
                "embedding_cache_misses": client.embed_misses - before_misses,
                "vector_bytes": int(vectors.nbytes), "vectors_shape": list(vectors.shape),
            }
            for qi, case in enumerate(cases):
                started = perf_counter()
                contexts, ranking = retrieve(case["question"], query_vectors[qi], chunk_set, vectors)
                row = {
                    "case_id": case["id"], "strategy": strategy, "split": case["split"],
                    "category": case["category"], "unanswerable": bool(case.get("unanswerable")),
                    "question": case["question"], "contexts": [asdict(c) for c in contexts],
                    "ranking": ranking, "context_tokens": tokens(serialized(contexts)),
                    "retrieval_seconds": perf_counter() - started,
                    "shared_query_embedding_seconds_per_query": query_seconds / len(cases),
                    "answer_rubric_coverage": None if case.get("unanswerable") else 0.0,
                    "full_rubric_match": False, "reference_supported_answer": False,
                    "abstained": False, **relevance_metrics(case, contexts),
                }
                write_json(run / "retrieval" / f"{strategy}-{case['id']}.json", row)
            index_path.parent.mkdir(parents=True, exist_ok=True)
            np.save(index_path.with_suffix(".npy"), vectors, allow_pickle=False)
            write_json(index_path, report)
            print("INDEXED", strategy, report["metrics"], flush=True)
    finally:
        client.close()


def record_paths(run: Path) -> list[Path]:
    paths = sorted((run / "retrieval").glob("*.json"))
    if len(paths) != 96:
        raise ValueError(f"Expected 96 retrieval records, found {len(paths)}; complete preparation first.")
    random.Random(CONFIG["seed"]).shuffle(paths)
    return paths


def answer(name: str) -> None:
    run = safe_run(name)
    manifest = verify_manifest(run)
    cases = {c["id"]: c for c in read_json(run / "cases.json")}
    client = models(run)
    try:
        check_model_identity(client, manifest)
        for number, path in enumerate(record_paths(run), 1):
            target = run / "answers" / path.name
            if target.exists():
                continue
            row = read_json(path)
            print(f"ANSWER {number}/96 {path.stem}", flush=True)
            contexts = [Chunk(**c) for c in row["contexts"]]
            if not contexts:
                row["error"] = "No source evidence fit the context budget."
                write_json(target, row)
                continue
            record = client.chat("answer", [
                {"role": "system", "content": ANSWER_SYSTEM},
                {"role": "user", "content": json.dumps({"question": row["question"], "evidence": [c.payload() for c in contexts]}, ensure_ascii=False)},
            ], answer_schema([c.chunk_id for c in contexts]), "answer-" + path.stem)
            row["answer_seconds"] = record["wall_seconds"]
            row["answer_prompt_tokens"] = record.get("raw", {}).get("prompt_eval_count")
            row["answer_output_tokens"] = record.get("raw", {}).get("eval_count")
            row["answer_load_seconds"] = record.get("raw", {}).get("load_duration", 0) / 1e9
            if record.get("error"):
                row["error"] = record["error"]
            else:
                try:
                    claims = validate_answer(record["parsed"], contexts)
                    row["claims"] = claims
                    row.update(answer_metrics(cases[row["case_id"]], claims, contexts))
                except ValueError as exc:
                    row["error"] = str(exc)
            write_json(target, row)
    finally:
        client.close()


def similarity_metrics(name: str) -> None:
    run = safe_run(name)
    manifest = verify_manifest(run)
    client = models(run)
    try:
        check_model_identity(client, manifest)
        for path in record_paths(run):
            target = run / "similarities" / path.name
            if target.exists():
                continue
            row = read_json(run / "answers" / path.name)
            context = {c["chunk_id"]: c["text"] for c in row["contexts"]}
            scores: dict[str, float] = {}
            started = perf_counter()
            for claim in row.get("claims", []):
                evidence_scores = []
                for cid in claim["cited_chunk_ids"]:
                    if cid not in context:
                        evidence_scores.append(-1.0)
                        continue
                    text = context[cid]
                    # Match against bounded excerpts rather than assuming a large
                    # context's aggregate vector proves every sentence in it.
                    windows = [text[a:b] for a, b in recursive_spans(text, 0, len(text), 160)]
                    vectors = client.embed([claim["text"], *windows])
                    evidence_scores.append(float(np.max(vectors[1:] @ vectors[0])))
                scores[claim["claim_id"]] = min(evidence_scores, default=-1)
            row["claim_similarities"] = scores
            row["similarity_seconds"] = perf_counter() - started
            write_json(target, row)
    finally:
        client.close()


def review(name: str) -> None:
    run = safe_run(name)
    manifest = verify_manifest(run)
    client = models(run)
    try:
        check_model_identity(client, manifest)
        for number, path in enumerate(record_paths(run), 1):
            target = run / "results" / path.name
            if target.exists():
                continue
            row = read_json(run / "similarities" / path.name)
            if row.get("error") or not row.get("claims"):
                row["review_seconds"] = 0.0
                row["review_skipped_reason"] = "generation failure" if row.get("error") else "abstention: no factual claims to review"
                write_json(target, row)
                continue
            print(f"REVIEW {number}/96 {path.stem}", flush=True)
            contexts = [Chunk(**c) for c in row["contexts"]]
            record = client.chat("reviewer", [
                {"role": "system", "content": REVIEW_SYSTEM},
                {"role": "user", "content": json.dumps({
                    "question": row["question"], "claims": row["claims"],
                    "evidence": [c.payload() for c in contexts]}, ensure_ascii=False)},
            ], review_schema([c["claim_id"] for c in row["claims"]]), "review-" + path.stem)
            row["review_seconds"] = record["wall_seconds"]
            row["review_load_seconds"] = record.get("raw", {}).get("load_duration", 0) / 1e9
            row["review_prompt_tokens"] = record.get("raw", {}).get("prompt_eval_count")
            row["review_output_tokens"] = record.get("raw", {}).get("eval_count")
            if record.get("error"):
                row["error"] = "review: " + record["error"]
            else:
                try:
                    row.update(review_metrics(row["claims"], contexts, record["parsed"], row["claim_similarities"]))
                except ValueError as exc:
                    row["error"] = "review: " + str(exc)
            write_json(target, row)
    finally:
        client.close()


def report(name: str) -> dict:
    run = safe_run(name)
    manifest = verify_manifest(run)
    paths = sorted((run / "results").glob("*.json"))
    rows = [read_json(p) for p in paths]
    if len(rows) != 96:
        raise ValueError(f"Run incomplete: {len(rows)}/96 results. No success-shaped report is produced.")
    sweep, chosen = threshold_sweep(rows)
    per_strategy = {}
    for strategy in STRATEGIES:
        selected = [r for r in rows if r["strategy"] == strategy]
        held = [r for r in selected if r["split"] == "held_out"]
        accepted = [r for r in held if passes(r, chosen["review_threshold"], chosen["similarity_threshold"])]
        per_strategy[strategy] = {
            "all": summary(selected), "held_out": summary(held),
            "index": read_json(run / "indexes" / f"{strategy}.json")["metrics"],
            "held_out_selected_gate": {
                "accepted": len(accepted), "attempts": len(held),
                "reference_supported": sum(bool(r.get("reference_supported_answer")) for r in accepted),
                "proxy_precision": mean_bool(accepted, "reference_supported_answer"),
            },
            "by_category": {category: summary([r for r in selected if r["category"] == category])
                            for category in sorted({r["category"] for r in selected})},
        }
    output = ROOT / "reports" / name
    output.mkdir(parents=True, exist_ok=True)
    aggregate = {"manifest": manifest, "strategies": per_strategy,
                 "threshold_selection": chosen, "threshold_sweep_calibration_only": sweep}
    write_json(output / "summary.json", aggregate)
    columns = ["strategy", "case_id", "split", "category", "unanswerable", "evidence_recall",
               "mrr", "context_precision", "context_tokens", "answer_rubric_coverage",
               "full_rubric_match", "reference_supported_answer", "abstained", "claim_count",
               "citation_validity", "cited_gold_coverage", "supported_claim_rate",
               "quote_provenance_rate", "review_score", "min_citation_similarity",
               "retrieval_seconds", "answer_seconds", "review_seconds", "similarity_seconds",
               "answer_load_seconds", "review_load_seconds", "error"]
    with (output / "per_question.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({key: value["held_out"] for key, value in per_strategy.items()}, indent=2), flush=True)
    return aggregate


def mean_bool(rows: list[dict], key: str) -> float | None:
    return sum(bool(r.get(key)) for r in rows) / len(rows) if rows else None


def main() -> None:
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(ROOT.parent / ".cache"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("snapshot", "validate", "prepare", "answer", "similarity", "review", "report", "run"))
    parser.add_argument("--run", default="pilot-20261002-v2")
    parser.add_argument("--corpus", type=Path, help="Read a new corpus; freeze it inside a new run.")
    parser.add_argument("--cases", type=Path, help="Read new case definitions; freeze them inside a new run.")
    parser.add_argument("--database", type=Path, default=ROOT.parents[1] / "backend" / "data" / "dev.db")
    parser.add_argument("--upload-root", type=Path,
                        default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "R.Space" / "uploads")
    args = parser.parse_args()
    if (args.corpus or args.cases) and args.phase not in {"prepare", "run", "validate"}:
        parser.error("--corpus/--cases apply only to prepare, run, or validate; later phases use frozen run inputs.")
    if args.phase == "snapshot":
        snapshot(args.database, args.upload_root, LOCAL / "corpus.json")
    elif args.phase == "validate":
        docs = load_corpus(args.corpus or LOCAL / "corpus.json")
        cases = bind_cases(docs, read_json(args.cases or ROOT / "cases.json"))
        print(f"Validated {len(docs)} documents and {len(cases)} source-grounded cases.")
    elif args.phase == "run":
        prepare(args.run, args.corpus, args.cases)
        for phase in (answer, similarity_metrics, review, report):
            phase(args.run)
    elif args.phase == "prepare":
        prepare(args.run, args.corpus, args.cases)
    else:
        {"answer": answer, "similarity": similarity_metrics,
         "review": review, "report": report}[args.phase](args.run)


if __name__ == "__main__":
    main()
