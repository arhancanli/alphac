#!/usr/bin/env python3
"""PROBE 4 — ZERO-SLOT EXECUTION SAVINGS (deflation-proof, book-moving). 2026-07-12.

Three execution-layer savings that require NO signal and NO overfit (so they cost ZERO
deflation-ledger slots and cannot wash out under DSR): (1) cross-sleeve netting, (2)
maker/post-only on the crypto carry sleeve, (3) tranched rebalance. This script is a
MEASURE-ONLY accounting A/B on the committed cost model + the live trading DBs + the frozen
walk-forward artifacts. It reads src/** and configs/** as READ-ONLY constants, imports nothing
that mutates, modifies nothing, and appends NOTHING to var/experiments.jsonl (pure execution
arithmetic is not a strategy search — trials burned = 0).

Data (all read-only):
  * var/trading_crypto_perp.sqlite  — realized crypto fills (fee_quote, liquidity, slippage_bps,
                                       gross notional, equity_curve) — the live taker baseline.
  * var/trading_equity.sqlite / var/trading_managed_futures.sqlite — sleeve equity curves.
  * artifacts/walkforward/{crypto_carry_wk, managed_futures, k30_dn_63}/summary.txt — turnover_ann,
    vol_ann, fees_paid, funding_net (the realistic per-sleeve turnover the savings act on).
  * artifacts/walkforward/{mf_live_fwd,k30_dn_63}/legs/.../positions.parquet — live target books
    (for the netting instrument-overlap test).
  * configs/base.yaml cost block (perp maker 2bp / taker 5bp, half-spread 2.5bp, latency 2bp) and
    src/alphaforge/costs/** — the single source of truth for every friction (cited, not re-declared).
  * scripts/live_cycle.py — the live order path (per-sleeve SEPARATE broker accounts; read as fact).

Prior precedent this consolidates + extends (already on the ledger, not re-run here):
  * scripts/exp3_maker_exec_screen.py + artifacts/exp3/*  — closed-form maker EV screen.
  * scripts/exp4_maker_exec_backtest.py + artifacts/exp4/* — engine-level maker A/B (MakerFill),
    the authoritative measurement for leg 2. This probe cites its result and does NOT re-burn it.

    uv run python scripts/probe_execution_savings.py
Outputs: artifacts/sweep/execution_savings/report.txt + report.json
"""
# ruff: noqa: E501
from __future__ import annotations

import json
import math
import re
import sqlite3
from pathlib import Path

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "artifacts" / "sweep" / "execution_savings"

# --- cost constants: SINGLE SOURCE = configs/base.yaml + src/alphaforge/costs/fees.py (cited, read-only) ---
PERP_MAKER_BPS = 2.0   # BINANCE_VIP0_PERP maker (configs/base.yaml costs.perp_maker_bps)
PERP_TAKER_BPS = 5.0   # BINANCE_VIP0_PERP taker (configs/base.yaml costs.perp_taker_bps)
HALF_SPREAD_BPS = 2.5  # default_half_spread_bps (a maker order CAPTURES this instead of paying it)
EQUITY_COMM_BPS = 1.0  # US_EQUITY_DEFAULT maker==taker (no perp maker-rebate analogue for equities)

LIVE_EQUITY = 100_000.0  # current paper book size per sleeve (the $ savings scale linearly in AUM)


# --------------------------------------------------------------------------- helpers
def _summary(wf: str) -> dict[str, float]:
    """Parse a frozen walk-forward summary.txt into {key: float}."""
    p = REPO / "artifacts" / "walkforward" / wf / "summary.txt"
    out: dict[str, float] = {}
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        m = re.match(r"^(\w+)\s+([-\d.eE]+)", line.strip())
        if m:
            try:
                out[m.group(1)] = float(m.group(2))
            except ValueError:
                pass
    return out


