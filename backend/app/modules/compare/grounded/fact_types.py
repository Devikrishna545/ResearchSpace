"""Typed fact definitions: what to retrieve, how to extract, and how to validate each type."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FactType:
    name: str
    label: str
    dimension: str
    definition: str
    query: str
    section_priors: tuple[str, ...]
    not_this: str
    attributes: tuple[str, ...] = ()
    comparison: str = "set"  # set | numeric | split | result | statistical | semantic
    table_relevant: bool = False
    extra_rules: tuple[str, ...] = field(default_factory=tuple)


FACT_TYPES: dict[str, FactType] = {t.name: t for t in (
    FactType("research_question", "Research question", "research_question",
             "The question or problem this paper itself sets out to answer.",
             "research question problem statement objective aim of this paper we address",
             ("Abstract", "Introduction"),
             "a problem addressed by cited prior work", comparison="semantic"),
    FactType("hypothesis", "Hypothesis", "research_question",
             "An explicit hypothesis or prediction stated by this paper's authors.",
             "we hypothesize hypothesis we expect predict",
             ("Introduction", "Method"),
             "a finding or a result", comparison="semantic"),
    FactType("assumption", "Assumption", "assumption",
             "An explicit assumption this paper's method or analysis relies on.",
             "we assume assumption under the assumption that",
             ("Method", "Introduction", "Discussion"),
             "a limitation or a result", comparison="semantic"),
    FactType("method", "Method", "method",
             "A named method, model, architecture or procedure proposed or used by this paper.",
             "proposed method model architecture approach algorithm we propose",
             ("Method", "Abstract"),
             "a dataset, a metric, or a baseline that is only compared against"),
    FactType("baseline", "Baseline", "baseline",
             "A named method this paper compares its own approach against.",
             "baseline compared with compare against prior methods state of the art",
             ("Results", "Method"),
             "the paper's own proposed method, a dataset or a metric"),
    FactType("dataset", "Dataset", "dataset",
             "A named dataset, corpus or benchmark this paper itself uses for training or evaluation.",
             "dataset corpus benchmark training data evaluation data we train on we evaluate on",
             ("Dataset", "Method", "Results"),
             "a model architecture, method, metric, or a dataset only mentioned in related work",
             table_relevant=True),
    FactType("population", "Population", "population",
             "The study population, participants or subjects this paper itself studies.",
             "participants subjects patients population cohort recruited",
             ("Method", "Dataset"),
             "a population studied only by cited work", attributes=("description", "size", "location", "time_period")),
    FactType("sample_size", "Sample size", "sample_size",
             "A number of samples, examples, tokens, documents or participants used by this paper.",
             "number of samples examples participants size of dataset tokens documents n =",
             ("Dataset", "Method", "Results"),
             "a model parameter count or a result value", attributes=("number", "unit", "applies_to"),
             comparison="numeric", table_relevant=True),
    FactType("inclusion_criterion", "Inclusion criterion", "population",
             "A criterion this paper uses to include data or participants.",
             "inclusion criteria included if eligible",
             ("Method", "Dataset"), "an exclusion criterion"),
    FactType("exclusion_criterion", "Exclusion criterion", "population",
             "A criterion this paper uses to exclude data or participants.",
             "exclusion criteria excluded removed filtered out",
             ("Method", "Dataset"), "an inclusion criterion"),
    FactType("preprocessing", "Preprocessing", "preprocessing",
             "A data preprocessing step this paper applies.",
             "preprocessing tokenization normalization filtering lowercased cleaned",
             ("Method", "Dataset"), "a model component"),
    FactType("train_test_split", "Train/test split", "split",
             "How this paper splits data into training, validation and test sets.",
             "train test split validation set held out training set test set fold cross-validation",
             ("Dataset", "Method", "Results"),
             "a dataset size unrelated to splitting", attributes=("train", "validation", "test", "unit", "scheme"),
             comparison="split", table_relevant=True),
    FactType("metric", "Metric", "metric",
             "An evaluation metric this paper reports, e.g. accuracy, F1, BLEU, perplexity.",
             "evaluation metric accuracy F1 precision recall BLEU perplexity measured by",
             ("Metrics", "Results", "Method"),
             "a result value or a method", attributes=("direction",), table_relevant=True),
    FactType("result", "Result", "result",
             "A quantitative result this paper reports for its own method.",
             "results table accuracy score achieves outperforms performance",
             ("Results",),
             "a result reported for cited prior work only",
             attributes=("metric", "value", "unit", "dataset", "split", "method", "condition"),
             comparison="result", table_relevant=True),
    FactType("uncertainty", "Uncertainty", "result",
             "A reported uncertainty: standard deviation, standard error, confidence interval or error bars.",
             "standard deviation confidence interval standard error variance error bars ±",
             ("Results",), "a p-value",
             attributes=("kind", "value", "lower", "upper", "level", "applies_to"), comparison="statistical",
             table_relevant=True),
    FactType("statistical_test", "Statistical test", "statistical_test",
             "A statistical significance test this paper reports, with its statistic and threshold if stated.",
             "significance test t-test p-value p < wilcoxon chi-square anova statistically significant",
             ("Results", "Method"), "an evaluation metric",
             attributes=("test", "statistic", "df", "p_value", "threshold", "applies_to"), comparison="statistical"),
    FactType("limitation", "Limitation", "limitation",
             "A limitation, weakness or threat to validity the authors acknowledge about their own work.",
             "limitation limitations drawback weakness threat to validity does not we do not fail",
             ("Limitations", "Discussion", "Conclusion"),
             "a favourable property, an advantage, or a limitation of prior work", comparison="semantic"),
    FactType("future_work", "Future work", "future_work",
             "Work the authors say they or others should do in future.",
             "future work in the future we plan to further research could extend",
             ("Conclusion", "Discussion", "Limitations"),
             "a completed contribution", comparison="semantic"),
)}

DIMENSION_ORDER = (
    "research_question", "assumption", "method", "baseline", "dataset", "population", "sample_size",
    "preprocessing", "split", "metric", "result", "statistical_test", "limitation", "future_work",
)

DIMENSION_LABELS = {
    "research_question": "Research question", "assumption": "Assumptions", "method": "Methods",
    "baseline": "Baselines", "dataset": "Datasets", "population": "Populations", "sample_size": "Sample sizes",
    "preprocessing": "Preprocessing", "split": "Train/test splits", "metric": "Metrics", "result": "Results",
    "statistical_test": "Statistical tests", "limitation": "Limitations", "future_work": "Future work",
}

SEMANTIC_DIMENSIONS = ("research_question", "assumption", "limitation", "future_work", "method")

GAP_CATEGORIES = (
    "population_gap", "dataset_gap", "method_gap", "baseline_gap", "metric_gap", "theoretical_gap",
    "reproducibility_gap", "generalizability_gap", "temporal_geographic_gap", "ethical_fairness_gap",
    "practical_deployment_gap",
)
