from __future__ import annotations

import argparse
import hashlib
import json
import random
import tarfile
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import httpx

from chat_chunking.corpus import Block, Document, clean, digest, load_corpus, read_json, write_json

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "local"
RAW = LOCAL / "raw"
DATASET = LOCAL / "dataset.json"
URLS = {
    "dev": "https://qasper-dataset.s3.us-west-2.amazonaws.com/qasper-train-dev-v0.3.tgz",
    "test": "https://qasper-dataset.s3.us-west-2.amazonaws.com/qasper-test-and-evaluator-v0.3.tgz",
}
QUOTAS = {"dev": {"extractive": 8, "abstractive": 4, "boolean": 4, "none": 4},
          "test": {"extractive": 40, "abstractive": 25, "boolean": 15, "none": 20}}


def download() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120, trust_env=False) as client:
        for split, url in URLS.items():
            target = RAW / f"{split}.tgz"
            meta = target.with_suffix(".provenance.json")
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest() != read_json(meta)["sha256"]:
                    raise ValueError(f"Archive checksum mismatch: {target}")
                continue
            temporary = target.with_suffix(".tmp")
            try:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    size = 0
                    with temporary.open("wb") as stream:
                        for part in response.iter_bytes():
                            size += len(part)
                            if size > 100 * 1024 * 1024:
                                raise ValueError("Dataset archive exceeds the100MiB safety cap.")
                            stream.write(part)
                with tarfile.open(temporary, "r:gz") as archive:
                    names = [m.name for m in archive.getmembers()]
                    expected = f"qasper-{split}-v0.3.json"
                    if not any(Path(n).name == expected for n in names):
                        raise ValueError(f"Official archive is missing {expected}.")
                temporary.replace(target)
                write_json(meta, {"url": url, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                                  "bytes": size, "members": names})
            finally:
                temporary.unlink(missing_ok=True)
        # Download the official evaluator and its license, without executing it.
        for name in ("scripts/evaluator.py", "LICENSE"):
            target = RAW / Path(name).name
            if target.exists():
                continue
            url = "https://raw.githubusercontent.com/allenai/qasper-led-baseline/main/" + name
            response = client.get(url)
            response.raise_for_status()
            target.write_bytes(response.content)
            write_json(target.with_suffix(".provenance.json"), {
                "url": url, "sha256": hashlib.sha256(response.content).hexdigest()})


def raw_split(split: str) -> dict:
    with tarfile.open(RAW / f"{split}.tgz", "r:gz") as archive:
        matches = [m for m in archive.getmembers() if Path(m.name).name == f"qasper-{split}-v0.3.json"]
        if len(matches) != 1 or not matches[0].isfile():
            raise ValueError("Ambiguous dataset archive member.")
        stream = archive.extractfile(matches[0])
        if stream is None:
            raise ValueError("Cannot read dataset archive member.")
        return json.load(stream)


def annotation(answer: dict) -> dict:
    if answer["unanswerable"]:
        return {"answer": "Unanswerable", "evidence": [], "type": "none"}
    if answer.get("extractive_spans"):
        text, kind = ", ".join(answer["extractive_spans"]), "extractive"
    elif answer.get("free_form_answer"):
        text, kind = answer["free_form_answer"], "abstractive"
    elif answer.get("yes_no") is not None:
        text, kind = ("Yes" if answer["yes_no"] else "No"), "boolean"
    else:
        raise ValueError("Malformed QASPER annotation: no answer type.")
    return {"answer": text, "type": kind, "evidence": answer["evidence"]}


def paper_document(paper_id: str, paper: dict) -> tuple[Document, list[dict]]:
    blocks: list[Block] = []
    originals: list[str] = []
    if paper.get("abstract", "").strip():
        blocks.append(Block(paper["abstract"], None, "Abstract"))
        originals.append(paper["abstract"])
    for section in paper["full_text"]:
        if section["section_name"].strip():
            blocks.append(Block(section["section_name"], None, section["section_name"]))
            originals.append(section["section_name"])
        for paragraph in section["paragraphs"]:
            if not paragraph.strip():
                continue
            blocks.append(Block(paragraph, None, section["section_name"] or "Unknown"))
            originals.append(paragraph)
    for item in paper.get("figures_and_tables", []):
        caption = item["caption"]
        if not caption.strip():
            continue
        blocks.append(Block(caption, None, "Figures and tables", kind="figure"))
        originals.append("FLOAT SELECTED: " + caption)
    if not blocks:
        raise ValueError(f"QASPER paper has no full text: {paper_id}")
    doc = Document("qasper-" + paper_id, paper["title"], "qasper_annotated_full_text",
                   blocks, ["not_a_fresh_pdf_extraction", "figure_pixels_not_loaded"])
    doc.finalize()
    units = [{"unit_id": f"{paper_id}-p{i}", "original": original, "doc_id": doc.doc_id,
              "start": block.start, "end": block.end, "kind": block.kind}
             for i, (original, block) in enumerate(zip(originals, blocks, strict=True))]
    return doc, units


