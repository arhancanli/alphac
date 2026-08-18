#!/usr/bin/env python3
"""Genuine broker-executed live paper cycle — turns a sleeve from SIMULATION into REAL Alpaca fills.

The red-team's #1 finding: our equity/MF "live" records are walk-forward simulations, not broker-
executed. This closes that gap. One cycle:
  1. read the strategy's TARGET book (the latest walk-forward leg's per-instrument weights),
  2. size those weights to the live Alpaca account (target_shares = weight * equity / price),
  3. diff against the CURRENT Alpaca positions -> delta orders (open new, trim, flip, close),
  4. submit each delta via AlpacaBroker with a DETERMINISTIC client_order_id (date+ticker) so a
     re-run never double-trades, and
  5. record the realized account equity to trading_<asset_class>.sqlite (read by the public state).

Start with managed-futures (17 liquid ETFs, all Alpaca-tradable, our soundest sleeve). Equity (200
survivorship-free names, some untradable) is the harder follow-on and trades its tradable subset.

    live_cycle.py --profile managed_futures --dry-run     # compute + print the orders, submit NOTHING
    live_cycle.py --profile managed_futures               # submit to Alpaca paper + record

Execution correctness (2026-08-01 live-log fixes; see tests/unit/test_live_cycle_execution.py):
  * FLIP-SPLIT — a position that reverses sign is submitted as TWO orders (flatten the current
    position, then open the target on the other side). A single oversized order across zero is
    what Alpaca rejects ('insufficient qty available for order (requested: 346.4156, available:
    166)'), which silently killed every flip. A same-side resize is still exactly ONE order.
    The zero-crossing OPEN leg is never emitted alone: the dust gate cannot drop the close leg out
    from under it, and a flip whose close leg cannot flatten the position (a fractional holding of
    a non-fractionable name) is withheld and DISCLOSED instead of sent to be rejected.
  * SHORTABILITY / FRACTIONABILITY — a short target on a non-shortable asset ('asset "FXE" cannot
    be sold short', HTTP 422) is never submitted: the name's target becomes 0 (any existing
    position still flattens) and the skip is disclosed loudly. Non-fractionable names are
    truncated to whole shares. A reject NEVER aborts the cycle.
  * AUDIT TRAIL — every submitted order and every reject/disclosed skip is written to the
    per-profile DB (tables ``orders`` / ``order_rejects``), so diagnosing an execution outage no
    longer means grepping logs.
"""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import glob
import json
import math
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# profile -> the walk-forward artifact whose latest leg holds the current target book
_WF = {
    "managed_futures": ["mf_live_fwd", "managed_futures"],
    "equity": ["equity_live_fwd", "k30_dn_63"],
    # AlphaLedger (eq_asset_growth). OPEN QUESTION, deliberately recorded here rather than in a
    # doc nobody re-reads: docs/design/PREREG_SLEEVE4_INVESTMENT.md pins the universe to
    # data/research/universe_allowlist_20260619.json (sha256 2fd82d30...) and states that altering
    # any row voids the pre-registration. The artifact below has NOT been confirmed to match that
    # pinned cohort. Until it is, this sleeve's 21-year NW t +3.19 rests on a document whose own
    # conditions may not hold. Wiring is safe (nothing trades until a launchd job calls it); the
    # evidence question is not settled by wiring.
    "alphaledger": ["prereg_investment"],
    # AlphaVintage (CPI-surprise IWM/SPY size spread). Its artifact is NOT produced by a
    # walk-forward run — the sleeve was validated as a probe — so scripts/alphavintage_target.py
    # writes the same leg layout from the pre-registered rule. Routing it here rather than giving
    # it a bespoke runner is deliberate: it inherits the price collar, participation cap,
    # flip-split and kill switch instead of forking a second, unguarded order path.
    "alphavintage": ["alphavintage_live"],
}
# profile -> its OWN Alpaca paper account (separate accounts = clean per-sleeve equity history, since
# Alpaca's portfolio history is account-level).
#
# *** NO FALLBACK. *** This dict used to be read with .get(), so an UNMAPPED profile returned None
# and AlpacaBroker silently fell back to _ENV_PATH (alpaca.env) — which is AlphaTrend's LIVE
# account. Adding a new sleeve and forgetting one line here would have submitted its book into a
# different sleeve's live account, commingling two track records irreversibly and corrupting the
# per-sleeve history that separate accounts exist to protect. There is no safe default for "which
# real account should this trade into", so an unmapped profile is now a hard failure.
_ACCOUNT_ENV = {
    "managed_futures": Path.home() / ".config" / "alphaforge" / "alpaca.env",          # PA3IQC5B7BC2
    "equity": Path.home() / ".config" / "alphaforge" / "alpaca_equity.env",            # PA397834GG9R
    "alphaledger": Path.home() / ".config" / "alphaforge" / "alpaca_ledger.env",       # PA3DYIG9B4AL
    "alphavintage": Path.home() / ".config" / "alphaforge" / "alpaca_vintage.env",     # PA39G6N49JRY
}


def _account_env(profile: str) -> Path:
    """The credentials file for ``profile``, or a hard failure. Never a default."""
    try:
        path = _ACCOUNT_ENV[profile]
    except KeyError:
        known = ", ".join(sorted(_ACCOUNT_ENV))
        raise SystemExit(
            f"REFUSING TO TRADE: profile {profile!r} has no Alpaca account mapped in _ACCOUNT_ENV.\n"
            f"  Known profiles: {known}\n"
            f"  Without a mapping this would silently submit into {_ACCOUNT_ENV['managed_futures']} "
            f"(AlphaTrend's live account) and commingle two sleeves' track records.\n"
            f"  Add {profile!r} -> its own ~/.config/alphaforge/alpaca_<sleeve>.env and retry."
        ) from None
    if not path.exists():
        raise SystemExit(
            f"REFUSING TO TRADE: profile {profile!r} maps to {path}, which does not exist.\n"
            f"  Create it with APCA_API_KEY_ID / APCA_API_SECRET_KEY / APCA_API_BASE_URL."
        )
    return path
