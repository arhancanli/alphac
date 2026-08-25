#!/usr/bin/env python3
"""End-to-end browser QA for the offline Active Ownership review workspace."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import ConsoleMessage, Page

REPO = Path(__file__).resolve().parents[2]
PACKET = REPO / "artifacts" / "labeling" / "active_ownership_13d_item4_v3_blind"
URL = "http://127.0.0.1:8765/review.html"
DESKTOP_SCREENSHOT = Path("/tmp/alphac-active-ownership-review-desktop.png")
MOBILE_SCREENSHOT = Path("/tmp/alphac-active-ownership-review-mobile.png")


def install_error_capture(page: Page, errors: list[str]) -> None:
    def on_console(message: ConsoleMessage) -> None:
        if message.type == "error":
            errors.append(f"console: {message.text}")

    page.on("console", on_console)
    page.on("pageerror", lambda error: errors.append(f"page: {error}"))


def complete_row(page: Page, index: int) -> None:
    page.locator(".docket-tab").nth(index).click()
    page.locator("label.choice").nth(1).click()
    page.locator("#sentence").fill("No specific current action is stated in this source excerpt.")
    page.locator("#ownership").fill("unresolved")


def desktop_flow(
    page: Page, errors: list[str], *, packet_dir: Path, workspace_url: str
) -> tuple[Path, Path]:
    install_error_capture(page, errors)
    page.goto(workspace_url)
    page.wait_for_load_state("networkidle")
    assert page.get_by_role("heading", name="Active Ownership Evidence Desk").is_visible()
    assert page.locator(".docket-tab").count() == 48
    assert page.locator("#progressCount").inner_text() == "0 / 48"

    # The signature interaction copies an exact source selection into the governed field.
    page.evaluate(
        """
        () => {
          const node = document.querySelector('#filingText').firstChild;
          const range = document.createRange();
          range.setStart(node, 0);
          range.setEnd(node, Math.min(80, node.length));
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
        }
        """
    )
    page.locator("#captureSelection").click()
    assert page.locator("#sentence").input_value().strip()

    page.locator("label.choice").nth(0).click()
    page.locator("#sentence").fill("A specific governance action is stated in this source excerpt.")
    page.locator("#ownership").fill("7.5")
    page.locator("#notes").fill("Browser QA record; not a research label.")
    assert page.locator("#progressCount").inner_text() == "1 / 48"

    # Browser-local autosave must survive reload without writing into the packet.
    page.reload()
    page.wait_for_load_state("networkidle")
    assert page.locator('input[name="intent"][value="true"]').is_checked()
    assert page.locator("#ownership").input_value() == "7.5"
    assert page.locator("#progressCount").inner_text() == "1 / 48"

    # Search and keyboard navigation remain usable without changing row order.
    page.locator("#search").fill("AO13D-048")
    assert page.locator(".docket-tab").count() == 1
    page.locator("#search").fill("")
    page.keyboard.press("Alt+ArrowRight")
    assert page.locator("#documentId").inner_text() == "AO13D-002"

    # Governed exports remain unavailable while even one record is incomplete.
    page.locator("#exportLabels").click()
    assert "Complete all 48" in page.locator("#statusBox").inner_text()

    for index in range(48):
        complete_row(page, index)
    assert page.locator("#progressCount").inner_text() == "48 / 48"

    manifest = json.loads((packet_dir / "manifest.json").read_text(encoding="utf-8"))
    page.locator("#reviewerName").fill("Independent Browser QA Reviewer")
    page.locator("#reviewerRole").fill("Source document reviewer")
    page.locator("#packetHash").fill(manifest["content_hash"])
    for selector in ("#flagIndependent", "#flagMachine", "#flagReturns", "#flagPersonal"):
        page.locator(selector).check()

    temp = Path(tempfile.mkdtemp(prefix="alphac-review-browser-"))
    with page.expect_download() as label_download:
        page.locator("#exportLabels").click()
    labels_path = temp / "completed_labels.csv"
    label_download.value.save_as(labels_path)
    with page.expect_download() as attestation_download:
        page.locator("#exportAttestation").click()
    attestation_path = temp / "completed_attestation.json"
    attestation_download.value.save_as(attestation_path)

    with labels_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 48
    assert rows[0]["packet_id"] == "AO13D-001"
    assert rows[-1]["packet_id"] == "AO13D-048"
    assert all(row["human_specific_active_intent"] == "false" for row in rows)
    assert all(row["human_aggregate_ownership_pct_or_unresolved"] == "unresolved" for row in rows)

    verification = subprocess.run(
        [
            sys.executable,
            str(packet_dir / "verify_review.py"),
            "--completed",
            str(labels_path),
            "--attestation",
            str(attestation_path),
        ],
        cwd=packet_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert verification.returncode == 0, verification.stderr
    assert json.loads(verification.stdout)["status"] == "REVIEW_RETURN_VALID"
    page.evaluate(
        """
        () => {
          document.querySelector('.docket-list').scrollTop = 0;
          document.querySelector('.document-scroll').scrollTop = 0;
          document.querySelector('.review-panel').scrollTop = 0;
          window.scrollTo(0, 0);
        }
        """
    )
    page.screenshot(path=str(DESKTOP_SCREENSHOT))
    return labels_path, attestation_path


def mobile_flow(page: Page, errors: list[str], *, workspace_url: str) -> None:
    install_error_capture(page, errors)
    page.goto(workspace_url)
    page.wait_for_load_state("networkidle")
    assert page.locator(".docket-list").is_visible()
    assert page.locator("#filingText").is_visible()
    assert page.locator("#ownership").is_visible()
    dimensions = page.evaluate(
        """
        () => ({
          scrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
          offenders: [...document.querySelectorAll('*')]
            .map((element) => ({
              tag: element.tagName,
              id: element.id,
              className: typeof element.className === 'string' ? element.className : '',
              left: element.getBoundingClientRect().left,
              right: element.getBoundingClientRect().right,
              width: element.getBoundingClientRect().width
            }))
            .filter((item) => item.left < -1 || item.right > window.innerWidth + 1)
            .slice(0, 20)
        })
        """
    )
    page.screenshot(path=str(MOBILE_SCREENSHOT))
    assert dimensions["scrollWidth"] <= dimensions["innerWidth"], json.dumps(dimensions, indent=2)


def main(*, packet_dir: Path = PACKET, workspace_url: str = URL) -> None:
    # Keep Playwright optional for ordinary pytest collection. This file is an
    # executable browser harness; the explicit QA command supplies Playwright.
    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        desktop = browser.new_context(
            viewport={"width": 1440, "height": 1000}, accept_downloads=True
        )
        labels, attestation = desktop_flow(
            desktop.new_page(), errors, packet_dir=packet_dir, workspace_url=workspace_url
        )
        desktop.close()
        mobile = browser.new_context(viewport={"width": 390, "height": 844}, accept_downloads=True)
        mobile_flow(mobile.new_page(), errors, workspace_url=workspace_url)
        mobile.close()
        browser.close()
    assert not errors, "\n".join(errors)
    print(
        json.dumps(
            {
                "status": "PASS_BROWSER_QA",
                "desktop_screenshot": str(DESKTOP_SCREENSHOT),
                "mobile_screenshot": str(MOBILE_SCREENSHOT),
                "verified_labels": str(labels),
                "verified_attestation": str(attestation),
                "console_or_page_errors": errors,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet-dir", type=Path, default=PACKET)
    parser.add_argument("--url", default=URL)
    arguments = parser.parse_args()
    main(packet_dir=arguments.packet_dir, workspace_url=arguments.url)
