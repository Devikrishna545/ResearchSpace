"""Deterministic comparison over validated facts only. No LLM participates here."""

import re
from dataclasses import dataclass, field
from itertools import combinations

from app.modules.compare.grounded import numerics
from app.modules.compare.grounded.fact_types import DIMENSION_LABELS, DIMENSION_ORDER, FACT_TYPES
from app.modules.compare.schemas.grounded import (
    COMMONALITY, DIFFERENCE, DIRECTLY_EVIDENCED, INSUFFICIENT, INSUFFICIENT_EVIDENCE, NOT_COMPARABLE,
    NUMERIC_COMPARISON, NUMERICALLY_VERIFIED, STATISTICAL_CHECK, Finding,
)

SET_DIMENSIONS = ("method", "baseline", "dataset", "population", "preprocessing", "metric")
CRITERIA_TYPES = ("inclusion_criterion", "exclusion_criterion")
PAREN_ACRONYM = re.compile(r"\(([A-Za-z0-9\-]{2,12})\)")


@dataclass
class PaperEvidence:
    paper_id: str
    label: str
    title: str
    build: object
    artifacts_by_id: dict
    facts: list = field(default_factory=list)  # every fact for the build, including rejected
    extraction_state: dict = field(default_factory=dict)

    @property
    def validated(self) -> list:
        return [f for f in self.facts if f.extraction_status == "validated"]

    def facts_for(self, dimension: str) -> list:
        return [f for f in self.validated if FACT_TYPES[f.fact_type].dimension == dimension]

    @property
    def short(self) -> str:
        title = self.title if len(self.title) <= 60 else self.title[:57].rstrip() + "…"
        return f"{self.label} (“{title}”)"


def entity_keys(value: str, dimension: str | None = None) -> set[str]:
    keys = {numerics.dataset_key(value)}
    for acronym in PAREN_ACRONYM.findall(value):
        keys.add(acronym.casefold())
    stripped = PAREN_ACRONYM.sub("", value).strip()
    if stripped:
        keys.add(numerics.dataset_key(stripped))
    if re.fullmatch(r"[A-Za-z0-9\-]{2,12}", value.strip()):
        keys.add(value.strip().casefold())
    # "Gigaword 5" and "Gigaword5" are the same name with different PDF spacing.
    keys |= {k.replace(" ", "") for k in keys}
    if dimension == "metric":
        keys.add("metric:" + (numerics.canonical_metric(value) or ""))
    return {k for k in keys if k and k != "metric:"}


def _sources(facts) -> list[str]:
    return list(dict.fromkeys(s for f in facts for s in f.source_ids))


