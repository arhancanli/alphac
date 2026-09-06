"""The site checks must expect what the sites are DESIGNED to do, not what they did in July.

2026-09-06: the nightly alert had read "standing red x4" since 27 August, and three of the four
were the monitor disagreeing with deliberate behaviour. ``www.canlicapital.com`` returns 301 to
the apex (in ``vercel.json`` since the first commit); the check expected 200 and first failed on
08-21. The app's ``/sign-in`` and ``/sign-up`` became ``redirect("/dashboard")`` when the
development auth gate was removed (meridian-app ``3eeef36``, 08-26); the check expected 200 and
failed from that night on. Ten nights of standing red is how a monitor that then crashed outright
(see ``test_health_check_runs_under_launchd_python.py``) went unnoticed for a night: the mail
already looked like that.

So the expectations now state the design: the www host redirects to the apex and nowhere else;
the legacy auth URLs redirect to the dashboard and nowhere else; the CTA routes the app actually
links to (dashboard, how-it-works, research) answer 200. A redirect that vanishes, a 404 on a
legacy URL, or a login page coming back are all FAIL.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "health_check_sites_under_test", _ROOT / "scripts" / "health_check.py"
)
assert _SPEC and _SPEC.loader
HEALTH = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(HEALTH)

LANDING = HEALTH.LANDING
APP = HEALTH.APP


def _healthy_codes() -> dict[str, int]:
    return {
        LANDING: 200,
        APP: 200,
        **{
            f"{LANDING}/{r}": 200
            for r in ("performance", "progress", "systems", "open", "research")
        },
        **{f"{APP}/{r}": 200 for r in ("dashboard", "how-it-works", "research")},
        f"{LANDING}/sitemap.xml": 200,
        f"{LANDING}/robots.txt": 200,
        f"{LANDING}/api/waitlist": 405,
    }


def _healthy_redirects() -> dict[str, tuple[int, str]]:
    www = LANDING.replace("//", "//www.")
    return {
        www: (301, f"{LANDING}/"),
        f"{APP}/sign-in": (307, f"{APP}/dashboard"),
        f"{APP}/sign-up": (307, f"{APP}/dashboard"),
    }


def _run(monkeypatch, codes: dict[str, int], redirects: dict[str, tuple[int, str]]) -> dict:
    monkeypatch.setattr(HEALTH, "RESULTS", [])

    def fake_http(url: str, method: str = "GET", timeout: int = 20) -> int:
        assert url in codes, f"check_sites probed an unexpected URL with http(): {url}"
        return codes[url]

    def fake_redirect(url: str, timeout: int = 20) -> tuple[int, str]:
        assert url in redirects, f"check_sites probed an unexpected URL with http_redirect(): {url}"
        return redirects[url]

    monkeypatch.setattr(HEALTH, "http", fake_http)
    monkeypatch.setattr(HEALTH, "http_redirect", fake_redirect)
    monkeypatch.setattr(HEALTH, "check_validation_api", lambda: None)
    HEALTH.check_sites()
    return {r["id"]: r for r in HEALTH.RESULTS}


def test_the_designed_behaviour_is_all_green(monkeypatch) -> None:
    res = _run(monkeypatch, _healthy_codes(), _healthy_redirects())
    reds = {k: v for k, v in res.items() if v["status"] != "PASS"}
    assert reds == {}, reds
    assert res["C3-landing-www"]["status"] == "PASS"
    assert res["C3-app-legacy-auth"]["status"] == "PASS"
    assert res["C3-app-routes"]["status"] == "PASS"
    assert "dashboard" in res["C3-app-routes"]["evidence"]
    assert "sign-in" not in res["C3-app-routes"]["evidence"]


def test_www_serving_the_site_directly_is_red(monkeypatch) -> None:
    """The apex is canonical. A 200 on www is a second copy of the site, not a pass."""
    redirects = _healthy_redirects()
    redirects[LANDING.replace("//", "//www.")] = (200, "")
    res = _run(monkeypatch, _healthy_codes(), redirects)
    assert res["C3-landing-www"]["status"] == "FAIL"


def test_www_redirecting_anywhere_but_the_apex_is_red(monkeypatch) -> None:
    redirects = _healthy_redirects()
    redirects[LANDING.replace("//", "//www.")] = (301, "http://canlicapital.com/")
    res = _run(monkeypatch, _healthy_codes(), redirects)
    assert res["C3-landing-www"]["status"] == "FAIL"
    assert "http://canlicapital.com/" in res["C3-landing-www"]["observed"]


def test_www_unreachable_is_red(monkeypatch) -> None:
    redirects = _healthy_redirects()
    redirects[LANDING.replace("//", "//www.")] = (0, "")
    assert _run(monkeypatch, _healthy_codes(), redirects)["C3-landing-www"]["status"] == "FAIL"


def test_a_legacy_auth_url_that_404s_is_red_and_named(monkeypatch) -> None:
    redirects = _healthy_redirects()
    redirects[f"{APP}/sign-up"] = (404, "")
    res = _run(monkeypatch, _healthy_codes(), redirects)
    assert res["C3-app-legacy-auth"]["status"] == "FAIL"
    assert "sign-up" in res["C3-app-legacy-auth"]["observed"]
    assert "sign-in" not in res["C3-app-legacy-auth"]["observed"]


def test_a_login_page_coming_back_is_red(monkeypatch) -> None:
    """The auth gate was removed on purpose; its return is a change someone must declare."""
    redirects = _healthy_redirects()
    redirects[f"{APP}/sign-in"] = (200, "")
    assert _run(monkeypatch, _healthy_codes(), redirects)["C3-app-legacy-auth"]["status"] == "FAIL"


def test_a_cta_route_erroring_is_its_own_red_row(monkeypatch) -> None:
    codes = _healthy_codes()
    codes[f"{APP}/research"] = 500
    res = _run(monkeypatch, codes, _healthy_redirects())
    assert res["C3-app-route-research"]["status"] == "FAIL"
    assert res["C3-app-route-research"]["observed"] == "500"


def test_apex_down_is_critical(monkeypatch) -> None:
    codes = _healthy_codes()
    codes[LANDING] = 0
    res = _run(monkeypatch, codes, _healthy_redirects())
    assert res["C3-landing-apex"]["status"] == "FAIL"
    assert res["C3-landing-apex"]["severity"] == "critical"