_MIN_ORDER_USD = 1.0   # skip dust deltas
# Per-name concentration sanity cap, as a fraction of account equity. PER PROFILE, because the
# right value depends on how many names the sleeve holds and a single global number is wrong for
# any book that is legitimately concentrated.
#
# A flat 0.05 was applied to every profile. That is correct for a 178-name dollar-neutral equity
# book, where a 5% single name IS an error. It is badly wrong for a two-instrument spread: an
# IWM/SPY macro sleeve has a median |weight| of 0.411, so 95.5% of its target weights would be
# clamped and the sleeve would trade at roughly 12% of its intended size — SILENTLY, because the
# clamp printed nothing. A sleeve that quietly trades a tenth of its book still reports its full
# backtest, which is the exact shape of an overstatement this project exists to avoid.
_MAX_PARTICIPATION_DEFAULT = 0.05
_MAX_PARTICIPATION_BY_PROFILE = {
    "managed_futures": 0.20,  # 17-market ETF basket, inverse-vol weighted: 5% is too tight
    "equity": 0.05,           # ~178 names, dollar-neutral: 5% single name would be an error
    "alphaledger": 0.05,      # ~179 names, dollar-neutral: same shape as AlphaMax
    # AlphaVintage holds exactly TWO instruments (IWM/SPY) with a median |weight| of 0.411, so a
    # 5% cap would clamp 95.5% of its targets and trade the sleeve at roughly a TENTH of its
    # intended size while its published backtest described the full one. 0.50 is above its
    # observed maximum, so the cap stays a sanity brake on corrupted weights rather than a
    # silent position limit. A concentrated book is not a risk error when the strategy IS a
    # two-legged spread; applying a diversified book's cap to it would be.
    "alphavintage": 0.50,
}


def _max_participation(profile: str) -> float:
    return _MAX_PARTICIPATION_BY_PROFILE.get(profile, _MAX_PARTICIPATION_DEFAULT)
# Marketable-LIMIT buffer: orders are priced through the sizing mid by this fraction (buy at
# mid*(1+b), sell at mid*(1-b)) instead of raw MARKET. Caps the worst-case fill at a known price —
# a fat print / gap / flash spike can no longer fill arbitrarily far from the decision price. A
# non-fill on a >0.75% gap day is the protection WORKING: the next cycle cancels the stale order
# and re-diffs against live positions (per-cycle coids make the corrective re-submit genuine).
_LIMIT_BUFFER = 0.0075
# RUNAWAY brakes on the SIZED TARGET book (not the optimizer's gross target — these are hard limits
# set generously ABOVE any sleeve's legitimate profile so a corrupted-weights/bad-equity book trips
# them while a normal book passes: MF ~1.0x gross, equity ~0.55x, crypto <=1.0x; trend net up to ~1.0x).
_GROSS_HARD_CAP = 1.5  # target book gross > this * equity => corrupted book => engage KILL, submit nothing
_NET_HARD_CAP = 1.2    # target book |net| > this * equity => corrupted book => engage KILL, submit nothing


def _recorded_equity(db: Path) -> list[float]:
    """Prior realized equity marks from a sleeve's trading DB (for the drawdown guard)."""
    if not db.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = con.execute(
            "SELECT equity_quote FROM equity_curve WHERE equity_quote IS NOT NULL ORDER BY ts"
        ).fetchall()
        con.close()
        return [float(r[0]) for r in rows]
    except sqlite3.Error:
        return []


# Asset-class guard (2026-07-18 marking-fix campaign, defect 2): the equity profile's WF
# artifact historically contained BINANCE:PERP:* rows (the equity WF universe was unscoped
# against the shared lake's crypto membership). The WF is now scoped at the source, but this
# executor-side guard stays as defense in depth: the equity book must NEVER submit a
# non-XUSE instrument to Alpaca, and anything dropped is printed LOUDLY.
_EQUITY_ID_PREFIX = "XUSE:"


def _target_weights(profile: str) -> dict[str, float]:
    """The strategy's current target book: {instrument_id: weight} from the latest WF leg."""
    for wf in _WF[profile]:
        legs = sorted(glob.glob(f"artifacts/walkforward/{wf}/legs/leg_*/positions.parquet"))
        if not legs:
            continue
        t = pq.read_table(legs[-1]).to_pydict()  # type: ignore[no-untyped-call]
        rows = list(zip(t["ts"], t["instrument_id"], t["weight"], strict=True))
        last_ts = max(r[0] for r in rows)
        w = {iid: float(wt) for ts, iid, wt in rows if ts == last_ts and abs(float(wt)) > 1e-9}
        if w and profile == "equity":
            bad = sorted(iid for iid in w if not iid.startswith(_EQUITY_ID_PREFIX))
            if bad:
                print(f"!!! ASSET-CLASS GUARD: dropping {len(bad)} non-{_EQUITY_ID_PREFIX} "
                      f"instrument(s) from the equity target book (never tradable here): {bad}")
                w = {iid: wt for iid, wt in w.items() if iid.startswith(_EQUITY_ID_PREFIX)}
        if w:
            return w
    return {}


# ----------------------------------------------------------------------------- order building
# A flip's two legs get their own client_order_ids (suffixes below) so idempotency still holds and
# the stale-order cancel — which filters on the "<profile>-" PREFIX — still sweeps both.
_COID_CLOSE = "-close"
_COID_OPEN = "-open"


def _trunc(x: float, dp: int) -> float:
    """Truncate TOWARD ZERO to ``dp`` decimals (never rounds a close leg ABOVE the held qty,
    which is exactly what Alpaca rejects as 'insufficient qty available for order')."""
    scale = 10.0**dp
    return math.trunc(x * scale) / scale


# A close leg that leaves LESS than this many shares behind has flattened the position: the only
# residuals below it come from _trunc's float arithmetic, never from a real broker holding (Alpaca
# reports positions to 9 decimals). Anything above it is a genuine leftover, and an open leg on top
# of it would still cross zero -> the open leg is withheld and disclosed.
_FLATTEN_EPS = 1e-8


