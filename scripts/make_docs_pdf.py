"""Render the project Markdown documentation to PDF.

Usage (from backend/): .\\.venv\\Scripts\\python.exe ..\\scripts\\make_docs_pdf.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import markdown
from xhtml2pdf import pisa

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "pdf"

CSS = """
@page { size: A4; margin: 16mm 14mm 18mm 14mm; @frame footer {
    -pdf-frame-content: footerContent; bottom: 8mm; margin-left: 14mm; margin-right: 14mm; height: 8mm; } }
body { font-family: Helvetica, Arial, sans-serif; font-size: 9.5pt; line-height: 1.45; color: #1f2933; }
h1 { font-size: 20pt; color: #26305c; margin: 0 0 8pt 0; border-bottom: 2px solid #26305c; padding-bottom: 4pt; }
h2 { font-size: 14pt; color: #26305c; margin: 16pt 0 6pt 0; border-bottom: 1px solid #c9ced9; padding-bottom: 2pt; }
h3 { font-size: 11.5pt; color: #3b4468; margin: 12pt 0 4pt 0; }
h4 { font-size: 10pt; color: #3b4468; margin: 10pt 0 3pt 0; }
p, li { font-size: 9.5pt; }
code { font-family: Courier, monospace; font-size: 8.5pt; background: #f3f4f7; color: #8a2b4a; }
pre { font-family: Courier, monospace; font-size: 7.6pt; background: #f7f8fa; border: 1px solid #dfe3ea;
      padding: 5pt; line-height: 1.25; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; }
th { background: #eceff5; color: #26305c; font-size: 8.4pt; padding: 4pt; border: 1px solid #c9ced9; text-align: left; }
td { font-size: 8.4pt; padding: 4pt; border: 1px solid #dfe3ea; }
blockquote { border-left: 3px solid #7c86b8; margin-left: 0; padding-left: 8pt; color: #4a5568; }
.cover { text-align: center; padding-top: 60mm; }
.cover h1 { font-size: 30pt; border: none; }
.cover .sub { font-size: 13pt; color: #5a6178; margin-top: 6pt; }
.cover .meta { font-size: 9.5pt; color: #7a8194; margin-top: 26pt; }
.footer { font-size: 7.5pt; color: #8a90a0; text-align: center; }
"""


def strip_mermaid(html: str) -> str:
    """xhtml2pdf cannot render mermaid; present the diagram source as a labelled block."""
    return re.sub(
        r'<pre><code class="language-mermaid">(.*?)</code></pre>',
        r'<p><b>Diagram (mermaid source)</b></p><pre>\1</pre>',
        html,
        flags=re.S,
    )


def build(md_path: Path, title: str, subtitle: str) -> Path:
    text = md_path.read_text(encoding="utf-8").lstrip("\ufeff").replace("\ufeff", "")
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "toc", "sane_lists"])
    body = strip_mermaid(body)
    # Keep the PDF ASCII-safe: xhtml2pdf's built-in fonts lack many glyphs.
    replacements = {
        "\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u00b7": "-",
        "\u2192": "->", "\u2190": "<-", "\u2265": ">=", "\u2264": "<=", "\u00d7": "x",
        "\u2248": "~", "\u00b1": "+/-",
        "\u2705": "[ok]", "\u274c": "[x]", "\u26a0": "[!]", "\u2713": "[ok]",
        "\U0001F534": "[critical]", "\U0001F7E0": "[high]", "\U0001F7E1": "[medium]",
        # Box drawing used by the ASCII architecture diagrams.
        "\u2500": "-", "\u2502": "|",
        "\u250c": "+", "\u2510": "+", "\u2514": "+", "\u2518": "+",
        "\u251c": "+", "\u2524": "+", "\u252c": "+", "\u2534": "+", "\u253c": "+",
        "\u2554": "+", "\u2557": "+", "\u255a": "+", "\u255d": "+",
        "\u2550": "=", "\u2551": "|",
        "\u25bc": "v", "\u25b2": "^", "\u25ba": ">", "\u25c4": "<",
        "\u2022": "*", "\u25cf": "*", "\u25a0": "#",
    }
    for src, dst in replacements.items():
        body = body.replace(src, dst)

    html = (
        '<html><head><meta charset="utf-8"><style>' + CSS + "</style></head><body>"
        '<div class="cover"><h1>' + title + '</h1><div class="sub">' + subtitle + "</div>"
        '<div class="meta">Research Assistant - local-first multi-agent research workspace<br/>'
        "Generated from " + md_path.name + "</div></div>"
        "<pdf:nextpage/>"
        '<div id="footerContent" class="footer">' + title + " - page <pdf:pagenumber/></div>"
        + body + "</body></html>"
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / (md_path.stem + ".pdf")
    with out.open("wb") as fh:
        result = pisa.CreatePDF(html, dest=fh, encoding="utf-8")
    if result.err:
        raise SystemExit("Failed to render " + md_path.name)
    return out


DOCS = [
    ("docs/10-hld.md", "High Level Design", "System architecture, flows and design decisions"),
    ("docs/11-lld.md", "Low Level Design", "Modules, algorithms, schema and API reference"),
    ("README.md", "Project Overview", "Features, setup and operations guide"),
    ("docs/01-requirements.md", "Requirements", "Functional and non-functional requirements"),
]


def main() -> int:
    for rel, title, subtitle in DOCS:
        path = ROOT / rel
        if not path.exists():
            print("skip (missing): " + rel)
            continue
        out = build(path, title, subtitle)
        print(str(out.relative_to(ROOT)) + "  (" + format(out.stat().st_size / 1024, ".0f") + " KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