def resolve_evidence(evidence: str, units: list[dict]) -> dict | None:
    normalized = clean(evidence)
    for unit in units:
        if clean(unit["original"]) == normalized:
            return unit
    if "FLOAT SELECTED" in evidence:
        suffix = normalized.split("FLOAT SELECTED", 1)[1].lstrip(": ").strip()
        matches = [u for u in units if u["kind"] == "figure" and
                   clean(u["original"]).split("FLOAT SELECTED", 1)[1].lstrip(": ").strip() == suffix]
        if len(matches) == 1:
            return matches[0]
    return None


def sample_qasper() -> tuple[list[Document], list[dict], list[dict], dict]:
    docs, cases, units = [], [], []
    used_papers: set[str] = set()
    counts = {}
    for split in ("dev", "test"):
        papers = raw_split(split)
        pool: dict[str, list[tuple[str, dict]]] = {k: [] for k in QUOTAS[split]}
        for pid, paper in sorted(papers.items()):
            for qa in paper["qas"]:
                refs = [annotation(a["answer"]) for a in qa["answers"]]
                if not refs:
                    raise ValueError("A QASPER question has no reference annotations.")
                dominant = Counter(r["type"] for r in refs).most_common(1)[0][0]
                pool[dominant].append((pid, qa))
        rng = random.Random(42 if split == "dev" else 43)
        counts[split] = {}
        for kind in ("none", "boolean", "abstractive", "extractive"):
            candidates = sorted(pool[kind], key=lambda pair: (pair[0], pair[1]["question_id"]))
            rng.shuffle(candidates)
            chosen = []
            for pid, qa in candidates:
                if pid not in used_papers:
                    chosen.append((pid, qa))
                    used_papers.add(pid)
                    if len(chosen) == QUOTAS[split][kind]:
                        break
            if len(chosen) != QUOTAS[split][kind]:
                raise ValueError(f"Cannot satisfy document-disjoint quota: {split}/{kind}")
            for pid, qa in chosen:
                doc, paper_units = paper_document(pid, papers[pid])
                refs = []
                missing = []
                for ref in [annotation(a["answer"]) for a in qa["answers"]]:
                    resolved = [resolve_evidence(e, paper_units) for e in ref["evidence"]]
                    missing.extend(e for e, u in zip(ref["evidence"], resolved, strict=True) if u is None)
                    refs.append({**ref, "evidence_units": [u["unit_id"] if u else None for u in resolved]})
                cases.append({
                    "case_id": "qasper-" + qa["question_id"],
                    "question_id": qa["question_id"], "question": qa["question"],
                    "split": "calibration" if split == "dev" else "held_out",
                    "official_split": split, "track": "qasper", "category": kind,
                    "scope_doc_ids": [doc.doc_id], "references": refs,
                    "alignment_missing": missing,
                    "label_provenance": "independent QASPER practitioners; all reference annotations preserved",
                })
                docs.append(doc)
                units.extend(paper_units)
            counts[split][kind] = len(chosen)
    return docs, cases, units, counts


def freeze() -> dict:
    if DATASET.exists():
        raise FileExistsError(f"Validation data already frozen: {DATASET}")
    docs, cases, units, counts = sample_qasper()
    from .supplement import build_supplement
    supplement_docs, supplement_cases, supplement_units = build_supplement()
    docs += supplement_docs
    cases += supplement_cases
    units += supplement_units
    if len(cases) != 200 or sum(c["split"] == "calibration" for c in cases) != 40:
        raise ValueError("Expected200 cases with40 calibration cases.")
    calibration = {d for c in cases if c["split"] == "calibration" for d in c["scope_doc_ids"]}
    held = {d for c in cases if c["split"] == "held_out" for d in c["scope_doc_ids"]}
    if calibration & held:
        raise ValueError("Calibration and held-out documents overlap.")
    payload = {
        "version": 1, "documents": [asdict(d) for d in docs], "cases": cases, "units": units,
        "qasper_sampling": counts, "seed": 42,
        "alignment_failed_case_ids": [c["case_id"] for c in cases if c.get("alignment_missing")],
        "source_archives": {s: read_json(RAW / f"{s}.provenance.json") for s in URLS},
        "label_limit": "Supplement labels are source-checked by the assistant, not independently human adjudicated. Do not certify95% safety without human review.",
    }
    payload["sha256"] = digest(payload)
    write_json(DATASET, payload)
    return payload


def load_dataset() -> dict:
    payload = read_json(DATASET)
    checked = dict(payload)
    expected = checked.pop("sha256")
    if digest(checked) != expected:
        raise ValueError("Frozen validation dataset checksum mismatch.")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("download", "inspect", "freeze"))
    args = parser.parse_args()
    if args.phase == "download":
        download()
    elif args.phase == "freeze":
        data = freeze()
        print("FROZEN", len(data["cases"]), "cases", len(data["documents"]), "documents",
              "alignment failures", len(data["alignment_failed_case_ids"]))
    else:
        for split in ("dev", "test"):
            papers = raw_split(split)
            print(split, len(papers), "papers", sum(len(p["qas"]) for p in papers.values()), "questions")
            first = next(iter(papers.values()))
            print("schema", list(first), "sample answer", first["qas"][0]["answers"][0]["answer"])


if __name__ == "__main__":
    main()