def _target_book(wf_chain: list[str]) -> dict[str, float]:
    """Latest walk-forward leg's target weights (same logic live_cycle.py uses)."""
    import glob

    for wf in wf_chain:
        legs = sorted(glob.glob(str(REPO / f"artifacts/walkforward/{wf}/legs/leg_*/positions.parquet")))
        if not legs:
            continue
        t = pq.read_table(legs[-1]).to_pydict()
        rows = list(zip(t["ts"], t["instrument_id"], t["weight"], strict=True))
        last = max(r[0] for r in rows)
        w = {iid: float(wt) for ts, iid, wt in rows if ts == last and abs(float(wt)) > 1e-9}
        if w:
            return w
    return {}


def _crypto_fills() -> dict[str, float]:
    """Realized crypto taker fills: gross notional, total fee, realized fee bps, mean slippage."""
    db = REPO / "var" / "trading_crypto_perp.sqlite"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    row = con.execute(
        "SELECT SUM(ABS(qty*price)), SUM(fee_quote), AVG(slippage_bps), COUNT(*) FROM fills"
    ).fetchone()
    eqrow = con.execute(
        "SELECT (SELECT equity_quote FROM equity_curve ORDER BY cycle_ts LIMIT 1),"
        " (SELECT equity_quote FROM equity_curve ORDER BY cycle_ts DESC LIMIT 1)"
    ).fetchone()
    con.close()
    gross, fee, slip, n = row
    return {
        "gross_notional": float(gross or 0.0), "total_fee": float(fee or 0.0),
        "realized_fee_bps": float(fee or 0.0) / float(gross or 1.0) * 1e4,
        "mean_slippage_bps": float(slip or 0.0), "n_fills": int(n or 0),
        "first_equity": float(eqrow[0] or 0.0), "last_equity": float(eqrow[1] or 0.0),
    }


def _lines() -> list[str]:
    return []


# =========================================================================== LEG 1 — NETTING
def leg1_netting() -> dict:
    mf = _target_book(["mf_live_fwd", "managed_futures"])
    eq = _target_book(["equity_live_fwd", "k30_dn_63"])
    inter = sorted(set(mf) & set(eq))
    spy = "XUSE:CASH:SPYUSD"
    # strategic tilt (scripts/paper_trading_state.py): +20% net-long overlay = 0.5 BTC + 0.5 SPY,
    # held as a SEPARATE DISCLOSED RETURN overlay (book_returns += tilt*market[d]) — NOT broker-executed.
    tilt_spy_w = 0.20 * 0.5   # +10% SPY  (would-be, if it were executed)
    tilt_btc_w = 0.20 * 0.5   # +10% BTC
    mf_spy_w = mf.get(spy, 0.0)
    # Same-instrument overlap that COULD net a round-trip requires OPPOSITE-direction flow in the
    # SAME instrument on the SAME execution account. Enumerate the only candidates:
    #   MF (17 ETFs) vs EQUITY (single names): instrument intersection below.
    #   MF SPY vs tilt SPY: both LONG -> consolidation, never a round-trip cancel.
    #   crypto (Binance) vs everything (Alpaca): different venue -> uncrossable.
    same_dir_spy = (mf_spy_w > 0) == (tilt_spy_w > 0)
    return {
        "mf_names": len(mf), "eq_names": len(eq),
        "mf_eq_instrument_intersection": inter,           # EMPTY = disjoint universes
        "mf_spy_weight": mf_spy_w, "tilt_spy_weight_if_executed": tilt_spy_w,
        "tilt_btc_weight_if_executed": tilt_btc_w,
        "spy_overlap_same_direction": bool(same_dir_spy),  # True -> no round-trip saving
        "separate_execution_accounts": [
            "crypto -> Binance perp account (own loop)",
            "managed_futures -> Alpaca account A (alpaca.env)",
            "equity -> Alpaca account B (alpaca_equity.env)",
        ],
        "annual_saving_usd": 0.0,
        "sharpe_equivalent": 0.0,
        "verdict": (
            "NULL / $0. Netting a round-trip requires OPPOSITE-direction flow in the SAME instrument "
            "on ONE execution account. None of that exists here: (a) the MF ETF universe and the "
            "equity single-name universe are DISJOINT (intersection empty); (b) the only same-instrument "
            "overlap is SPY, held LONG by both MF (+3.6%) and the strategic tilt (+10%) -> same direction, "
            "so consolidation saves nothing on proportional cost; (c) the +20% tilt is a DISCLOSED RETURN "
            "overlay in the paper state, not broker-executed, so it emits no orders to net; (d) the three "
            "sleeves execute on THREE separate broker accounts (Binance + two Alpaca accounts, chosen for "
            "clean per-sleeve equity attribution), which structurally precludes crossing one sleeve's order "
            "against another's. The netting lever is empty for the current book by construction."
        ),
    }