def _delta_orders(*, profile: str, cycle_ms: int, instrument_id: str, symbol: str,
                  cur_shares: float, tgt_shares: float, mid: float, market_orders: bool,
                  whole_only: bool = False, skips: list[str] | None = None) -> list[Any]:
    """PURE: the order(s) that move ``cur_shares`` to ``tgt_shares`` for one name.

    Same-side resize (including open-from-flat and close-to-flat) -> exactly ONE order, built
    byte-identically to the pre-flip-split executor (same coid, side, qty, limit price, reason).

    SIGN FLIP (cur and tgt strictly opposite) -> TWO orders: first flatten the current position to
    zero, then open the target on the other side. Alpaca rejects a single order that crosses zero
    ('insufficient qty available for order'), so the one-order form NEVER executed a flip. The open
    leg may itself be refused until the close leg fills (the broker still sees the old position);
    that is a clean, audited reject and the next cycle re-diffs against a flat book and opens.

    THE OPEN LEG IS NEVER EMITTED ALONE. It is the only order this function can build that crosses
    zero, and it is appended solely after a close leg that flattens the WHOLE current position:
      * the $1 dust gate is not applied to the close leg (a dust-sized current position — cur=+0.02
        with tgt=-100 — used to drop the close and submit the lone crossing SELL 100);
      * when the close leg cannot flatten the position at all (a fractional holding of a
        non-fractionable name: cur=+0.5 truncates to 0 whole shares) the ENTIRE flip is skipped;
      * when the close leg can only flatten part of it (cur=+5.5 whole-share-only -> closes 5,
        0.5 left) the close is still sent (it de-risks) but the open is withheld.
    Each withheld flip appends a human-readable line to ``skips`` (when provided) so the caller can
    disclose and audit it instead of sending an order the broker is guaranteed to reject.

    ``whole_only`` (non-fractionable asset) truncates every qty toward zero to whole shares — the
    same treatment short targets always get.
    """
    from alphaforge.core.types import OrderRequest, OrderType, Side

    def _mk(signed_qty: float, *, suffix: str, tag: str, reduce_only: bool = False) -> Any:
        side = Side.BUY if signed_qty > 0 else Side.SELL
        if market_orders:
            otype, px = OrderType.MARKET, mid
        else:
            otype = OrderType.LIMIT
            px = round(mid * (1 + _LIMIT_BUFFER), 2) if side is Side.BUY else round(mid * (1 - _LIMIT_BUFFER), 2)
        return OrderRequest(
            client_order_id=f"{profile}-{cycle_ms}-{symbol}{suffix}", instrument_id=instrument_id,
            side=side, qty=abs(signed_qty), order_type=otype, reduce_only=reduce_only,
            decision_ts=cycle_ms, decision_price=px, reason=f"{profile}-{tag}",
        )

    delta = tgt_shares - cur_shares
    # Alpaca forbids fractional SHORT sales (and any fractional order on a non-fractionable asset)
    if tgt_shares < 0 or whole_only:
        delta = float(int(delta))
    delta = round(delta, 4)
    if abs(delta) * mid < _MIN_ORDER_USD:  # dust gate on the NET delta (unchanged)
        return []
    if cur_shares * tgt_shares >= 0.0:  # not a flip -> exactly one order, as before
        return [_mk(delta, suffix="", tag="rebalance")]
    # --- flip: close the current side, then open the other side ---
    close_qty = _trunc(abs(cur_shares), 0 if whole_only else 9)
    if close_qty <= 0.0:
        # Nothing about this position is closable (a sub-1-share holding of a whole-share-only
        # name), so the open leg would be a LONE order crossing zero -> guaranteed reject. Skip the
        # name and disclose it instead.
        if skips is not None:
            why = "whole-share-only name" if whole_only else "below the smallest submittable size"
            skips.append(f"flip {cur_shares:+.6f} -> {tgt_shares:+.2f} withheld: the "
                         f"{abs(cur_shares):.6f}-share position cannot be flattened ({why}), and an "
                         f"open leg on top of it would cross zero and be rejected")
        return []
    # The close leg is exempt from the dust gate: it is reduce-only, it can never cross zero, and
    # dropping it is precisely what left the open leg standing alone.
    out: list[Any] = [_mk(-cur_shares / abs(cur_shares) * close_qty, suffix=_COID_CLOSE,
                          tag="flip-close", reduce_only=True)]
    if abs(cur_shares) - close_qty > _FLATTEN_EPS:
        # A real residual survives the close (whole-share truncation of a fractional holding), so an
        # open leg would still cross zero. Keep the de-risking close, withhold the open, disclose.
        if skips is not None:
            skips.append(f"flip {cur_shares:+.4f} -> {tgt_shares:+.2f} open leg withheld: the close "
                         f"leg can only flatten {close_qty:.4f} of {abs(cur_shares):.4f} shares "
                         f"(whole-share-only name); opening over the residual would cross zero")
        return out
    open_qty = _trunc(abs(tgt_shares), 0 if (whole_only or tgt_shares < 0) else 4)
    if open_qty * mid >= _MIN_ORDER_USD:
        out.append(_mk(tgt_shares / abs(tgt_shares) * open_qty, suffix=_COID_OPEN, tag="flip-open"))
    return out


# ----------------------------------------------------------------------------- broker asset flags
class _AssetMeta:
    """Alpaca's per-asset tradability flags (shortable / fractionable), fetched ONCE per cycle.

    One bulk GET /v2/assets (~14k rows, ~3s) instead of one call per name. If it fails we simply
    return None ("unknown") for every symbol and fall back to catching the broker's 422/403 —
    either way an unfillable name is a disclosed skip, never an aborted cycle.
    """

    def __init__(self, broker: Any) -> None:
        self._broker = broker
        self._map: dict[str, tuple[bool, bool]] | None = None
        self._loaded = False

    def _load(self) -> None:
        self._loaded = True
        client = getattr(self._broker, "_client", None)
        base = getattr(self._broker, "_base", None)
        if client is None or not base:
            return
        try:
            r = client.get(f"{base}/v2/assets", params={"status": "active", "asset_class": "us_equity"})
            if r.status_code != 200:
                print(f"  (asset flags unavailable: HTTP {r.status_code} — falling back to reject-catching)")
                return
            rows = r.json()
        except Exception as e:  # never let a metadata fetch break the cycle
            print(f"  (asset flags unavailable: {str(e)[:60]} — falling back to reject-catching)")
            return
        m: dict[str, tuple[bool, bool]] = {}
        for a in rows:
            sym = str(a.get("symbol") or "")
            if sym:
                m[sym] = (bool(a.get("shortable")), bool(a.get("fractionable")))
        self._map = m or None

    def flags(self, symbol: str) -> tuple[bool, bool] | None:
        """(shortable, fractionable) for ``symbol``, or None when unknown."""
        if not self._loaded:
            self._load()
        if self._map is None:
            return None
        return self._map.get(symbol)


