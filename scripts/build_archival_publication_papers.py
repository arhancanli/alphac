#!/usr/bin/env python3
"""Render and validate archival paper assets for every registered sleeve bundle."""

from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Final

from pypdf import PdfReader, PdfWriter
from pypdf import __version__ as PYPDF_VERSION

ROOT: Final = Path(__file__).resolve().parents[1]
REGISTRY: Final = ROOT / "config/external_publication_registry.json"
STATIC_RESEARCH: Final = ROOT.parent / "meridian/research"
CHROME: Final = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
FIXED_PDF_DATE: Final = "D:20260823000000+04'00'"
VOID_TAGS: Final = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}
SHORT_TITLE_OVERRIDES: Final = {
    "alphavintage_macro_surprise": "AlphaVintage inflation surprise: corrected null",
    "equity_quality": "Equity fundamental quality: complete trial lineage",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


class _BodyCapture(HTMLParser):
    """Capture the generated site's exact paper body while preserving safe markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class", "") or ""
        if self.depth == 0 and tag == "div" and "paper__body" in classes.split():
            self.depth = 1
            return
        if self.depth:
            self.parts.append(self.get_starttag_text())
            if tag not in VOID_TAGS:
                self.depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.depth:
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag: str) -> None:
        if self.depth:
            self.depth -= 1
            if self.depth:
                self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if self.depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self.depth:
            self.parts.append(f"&#{name};")


def _paper_body(source_html: Path) -> str:
    parser = _BodyCapture()
    parser.feed(source_html.read_text())
    body = "".join(parser.parts).strip()
    if not body or "<h2" not in body:
        raise ValueError(f"could not extract a complete paper body from {source_html}")
    return body


def _bibliography_html(references_path: Path) -> str:
    if not references_path.is_file():
        return ""
    document = json.loads(references_path.read_text())
    if document.get("status") != "COMPLETE_NORMALIZED_BIBLIOGRAPHY":
        raise ValueError(f"bibliography is not complete: {references_path}")
    rows: list[str] = []
    for reference in document["references"]:
        authors = ", ".join(
            " ".join(
                part
                for part in (author.get("given", ""), author.get("family", ""))
                if part
            )
            for author in reference["authors"]
        )
        venue = str(reference.get("container_title", ""))
        url = html.escape(str(reference["url"]), quote=True)
        rows.append(
            "<li>"
            f"{html.escape(authors)} ({reference['year']}). "
            f"<em>{html.escape(str(reference['title']))}</em>. "
            f"{html.escape(venue)}. <a href=\"{url}\">{url}</a>"
            "</li>"
        )
    return (
        "<section class=\"bibliography\"><h2>References</h2><ol>"
        + "".join(rows)
        + "</ol></section>"
    )


CSS: Final = r"""
@page { size: A4; margin: 19mm 20mm 21mm; }
* { box-sizing: border-box; }
html { font-size: 10.6pt; }
body { color: #17202a; font-family: Georgia, "Times New Roman", serif;
       line-height: 1.46; margin: 0; }
.cover { min-height: 247mm; display: flex; flex-direction: column;
         justify-content: space-between; page-break-after: always; }
.rule { width: 62px; height: 4px; background: #9a6b2f; margin: 8mm 0 14mm; }
.kicker, .meta, .boundary { font-family: Arial, Helvetica, sans-serif; }
.kicker { color: #6f532d; font-size: 8.4pt; font-weight: 700;
          letter-spacing: .13em; text-transform: uppercase; }
h1 { color: #111923; font-size: 29pt; font-weight: 500; line-height: 1.08;
     margin: 0; max-width: 155mm; }
.author { font-size: 14pt; margin-top: 13mm; }
.affiliation { color: #53606d; font-family: Arial, Helvetica, sans-serif;
               font-size: 9.4pt; }
.meta { border-top: 1px solid #c8c1b5; color: #4b5661; display: grid;
        font-size: 8.5pt; gap: 2mm; grid-template-columns: 34mm 1fr; padding-top: 6mm; }
.meta strong { color: #202b36; letter-spacing: .04em; text-transform: uppercase; }
.boundary { background: #f1eee8; border-left: 3px solid #9a6b2f; color: #35414c;
            font-size: 8.7pt; margin-top: 8mm; padding: 4mm 5mm; }
.paper { max-width: 170mm; }
.paper > p:first-child { background: #f4f2ed; border: 1px solid #ddd7cc;
                         font-family: Arial, Helvetica, sans-serif;
                         font-size: 8.2pt; padding: 4mm; }
h2 { border-bottom: .6pt solid #cfc8bc; color: #17202a; font-size: 16pt;
     font-weight: 500; margin: 9mm 0 3mm; padding-bottom: 1.5mm;
     page-break-after: avoid; }
h3 { color: #263746; font-size: 12.5pt; margin: 6mm 0 2mm;
     page-break-after: avoid; }
p { margin: 0 0 3.2mm; orphans: 3; widows: 3; }
ul, ol { margin: 2mm 0 4mm 6mm; padding-left: 5mm; }
li { margin-bottom: 1.3mm; }
.bibliography li { margin-bottom: 2.2mm; }
.bibliography a { overflow-wrap: anywhere; word-break: break-word; }
table { border-collapse: collapse; font-family: Arial, Helvetica, sans-serif;
        font-size: 7.4pt; margin: 4mm 0 6mm; page-break-inside: avoid; width: 100%; }
th { background: #e8e3da; color: #222d37; font-weight: 700; }
th, td { border: .5pt solid #c8c1b5; padding: 1.5mm 1.8mm;
         text-align: left; vertical-align: top; }
code { background: #f0eee9; border-radius: 2px;
       font-family: "SFMono-Regular", Consolas, monospace; font-size: 8.1pt;
       padding: .2mm .7mm; }
pre { background: #18222c; color: #edf1f4; font-size: 7.4pt; line-height: 1.35;
      overflow-wrap: anywhere; padding: 4mm; white-space: pre-wrap; }
a { color: #5f4828; text-decoration: underline; text-decoration-thickness: .5pt; }
blockquote { border-left: 2pt solid #b48a50; color: #465461;
             margin-left: 0; padding-left: 5mm; }
"""


def _short_title(markdown: str, fallback: str, key: str) -> str:
    match = re.search(r"^\*\*Short title:\*\*\s*(.+?)\s*$", markdown, flags=re.MULTILINE)
    value = match.group(1).strip() if match else SHORT_TITLE_OVERRIDES.get(key, fallback)
    if len(value) > 65:
        raise ValueError(f"paper has no search-safe short title: {value}")
    return value


def _description(abstract: str) -> str:
    plain = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", abstract)
    plain = re.sub(r"[*_`#]", "", plain)
    plain = "Archival preprint bundle by Arhan Canli. " + " ".join(plain.split())
    if len(plain) <= 158:
        return plain
    return plain[:155].rsplit(" ", maxsplit=1)[0] + "…"


def _seo_title(short_title: str) -> str:
    suffix = " — archival paper"
    available = 65 - len(suffix)
    base = (
        short_title
        if len(short_title) <= available
        else short_title[:available].rsplit(" ", 1)[0]
    )
    return base.rstrip(": —-") + suffix


def _html_document(
    *,
    title: str,
    seo_title: str,
    description: str,
    canonical: str,
    body: str,
    version: str,
    key: str,
) -> str:
    title_html = html.escape(title)
    seo_title_html = html.escape(seo_title)
    description_html = html.escape(description, quote=True)
    canonical_html = html.escape(canonical, quote=True)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="author" content="Arhan Canli">
<meta name="description" content="{description_html}">
<meta name="generator" content="ALPHAC archival paper renderer">
<link rel="canonical" href="{canonical_html}">
<meta property="og:type" content="article">
<meta property="og:title" content="{title_html}">
<meta property="og:description" content="{description_html}">
<meta property="og:url" content="{canonical_html}">
<title>{seo_title_html}</title><style>{CSS}</style></head><body>
<section class="cover"><div><div class="kicker">Canli Capital Research / ALPHAC</div>
<div class="rule"></div><h1>{title_html}</h1><div class="author">Arhan Canli</div>
<div class="affiliation">Founder, System Architect, and Quantitative Researcher<br>
Canli Capital / AlphaC Algorithms</div></div><div><div class="meta">
<strong>Version</strong><span>{html.escape(version)}</span>
<strong>Released</strong><span>23 August 2026</span>
<strong>Registry key</strong><span>{html.escape(key)}</span>
<strong>Status</strong><span>Working paper preprint / not peer reviewed</span></div>
<div class="boundary">Research simulation and, where explicitly identified, Alpaca paper
evidence. No funded performance, peer review, independent replication, external acceptance, or
future return is claimed.</div></div></section><article class="paper">{body}</article>
</body></html>
"""


def _latex_document(title: str, print_bibliography: bool) -> str:
    escaped = title
    for old, new in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
                     ("#", r"\#"), ("_", r"\_")):
        escaped = escaped.replace(old, new)
    bibliography_packages = ""
    bibliography_end = ""
    if print_bibliography:
        bibliography_packages = (
            "\\usepackage[backend=biber,style=authoryear,maxbibnames=99]{biblatex}\n"
            "\\addbibresource{references.bib}\n"
        )
        bibliography_end = "\\clearpage\n\\nocite{*}\n\\printbibliography\n"
    return rf"""\documentclass[11pt,a4paper]{{article}}
\usepackage[margin=24mm]{{geometry}}
\usepackage[T1]{{fontenc}}
\usepackage{{lmodern,microtype,booktabs,longtable,hyperref,xcolor}}
\usepackage[smartEllipses,fencedCode]{{markdown}}
{bibliography_packages}
\hypersetup{{colorlinks=true,linkcolor=black,urlcolor=blue,
pdftitle={{{escaped}}},pdfauthor={{Arhan Canli}}}}
\title{{{escaped}}}
\author{{Arhan Canli\\Canli Capital / AlphaC Algorithms}}
\date{{23 August 2026\\Working paper preprint; not peer reviewed}}
\begin{{document}}
\maketitle
\noindent\fbox{{\parbox{{0.94\linewidth}}{{Research simulation and, where explicitly identified,
Alpaca paper evidence. No funded performance, peer review, independent replication, external
acceptance, or future return is claimed.}}}}
\vspace{{1em}}
\markdownInput{{paper.md}}
{bibliography_end}
\end{{document}}
"""


def _normalize_pdf(raw: Path, output: Path, title: str) -> None:
    reader = PdfReader(raw)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata(
        {
            "/Title": title,
            "/Author": "Arhan Canli",
            "/Subject": "ALPHAC quantitative research working paper; not peer reviewed",
            "/Creator": "ALPHAC archival paper renderer",
            "/Producer": "Chromium PDF engine; normalized with pypdf",
            "/CreationDate": FIXED_PDF_DATE,
            "/ModDate": FIXED_PDF_DATE,
        }
    )
    if reader.pages:
        writer.add_outline_item(title, 0)
    with output.open("wb") as handle:
        writer.write(handle)


def _font_names(reader: PdfReader) -> list[str]:
    names: set[str] = set()
    for page in reader.pages:
        resources = page.get("/Resources", {}).get_object()
        fonts = resources.get("/Font", {}).get_object()
        for value in fonts.values():
            font = value.get_object()
            name = str(font.get("/BaseFont", "")).lstrip("/")
            if name:
                names.add(name)
    return sorted(names)


def _validation(
    pdf: Path,
    title: str,
    key: str,
    source_markdown: Path,
    source_html: Path,
    bibliography_expected: bool,
) -> dict[str, Any]:
    reader = PdfReader(pdf)
    page_text = [(page.extract_text() or "").strip() for page in reader.pages]
    joined = "\n".join(page_text)
    metadata = reader.metadata
    failures: list[str] = []
    if len(reader.pages) < 2:
        failures.append("FEWER_THAN_TWO_PAGES")
    if any(len(text) < 40 for text in page_text):
        failures.append("BLANK_OR_NEAR_BLANK_PAGE")
    if "Arhan Canli" not in joined:
        failures.append("AUTHOR_NOT_EXTRACTABLE")
    if "not peer reviewed" not in joined.lower():
        failures.append("PEER_REVIEW_BOUNDARY_NOT_EXTRACTABLE")
    if bibliography_expected and "references" not in joined.lower():
        failures.append("BIBLIOGRAPHY_NOT_EXTRACTABLE")
    if metadata.title != title or metadata.author != "Arhan Canli":
        failures.append("PDF_METADATA_MISMATCH")
    widths = [round(float(page.mediabox.width), 2) for page in reader.pages]
    heights = [round(float(page.mediabox.height), 2) for page in reader.pages]
    dimensions = zip(widths, heights, strict=True)
    if not all(590 <= width <= 600 and 838 <= height <= 846 for width, height in dimensions):
        failures.append("PAGE_SIZE_NOT_A4")
    fonts = _font_names(reader)
    if not fonts:
        failures.append("NO_FONT_RESOURCES_FOUND")
    chrome_version = subprocess.run(
        [str(CHROME), "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    bibliography_bindings = {
        name: {"path": name, "sha256": _sha256(source_markdown.parent / name)}
        for name in ("references.bib", "references.json")
        if (source_markdown.parent / name).is_file()
    }
    return {
        "schema": "canli.alphac-archival-pdf-validation.v1",
        "registry_key": key,
        "author": "Arhan Canli",
        "status": "PASS_MACHINE_PDF_VALIDATION" if not failures else "FAIL",
        "passes": not failures,
        "pages": len(reader.pages),
        "extractable_characters": len(joined),
        "minimum_extractable_characters_on_page": min(map(len, page_text), default=0),
        "page_width_points": sorted(set(widths)),
        "page_height_points": sorted(set(heights)),
        "font_resources": fonts,
        "metadata": {"title": metadata.title, "author": metadata.author},
        "source_bindings": {
            "paper_markdown": {
                "path": str(source_markdown.relative_to(ROOT)),
                "sha256": _sha256(source_markdown),
            },
            "static_site_paper_html": {
                "path": str(source_html),
                "sha256": _sha256(source_html),
            },
            "renderer": {
                "path": str(Path(__file__).resolve().relative_to(ROOT)),
                "sha256": _sha256(Path(__file__).resolve()),
            },
            "bibliography": bibliography_bindings,
        },
        "render_environment": {
            "pdf_engine": chrome_version,
            "pdf_normalizer": f"pypdf {PYPDF_VERSION}",
            "latex_compilation_validated": False,
        },
        "failures": failures,
        "claim_boundary": (
            "Machine validation proves page geometry, extractable text, metadata, font resources, "
            "and required disclosures. Visual inspection is separate and is not peer review, "
            "content validation, accessibility certification, or independent replication."
        ),
    }


def _ro_crate(out: Path, title: str, version: str) -> dict[str, Any]:
    files = sorted(
        str(path.relative_to(out))
        for path in out.rglob("*")
        if path.is_file() and path.name not in {"ro-crate-metadata.json", "SHA256SUMS"}
    )
    graph: list[dict[str, Any]] = [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "about": {"@id": "./"},
            "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
        },
        {
            "@id": "./",
            "@type": "Dataset",
            "name": title,
            "version": version,
            "datePublished": "2026-08-23",
            "author": {"@id": "#arhan-canli"},
            "hasPart": [{"@id": name} for name in files],
        },
        {"@id": "#arhan-canli", "@type": "Person", "name": "Arhan Canli"},
    ]
    graph.extend(
        {"@id": name, "@type": "File", "sha256": _sha256(out / name)} for name in files
    )
    return {"@context": "https://w3id.org/ro/crate/1.1/context", "@graph": graph}


def build_one(item: dict[str, Any]) -> Path:
    bundle_manifest = ROOT / item["bundle_manifest"]
    out = bundle_manifest.parent
    paper_metadata = json.loads((out / "paper.json").read_text())
    title = str(paper_metadata["title"])
    version = str(paper_metadata["version"])
    paper_markdown = (out / "paper.md").read_text()
    short_title = _short_title(paper_markdown, title, item["key"])
    seo_title = _seo_title(short_title)
    description = _description(str(paper_metadata["abstract"]))
    canonical = (
        f"https://canlicapital.com/publication/{item['bundle_slug']}/"
        f"v{version}/paper"
    )
    source_slug = Path(item["source_paper"]).stem.lower().replace("_", "-")
    source_html = STATIC_RESEARCH / f"{source_slug}.html"
    if not source_html.is_file():
        raise FileNotFoundError(source_html)
    source_html_text = source_html.read_text()
    source_hash_match = re.search(
        r'<meta name="alphac-source-sha256" content="([0-9a-f]{64})"\s*/?>',
        source_html_text,
    )
    expected_source_hash = _sha256(out / "paper.md")
    if source_hash_match is None:
        raise RuntimeError(
            f"static research HTML has no source-hash contract for {item['key']}"
        )
    if source_hash_match.group(1) != expected_source_hash:
        raise RuntimeError(
            f"static research HTML is stale for {item['key']}: "
            f"{source_hash_match.group(1)} != {expected_source_hash}"
        )
    if not CHROME.is_file():
        raise FileNotFoundError(CHROME)

    references_json = out / "references.json"
    bibliography = _bibliography_html(references_json)
    (out / "paper.html").write_text(
        _html_document(
            title=title,
            seo_title=seo_title,
            description=description,
            canonical=canonical,
            body=_paper_body(source_html) + bibliography,
            version=version,
            key=item["key"],
        )
    )
    (out / "paper.tex").write_text(
        _latex_document(title, print_bibliography=references_json.is_file())
    )
    with tempfile.TemporaryDirectory(prefix="alphac-pdf-") as temp_dir:
        raw = Path(temp_dir) / "raw.pdf"
        completed = subprocess.run(
            [
                str(CHROME),
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--allow-file-access-from-files",
                "--no-pdf-header-footer",
                "--generate-pdf-document-outline",
                f"--print-to-pdf={raw}",
                (out / "paper.html").resolve().as_uri(),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0 or not raw.is_file():
            raise RuntimeError(
                f"Chromium PDF render failed for {item['key']}: {completed.stderr}"
            )
        _normalize_pdf(raw, out / "paper.pdf", title)

    validation = _validation(
        out / "paper.pdf",
        title,
        item["key"],
        out / "paper.md",
        source_html,
        bibliography_expected=True,
    )
    validation["source_bindings"]["static_site_paper_html"][
        "declared_markdown_sha256"
    ] = source_hash_match.group(1)
    validation["source_bindings"]["static_site_paper_html"][
        "matches_paper_markdown"
    ] = True
    if not validation["passes"]:
        raise RuntimeError(f"PDF validation failed for {item['key']}: {validation['failures']}")
    _write_json(out / "pdf_validation.json", validation)

    manifest = json.loads(bundle_manifest.read_text())
    manifest["archival_assets"] = {
        "html": {"path": "paper.html", "sha256": _sha256(out / "paper.html")},
        "latex": {"path": "paper.tex", "sha256": _sha256(out / "paper.tex")},
        "pdf": {
            "path": "paper.pdf",
            "sha256": _sha256(out / "paper.pdf"),
            "pages": validation["pages"],
            "machine_validation": "PASS",
            "visual_inspection": "PENDING_SEPARATE_RECEIPT",
        },
    }
    bibliography_assets: dict[str, dict[str, str]] = {}
    for name in ("references.bib", "references.json"):
        path = out / name
        if path.is_file():
            bibliography_assets[name] = {"path": name, "sha256": _sha256(path)}
    manifest["archival_assets"]["bibliography"] = bibliography_assets
    _write_json(bundle_manifest, manifest)
    _write_json(out / "ro-crate-metadata.json", _ro_crate(out, title, version))
    checksum_files = sorted(
        path for path in out.rglob("*") if path.is_file() and path.name != "SHA256SUMS"
    )
    (out / "SHA256SUMS").write_text(
        "".join(f"{_sha256(path)}  {path.relative_to(out)}\n" for path in checksum_files)
    )
    return out


def main() -> int:
    registry = json.loads(REGISTRY.read_text())
    outputs = [build_one(item) for item in registry["sleeves"]]
    print(f"rendered and machine-validated {len(outputs)} archival paper PDFs")
    for output in outputs:
        validation = json.loads((output / "pdf_validation.json").read_text())
        print(f"{output.relative_to(ROOT)}: {validation['pages']} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