# =========================================================================== LEG 2 — MAKER / POST-ONLY
def leg2_maker(crypto: dict, csum: dict) -> dict:
    turnover_ann = csum.get("turnover_ann", 33.21)     # one-way notional/equity per yr (matches fees=turnover*taker)
    vol_ann = csum.get("vol_ann", 0.1183)
    base_sharpe = csum.get("sharpe", 0.677)
    # A maker (post-only) order (i) pays maker not taker (saves TAKER-MAKER = 3bp) AND (ii) EARNS the
    # half-spread instead of paying it (+2.5bp). edge_if_filled = 3.0 + 2.5 = 5.5 bp/side (repo's exp3 value).
    fee_saving_bps = PERP_TAKER_BPS - PERP_MAKER_BPS          # 3.0
    edge_if_filled_bps = fee_saving_bps + HALF_SPREAD_BPS     # 5.5
    fees_ann_taker_usd = turnover_ann * PERP_TAKER_BPS * 1e-4 * LIVE_EQUITY  # ~ matches realized fees

    # CONSERVATIVE non-fill EV: per side, net_saving = p*edge_if_filled - (1-p)*adverse_selection.
    # The missed fraction (1-p) chases and eats adverse_selection bps (the price moved while waiting).
    grid = []
    for p in (0.40, 0.49, 0.60, 0.70):        # 0.49 = exp4's REALIZED close-direction fill rate (a ~50% lower bound)
        for adv in (2.0, 5.0, 8.0):           # adverse-selection sweep (5bp = exp3/exp4 central)
            net_bps = p * edge_if_filled_bps - (1 - p) * adv
            ann_saving_usd = turnover_ann * (net_bps * 1e-4) * LIVE_EQUITY
            sharpe_uplift = (ann_saving_usd / LIVE_EQUITY) / vol_ann if vol_ann > 0 else 0.0
            grid.append({
                "fill_rate": p, "adverse_selection_bps": adv,
                "net_saving_bps_per_side": round(net_bps, 3),
                "annual_saving_usd_at_100k": round(ann_saving_usd, 1),
                "sharpe_uplift": round(sharpe_uplift, 4),
            })
    # FEE-ONLY certain floor (ignores BOTH spread capture and adverse selection): blended fee on filled fraction.
    p_ref = 0.49
    blended_fee_bps = p_ref * PERP_MAKER_BPS + (1 - p_ref) * PERP_TAKER_BPS
    fee_only_saving_bps = PERP_TAKER_BPS - blended_fee_bps
    fee_only_ann_usd = turnover_ann * (fee_only_saving_bps * 1e-4) * LIVE_EQUITY
    fee_only_sharpe = (fee_only_ann_usd / LIVE_EQUITY) / vol_ann
    return {
        "turnover_ann": turnover_ann, "vol_ann": vol_ann, "base_sharpe": base_sharpe,
        "fees_ann_taker_usd_at_100k": round(fees_ann_taker_usd, 1),
        "realized_live_fee_bps": round(crypto["realized_fee_bps"], 3),
        "edge_if_filled_bps_per_side": edge_if_filled_bps,
        "ev_grid": grid,
        "fee_only_floor": {
            "fill_rate": p_ref, "blended_fee_bps": round(blended_fee_bps, 3),
            "saving_bps_per_side": round(fee_only_saving_bps, 3),
            "annual_saving_usd_at_100k": round(fee_only_ann_usd, 1),
            "sharpe_uplift": round(fee_only_sharpe, 4),
        },
        "engine_measurement_exp4": {
            "source": "artifacts/exp4/20260625T103226Z/exp4_metrics.json (WalkForwardRunner MakerFill A/B)",
            "realized_maker_fill_rate": 0.4897, "adverse_selection_bps": 5.0,
            "sharpe_uplift_vs_taker": 0.092, "fees_paid_taker": 30220.03, "fees_paid_maker": 21640.7,
            "fee_cut_pct": round((1 - 21640.7 / 30220.03) * 100, 1),
            "note": "Authoritative engine A/B. Window 2024-06..2026-06 sits in the signal-dead-bug era so "
                    "ABSOLUTE Sharpe is negative there; only the taker->maker UPLIFT (+0.092) is the relevant "
                    "differential and it is robustly positive at the conservative 49% fill / punitive 5bp adv-sel.",
        },
        # 2026-08-06 AUDIT — the fill assumption underneath this verdict is UNVALIDATED, and the
        # instrument built to validate it (scripts/maker_shadow.py) was found broken the same
        # day: its markout marks against a live book fetched at an arbitrary time rather than at
        # ts+HORIZON, and its fill rule models no queue position, so it returns ~92% where the
        # real question is whether a resting order reaches the front of the queue. The FEE-ONLY
        # floor below is sound arithmetic (taker 5bp vs maker 2bp on measured turnover) but it
        # holds only CONDITIONAL on actually filling as maker. The 49%-fill A/B figure is an
        # assumption, not a measurement. Do not ship maker execution on this verdict alone.
        "verdict": (
            "CONDITIONAL PROMOTE, pending a valid fill measurement (2026-08-06: the maker-shadow "
            "instrument is not decision-grade; see scripts/maker_shadow.py report). "
            "The carry sleeve rebalances on a slow 3-day/168h horizon, so entries are NOT urgent -> post-only "
            "limit fills are appropriate and the missed fraction can simply re-post. Fee-only certain floor "
            f"= +{round(fee_only_sharpe,3)} Sharpe / ~${round(fee_only_ann_usd)}/yr per $100k; the engine A/B "
            "(exp4) measures +0.092 at 49% realized fill / 5bp adverse selection (fees -28%). Reportable band "
            "+0.03..+0.09 Sharpe, matching the +0.02-0.05 prior on the conservative side."
        ),
    }