# ----------------------------------------------------------------------------- reject handling
def _parse_reject(reason: str) -> tuple[str, str]:
    """('42210000', 'asset "FXE" cannot be sold short') from an AlpacaBroker ack reason.

    Ack reasons look like ``HTTP 422: {"code":42210000,"message":"..."}``; anything unparseable
    degrades to (the HTTP token, the raw text) so the audit row is still informative.
    """
    head, _, tail = reason.partition(": ")
    code = head.strip() or "unknown"
    body = tail.strip()
    try:
        j = json.loads(body)
        if isinstance(j, dict):
            return str(j.get("code", code)), str(j.get("message", body))
    except (ValueError, TypeError):
        pass
    return code, body or reason


def _skip_kind(message: str) -> str | None:
    """Classify a broker rejection that is a KNOWN untradable-name condition (a disclosed skip,
    not an execution failure): the name is simply dropped and the rest of the book proceeds."""
    m = message.lower()
    if "cannot be sold short" in m or "not shortable" in m:
        return "not-shortable"
    if "not fractionable" in m or "fractional" in m:
        return "not-fractionable"
    return None



def dt_date_str() -> str:
    """Today's date in US/Eastern, which is the market's day rather than the operator's."""
    return datetime.now(tz=__import__("datetime").timezone(
        __import__("datetime").timedelta(hours=-5))).date().isoformat()

# ----------------------------------------------------------------------------- audit trail
_ORDERS_DDL = """CREATE TABLE IF NOT EXISTS orders (
    client_order_id TEXT PRIMARY KEY,
    ts INTEGER NOT NULL,
    instrument_id TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    price REAL,
    order_type TEXT,
    intent TEXT,
    accepted INTEGER,
    broker_order_id TEXT
)"""
_REJECTS_DDL = """CREATE TABLE IF NOT EXISTS order_rejects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    client_order_id TEXT,
    instrument_id TEXT NOT NULL,
    code TEXT,
    message TEXT
)"""


_FILLS_DDL = """CREATE TABLE IF NOT EXISTS fills (
    client_order_id TEXT PRIMARY KEY,
    broker_order_id TEXT,
    ts INTEGER NOT NULL,
    submitted_ts INTEGER,
    instrument_id TEXT NOT NULL,
    side TEXT NOT NULL,
    status TEXT NOT NULL,
    submitted_qty REAL,
    filled_qty REAL,
    limit_price REAL,
    fill_price REAL,
    notional REAL
)"""
_EXECUTION_HEALTH_DDL = """CREATE TABLE IF NOT EXISTS execution_health (
    profile TEXT PRIMARY KEY,
    consecutive_fill_reconcile_failures INTEGER NOT NULL DEFAULT 0,
    last_success_ts INTEGER,
    last_failure_ts INTEGER,
    last_error TEXT
)"""
_FILL_RECONCILE_HALT_AFTER = 3


@dataclass(frozen=True, slots=True)
class FillReconcileResult:
    """One outcome-audit attempt and its persisted consecutive-failure state."""

    rows_written: int
    unfilled_pct: float
    succeeded: bool
    consecutive_failures: int
    error: str | None = None


def _audit_open(db: Path) -> sqlite3.Connection:
    """The per-profile trading DB with the order/reject/fill audit tables ensured."""
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute(_ORDERS_DDL)
    con.execute(_REJECTS_DDL)
    con.execute(_FILLS_DDL)
    con.execute(_EXECUTION_HEALTH_DDL)
    con.commit()
    return con


def _reconcile_fills(con: sqlite3.Connection, broker: Any, *, profile: str,
                     lookback_days: int = 45) -> FillReconcileResult:
    """Record prior order outcomes and persist reconciliation health.

    Added 2026-08-06. Until now the equity and managed-futures sleeves -- 60% of ALPHAC by
    weight -- wrote only SUBMISSIONS to disk. Nothing recorded whether an order actually
    filled, so the only realized execution record for two of three sleeves lived on the
    broker's servers and no local query could measure slippage or non-fills. A 20.9% non-fill
    rate, concentrated in names that moved against the book, went unseen for 37 live days.

    Runs at the START of a cycle so it captures the PREVIOUS cycle's outcomes, which is the
    only time they are knowable: orders are submitted pre-open and resolve at the open hours
    later. Terminal-but-unfilled orders are recorded too (that is the whole point), so
    ``filled_qty < submitted_qty`` is directly queryable.

    This function never places, cancels or modifies an order. A single failure remains
    non-fatal, but failures are persisted and counted. The caller halts before new submission
    after ``_FILL_RECONCILE_HALT_AFTER`` consecutive failures: repeatedly trading while the
    local record cannot establish prior outcomes is an operational-risk breach, not harmless
    observability lag.
    """
    try:
        row = con.execute("SELECT MAX(submitted_ts) FROM fills").fetchone()
        floor_ms = int(time.time() * 1000) - lookback_days * 86_400_000
        after_ms = max(int(row[0]), floor_ms) if row and row[0] else floor_ms
        orders = broker.closed_orders(after_ms=after_ms)
        written = 0
        sub_notional = 0.0
        miss_notional = 0.0
        for o in orders:
            coid = str(o.get("client_order_id") or "")
            if not coid.startswith(f"{profile}-"):
                continue  # each sleeve owns only its own orders on a shared account
            sub_qty = float(o.get("qty") or 0.0)
            fil_qty = float(o.get("filled_qty") or 0.0)
            fill_px = float(o.get("filled_avg_price") or 0.0) or None
            lim_px = float(o.get("limit_price") or 0.0) or None
            ref_px = fill_px or lim_px or 0.0
            sub_notional += sub_qty * ref_px
            miss_notional += max(sub_qty - fil_qty, 0.0) * ref_px
            con.execute(
                "INSERT OR REPLACE INTO fills (client_order_id, broker_order_id, ts, "
                "submitted_ts, instrument_id, side, status, submitted_qty, filled_qty, "
                "limit_price, fill_price, notional) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (coid, str(o.get("id") or ""), _rfc3339_ms(o.get("filled_at") or o.get("updated_at")),
                 _rfc3339_ms(o.get("submitted_at")), str(o.get("symbol") or ""),
                 str(o.get("side") or ""), str(o.get("status") or ""),
                 sub_qty, fil_qty, lim_px, fill_px, fil_qty * (fill_px or 0.0)),
            )
            written += 1
        con.commit()
        pct = 100.0 * miss_notional / sub_notional if sub_notional > 0 else 0.0
        now = int(time.time() * 1000)
        con.execute(
            "INSERT INTO execution_health (profile, consecutive_fill_reconcile_failures, "
            "last_success_ts, last_failure_ts, last_error) VALUES (?,0,?,NULL,NULL) "
            "ON CONFLICT(profile) DO UPDATE SET consecutive_fill_reconcile_failures=0, "
            "last_success_ts=excluded.last_success_ts, last_error=NULL",
            (profile, now),
        )
        con.commit()
        return FillReconcileResult(written, pct, True, 0)
    except Exception as e:
        message = str(e)[:500]
        now = int(time.time() * 1000)
        try:
            con.execute(
                "INSERT INTO execution_health (profile, consecutive_fill_reconcile_failures, "
                "last_success_ts, last_failure_ts, last_error) VALUES (?,1,NULL,?,?) "
                "ON CONFLICT(profile) DO UPDATE SET consecutive_fill_reconcile_failures="
                "execution_health.consecutive_fill_reconcile_failures+1, "
                "last_failure_ts=excluded.last_failure_ts, last_error=excluded.last_error",
                (profile, now, message),
            )
            con.commit()
            row = con.execute(
                "SELECT consecutive_fill_reconcile_failures FROM execution_health WHERE profile=?",
                (profile,),
            ).fetchone()
            failures = int(row[0]) if row else 1
        except sqlite3.Error:
            failures = _FILL_RECONCILE_HALT_AFTER
        print(f"  (fill reconciliation failed {failures} consecutive cycle(s): {message})")
        return FillReconcileResult(0, 0.0, False, failures, message)


