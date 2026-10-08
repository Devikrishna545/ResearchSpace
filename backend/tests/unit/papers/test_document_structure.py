from app.modules.papers.service import _chunk_pages, _detect_section, _section_segments


def test_real_numbered_headings_survive_before_word_chunking():
    page = (
        "1 Introduction\n"
        "The opening explains the research question and motivation in enough words.\n"
        "2 Model Architectures\n"
        "The paper compares two language model architectures and how they are trained.\n"
        "3 New Log-linear Models\n"
        "The model learns vector representations from a training corpus.\n"
        "4 Results\n"
        "The evaluation describes accuracy and reports what the model achieved."
    )
    chunks = _chunk_pages([page], size=40, overlap=5)
    assert [chunk["section"] for chunk in chunks] == [
        "Introduction — 1 Introduction", "Method — 2 Model Architectures",
        "Method — 3 New Log-linear Models", "Results — 4 Results",
    ]
    assert all(chunk["page"] == 1 for chunk in chunks)
    assert chunks[-1]["text"].startswith("4 Results The evaluation")


def test_new_page_without_heading_stays_unknown_instead_of_inheriting_results():
    pages = [
        "1 Introduction\nThe paper frames the topic.\n"
        "4 Results\nA factual result in the first page with a measured score.",
        "The next page starts with ordinary prose and does not identify a heading.",
    ]
    chunks = _chunk_pages(pages, size=40, overlap=5)
    assert [chunk["section"] for chunk in chunks] == [
        "Introduction — 1 Introduction", "Results — 4 Results", None,
    ]
    assert [chunk["page"] for chunk in chunks] == [1, 1, 2]
    assert _detect_section("the method improved the result") is None
    assert _detect_section("A result shows accuracy") is None


def test_reference_list_is_not_mistaken_for_numbered_headings():
    page = (
        "1 Introduction\nThe opening explains the work.\n"
        "5 References\n"
        "1 Introduction to a textbook, 2016\n"
        "2 Model architectures in a different publication, 2020\n"
        "3 Results reported by a different author, 2021"
    )
    assert [chunk["section"] for chunk in _chunk_pages([page], size=40, overlap=5)] == [
        "Introduction — 1 Introduction", "References — 5 References",
    ]


def test_conservative_unnumbered_headings_and_raw_unknown_numbered_title():
    assert _detect_section("Methods") == "Method — Methods"
    assert _detect_section("7 Novel Results for Real Research") == "7 Novel Results for Real Research"
    assert _detect_section("The experimental method improves classification") is None
    assert _detect_section("1.25. In this case we have that |X| =O(|C|0.8).") is None
    assert _detect_section("0.05. We run 50 iterations for vectors smaller than") is None
    assert _detect_section("2010. Word representations: a simple and general method") is None
    assert _detect_section("3 The GloV e Model") == "Method — 3 The GloV e Model"
    assert _detect_section("4.2 Corpora and training details") == "Dataset — 4.2 Corpora and training details"
    assert _section_segments("unstructured introduction of plain prose") == [
        ("unstructured introduction of plain prose", None),
    ]


def test_abstract_or_web_capture_has_no_invented_pdf_sections():
    paragraph = "2 Model Architectures\nThis is abstract or web-capture text, not parsed PDF pages."
    parts = _chunk_pages([paragraph], heading_aware=False)
    assert len(parts) == 1
    assert parts[0]["section"] is None
    assert parts[0]["page"] == 1


def test_blank_or_scanned_pages_never_fabricate_structure():
    assert _chunk_pages(["", "  \n  "]) == []


def test_unrecognized_heading_breaks_previous_real_section_instead_of_propagating():
    page = (
        "1 Introduction\n"
        "This paragraph frames the problem and explains motivation.\n"
        "OTHER EXPERIMENTAL DETAILS\n"
        "Later text belongs to an unknown section, not the introduction."
    )
    assert [chunk["section"] for chunk in _chunk_pages([page], size=40, overlap=5)] == [
        "Introduction — 1 Introduction", None,
    ]


def test_numbered_medical_table_rows_without_outline_remain_unknown():
    page = (
        "ABSTRACT\nThe study discusses several conditions.\n"
        "INTRODUCTION\nA short account of disease prevention.\n"
        "S.NO. Disease Description Symptoms\n"
        "1 Coronary Artery Disease\n2 Stroke Reduced blood supply\n"
        "REFERENCES:\n"
        "1. Zuraini NZ, Sekar M, Wu YS, Gan SH, Bonam SR, Mat Rani NN\n"
    )
    parts = _chunk_pages([page], size=40, overlap=5)
    assert not any(section and "Coronary Artery Disease" in section for section in (p["section"] for p in parts))
    assert not any(section and "Zuraini" in section for section in (p["section"] for p in parts))
    assert any(part["section"] and part["section"].startswith("References") for part in parts)
