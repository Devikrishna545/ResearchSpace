"""Preregistered source-checked PDF questions; not independent human annotations."""

from __future__ import annotations

import re
from copy import deepcopy

from chat_chunking.corpus import LOCAL as PILOT_LOCAL, Document, load_corpus

# (category, question, concise reference answer, source anchor, numeric assertion)
FACTS = {
    "guppy-fullpdf": [
        ("definition", "In which host language is Guppy embedded?", "Python", r"domain-specific language embedded in Python", None),
        ("definition", "What type of programs is Guppy designed to express?", "Hybrid quantum-classical programs with complex control flow.", r"high-level hybrid quantum programs with complex control flow", None),
        ("method", "What two operations are disallowed for Guppy's linear qubits?", "They cannot be copied or discarded.", r"Qubits in.{0,40}linear.{0,80}cannot be copied or discarded", None),
        ("method", "When does Guppy catch common errors associated with linear qubits?", "At compile time.", r"catch common programming errors at compile time", None),
        ("method", "What intermediate representation does Guppy statically compile to?", "Hugr", r"statically compiled.{0,130}Hugr", None),
        ("figure", "Which protocol is illustrated by Guppy Figure 1b?", "Quantum teleportation.", r"Figure 1b implements the quantum teleportation protocol", None),
        ("method", "Which decorator marks a function for the Guppy compiler?", "@guppy", r"users add the @guppy decorator", None),
        ("method", "How are pytket circuits represented as Guppy functions?", "As functions of type list[Qubit] -> list[Qubit].", r"pytket.{0,120}list\[Qubit\].{0,30}list\[Qubit\]", None),
    ],
    "qppl-fullpdf": [
        ("definition", "What kind of data does Quantum Programming Without the Quantum Physics use?", "Familiar classical data.", r"all data are familiar classical data", None),
        ("method", "What is the proposal's only nonclassical primitive?", "A random number generator that can return negative probabilities.", r"only non-classical element.{0,130}negative probabil", None),
        ("method", "How does the paper describe measurement without qubits?", "As effective loss of signs on probabilities.", r"measurements can be understood.{0,120}loss of signs on probabilities", None),
        ("method", "Are reversibility constraints derived or imposed ad hoc in the proposal?", "Derived from commonsense assumptions about probabilistic programming.", r"reversibility are derived.{0,180}ad-hoc basis", None),
        ("definition", "What is the name of the simple quantum programming language presented?", "QPPL", r"simple quantum programming language QPPL", None),
        ("definition", "What is the name of the toy classical probabilistic language?", "CPPL", r"toy language, CPPL", None),
        ("method", "What change turns the classical probabilistic model into the quantum model?", "Allowing negative probabilities.", r"negative probabilities, giving a simple quantum programming language QPPL", None),
        ("method", "Does the proposal need qubits or collapse to capture measurement semantics?", "No; it captures measurement semantics without mentioning qubits or collapse.", r"semantics of measurement without ever mentioning qubits or collapse", None),
    ],
    "glove-fullpdf": [
        ("definition", "Which two families of word-vector methods does GloVe combine?", "Global matrix factorization and local context-window methods.", r"global matrix factorization and local context window methods", None),
        ("method", "Does GloVe train on all co-occurrence matrix cells or only nonzero elements?", "Only nonzero elements of the word-word co-occurrence matrix.", r"training only on the nonzero elements.{0,100}occurrence matrix", None),
        ("numeric", "What cutoff x_max is used in the GloVe weighting function?", "100", r"fix to xmax = 100", r"\b100\b"),
        ("numeric", "What alpha exponent is used in GloVe Figure1?", "3/4", r"Figure 1: Weighting function.{0,40}3/4", r"3\s*/\s*4|0\.75"),
        ("numeric", "How many most-frequent words are retained in GloVe's vocabulary?", "400,000", r"vocabulary of the 400,000 most frequent words", r"400[ ,]?000|400\s*(?:k|thousand)"),
        ("table", "What is total analogy accuracy for GloVe 300 on 42B tokens in Table 2?", "75.0%", r"GloVe 300 42B\s*\|?\s*81\.9 69\.3 75\.0", r"\b75(?:\.0)?\s*(?:%|percent)?\b"),
        ("table", "What is semantic analogy accuracy for GloVe 300 on 42B tokens in Table 2?", "81.9%", r"GloVe 300 42B\s*\|?\s*81\.9 69\.3 75\.0", r"81\.9"),
        ("table", "What is syntactic analogy accuracy for GloVe 300 on 42B tokens in Table 2?", "69.3%", r"GloVe 300 42B\s*\|?\s*81\.9 69\.3 75\.0", r"69\.3"),
        ("figure", "What vector dimensionality is shared by GloVe Figure 4 models?", "300 dimensions.", r"Figure 4:.{0,600}300-dimensional vectors", r"\b300\b"),
        ("figure", "What symmetric window size is used for GloVe Figure 4?", "10", r"Figure 4:.{0,850}symmetric context window of size 10", r"\b10\b"),
        ("method", "Which statistic evaluates GloVe word-similarity scores against human judgements?", "Spearman rank correlation.", r"Spearman.{0,20}rank correlation coefficient", None),
        ("cross_paper", "Contrast GloVe training statistics with Skip-gram's prediction objective.", "GloVe uses global word co-occurrence statistics; Skip-gram predicts surrounding words from a current word.", r"global word-word co-occurrence counts", None),
    ],
    "word2vec-fullpdf": [
        ("definition", "Which two architectures are proposed in Efficient Estimation of Word Representations?", "Continuous Bag-of-Words and Continuous Skip-gram.", r"3\.1 Continuous Bag-of-Words Model", None),
        ("method", "Does CBOW preserve the order of context words?", "No, their order does not influence the projection.", r"order of words.{0,250}projection", None),
        ("method", "What word serves as Skip-gram input?", "The current word.", r"we use each current word as an input", None),
        ("method", "What does Skip-gram try to predict from the current word?", "Words before and after the current word within a context range.", r"we use each current word as an input.{0,420}current word", None),
        ("numeric", "What training time is reported in the word2vec abstract?", "Less than a day.", r"less than a day.{0,100}1\.6 billion", None),
        ("numeric", "What dataset size is reported in the word2vec abstract?", "1.6 billion words.", r"less than a day.{0,100}1\.6 billion", r"1\.6\s*(?:billion|B)"),
        ("method", "Which tree represents the vocabulary in word2vec hierarchical softmax?", "A Huffman binary tree.", r"vocabulary is represented as a Huffman binary tree", None),
        ("numeric", "What dimension is used in word2vec Table 3's architecture comparison?", "640 dimensions.", r"Table 3:.{0,180}640-dimensional", r"\b640\b"),
        ("numeric", "How large is the Google News corpus used in the accuracy maximization experiment?", "About 6 billion tokens.", r"Google News corpus.{0,100}6B tokens", r"\b6\s*(?:B|billion)"),
        ("numeric", "How many words are retained for the Google News experiment's vocabulary?", "1 million most frequent words.", r"vocabulary size to 1 million most frequent words", r"\b1\s*million|1[ ,]?000[ ,]?000"),
        ("method", "What binary codes do Huffman trees assign to frequent words?", "Short binary codes.", r"Huffman trees assign short binary codes to frequent words", None),
        ("cross_paper", "How does word2vec's Google News vocabulary size compare with GloVe's vocabulary?", "Word2vec uses 1 million most frequent words; GloVe uses 400,000.", r"vocabulary size to 1 million most frequent words", r"1\s*million|1[ ,]?000[ ,]?000"),
    ],
    "tensor-fullpdf": [
        ("definition", "What main difficulty of tensor-network algorithms does Tensor Quantum Programming identify?", "High ranks, also called bond dimensions.", r"primary challenge.{0,110}high ranks \(bond dimensions\)", None),
        ("method", "What objects are encoded as quantum circuits by the proposed algorithm?", "Matrix Product Operators.", r"encodes Matrix Product Operators into quantum circuits", None),
        ("method", "How does the proposed circuit depth scale with the qubit count?", "Linearly.", r"depth that depends linearly on the number of qubits", None),
        ("numeric", "Up to how many qubits does Tensor Quantum Programming demonstrate effectiveness?", "50 qubits.", r"effectiveness on up to 50 qubits", r"\b50\b"),
        ("method", "What two tensor-based procedures were already known before the matrix-encoding work?", "Vector encoding and state readout.", r"tensor-based vector-encoding and state-readout are known procedures", None),
        ("method", "Which less-developed encoding step motivates this work?", "Matrix encoding for matrix-vector multiplication on quantum devices.", r"matrix-encoding required for performing matrix-vector multiplications", None),
        ("application", "Which differential-equation application domain is explicitly named in the abstract?", "Differential equations.", r"matrices frequently encountered in differential equations", None),
        ("application", "Which optimization application domain is named in the abstract?", "Optimization problems.", r"differential equations, optimization problems, and quantum chemistry", None),
        ("application", "Which chemistry application domain is named in the abstract?", "Quantum chemistry.", r"differential equations, optimization problems, and quantum chemistry", None),
        ("method", "Why might quantum computers overcome high tensor ranks?", "An ideal quantum computer can represent tensors with arbitrarily high ranks.", r"ideal quantum computer can represent tensors with arbitrarily high ranks", None),
        ("method", "Is the circuit-building method based on tensor networks or a word-vector co-occurrence matrix?", "Tensor networks.", r"leverages tensor networks for hybrid quantum computing", None),
        ("cross_paper", "Do Tensor Quantum Programming and GloVe study the same computing problem?", "No. Tensor Quantum Programming studies quantum circuit encoding; GloVe learns word representations.", r"encodes Matrix Product Operators into quantum circuits", None),
    ],
    "nisq-fullpdf": [
        ("definition", "What does NISQ stand for in Preskill's paper?", "Noisy Intermediate-Scale Quantum.", r"Noisy Intermediate-Scale Quantum", None),
        ("numeric", "What qubit-count range is highlighted in Preskill's abstract?", "50-100 qubits.", r"50-100qubits", r"50\s*[-–]\s*100"),
        ("method", "What limits the size of reliably executable NISQ circuits?", "Noise in quantum gates.", r"noise in quantum gates will limit the size of quantum circuits", None),
        ("application", "Which many-body physics activity does Preskill identify for NISQ devices?", "Exploring many-body quantum physics.", r"useful tools for exploring many-body quantum physics", None),
        ("method", "What provides the paper's basis for expecting quantum computers to be scalable?", "Quantum error correction.", r"quantum error correction.{0,130}scalable", None),
        ("method", "What provides the paper's basis for thinking quantum computing is powerful?", "Quantum complexity.", r"quantum complexity.{0,110}powerful", None),
        ("definition", "Which underlying idea connects quantum complexity and error correction?", "Quantum entanglement.", r"Underlying both of these principles is the idea of.{0,10}quantum entanglement", None),
        ("definition", "What does VQE stand for?", "Variational Quantum Eigensolver.", r"Variational Quantum Eigensolver \(VQE\)", None),
        ("method", "Does Preskill claim it is already known that QAOA or VQE will outperform classical approximation algorithms?", "No; he says nobody knows and experiments must test it.", r"QAOA or VQE.{0,160}Nobody knows", None),
        ("method", "What does Preskill call for after more accurate gates in the longer term?", "Fully fault-tolerant quantum computing.", r"more accurate quantum gates and, eventually, fully fault-tolerant quantum computing", None),
        ("method", "Does the paper guarantee quantum computers efficiently solve worst-case NP-hard optimization problems?", "No; approximate improvements are conceivable but not guaranteed.", r"worst-case instances of NP-hard.{0,220}not guaranteed", None),
        ("cross_paper", "Contrast Preskill's circuit-depth limitation with Tensor Quantum Programming's depth scaling.", "Preskill notes noisy gates limit reliable circuit size; Tensor Quantum Programming gives depth linear in qubit count.", r"noise in quantum gates will limit the size of quantum circuits", None),
    ],
}
NEGATIVES = {
    "guppy-fullpdf": [
        "What exact2027 Guppy release date is stated in this paper?",
        "What randomized clinical-trial diabetes cure rate does the Guppy paper report?",
    ],
    "qppl-fullpdf": [
        "What exact IBM hardware wall-clock speedup does this paper establish for GloVe?",
        "What stock-market return is guaranteed by the proposed quantum programming language?",
    ],
    "glove-fullpdf": [
        "What clinical-trial diabetes cure rate is established by GloVe?",
        "What identical qubit count did GloVe and Tensor Quantum Programming use for word training?",
        "What exact2027 release date for Guppy is announced in the GloVe paper?",
    ],
    "word2vec-fullpdf": [
        "What glucose-treatment dosage does the word2vec paper recommend?",
        "What quantum hardware qubit count did CBOW require for training?",
        "What exact2027 Guppy release date does the word2vec paper announce?",
    ],
    "tensor-fullpdf": [
        "What clinical-trial cure rate does Tensor Quantum Programming establish?",
        "What exact2027 Guppy release date is announced in this paper?",
        "What Google News vocabulary size does the quantum-circuit algorithm use to train word vectors?",
    ],
    "nisq-fullpdf": [
        "What guaranteed annual stock-market return does Preskill's NISQ paper promise?",
        "What clinical diabetes cure rate is established by this NISQ paper?",
        "What exact2027 Guppy release date does Preskill announce?",
    ],
}
CROSS = {
    ("glove-fullpdf", 12): ("word2vec-fullpdf", r"we use each current word as an input.{0,420}current word"),
    ("word2vec-fullpdf", 12): ("glove-fullpdf", r"vocabulary of the 400,000 most frequent words"),
    ("tensor-fullpdf", 12): ("glove-fullpdf", r"global matrix factorization and local context window methods"),
    ("nisq-fullpdf", 12): ("tensor-fullpdf", r"depth that depends linearly on the number of qubits"),
}


