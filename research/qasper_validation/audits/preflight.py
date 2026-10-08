"""Three-arm protocol check on one calibration question, separate from final results."""

from __future__ import annotations

import argparse
import json

import numpy as np

from chat_chunking.chunking import ChunkSet
from chat_chunking.corpus import digest, read_json, write_json
from chat_chunking.evaluation import review_metrics
from chat_chunking.local_models import LocalModels, REVIEW_SYSTEM, answer_schema, review_schema
from chat_chunking.retrieval import retrieve
from qasper_validation.chunkers import ARMS
from qasper_validation.runner import ANSWER_SYSTEM, CONFIG, run_path, verify
from qasper_validation.scoring import validate_generated


def main(name: str) -> dict:
    run = run_path(name)
    manifest = verify(run)
    data = read_json(run / "inputs.json")
    case = next(c for c in data["cases"] if c["track"] == "qasper"
                and c["split"] == "calibration" and c["category"] == "extractive")
    scope = digest(sorted(case["scope_doc_ids"]))[:16]
    llm = LocalModels(run / "protocol_preflight", answer=CONFIG["answer"],
                      reviewer=CONFIG["reviewer"], embedding=CONFIG["embedding"])
    records = []
    try:
        if llm.identities != manifest["model_digests"]:
            raise ValueError("Preflight models differ from registered models.")
        query = llm.embed([case["question"]])[0]
        for arm in ARMS:
            path = run / "indexes" / f"{arm}-{scope}.json"
            index = ChunkSet.from_payload(read_json(path))
            vectors = np.load(path.with_suffix(".npy"), allow_pickle=False)
            contexts, _ = retrieve(case["question"], query, index, vectors)
            schema = answer_schema([c.chunk_id for c in contexts])
            schema["properties"]["answer"] = {"type": "string"}
            schema["required"].append("answer")
            answer = llm.chat("answer", [
                {"role": "system", "content": ANSWER_SYSTEM},
                {"role": "user", "content": json.dumps({"question": case["question"],
                    "evidence": [c.payload() for c in contexts]}, ensure_ascii=False)},
            ], schema, "answer-" + arm, 42)
            if answer.get("error"):
                raise ValueError(f"{arm} answer preflight failed: {answer['error']}")
            text, claims = validate_generated(answer["parsed"], {c.chunk_id for c in contexts})
            result = {"arm": arm, "answer_valid": True, "claims": len(claims),
                      "answer_seconds": answer["wall_seconds"]}
            if claims:
                review = llm.chat("reviewer", [
                    {"role": "system", "content": REVIEW_SYSTEM},
                    {"role": "user", "content": json.dumps({"question": case["question"],
                        "answer": text, "claims": claims,
                        "evidence": [c.payload() for c in contexts]}, ensure_ascii=False)},
                ], review_schema([c["claim_id"] for c in claims]), "review-" + arm, 42)
                if review.get("error"):
                    raise ValueError(f"{arm} reviewer preflight failed: {review['error']}")
                review_metrics(claims, contexts, review["parsed"], {})
                result["review_valid"] = True
                result["review_seconds"] = review["wall_seconds"]
            else:
                result["review_skipped"] = "valid abstention"
            records.append(result)
            print("PREFLIGHT", result, flush=True)
        output = {"protocol_check_only": True, "not_used_for_strategy_selection": True,
                  "calibration_case": case["case_id"], "arms": records}
        write_json(run / "protocol_preflight" / "verification.json", output)
        return output
    finally:
        llm.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="qasper-pdf-20261002-v2")
    main(parser.parse_args().run)
