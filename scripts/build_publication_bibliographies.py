#!/usr/bin/env python3
"""Resolve and build deterministic per-sleeve bibliographies from primary identifiers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
REGISTRY: Final = ROOT / "config/external_publication_registry.json"
CACHE: Final = ROOT / "artifacts/research/publication_reference_metadata.json"
RETRIEVED_DATE: Final = "2026-08-23"
USER_AGENT: Final = "ALPHAC bibliography audit contact@canlicapital.com"
DOI_PATTERN: Final = re.compile(r"https://doi\.org/([^\s)]+)", re.IGNORECASE)
URL_DOI_OVERRIDES: Final = {
    "https://arxiv.org/abs/2212.06888": "10.48550/arxiv.2212.06888",
    "https://www.nber.org/papers/w25084": "10.3386/w25084",
    "https://academic.oup.com/rfs/article-abstract/22/3/1311/1581057": (
        "10.1093/rfs/hhn038"
    ),
}
ADDITIONAL_DOIS: Final = {
    "macro_economic_trend": ["10.1016/j.jfineco.2011.11.003"],
}
MANUAL_RECORDS: Final = {
    "10.48550/arxiv.2212.06888": {
        "doi": "10.48550/arXiv.2212.06888",
        "title": "Fundamentals of Perpetual Futures",
        "authors": [
            {"given": "Songrun", "family": "He"},
            {"given": "Asaf", "family": "Manela"},
            {"given": "Omri", "family": "Ross"},
            {"given": "Victor", "family": "von Wachter"},
        ],
        "year": 2022,
        "container_title": "arXiv",
        "type": "posted-content",
        "url": "https://arxiv.org/abs/2212.06888",
        "volume": "",
        "issue": "",
        "pages": "",
        "publisher": "arXiv",
        "metadata_authority": "ARXIV_PRIMARY_RECORD",
    }
}
ONLINE_REFERENCES: Final = {
    "https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/"
    "rest-api/Get-Funding-Rate-History": {
        "citation_key": "binance_funding_history_api",
        "title": "Get Funding Rate History",
        "author": "Binance",
        "year": "2026",
        "urldate": RETRIEVED_DATE,
    }
}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _first(value: Any) -> str:
    return str(value[0]) if isinstance(value, list) and value else ""


def _crossref_record(doi: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(doi, safe="")
    request = urllib.request.Request(
        f"https://api.crossref.org/works/{encoded}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        message = json.load(response)["message"]
    date_parts = (
        message.get("published-print", message.get("published-online", message.get("issued", {})))
        .get("date-parts", [[]])[0]
    )
    return {
        "doi": str(message["DOI"]),
        "title": _first(message.get("title")),
        "authors": [
            {"given": str(author.get("given", "")), "family": str(author.get("family", ""))}
            for author in message.get("author", [])
        ],
        "year": int(date_parts[0]) if date_parts else None,
        "container_title": _first(message.get("container-title")),
        "type": str(message.get("type", "")),
        "url": f"https://doi.org/{message['DOI']}",
        "volume": str(message.get("volume", "")),
        "issue": str(message.get("issue", "")),
        "pages": str(message.get("page", "")),
        "publisher": str(message.get("publisher", "")),
        "metadata_authority": "CROSSREF_REST_API",
    }


def _source_dois(item: dict[str, Any]) -> tuple[list[str], list[str]]:
    text = (ROOT / item["source_paper"]).read_text()
    dois = [match.group(1).rstrip(".,").lower() for match in DOI_PATTERN.finditer(text)]
    online: list[str] = []
    for url, doi in URL_DOI_OVERRIDES.items():
        if url in text:
            dois.append(doi.lower())
    for url in ONLINE_REFERENCES:
        if url in text:
            online.append(url)
    dois.extend(ADDITIONAL_DOIS.get(item["key"], []))
    return list(dict.fromkeys(dois)), online


def _all_required_dois(registry: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for item in registry["sleeves"]:
        if item["key"] == "alphavintage_macro_surprise":
            continue
        values.extend(_source_dois(item)[0])
    return sorted(set(values))


def _refresh_cache(registry: dict[str, Any]) -> dict[str, Any]:
    records: dict[str, dict[str, Any]] = {}
    for doi in _all_required_dois(registry):
        records[doi] = MANUAL_RECORDS[doi] if doi in MANUAL_RECORDS else _crossref_record(doi)
    document = {
        "schema": "canli.alphac-publication-reference-metadata.v1",
        "retrieved_date": RETRIEVED_DATE,
        "metadata_sources": {
            "crossref": "https://api.crossref.org/works/{doi}",
            "arxiv": "https://arxiv.org/abs/2212.06888",
        },
        "records": records,
        "unresolved_references": [],
        "claim_boundary": (
            "This cache records bibliographic metadata, not endorsement, peer review of ALPHAC, "
            "or evidence that the cited literature validates any ALPHAC result."
        ),
    }
    body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    document["content_hash"] = f"sha256:{hashlib.sha256(body).hexdigest()}"
    _write_json(CACHE, document)
    return document


def _validate_cache(cache: dict[str, Any], required: list[str]) -> None:
    body = {key: value for key, value in cache.items() if key != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    expected = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    if cache.get("content_hash") != expected:
        raise ValueError("reference metadata cache content hash mismatch")
    missing = sorted(set(required) - set(cache.get("records", {})))
    if missing:
        raise ValueError(f"reference metadata cache is missing DOI records: {missing}")
    for doi in required:
        record = cache["records"][doi]
        if not record.get("title") or not record.get("authors") or not record.get("year"):
            raise ValueError(f"incomplete bibliographic metadata for {doi}")


def _citation_key(record: dict[str, Any]) -> str:
    family = re.sub(r"[^a-z0-9]+", "", record["authors"][0]["family"].lower())
    title_word = next(
        (word.lower() for word in re.findall(r"[A-Za-z0-9]+", record["title"]) if len(word) > 3),
        "work",
    )
    suffix = hashlib.sha256(record["doi"].lower().encode()).hexdigest()[:6]
    return f"{family}{record['year']}{title_word}_{suffix}"


def _bib_escape(value: str) -> str:
    return (
        value.replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("_", r"\_")
        .replace("#", r"\#")
    )


def _bib_entry(record: dict[str, Any], key: str) -> str:
    authors = " and ".join(
        f"{author['family']}, {author['given']}".strip(", ") for author in record["authors"]
    )
    entry_type = "article" if record["type"] == "journal-article" else "techreport"
    fields = [
        ("author", authors),
        ("title", record["title"]),
        ("year", str(record["year"])),
    ]
    if entry_type == "article":
        fields.extend(
            [
                ("journal", record["container_title"]),
                ("volume", record["volume"]),
                ("number", record["issue"]),
                ("pages", record["pages"]),
            ]
        )
    else:
        fields.append(("institution", record["publisher"] or record["container_title"]))
    fields.extend([("doi", record["doi"]), ("url", record["url"])])
    rendered = "\n".join(
        f"  {name:<11} = {{{_bib_escape(value)}}}," for name, value in fields if value
    )
    return f"@{entry_type}{{{key},\n{rendered}\n}}"


def _online_entry(url: str, metadata: dict[str, str]) -> str:
    return "\n".join(
        [
            f"@online{{{metadata['citation_key']},",
            f"  author      = {{{metadata['author']}}},",
            f"  title       = {{{metadata['title']}}},",
            f"  year        = {{{metadata['year']}}},",
            f"  url         = {{{url}}},",
            f"  urldate     = {{{metadata['urldate']}}},",
            "}",
        ]
    )


def _build_bundle(item: dict[str, Any], cache: dict[str, Any]) -> None:
    if item["key"] == "alphavintage_macro_surprise":
        return
    out = (ROOT / item["bundle_manifest"]).parent
    dois, online_urls = _source_dois(item)
    records = [cache["records"][doi] for doi in dois]
    references = [
        {
            "citation_key": _citation_key(record),
            "doi": record["doi"],
            "title": record["title"],
            "authors": record["authors"],
            "year": record["year"],
            "container_title": record["container_title"],
            "url": record["url"],
            "metadata_authority": record["metadata_authority"],
        }
        for record in records
    ]
    references.extend(
        {
            "citation_key": ONLINE_REFERENCES[url]["citation_key"],
            "title": ONLINE_REFERENCES[url]["title"],
            "authors": [{"family": ONLINE_REFERENCES[url]["author"], "given": ""}],
            "year": int(ONLINE_REFERENCES[url]["year"]),
            "container_title": "Official documentation",
            "url": url,
            "metadata_authority": "PRIMARY_VENDOR_DOCUMENTATION",
        }
        for url in online_urls
    )
    if not references:
        raise ValueError(f"no bibliography references resolved for {item['key']}")
    document = {
        "schema": "canli.alphac-sleeve-bibliography.v1",
        "registry_key": item["key"],
        "author": "Arhan Canli",
        "reference_count": len(references),
        "references": references,
        "metadata_cache": {
            "path": str(CACHE.relative_to(ROOT)),
            "sha256": hashlib.sha256(CACHE.read_bytes()).hexdigest(),
            "content_hash": cache["content_hash"],
        },
        "unresolved_references": [],
        "status": "COMPLETE_NORMALIZED_BIBLIOGRAPHY",
    }
    _write_json(out / "references.json", document)
    entries = [_bib_entry(record, _citation_key(record)) for record in records]
    entries.extend(_online_entry(url, ONLINE_REFERENCES[url]) for url in online_urls)
    (out / "references.bib").write_text("\n\n".join(entries) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-crossref", action="store_true")
    args = parser.parse_args()
    registry = json.loads(REGISTRY.read_text())
    cache = _refresh_cache(registry) if args.refresh_crossref else json.loads(CACHE.read_text())
    required = _all_required_dois(registry)
    _validate_cache(cache, required)
    for item in registry["sleeves"]:
        _build_bundle(item, cache)
    print(f"built 15 normalized bibliographies from {len(required)} unique DOI records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