def evidence_for(doc: Document, pattern: str, units: list[dict]) -> dict:
    matches = list(re.finditer(pattern.replace(" ", r"\s+"), doc.text, re.I | re.S))
    if not matches:
        raise ValueError(f"Supplement reference not found in {doc.title}: {pattern}")
    match = matches[0]
    selected = [u for u in units if u["doc_id"] == doc.doc_id and u["end"] > match.start() and u["start"] < match.end()]
    if not selected:
        raise ValueError("Supplement source anchor has no source units.")
    return {"evidence_units": [u["unit_id"] for u in selected],
            "evidence": [u["original"] for u in selected]}


def build_supplement() -> tuple[list[Document], list[dict], list[dict]]:
    docs = load_corpus(PILOT_LOCAL / "corpora" / "fullpdf-20261002" / "corpus.json")
    by = {d.doc_id: d for d in docs}
    units = [{"unit_id": f"pdf-{d.doc_id}-p{i}", "doc_id": d.doc_id,
              "original": b.text, "start": b.start, "end": b.end, "kind": b.kind}
             for d in docs for i, b in enumerate(d.blocks)]
    calibration = {"guppy-fullpdf", "qppl-fullpdf"}
    cases = []
    for pid, facts in FACTS.items():
        for index, (category, question, answer, pattern, numerical) in enumerate(facts, 1):
            reference = evidence_for(by[pid], pattern, units)
            scope = calibration if pid in calibration else set(by) - calibration
            if (pid, index) in CROSS:
                other, anchor = CROSS[pid, index]
                extra = evidence_for(by[other], anchor, units)
                reference["evidence_units"] += extra["evidence_units"]
                reference["evidence"] += extra["evidence"]
            case = {
                "case_id": f"pdf-{pid}-{index:02}", "question": question,
                "split": "calibration" if pid in calibration else "held_out",
                "track": "pdf_supplement", "category": category, "scope_doc_ids": sorted(scope),
                "references": [{**reference, "answer": answer, "type": "abstractive"}],
                "alignment_missing": [], "label_provenance": "assistant-authored, source-anchor checked; pending independent human adjudication",
            }
            if numerical:
                case["numeric_regex"] = numerical
            if pid == "glove-fullpdf" and index in (6, 7, 8):
                values = {6: "75.0", 7: "81.9", 8: "69.3"}
                case["forbidden_numeric"] = [rf"\b{re.escape(v)}\s*(?:%|percent)" for i, v in values.items() if i != index]
            cases.append(case)
        for index, question in enumerate(NEGATIVES[pid], len(facts) + 1):
            cases.append({
                "case_id": f"pdf-{pid}-{index:02}", "question": question,
                "split": "calibration" if pid in calibration else "held_out",
                "track": "pdf_supplement", "category": "unanswerable",
                "scope_doc_ids": sorted(calibration if pid in calibration else set(by) - calibration),
                "references": [{"answer": "Unanswerable", "type": "none", "evidence": [], "evidence_units": []}],
                "alignment_missing": [], "label_provenance": "assistant-authored absent/false-premise check; pending independent human adjudication",
            })
    if len(cases) != 80:
        raise ValueError(f"Expected80 supplemental cases, got{len(cases)}.")
    return docs, cases, units