class DeterministicComparator:
    def __init__(self, papers: list[PaperEvidence]):
        self.papers = papers
        self._counter = 0

    def _id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter:03d}"

    def matrix(self) -> list[dict]:
        rows = []
        for dimension in DIMENSION_ORDER:
            cells = {}
            for paper in self.papers:
                facts = paper.facts_for(dimension)
                types = [n for n, t in FACT_TYPES.items() if t.dimension == dimension]
                failed = [n for n in types if (paper.extraction_state.get(n) or {}).get("status") == "failed"]
                if facts:
                    cells[paper.label] = {"status": "evidenced", "values": [
                        {"fact_id": f.id, "value": f.value, "fact_type": f.fact_type, "page": f.page,
                         "source_id": f.source_ids[0] if f.source_ids else None, "attributes": f.attributes or {}}
                        for f in facts]}
                elif failed:
                    cells[paper.label] = {"status": "extraction_failed", "values": [],
                                          "note": "Extraction failed; this is not evidence of absence."}
                else:
                    cells[paper.label] = {"status": "insufficient_evidence", "values": []}
            rows.append({"dimension": dimension, "label": DIMENSION_LABELS[dimension], "cells": cells})
        return rows

    def compare(self) -> list[Finding]:
        return [*self.compare_entities(), *self.compare_numerics()]

    def compare_entities(self) -> list[Finding]:
        findings: list[Finding] = []
        for dimension in SET_DIMENSIONS:
            findings.extend(self._set_dimension(dimension, ("population",) if dimension == "population" else None))
        findings.extend(self._criteria())
        return findings

    def compare_numerics(self) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._sample_sizes())
        findings.extend(self._splits())
        findings.extend(self._results())
        findings.extend(self._statistics())
        return findings

    def comparable_pairs(self, entity_findings: list[Finding]) -> set[frozenset]:
        """Paper pairs shown to share a dataset or population: the minimum for a direct contradiction."""
        pairs = set()
        for finding in entity_findings:
            if finding.kind == COMMONALITY and finding.dimension in {"dataset", "population"}:
                ids = finding.paper_ids
                pairs.update(frozenset((a, b)) for i, a in enumerate(ids) for b in ids[i + 1:])
        return pairs

    def _insufficient(self, dimension: str, missing: list[PaperEvidence]) -> Finding:
        names = ", ".join(p.short for p in missing)
        return Finding(finding_id=self._id("ins"), kind=INSUFFICIENT, dimension=dimension,
                       statement=f"Insufficient evidence: no validated {DIMENSION_LABELS[dimension].lower()} for {names}.",
                       paper_ids=[p.paper_id for p in missing], evidence_status=INSUFFICIENT_EVIDENCE,
                       verification_status="policy", display_status="coverage", basis="direct_evidence")

    def _set_dimension(self, dimension: str, fact_types: tuple[str, ...] | None = None) -> list[Finding]:
        label = DIMENSION_LABELS[dimension].lower()
        per_paper = {}
        for paper in self.papers:
            facts = [f for f in paper.facts_for(dimension) if fact_types is None or f.fact_type in fact_types]
            per_paper[paper.paper_id] = facts
        missing = [p for p in self.papers if not per_paper[p.paper_id]]
        present = [p for p in self.papers if per_paper[p.paper_id]]
        out = []
        if missing:
            out.append(self._insufficient(dimension, missing))
        if len(present) < 2:
            return out
        # Group facts by entity key across papers.
        groups: list[dict] = []
        for paper in present:
            for fact in per_paper[paper.paper_id]:
                keys = entity_keys(fact.value, dimension)
                group = next((g for g in groups if g["keys"] & keys), None)
                if group is None:
                    group = {"keys": set(keys), "facts": {}}
                    groups.append(group)
                group["keys"] |= keys
                group["facts"].setdefault(paper.paper_id, []).append(fact)
        for group in groups:
            owners = [p for p in present if p.paper_id in group["facts"]]
            facts = [f for p in owners for f in group["facts"][p.paper_id]]
            display = group["facts"][owners[0].paper_id][0].value
            if len(owners) >= 2:
                who = "All selected papers" if len(owners) == len(self.papers) else " and ".join(p.short for p in owners)
                verb = "report" if dimension != "metric" else "report the metric"
                statement = f"{who} {verb} {label[:-1] if label.endswith('s') else label} “{display}”."
                if dimension == "metric":
                    direction = numerics.metric_direction(display)
                    statement = f"{who} report the metric “{display}” ({direction.replace('_', ' ')})." if direction != "unknown" else statement
                out.append(Finding(finding_id=self._id("cmp"), kind=COMMONALITY, dimension=dimension, statement=statement,
                                   paper_ids=[p.paper_id for p in owners], fact_ids=[f.id for f in facts], source_ids=_sources(facts),
                                   evidence_status=DIRECTLY_EVIDENCED, verification_status="deterministic",
                                   display_status="shown", basis="direct_evidence",
                                   computed={"match": "normalized_entity_key", "keys": sorted(group["keys"])}))
            else:
                others = [p for p in present if p.paper_id != owners[0].paper_id]
                statement = (f"{owners[0].short} reports {label[:-1] if label.endswith('s') else label} “{display}”; "
                             f"no validated evidence shows {' or '.join(p.short for p in others)} using it.")
                out.append(Finding(finding_id=self._id("dif"), kind=DIFFERENCE, dimension=dimension, statement=statement,
                                   paper_ids=[owners[0].paper_id], fact_ids=[f.id for f in facts], source_ids=_sources(facts),
                                   evidence_status=DIRECTLY_EVIDENCED, verification_status="deterministic",
                                   display_status="shown", basis="direct_evidence",
                                   reason="Absence in the other paper's validated facts is not proof that it does not use this; "
                                          "extraction may have missed it."))
        return out

    def _criteria(self) -> list[Finding]:
        findings = []
        for fact_type in CRITERIA_TYPES:
            present = [p for p in self.papers if any(f.fact_type == fact_type for f in p.validated)]
            if len(present) >= 2:
                findings.extend(f for f in self._set_dimension("population", (fact_type,)) if f.kind != INSUFFICIENT)
        return findings

    def _numeric_facts(self, paper: PaperEvidence, fact_type: str) -> list:
        return [f for f in paper.validated if f.fact_type == fact_type]

    def _sample_sizes(self) -> list[Finding]:
        findings = []
        for a, b in combinations(self.papers, 2):
            for fa in self._numeric_facts(a, "sample_size"):
                for fb in self._numeric_facts(b, "sample_size"):
                    na = numerics.parse_number((fa.attributes or {}).get("number") or fa.value)
                    nb = numerics.parse_number((fb.attributes or {}).get("number") or fb.value)
                    if na is None or nb is None:
                        continue
                    if (fa.attributes or {}).get("unit"):
                        na.unit = numerics.singular(str(fa.attributes["unit"]).lower())
                    if (fb.attributes or {}).get("unit"):
                        nb.unit = numerics.singular(str(fb.attributes["unit"]).lower())
                    result = numerics.compare_counts(na, nb)
                    if not result["comparable"]:
                        continue
                    ratio = result.get("ratio")
                    statement = (f"Sample size: {a.short} reports {fa.value}; {b.short} reports {fb.value}"
                                 + (f" (ratio {ratio:.3g}×, computed)." if ratio else " (computed)."))
                    findings.append(Finding(finding_id=self._id("num"), kind=NUMERIC_COMPARISON, dimension="sample_size",
                                            statement=statement, paper_ids=[a.paper_id, b.paper_id], fact_ids=[fa.id, fb.id],
                                            source_ids=_sources([fa, fb]), computed=result, evidence_status=NUMERICALLY_VERIFIED,
                                            verification_status="deterministic", display_status="shown", basis="code_calculation"))
        return findings

    def _splits(self) -> list[Finding]:
        findings = []
        for a, b in combinations(self.papers, 2):
            for fa in self._numeric_facts(a, "train_test_split"):
                for fb in self._numeric_facts(b, "train_test_split"):
                    result = numerics.compare_splits(fa.attributes or {}, fb.attributes or {})
                    if result["comparable"]:
                        diffs = ", ".join(f"{k} {v:+.1%}" for k, v in result["fraction_difference"].items())
                        statement = f"Data split proportions differ by {diffs} ({a.short} minus {b.short}, computed)."
                        status, kind, basis = NUMERICALLY_VERIFIED, NUMERIC_COMPARISON, "code_calculation"
                    else:
                        statement = f"Train/test splits of {a.short} and {b.short} cannot be compared: {result['reason']}."
                        status, kind, basis = DIRECTLY_EVIDENCED, NOT_COMPARABLE, "direct_evidence"
                    findings.append(Finding(finding_id=self._id("spl"), kind=kind, dimension="split", statement=statement,
                                            paper_ids=[a.paper_id, b.paper_id], fact_ids=[fa.id, fb.id], source_ids=_sources([fa, fb]),
                                            computed=result, evidence_status=status, verification_status="deterministic",
                                            display_status="shown", basis=basis))
        return findings

    def _result_value(self, paper: PaperEvidence, fact) -> tuple[numerics.ParsedNumber | None, bool | None]:
        attrs = fact.attributes or {}
        number = numerics.parse_number(attrs.get("value") or fact.value)
        source = paper.artifacts_by_id.get(fact.source_ids[0]) if fact.source_ids else None
        in_table = numerics.value_in_table(str(attrs.get("value") or fact.value), source.cells) if source is not None and source.kind == "table" else None
        return number, in_table

    def _results(self) -> list[Finding]:
        findings = []
        for a, b in combinations(self.papers, 2):
            for fa in self._numeric_facts(a, "result"):
                for fb in self._numeric_facts(b, "result"):
                    attrs_a, attrs_b = fa.attributes or {}, fb.attributes or {}
                    metric_a, metric_b = numerics.canonical_metric(attrs_a.get("metric")), numerics.canonical_metric(attrs_b.get("metric"))
                    if not metric_a or metric_a != metric_b:
                        continue  # different or unknown metrics are not even candidates for comparison
                    na, table_a = self._result_value(a, fa)
                    nb, table_b = self._result_value(b, fb)
                    if na is None or nb is None:
                        continue
                    ok, reasons = numerics.result_conditions_match(attrs_a, attrs_b, fa.value, fb.value)
                    if table_a is False or table_b is False:
                        ok, reasons = False, [*reasons, "a reported value was not found in its source table"]
                    base = dict(paper_ids=[a.paper_id, b.paper_id], fact_ids=[fa.id, fb.id], source_ids=_sources([fa, fb]),
                                verification_status="deterministic", display_status="shown", dimension="result")
                    if not ok:
                        findings.append(Finding(finding_id=self._id("res"), kind=NOT_COMPARABLE,
                                                statement=(f"{metric_a} results of {a.short} ({na.raw}) and {b.short} ({nb.raw}) "
                                                           f"are not directly comparable: {'; '.join(reasons)}."),
                                                computed={"reasons": reasons, "metric": metric_a}, evidence_status=DIRECTLY_EVIDENCED,
                                                basis="direct_evidence", **base))
                        continue
                    result = numerics.compare_values(na, nb, metric_a)
                    if not result.get("comparable"):
                        findings.append(Finding(finding_id=self._id("res"), kind=NOT_COMPARABLE,
                                                statement=f"{metric_a} values cannot be compared: {result['reason']}.",
                                                computed=result, evidence_status=DIRECTLY_EVIDENCED, basis="direct_evidence", **base))
                        continue
                    result["table_confirmed"] = {"a": table_a, "b": table_b}
                    if "difference_percentage_points" in result:
                        delta = f"{result['difference_percentage_points']:+.4g} percentage points"
                    else:
                        delta = f"{result['difference']:+.4g}"
                    rel = result.get("relative_change_percent")
                    rel_text = f", {rel:+.3g}% relative change" if rel is not None else ""
                    statement = (f"On {attrs_a.get('dataset')}, {metric_a}: {a.short} reports {na.raw}, {b.short} reports {nb.raw}; "
                                 f"difference {delta}{rel_text} (computed in code).")
                    findings.append(Finding(finding_id=self._id("res"), kind=NUMERIC_COMPARISON, statement=statement,
                                            computed=result, evidence_status=NUMERICALLY_VERIFIED, basis="code_calculation", **base))
        return findings

    def _statistics(self) -> list[Finding]:
        findings = []
        for paper in self.papers:
            for fact in [f for f in paper.validated if f.fact_type in {"statistical_test", "uncertainty"}]:
                report = numerics.check_statistics(fact.attributes or {})
                if not report["checks"]:
                    continue
                failed = [c["check"] for c in report["checks"] if not c["ok"]]
                statement = (f"{paper.short}: reported {FACT_TYPES[fact.fact_type].label.lower()} “{fact.value}” "
                             + ("passes all code checks." if not failed else f"fails code checks: {', '.join(failed)}."))
                findings.append(Finding(finding_id=self._id("sta"), kind=STATISTICAL_CHECK, dimension="statistical_test",
                                        statement=statement, paper_ids=[paper.paper_id], fact_ids=[fact.id],
                                        source_ids=_sources([fact]), computed=report, evidence_status=NUMERICALLY_VERIFIED,
                                        verification_status="deterministic", display_status="shown", basis="code_calculation"))
        tests = {p.paper_id: {str((f.attributes or {}).get("test") or f.value).casefold() for f in p.validated if f.fact_type == "statistical_test"}
                 for p in self.papers}
        for a, b in combinations(self.papers, 2):
            shared = tests[a.paper_id] & tests[b.paper_id]
            if shared:
                facts = [f for p in (a, b) for f in p.validated if f.fact_type == "statistical_test"
                         and str((f.attributes or {}).get("test") or f.value).casefold() in shared]
                findings.append(Finding(finding_id=self._id("sta"), kind=COMMONALITY, dimension="statistical_test",
                                        statement=f"{a.short} and {b.short} both report the statistical test(s): {', '.join(sorted(shared))}.",
                                        paper_ids=[a.paper_id, b.paper_id], fact_ids=[f.id for f in facts], source_ids=_sources(facts),
                                        evidence_status=DIRECTLY_EVIDENCED, verification_status="deterministic",
                                        display_status="shown", basis="direct_evidence"))
        return findings