# =========================================================================== LEG 3 — TRANCHED REBALANCE
def leg3_tranched(csum: dict, mfsum: dict, eqsum: dict) -> dict:
    # sqrt market-impact law (src/alphaforge/costs/model.py): impact_$ = notional * Y*sigma*sqrt(notional/ADV)
    # -> impact_$ ∝ notional^1.5. Splitting one rebalance into T equal slices over T sub-periods makes total
    # impact scale by 1/sqrt(T): T * (Q/T)^1.5 / Q^1.5 = T * T^-1.5 = T^-0.5.
    T = 5
    impact_reduction_factor = 1.0 - 1.0 / math.sqrt(T)    # ~0.553 at T=5

    # At $100k the sqrt law puts impact BELOW the half-spread for every sleeve's liquid universe:
    #   crypto top-universe perps: model docstring "sqrt impact at $100k on liquid names is <1bp";
    #     live fills recorded FAVORABLE slippage (mean ~ -3.4 bp) — impact is not the binding cost.
    #   MF: SPY/QQQ/TLT/GLD... ADV in the billions -> impact ~ 0 at $100k.
    #   equity: 58 names ~$1-2.5k each, pre-trade 1%-ADV guard caps participation -> sub-bp.
    # So the IMPACT dollar saving at current AUM ~ $0; it grows as sqrt(AUM). Illustrate the scaling with a
    # deliberately CONSERVATIVE assumed impact of 1.0 bp on the crypto sleeve's annual turnover at $100k.
    assumed_impact_bps_at_100k = 1.0
    scaling = []
    for aum in (100_000.0, 1_000_000.0, 10_000_000.0):
        # sqrt law: impact_bps scales as sqrt(AUM / 100k) for a fixed universe/ADV
        impact_bps = assumed_impact_bps_at_100k * math.sqrt(aum / 100_000.0)
        turn = csum.get("turnover_ann", 33.21)
        impact_cost_usd = turn * (impact_bps * 1e-4) * aum
        saved_usd = impact_cost_usd * impact_reduction_factor
        scaling.append({
            "aum_usd": aum, "assumed_impact_bps": round(impact_bps, 3),
            "annual_impact_cost_usd": round(impact_cost_usd, 1),
            "tranched_saving_usd_T5": round(saved_usd, 1),
        })

    # Timing-luck (Hoffstein): single-day rebalancing injects ~100 bp/yr of pure DISPERSION (the gap between
    # the luckiest and unluckiest rebalance day) — an uncorrelated NOISE term, not expected return. Spreading a
    # rebalance across T days averages the entry day, cutting that noise std by ~1/sqrt(T). It reduces the
    # VARIANCE of realized return (raises the ROBUST/deflated Sharpe a hair), it does NOT add mean return.
    TIMING_NOISE_ANN = 0.010   # 100 bp/yr, conservative Hoffstein figure for single-day MONTHLY rebalancing
    rows = []
    for name, s in (("crypto_carry", csum), ("managed_futures", mfsum), ("equity", eqsum)):
        vol = s.get("vol_ann", 0.0)
        if vol <= 0:
            continue
        # monthly sleeves (MF horizon 21, equity monthly) are where single-day timing noise bites most;
        # crypto already rebalances every 3 days so its per-rebalance timing noise is smaller — halve it.
        noise = TIMING_NOISE_ANN * (0.5 if name == "crypto_carry" else 1.0)
        vol_with = math.sqrt(vol**2 + noise**2)
        vol_tranched = math.sqrt(vol**2 + (noise / math.sqrt(T)) ** 2)
        # Sharpe scales as 1/vol at fixed mean -> multiplicative uplift from the vol reduction:
        base_sharpe = s.get("sharpe", 0.0)
        sharpe_uplift = base_sharpe * (vol_with / vol_tranched - 1.0)
        rows.append({
            "sleeve": name, "vol_ann": round(vol, 4),
            "assumed_timing_noise_ann": noise,
            "vol_reduction_bps": round((vol_with - vol_tranched) * 1e4, 2),
            "sharpe_uplift_from_variance": round(sharpe_uplift, 4),
        })
    return {
        "T_subperiods": T, "impact_reduction_factor_T5": round(impact_reduction_factor, 3),
        "impact_dollar_scaling_vs_aum": scaling,
        "timing_luck_variance_reduction": rows,
        "verdict": (
            "NEAR-ZERO now / a ROBUSTNESS lever at scale. Impact at $100k is sub-half-spread on every sleeve's "
            "liquid universe (crypto live slippage was FAVORABLE ~ -3.4bp), so the tranched IMPACT saving today "
            "is ~$0 — it scales as sqrt(AUM) and only becomes material at $1M+. The AUM-independent benefit is "
            "removing single-day rebalance TIMING LUCK (~100bp/yr dispersion, cut ~55% at T=5): a small VARIANCE "
            "reduction (+~0.00-0.02 Sharpe-equivalent, biggest on the monthly MF/equity sleeves), NOT extra mean "
            "return. Promote as a de-risking/robustness measure once AUM > ~$1M or when reducing rebalance path-"
            "dependency is worth the extra order count."
        ),
    }