def _fill_reconciliation_requires_halt(result: FillReconcileResult) -> bool:
    """True once outcome lineage has failed for the configured consecutive threshold."""
    return not result.succeeded and result.consecutive_failures >= _FILL_RECONCILE_HALT_AFTER


def _halt_on_fill_reconciliation_breach(
    result: FillReconcileResult,
    *,
    profile: str,
    kill: Any,
    con: sqlite3.Connection,
    broker: Any,
) -> bool:
    """Engage the persistent kill switch and close resources at the failure threshold."""
    if not _fill_reconciliation_requires_halt(result):
        return False
    reason = (f"live_cycle {profile}: fill-outcome reconciliation failed "
              f"{result.consecutive_failures} consecutive cycles")
    print(f"!!! EXECUTION LINEAGE BREACH: {reason}. Submitting NOTHING.")
    kill.engage(reason)
    con.close()
    broker.close()
    return True


def _rfc3339_ms(s: Any) -> int:
    """RFC3339 timestamp -> epoch ms; 0 when absent or unparseable (never raises)."""
    if not s:
        return 0
    try:
        return int(datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return 0


def _audit_order(con: sqlite3.Connection, *, order: Any, ts: int, accepted: bool,
                 broker_order_id: str | None, intent: str) -> None:
    try:
        con.execute(
            "INSERT OR REPLACE INTO orders (client_order_id, ts, instrument_id, side, qty, price, "
            "order_type, intent, accepted, broker_order_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (order.client_order_id, int(ts), order.instrument_id, str(order.side.value),
             float(order.qty), float(order.decision_price), str(order.order_type.value),
             intent, 1 if accepted else 0, broker_order_id),
        )
        con.commit()
    except sqlite3.Error as e:  # an audit failure must never break execution
        print(f"  (audit write failed: {e})")


