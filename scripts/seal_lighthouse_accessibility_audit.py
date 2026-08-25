#!/usr/bin/env python3
"""Seal current multi-route Lighthouse accessibility evidence without overstating WCAG scope."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

REPO: Final = Path(__file__).resolve().parents[1]
OUT: Final = REPO / "artifacts" / "audit" / "research_accessibility_audit.json"
REQUIRED_ROUTES: Final = ("/", "/dashboard", "/how-it-works", "/research")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _route_from_report(report: dict[str, Any]) -> tuple[str, str]:
    final_url = str(report.get("finalUrl") or report.get("requestedUrl") or "")
    parsed = urlsplit(final_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("accessibility evidence must come from the declared local production host")
    route = parsed.path.rstrip("/") or "/"
    return route, final_url


def _validate_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    category = report.get("categories", {}).get("accessibility")
    if not isinstance(category, dict) or category.get("score") != 1:
        raise ValueError(f"Lighthouse accessibility score must be exactly 1.0: {path}")
    audits = report.get("audits", {})
    refs = category.get("auditRefs", [])
    if not isinstance(refs, list) or not refs:
        raise ValueError(f"Lighthouse accessibility audit references are missing: {path}")
    try:
        selected = [audits[ref["id"]] for ref in refs]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Lighthouse accessibility audit payload is incomplete: {path}") from exc
    binary_failures = [
        audit
        for audit in selected
        if audit.get("scoreDisplayMode") == "binary" and audit.get("score") == 0
    ]
    if binary_failures:
        raise ValueError(f"refusing to seal binary accessibility failures: {path}")

    route, final_url = _route_from_report(report)
    modes: dict[str, int] = {}
    for audit in selected:
        mode = str(audit.get("scoreDisplayMode", "unknown"))
        modes[mode] = modes.get(mode, 0) + 1
    return {
        "route": route,
        "final_url": final_url,
        "tested_at": report["fetchTime"],
        "lighthouse_version": report["lighthouseVersion"],
        "accessibility_score": 100,
        "category_audits": len(refs),
        "binary_checks_passed": sum(
            audit.get("scoreDisplayMode") == "binary" and audit.get("score") == 1
            for audit in selected
        ),
        "binary_checks_failed": 0,
        "audit_modes": modes,
        "source_report_sha256": sha256_file(path),
    }


def _load_interaction_audit(path: Path) -> dict[str, Any]:
    audit = json.loads(path.read_text(encoding="utf-8"))
    body = {key: value for key, value in audit.items() if key != "content_hash"}
    expected_hash = "sha256:" + hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    routes = audit.get("routes", [])
    checks = {
        "schema": audit.get("schema") == "canli.site-accessibility-interaction-audit.v1",
        "content_hash": audit.get("content_hash") == expected_hash,
        "aggregate_passes": audit.get("passes") is True,
        "route_order": [row.get("route") for row in routes] == list(REQUIRED_ROUTES),
        "every_route_passes": all(row.get("passes") is True for row in routes),
        "every_keyboard_check_passes": all(
            (row.get("keyboard") or {}).get("passes") is True for row in routes
        ),
        "every_layout_check_passes": all(
            (row.get("reflow_320_css_px_and_targets") or {}).get("passes") is True
            for row in routes
        ),
        "every_motion_check_passes": all(
            (row.get("reduced_motion") or {}).get("passes") is True for row in routes
        ),
        "forced_colors_render": all(
            row.get("forced_colors_main_visible") is True for row in routes
        ),
        "zero_browser_errors": all(not row.get("browser_errors") for row in routes),
    }
    failed = [name for name, passes in checks.items() if not passes]
    if failed:
        raise ValueError(f"interaction accessibility evidence fails closed: {', '.join(failed)}")
    return audit


def seal(
    report_paths: Sequence[Path],
    interaction_audit_path: Path,
    out: Path,
) -> dict[str, Any]:
    route_evidence: dict[str, dict[str, Any]] = {}
    for path in report_paths:
        evidence = _validate_report(path)
        route = evidence["route"]
        if route in route_evidence:
            raise ValueError(f"duplicate Lighthouse route: {route}")
        route_evidence[route] = evidence
    missing = sorted(set(REQUIRED_ROUTES) - route_evidence.keys())
    extra = sorted(route_evidence.keys() - set(REQUIRED_ROUTES))
    if missing or extra:
        raise ValueError(f"route coverage mismatch; missing={missing}, extra={extra}")

    routes = [route_evidence[route] for route in REQUIRED_ROUTES]
    versions = {route["lighthouse_version"] for route in routes}
    if len(versions) != 1:
        raise ValueError("all route reports must use one Lighthouse version")
    interaction_audit = _load_interaction_audit(interaction_audit_path)
    payload: dict[str, Any] = {
        "schema": "canli.site-accessibility-audit.v3",
        "project_lead": "Arhan Canli",
        "environment": "LOCAL_PRODUCTION_BUILD",
        "tested_at": max(route["tested_at"] for route in routes),
        "lighthouse_version": versions.pop(),
        "accessibility_score": min(route["accessibility_score"] for route in routes),
        "routes_tested": list(REQUIRED_ROUTES),
        "route_evidence": routes,
        "category_audits": sum(route["category_audits"] for route in routes),
        "binary_checks_passed": sum(route["binary_checks_passed"] for route in routes),
        "binary_checks_failed": 0,
        "interaction_audit": {
            "schema": interaction_audit["schema"],
            "content_hash": interaction_audit["content_hash"],
            "source_sha256": sha256_file(interaction_audit_path),
            "tested_at": interaction_audit["tested_at"],
            "passes": interaction_audit["passes"],
            "routes_tested": [row["route"] for row in interaction_audit["routes"]],
            "public_path": "/glassbox/accessibility_interaction_audit.json",
        },
        "manual_checks_completed": [],
        "automated_supplemental_checks": [
            "complete forward Tab traversal and skip-link focus transfer",
            "focused-element center visibility against fixed content",
            "320-CSS-pixel reflow and non-inline 24-pixel control targets",
            "reduced-motion computed-style enforcement",
            "forced-colors main-content rendering",
            "browser console and page-error capture",
        ],
        "untested_human_dimensions": [
            "human keyboard usability and focus-order review",
            "screen-reader review with VoiceOver, NVDA, or TalkBack",
            "human review at browser zoom levels up to 400 percent",
            "visual review in platform high-contrast modes",
            "touch usability across physical devices",
        ],
        "reproduction": {
            "build": "npm run build",
            "serve": "npm start",
            "audit_template": (
                "npx --no-install lighthouse http://127.0.0.1:3000{route} "
                "--only-categories=accessibility --output=json"
            ),
        },
        "claim_boundary": (
            "This receipt seals Lighthouse and supplemental automated Chromium accessibility "
            "evidence across the four named public routes on local production builds. Perfect "
            "automated results are not complete WCAG 2.2 AA conformance, a human keyboard or "
            "screen-reader certification, or proof about an undeployed build. Untested human "
            "dimensions remain explicit and fail any broader conformance claim open."
        ),
    }
    payload["content_hash"] = content_hash(payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--interaction-audit", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    print(json.dumps(seal(args.reports, args.interaction_audit, args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
