"""Adapt source serialization, not expected answers, for the full-PDF rerun."""

from __future__ import annotations

from copy import deepcopy

from .corpus import ROOT, digest, load_corpus, read_json, write_json
from .evaluation import bind_cases
from .full_pdf import DATASET


def definitions(original: dict) -> dict:
    data = deepcopy(original)
    data["version"] = 2
    data["parent_case_spec_sha256"] = digest(original)
    data["adaptations"] = {
        "q19": "Replace the non-PDF web introduction with Preskill's original NISQ research paper.",
        "other_questions": "The remaining23 questions, splits and answer rubrics are unchanged.",
        "evidence_patterns": "Accept whitespace/page-layout serialization; expected values and semantic labels unchanged.",
        "q17_category": "Full-PDF abstract question, no longer an abstract-only source.",
    }
    for case in data["cases"]:
        for evidence in case["evidence"]:
            evidence["pattern"] = evidence["pattern"].replace(" ", r"\s+")
        if case["id"] == "q17":
            case["category"] = "abstract_definition"
        if case["id"] == "q19":
            case.update({
                "category": "full_pdf_noise",
                "question": "In Preskill's NISQ paper, what does NISQ stand for and how does noise in quantum gates constrain computation?",
                "evidence": [{
                    "title": "Quantum Computing in the NISQ era",
                    "pattern": r"Noisy\s+Intermediate-Scale\s+Quantum.{0,500}noise\s+in\s+quantum\s+gates\s+will\s+limit\s+the\s+size\s+of\s+quantum\s+circuits",
                }],
                "concepts": [r"Noisy\s+Intermediate.Scale\s+Quantum",
                             r"noise|errors?", r"(?:limit|restrict|constrain|size|depth|length).{0,60}circuit|circuit.{0,60}(?:limit|restrict|constrain|size|depth|length)"],
            })
    return data


def main() -> None:
    output = DATASET / "case_spec.json"
    if output.exists():
        raise FileExistsError(f"Frozen full-PDF questions already exist: {output}")
    spec = definitions(read_json(ROOT / "cases.json"))
    cases = bind_cases(load_corpus(DATASET / "corpus.json"), spec)
    if len(cases) != 24:
        raise ValueError("Expected24 questions.")
    write_json(output, spec)
    print("Validated and froze24 full-PDF cases;23 question/rubric pairs unchanged.")


if __name__ == "__main__":
    main()