def _audit_reject(con: sqlite3.Connection, *, ts: int, instrument_id: str, code: str,
                  message: str, client_order_id: str | None = None) -> None:
    try:
        con.execute(
            "INSERT INTO order_rejects (ts, client_order_id, instrument_id, code, message) "
            "VALUES (?,?,?,?,?)",
            (int(ts), client_order_id, instrument_id, code, message[:500]),
        )
        con.commit()
    except sqlite3.Error as e:
        print(f"  (audit write failed: {e})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="live_cycle")
    ap.add_argument("--profile", default="managed_futures")
    ap.add_argument("--dry-run", action="store_true", help="compute + print the orders, submit nothing")
    ap.add_argument("--ignore-calendar", action="store_true",
                    help="submit even when the US equity calendar says the market is closed "
                         "(the calendar gate exists because weekend orders never fill)")
    ap.add_argument("--no-cancel-stale", action="store_true",
                    help="keep this sleeve's still-open orders (default: cancel them first)")
    ap.add_argument("--i-understand-real-money", action="store_true",
                    help="DELIBERATELY arm a non-paper (real-money) Alpaca account. Without this flag a "
                         "live URL is refused, so flipping the env alone can never arm real trading.")
    ap.add_argument("--market-orders", action="store_true",
                    help="revert to raw MARKET orders (default: marketable LIMIT at mid +/- "
                         f"{_LIMIT_BUFFER:.2%}, which caps the worst-case fill)")
    a = ap.parse_args(argv)

    from alphaforge.config.settings import load_settings
    from alphaforge.core.time import now_ms
    from alphaforge.core.types import OrderRequest
    from alphaforge.execution.alpaca_broker import AlpacaBroker, _symbol
    from alphaforge.risk.killswitch import KillSwitch
    from alphaforge.risk.limits import RiskLimits

    settings = load_settings(a.profile)
    asset_class = settings.data.asset_class.value
    limits = RiskLimits.from_cfg(settings.risk)  # the SAME hard limits the crypto loop enforces
    db = load_settings().paths.var_dir / f"trading_{a.profile}.sqlite"  # shared var/, read by the public state
    kill = KillSwitch(load_settings().paths.var_dir / "KILL")
    if kill.engaged():
        print(f"KILL switch engaged ({kill.path}) — refusing to trade. A human must disengage to resume.")
        return 1
    target_w = _target_weights(a.profile)
    if not target_w:
        print(f"no target book for {a.profile} (run its walk-forward first)")
        return 1

    broker = AlpacaBroker(env_path=_account_env(a.profile))
    # Real money is a DELIBERATE arming: a non-paper account requires the explicit flag AND this gated
    # executor (the KILL + drawdown + book-cap checks below). Flipping the env to a live URL alone is
    # refused — so a one-line config change can never silently arm real trading through this path.
    if not broker.is_paper and not a.i_understand_real_money:
        print("REFUSING: a non-paper (real-money) Alpaca account requires --i-understand-real-money. Aborting.")
        return 1
    if not broker.is_paper:
        print("!!! LIVE REAL-MONEY MODE armed via --i-understand-real-money — gated by KILL + drawdown + book caps.")

    # TRADING-CALENDAR GATE (2026-08-06). Measured from the fill ledger: a single Saturday
    # 00:00 UTC cycle submitted 180 orders worth $216,388 and every one died unfilled, and
    # weekend-submitted orders were 36.1% of ALL missed notional across the live record at a
    # 100% miss rate. Orders placed into a closed market are not a strategy outcome, they are
    # a question nobody asked. This is ENGINEERING, not selection: it changes WHEN an unchanged
    # book is submitted, never what the book is.
    # Fails OPEN by design. is_trading_day() returns None when the calendar is unreachable, and
    # a data-source outage must not silently halt a live sleeve -- a missed session is a hole in
    # the forward record, which is the most valuable asset this project has.
    # Asked via getattr, never assumed. A broker that cannot answer this question is not
    # broken: the crypto sleeve trades 24/7 and has no US equity calendar, so gating it on one
    # would halt a sleeve that should be running. Only a broker that HAS a calendar and says
    # "closed" stops a cycle.
    _calendar = getattr(broker, "is_trading_day", None)
    if not a.dry_run and not a.ignore_calendar and callable(_calendar):
        trading = _calendar()
        if trading is False:
            print(f"SKIP: {dt_date_str()} is not a US equity session. "
                  "Nothing submitted (orders into a closed market never fill).")
            return 0
        if trading is None:
            print("WARN: could not reach the trading calendar; proceeding (fail-open).")
    # Cancel THIS sleeve's still-open (unfilled) orders before re-pricing. Without this a cycle that
    # runs again before a fill (e.g. repeatedly over a weekend) would STACK a second full book on top
    # of the first. Each run thus converges to the current target rather than accumulating. Filtered
    # by client_order_id prefix so AlphaMax's orders are never touched.
    if not a.dry_run and not a.no_cancel_stale:
        stale = [o for o in broker.open_orders() if o.client_order_id.startswith(f"{a.profile}-")]
        for o in stale:
            broker.cancel(o.client_order_id)
        if stale:
            print(f"canceled {len(stale)} stale open orders for {a.profile}")

    acct = broker.account()
    equity = acct.equity_quote
    if not (math.isfinite(equity) and equity > 0.0):
        print(f"REFUSING: account equity {equity!r} is not finite/positive — accounting error upstream. Aborting.")
        broker.close()
        return 1
    current = {p.instrument_id: p.qty for p in acct.positions}
    # drawdown guard: if the realized curve is >= dd_flat below its high-water mark, this cycle may only
    # DE-RISK (trim/close toward zero) — never open or add exposure. The same threshold the loop uses.
    derisk_only = False
    prior_eq = _recorded_equity(db)
    if prior_eq:
        hwm = max(max(prior_eq), equity)
        dd = 1.0 - equity / hwm if hwm > 0 else 0.0
        if dd >= limits.dd_flat_frac:
            derisk_only = True
    print(f"=== live cycle: {a.profile} ({asset_class}) {'[DRY RUN]' if a.dry_run else '[LIVE]'} ===")
    print(f"account equity ${equity:,.0f} | {len(target_w)} target names | {len(current)} current positions"
          + ("  | !! DRAWDOWN >= flat threshold: DE-RISK ONLY !!" if derisk_only else ""))

    # price each name off the latest quote mid (market may be closed -> last quote)
    universe = sorted(set(target_w) | set(current))
    orders: list[OrderRequest] = []
    # Names whose target was shrunk by the concentration cap, reported in aggregate after the loop:
    # one clamped name is a detail, but a book where the cap binds on most names is a sleeve trading
    # a fraction of its intended size while still publishing its full backtest.
    _capped_names: list[tuple[str, float, float]] = []
    cycle_ms = now_ms()  # one timestamp for the whole cycle -> unique client_order_ids (see below)
    book_gross = 0.0     # the SIZED TARGET book's gross/net (runaway brake, checked after the loop)
    book_net = 0.0
    meta = _AssetMeta(broker)   # broker-side shortable/fractionable flags (one bulk call, lazily)
    disclosed: list[tuple[str, str, str]] = []  # (instrument_id, code, message) pre-checked skips
    for iid in universe:
        tw = target_w.get(iid, 0.0)
        try:
            ob = broker.order_book(iid)
        except Exception as e:
            print(f"  {_symbol(iid):6} skip (no quote: {str(e)[:40]})")
            continue
        ref = None  # an independent reference price to sanity-check the sizing mid against
        if ob.bids and ob.asks:
            mid = (ob.bids[0][0] + ob.asks[0][0]) / 2.0
            try:
                ref = broker.last_trade(iid)
            except Exception:
                ref = None
        else:
            # no two-sided quote (common when the market is closed) -> fall back to the last trade
            try:
                mid = broker.last_trade(iid)
            except Exception:
                mid = 0.0
        if mid <= 0.0:
            print(f"  {_symbol(iid):6} skip (no price)")
            continue
        # price collar: a quote mid far from the last trade is a crossed/garbage book — using it as the
        # sizing denominator would mis-size the order. Reject the name rather than trade on a bad price.
        if ref and ref > 0.0 and abs(mid - ref) / ref > limits.price_collar_frac:
            print(f"  {_symbol(iid):6} skip (quote ${mid:.2f} off last-trade ${ref:.2f} > {limits.price_collar_frac:.0%} collar)")
            continue
        cap = _max_participation(a.profile)
        tw_capped = max(-cap, min(cap, tw))
        if abs(tw_capped) < abs(tw) - 1e-12:
            # DISCLOSE, never clamp in silence. A quietly-shrunk book reports its full backtest.
            _capped_names.append((_symbol(iid), tw, tw_capped))
            print(f"  {_symbol(iid):6} CONCENTRATION CAP: target {tw:+.4f} -> {tw_capped:+.4f} "
                  f"(profile cap {cap:.0%} of equity)")
        raw = tw_capped * equity / mid
        # Alpaca forbids fractional SHORT positions, so any short target is truncated to a whole
        # share count; longs may stay fractional. (Truncate toward zero -> never oversizes a short.)
        tgt_shares = float(int(raw)) if raw < 0 else round(raw, 4)
        # TRADABILITY pre-check (broker flags): an unfillable order is never sent. A SHORT target on
        # a non-shortable name becomes 0 (an existing position still flattens — that IS fillable),
        # and a non-fractionable name trades whole shares only. Both are DISCLOSED, and neither can
        # stop the rest of the book. If the flags are unavailable, the submit-time reject-catch below
        # gives the same outcome one cycle later.
        flags = meta.flags(_symbol(iid))
        whole_only = flags is not None and not flags[1]
        if tgt_shares < 0 and flags is not None and not flags[0]:
            print(f"  {_symbol(iid):6} DISCLOSED SKIP (not shortable at the broker): target "
                  f"{tgt_shares:+.0f} -> 0" + (f", flattening cur {current.get(iid, 0.0):+.2f}"
                                               if current.get(iid, 0.0) else ""))
            disclosed.append((iid, "precheck_not_shortable",
                              f'asset "{_symbol(iid)}" is not shortable; target {tgt_shares:+.0f} dropped to 0'))
            tgt_shares = 0.0
        elif whole_only and tgt_shares != float(int(tgt_shares)):
            tgt_shares = float(int(tgt_shares))
        book_gross += abs(tgt_shares * mid)   # accumulate the intended target book (every priced name)
        book_net += tgt_shares * mid
        cur_shares = current.get(iid, 0.0)
        # client_order_ids unique PER CYCLE (cycle_ms), not per UTC-day: combined with cancel-stale +
        # diffing against live positions, a corrective re-run after a partial fill issues a genuinely
        # new order instead of being silently deduped by Alpaca to the old (stale) order's ack. A
        # FLIP yields two legs (…-close / …-open), each with its own id and both swept by the
        # "<profile>-" prefixed cancel-stale. Dust deltas come back as no orders at all.
        flip_skips: list[str] = []  # flip legs the builder refused to send (would cross zero)
        name_orders = _delta_orders(
            profile=a.profile, cycle_ms=cycle_ms, instrument_id=iid, symbol=_symbol(iid),
            cur_shares=cur_shares, tgt_shares=tgt_shares, mid=mid,
            market_orders=a.market_orders, whole_only=whole_only, skips=flip_skips,
        )
        for msg in flip_skips:
            print(f"  {_symbol(iid):6} DISCLOSED SKIP (unclosable flip): {msg}")
            disclosed.append((iid, "precheck_unclosable_flip", msg))
        if not name_orders:
            continue
        # drawdown de-risk gate: in a deep drawdown only orders that shrink a position toward zero
        # (no flip, smaller magnitude) are allowed — never open or add exposure.
        if derisk_only and not (cur_shares != 0.0 and abs(tgt_shares) < abs(cur_shares)
                                and tgt_shares * cur_shares >= 0.0):
            print(f"  {_symbol(iid):6} skip (de-risk-only: not a reducing trade)")
            continue
        orders.extend(name_orders)
        for o in name_orders:
            intent = o.reason.removeprefix(f"{a.profile}-")
            tag = "" if intent == "rebalance" else f"  [{intent}]"
            print(f"  {_symbol(iid):6} w={tw_capped:+.3f} tgt={tgt_shares:+.2f} cur={cur_shares:+.2f} "
                  f"-> {o.side.name} {o.qty:.2f} @~${mid:.2f}  (${o.qty*mid:,.0f}){tag}")

    # CONCENTRATION-CAP DISCLOSURE. Reported in aggregate because the aggregate is what matters: if
    # the cap binds on most of the book, this sleeve is trading a fraction of its intended size
    # while its published backtest describes the full one. That gap must be visible in the log, not
    # inferred later from a puzzling live-vs-backtest divergence.
    if _capped_names:
        n_priced = len(universe)
        frac = len(_capped_names) / max(n_priced, 1)
        intended = sum(abs(t) for _, t, _ in _capped_names)
        allowed = sum(abs(c) for _, _, c in _capped_names)
        shrink = 1.0 - (allowed / intended) if intended > 0 else 0.0
        print(f"\n!! CONCENTRATION CAP BOUND on {len(_capped_names)}/{n_priced} names "
              f"({frac:.0%} of the book), shrinking their combined target by {shrink:.0%} "
              f"(cap {_max_participation(a.profile):.0%} of equity for profile {a.profile!r}).")
        if frac > 0.25:
            print("   THIS SLEEVE IS TRADING SUBSTANTIALLY BELOW ITS INTENDED SIZE. Its published "
                  "backtest describes the UNCAPPED book. Either raise the profile's cap in "
                  "_MAX_PARTICIPATION_BY_PROFILE to match the strategy's real concentration, or "
                  "re-derive its expected return at the capped size. Do not leave them mismatched.")

    # RUNAWAY brake: a sized target book grossly above any sleeve's legitimate profile means corrupted
    # weights or a bad equity read — submit NOTHING and engage the KILL switch for human review.
    gross_x, net_x = book_gross / equity, abs(book_net) / equity
    print(f"\ntarget book: gross {gross_x:.2f}x  net {book_net/equity:+.2f}x equity  ({len(orders)} delta orders"
          + (" — DRY RUN, nothing submitted)" if a.dry_run else ")"))
    if gross_x > _GROSS_HARD_CAP or net_x > _NET_HARD_CAP:
        print(f"!!! RISK BREACH: target gross {gross_x:.2f}x / net {net_x:.2f}x exceeds hard caps "
              f"({_GROSS_HARD_CAP}/{_NET_HARD_CAP}) — corrupted book. Submitting NOTHING.")
        if not a.dry_run:
            kill.engage(f"live_cycle {a.profile}: target gross {gross_x:.2f}x net {net_x:.2f}x > hard caps")
            print(f"    engaged KILL ({kill.path}) — a human must review + disengage before any sleeve trades.")
        broker.close()
        return 1
    if a.dry_run:
        broker.close()
        return 0
    if kill.engaged():  # re-check immediately before submission (it may have engaged mid-cycle)
        print("KILL engaged during cycle — submitting nothing.")
        broker.close()
        return 1

    # AUDIT TRAIL: the per-profile DB gains an `orders` + `order_rejects` record of THIS cycle, so a
    # future execution outage is diagnosable from the DB instead of by grepping logs.
    con = _audit_open(db)

    # FILL RECONCILIATION (2026-08-06): record what happened to the PREVIOUS cycle's orders
    # before submitting this one. Outcomes are only knowable now -- orders go in pre-open and
    # resolve at the open, hours after the cycle that placed them has exited. Read-only against
    # the broker; it never places or cancels anything.
    fill_reconcile = _reconcile_fills(con, broker, profile=a.profile)
    if fill_reconcile.rows_written:
        print(f"reconciled {fill_reconcile.rows_written} closed orders | unfilled notional "
              f"{fill_reconcile.unfilled_pct:.1f}%")
    if _halt_on_fill_reconciliation_breach(
        fill_reconcile, profile=a.profile, kill=kill, con=con, broker=broker
    ):
        return 1

    for iid, code, msg in disclosed:  # tradability skips decided before submission
        _audit_reject(con, ts=cycle_ms, instrument_id=iid, code=code, message=msg)

    # submit (idempotent on client_order_id) + count acks. NOTHING here may abort the cycle: a
    # per-name rejection (or even a transport error) is recorded and the remaining book proceeds.
    accepted = rejected = skipped = 0
    for submit_order in orders:
        intent = submit_order.reason.removeprefix(f"{a.profile}-")
        try:
            ack = broker.submit(submit_order)
        except Exception as e:  # one bad name must never kill the rest of the book
            rejected += 1
            print(f"  REJECTED {_symbol(submit_order.instrument_id)}: transport error: "
                  f"{str(e)[:120]}")
            _audit_order(con, order=submit_order, ts=cycle_ms, accepted=False,
                         broker_order_id=None, intent=intent)
            _audit_reject(con, ts=cycle_ms, instrument_id=submit_order.instrument_id,
                          code="exception", message=str(e),
                          client_order_id=submit_order.client_order_id)
            continue
        _audit_order(con, order=submit_order, ts=cycle_ms, accepted=ack.accepted,
                     broker_order_id=ack.broker_order_id, intent=intent)
        if ack.accepted:
            accepted += 1
            continue
        rejected += 1
        code, msg = _parse_reject(ack.reason or "")
        _audit_reject(con, ts=cycle_ms, instrument_id=submit_order.instrument_id, code=code,
                      message=msg, client_order_id=submit_order.client_order_id)
        kind = _skip_kind(msg)
        if kind is not None:
            skipped += 1
            print(f"  DISCLOSED SKIP {_symbol(submit_order.instrument_id)} ({kind}): {msg} — name dropped this "
                  f"cycle, rest of the book unaffected")
        else:
            print(f"  REJECTED {_symbol(submit_order.instrument_id)}: {ack.reason}")
    print(f"submitted {accepted}/{len(orders)} accepted"
          + (f" | {rejected} rejected ({skipped} untradable-name skips)" if rejected else "")
          + (f" | {len(disclosed)} pre-checked skips" if disclosed else ""))

    # record the realized account equity to the per-SLEEVE trading DB (read by paper_trading_state).
    # Keyed by profile, NOT asset_class: AlphaTrend(MF-ETFs) and AlphaMax(equities) are both the
    # "equity" asset class but are different sleeves and must never share a curve. It lives in the
    # SHARED default var/ (where the crypto loop's trading_crypto_perp.sqlite lives and where the
    # state reads it) — NOT this profile's isolated data dir (var_mf), which is for the lake only.
    # (db was resolved at cycle start for the drawdown guard; the audit connection is reused.)
    con.execute("CREATE TABLE IF NOT EXISTS equity_curve (ts INTEGER PRIMARY KEY, equity_quote REAL)")
    # Alpaca's authoritative MTM daily series (captures fills + marks; survives the pre-open run time)
    # plus the current live equity as the freshest mark.
    hist = broker.portfolio_history(period="all", timeframe="1D")
    hist.append((now_ms(), broker.account().equity_quote))
    # *** REPLACE THE CURVE, DO NOT MERGE INTO IT — the +893% phantom, fixed 2026-08-11. ***
    # `portfolio_history(period="all")` returns THIS account's COMPLETE history, so it is
    # authoritative on its own and merging it into whatever is already there is unsound. With
    # INSERT OR REPLACE, rows written while the profile pointed at a SUPERSEDED account survive at
    # any timestamp the new account's history does not happen to cover. That is what happened at
    # the v3 cutover: AlphaTrend's curve ended up holding $1,000,000 marks (v3) interleaved with
    # $100,681 marks (the old v2 $100k account), and the day-over-day step between them published
    # as a +893% return — which combined into an ALPHAC curve of 100,000 -> 400,207 in one day,
    # served publicly. A 300% gain that never happened.
    #
    # Deleting first makes the table exactly one account's history and SELF-HEALS any existing
    # contamination on the next run. Guarded on a non-trivial payload so a degraded broker
    # response can never wipe a good curve — if the venue returns nothing useful we keep what we
    # have and merge, which is the old behaviour and strictly better than an empty record.
    if len(hist) >= 2:
        con.execute("DELETE FROM equity_curve")
    con.executemany("INSERT OR REPLACE INTO equity_curve (ts, equity_quote) VALUES (?, ?)", hist)
    con.commit()
    con.close()
    print(f"recorded {len(hist)} equity marks (latest ${hist[-1][1]:,.0f}) -> {db.name}")
    broker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