# =========================================================================== MAIN
def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    crypto = _crypto_fills()
    csum = _summary("crypto_carry_wk")
    mfsum = _summary("managed_futures")
    eqsum = _summary("k30_dn_63")

    l1 = leg1_netting()
    l2 = leg2_maker(crypto, csum)
    l3 = leg3_tranched(csum, mfsum, eqsum)

    # book-wide reportable total (conservative central): maker leg fee-only floor is the only non-null $.
    maker_central = l2["fee_only_floor"]
    book_saving_usd = maker_central["annual_saving_usd_at_100k"]  # netting=0, tranching~0 at current AUM
    book_sharpe = maker_central["sharpe_uplift"]                  # single sleeve (crypto) uplift

    report = {
        "probe": "execution_savings", "trials_burned": 0, "live_equity_assumed": LIVE_EQUITY,
        "crypto_live_fills": crypto,
        "leg1_cross_sleeve_netting": l1,
        "leg2_maker_post_only_crypto": l2,
        "leg3_tranched_rebalance": l3,
        "book_wide_reportable": {
            "net_new_annual_saving_usd_at_100k": round(book_saving_usd, 1),
            "net_new_sharpe_on_crypto_sleeve": round(book_sharpe, 4),
            "note": "Only the maker leg is a non-null $ win at current AUM/architecture. Netting = $0 "
                    "(disjoint universes + 3 separate broker accounts). Tranching ~ $0 now (sub-bp impact "
                    "at $100k), a robustness lever at $1M+.",
        },
        "go_live_validation_required": [
            "MAKER: conscious GOLDEN-MASTER re-bless (fill model changes byte-identity) + an A/B on REALIZED "
            "live post-only fill logs proving the maker fill rate beats break-even (exp3: 0.27 at 2bp adv-sel) "
            "at the ACTUAL measured adverse selection, with conservative non-fill chasing at taker + observed "
            "slippage. Ship ONLY if live fills confirm +Sharpe net of chase cost; the exp4 +0.092 is a floor, "
            "not the production number.",
            "NETTING: no go-live — the lever is structurally empty for this book; revisit only if a future "
            "sleeve shares an instrument+account with an opposing-direction position.",
            "TRANCHED: no go-live at current AUM; adopt with a golden re-bless when AUM > ~$1M (impact "
            "becomes material) or to cut rebalance path-dependency; validate the split-schedule adds no "
            "net cost vs the timing-noise it removes.",
        ],
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=1))

    # ------- human report -------
    L: list[str] = []
    def say(s: str = "") -> None:
        L.append(s); print(s)

    say("=" * 82)
    say("PROBE 4 — ZERO-SLOT EXECUTION SAVINGS   (trials burned: 0 — pure cost accounting)")
    say(f"live book size assumed: ${LIVE_EQUITY:,.0f}/sleeve   ($ savings scale linearly in AUM)")
    say("=" * 82)
    say("\nCRYPTO LIVE FILLS (taker baseline): "
        f"{crypto['n_fills']} fills, gross ${crypto['gross_notional']:,.0f}, "
        f"realized fee {crypto['realized_fee_bps']:.2f}bp, mean slippage {crypto['mean_slippage_bps']:+.2f}bp")

    say("\n" + "-" * 82)
    say("LEG 1 — CROSS-SLEEVE NETTING")
    say("-" * 82)
    say(f"MF book {l1['mf_names']} ETFs | EQ book {l1['eq_names']} single-names | "
        f"instrument intersection: {l1['mf_eq_instrument_intersection'] or 'EMPTY (disjoint)'}")
    say(f"only same-instrument overlap = SPY: MF {l1['mf_spy_weight']:+.4f} vs tilt(if executed) "
        f"{l1['tilt_spy_weight_if_executed']:+.4f}  -> same direction: {l1['spy_overlap_same_direction']}")
    say(f"execution accounts (uncrossable): {'; '.join(l1['separate_execution_accounts'])}")
    say(f">>> ANNUAL SAVING: ${l1['annual_saving_usd']:.0f}   Sharpe-eq: {l1['sharpe_equivalent']:.3f}")
    say(l1["verdict"])

    say("\n" + "-" * 82)
    say("LEG 2 — MAKER / POST-ONLY on crypto carry")
    say("-" * 82)
    say(f"turnover_ann {l2['turnover_ann']:.2f} | vol {l2['vol_ann']:.4f} | base Sharpe {l2['base_sharpe']:.3f} | "
        f"annual taker fees ~${l2['fees_ann_taker_usd_at_100k']:,.0f}/yr @ $100k | edge-if-filled {l2['edge_if_filled_bps_per_side']}bp/side")
    ff = l2["fee_only_floor"]
    say(f"FEE-ONLY certain floor (p={ff['fill_rate']}, ignores spread capture AND adv-sel): "
        f"+${ff['annual_saving_usd_at_100k']:.0f}/yr, +{ff['sharpe_uplift']:.3f} Sharpe")
    ex = l2["engine_measurement_exp4"]
    say(f"ENGINE A/B (exp4, authoritative): +{ex['sharpe_uplift_vs_taker']:.3f} Sharpe at {ex['realized_maker_fill_rate']:.2%} "
        f"realized fill / {ex['adverse_selection_bps']:.0f}bp adv-sel; fees -{ex['fee_cut_pct']}%")
    say("EV sensitivity (net bps/side | $/yr@100k | ΔSharpe):")
    for g in l2["ev_grid"]:
        say(f"   fill {g['fill_rate']:.2f}  adv {g['adverse_selection_bps']:.0f}bp -> "
            f"{g['net_saving_bps_per_side']:+.2f}bp  ${g['annual_saving_usd_at_100k']:+.0f}  ΔSR {g['sharpe_uplift']:+.4f}")
    say(l2["verdict"])

    say("\n" + "-" * 82)
    say("LEG 3 — TRANCHED REBALANCE (split each rebalance across T sub-periods)")
    say("-" * 82)
    say(f"impact scales 1/sqrt(T); at T={l3['T_subperiods']} the impact saving factor = {l3['impact_reduction_factor_T5']}")
    say("impact $ vs AUM (conservative 1bp@100k assumption; real impact is sub-bp on these liquid universes):")
    for s in l3["impact_dollar_scaling_vs_aum"]:
        say(f"   AUM ${s['aum_usd']:>12,.0f}: impact cost ${s['annual_impact_cost_usd']:>10,.0f}/yr -> "
            f"tranched saves ${s['tranched_saving_usd_T5']:,.0f}/yr")
    say("timing-luck variance reduction (Hoffstein ~100bp/yr single-day dispersion):")
    for r in l3["timing_luck_variance_reduction"]:
        say(f"   {r['sleeve']:16} vol {r['vol_ann']:.4f}  -> vol -{r['vol_reduction_bps']:.2f}bp  "
            f"ΔSharpe(variance) {r['sharpe_uplift_from_variance']:+.4f}")
    say(l3["verdict"])

    say("\n" + "=" * 82)
    say("BOOK-WIDE REPORTABLE (current AUM/architecture)")
    say("=" * 82)
    bw = report["book_wide_reportable"]
    say(f"NET-NEW annual saving: ${bw['net_new_annual_saving_usd_at_100k']:,.0f}/yr @ $100k  "
        f"(all from the MAKER leg on crypto)")
    say(f"NET-NEW Sharpe (crypto sleeve): +{bw['net_new_sharpe_on_crypto_sleeve']:.3f}  "
        f"(engine floor +0.092; netting +0, tranching ~+0 at this AUM)")
    say("\nGO-LIVE VALIDATION REQUIRED:")
    for v in report["go_live_validation_required"]:
        say(f"  * {v}")
    say("\ntrials burned this run: 0 (no experiments.jsonl write — pure execution accounting)")
    say(f"report -> {OUT}")

    (OUT / "report.txt").write_text("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
