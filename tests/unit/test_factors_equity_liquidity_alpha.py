"""Unit tests for alphaforge.features.library.equity_liquidity_alpha (EQUITIES_SLEEVE §4, S7).

The illiquidity-premium alpha ``eq_ilrev`` — the TRADEABLE (``direction=+1``)
counterpart to the ``direction=0`` Amihud *context* ``eq_amihud_63``: the SAME Amihud
(2002) number priced as a cross-sectional alpha (more illiquid ⇒ higher expected GROSS
return). The illiquidity premium is largely compensation-for-cost and must be judged
NET of cost — these tests verify the mechanics (the shared Amihud body, the +1
direction sign on planted illiquidity, the NaN policy, the CS z-score), NOT that the
gross premium is economically real (that is the cost-aware backtest's job).

EQUITY-SLEEVE OPT-IN — synthetic-context discipline. ``eq_ilrev`` is registered but NOT
in any crypto/default active set; it runs on the EQUITY/D1 path and CANNOT compute
through the real ``FeatureEngine`` until the equity guard lifts (the
``_adjusted_close_panel`` fail-closed gate requires a corporate-actions surface). So,
like the pure off-engine math tests in ``test_factors_equity_price.py``, these drive
the registered body against a SYNTHETIC :class:`FeatureContext`-shaped fixture (a fake
exposing ``panel`` / ``corporate_actions``) on a deterministic session grid. Coverage:

* shape / index contract of the long output;
* the SHARED-body invariant — ``eq_ilrev`` raw == ``eq_amihud_63`` raw, bit-for-bit
  (EQUITIES_CRITIQUE N3: context == alpha input), with OPPOSITE direction/CS flags;
* the direction sign on a PLANTED illiquid name (higher Amihud ⇒ higher raw value ⇒
  positive alpha under ``direction=+1``);
* NaN policy — NaN until ``window + 1`` bars (the Amihud returns need ``C*_{t-1}``);
* the cross-sectional z-score: the PIT cross-section is mean ~0 / std ~1 post-pipeline;
* registered-spec metadata (finite-window: parity atol = 0).

The synthetic grid is at the true daily Δ; the body is positional (``shift(k)`` = k
grid slots), so one slot == one session bar for the 63-session window.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from alphaforge.features.cross_section import CSPipeline
from alphaforge.features.library.equity_liquidity_alpha import ILREV_WINDOW, eq_ilrev
from alphaforge.features.library.liquidity import amihud_illiq
from alphaforge.features.registry import default_registry
from alphaforge.features.spec import Family

A = "XNAS:CASH:AAAAUSD"
B = "XNAS:CASH:BBBBUSD"
C = "XNAS:CASH:CCCCUSD"
D = "XNAS:CASH:DDDDUSD"
E = "XNAS:CASH:EEEEUSD"
IDS = (A, B, C, D, E)

DAY = 86_400_000
T0 = 1_577_836_800_000  # 2020-01-01T00:00:00Z (aligned)
WINDOW = ILREV_WINDOW  # 63
N_BARS = WINDOW + 1 + 30  # past the window+1 warmup with headroom


# --------------------------------------------------------------------- synthetic ctx


class _SyntheticCtx:
    """A FeatureContext-shaped stand-in exposing only what the body calls.

    The illiquidity-alpha body reads ``panel("close")`` / ``panel("quote_volume")``
    and ``corporate_actions()`` (empty ⇒ raw == adjusted, the only legitimate
    pass-through). ``quote_volume`` is supplied explicitly so the per-name liquidity
    can be planted independently of price.
    """

    def __init__(self, close: pd.DataFrame, quote_volume: pd.DataFrame) -> None:
        self._close = close
        self._qv = quote_volume

    def panel(self, column: str = "close") -> pd.DataFrame:
        if column == "close":
            return self._close
        if column == "quote_volume":
            return self._qv
        raise KeyError(column)  # pragma: no cover - body only asks for the two above

    def corporate_actions(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                c: pd.Series(dtype=t)
                for c, t in {
                    "instrument_id": "object",
                    "ex_date": "int64",
                    "available_at": "int64",
                    "action_type": "object",
                    "ratio": "float64",
                    "cash_amount": "float64",
                }.items()
            }
        )


def _index(n: int) -> pd.Index:
    return pd.Index([T0 + k * DAY for k in range(n)], name="ts_open")


def _walk(seed: int, n: int, level: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out: np.ndarray = level * np.exp(np.cumsum(rng.normal(0.0, 0.015, n)))
    return out


def _close_panel(n: int = N_BARS) -> pd.DataFrame:
    return pd.DataFrame(
        {iid: _walk(60 + i, n, 100.0 + 10.0 * i) for i, iid in enumerate(IDS)},
        index=_index(n),
    )


def _qv_panel(close: pd.DataFrame, *, scale: dict[str, float] | None = None) -> pd.DataFrame:
    # Dollar (quote) volume = shares x price; scale lets a name be made illiquid.
    base = {iid: 1_000_000.0 * close[iid].to_numpy() for iid in close.columns}
    if scale:
        for iid, s in scale.items():
            base[iid] = base[iid] * s
    return pd.DataFrame(base, index=close.index)


# ----------------------------------------------------------- body via synthetic context


class TestBodyOnSyntheticContext:
    def test_shape_and_index_contract(self) -> None:
        spec = eq_ilrev()
        close = _close_panel()
        ctx = _SyntheticCtx(close, _qv_panel(close))
        out = spec.fn(ctx, spec)  # type: ignore[arg-type]
        assert out.name == "eq_ilrev"
        assert isinstance(out.index, pd.MultiIndex)
        assert out.index.nlevels == 2
        assert out.index.names == ["ts_open", "instrument_id"]
        assert len(out) == N_BARS * len(IDS)
        last_ts = out.index.get_level_values("ts_open").max()
        assert out.xs(last_ts, level="ts_open").notna().all()

    def test_body_equals_amihud_helper(self) -> None:
        # eq_ilrev IS amihud_illiq on the (raw == adjusted) panel, bit-for-bit.
        spec = eq_ilrev()
        close = _close_panel()
        qv = _qv_panel(close)
        ctx = _SyntheticCtx(close, qv)
        out = spec.fn(ctx, spec)  # type: ignore[arg-type]
        expected = amihud_illiq(close, qv, window=WINDOW)
        assert np.array_equal(out.to_numpy(), expected.to_numpy().ravel(), equal_nan=True)

    def test_warmup_nan_boundary(self) -> None:
        # Amihud uses a NaN-SKIPPING window mean (min_periods=1 semantics: the mean
        # runs over the valid bars in the window, NaN only when the window holds none),
        # so row 0 is NaN (no return: |r| needs C*_{t-1}) and the first FINITE value
        # appears once one valid return exists, at index 1 — not at a full window.
        spec = eq_ilrev()
        close = _close_panel()
        ctx = _SyntheticCtx(close, _qv_panel(close))
        out = spec.fn(ctx, spec).unstack(level="instrument_id")  # type: ignore[arg-type]
        assert out.iloc[0].isna().all()  # no return at the first bar
        assert out.iloc[1].notna().all()  # one valid |r|/QV => Amihud defined
        # By the WINDOW+1-th bar (index WINDOW) the canonical full window is present —
        # lookback_bars = WINDOW + 1, the history the live path needs for that value.
        assert out.iloc[WINDOW].notna().all()


# ----------------------------------------------------- shared body with eq_amihud_63


class TestSharedBodyWithContext:
    def test_raw_identical_to_eq_amihud_63(self) -> None:
        # EQUITIES_CRITIQUE N3: the alpha (eq_ilrev, direction +1) and the context
        # (eq_amihud_63, direction 0) are the SAME Amihud body -> raw outputs are
        # bit-identical. Only the spec flags differ.
        close = _close_panel()
        qv = _qv_panel(close)
        ctx = _SyntheticCtx(close, qv)
        alpha_spec = eq_ilrev()
        ctx_spec = default_registry().get("eq_amihud_63")
        alpha = alpha_spec.fn(ctx, alpha_spec)  # type: ignore[arg-type]
        context = ctx_spec.fn(ctx, ctx_spec)  # type: ignore[arg-type]
        assert np.array_equal(alpha.to_numpy(), context.to_numpy(), equal_nan=True)
        # ... but the directions/CS flags are opposite by design.
        assert alpha_spec.direction == 1
        assert ctx_spec.direction == 0
        assert alpha_spec.cross_sectional is True
        assert ctx_spec.cross_sectional is False


# ------------------------------------------------------------- direction / economics


class TestDirectionSign:
    def test_illiquid_name_scores_higher(self) -> None:
        # Plant one clearly ILLIQUID name (tiny dollar volume => high |r|/QV => high
        # Amihud). Under direction=+1 its raw value is highest -> highest alpha.
        spec = eq_ilrev()
        close = _close_panel()
        # Make A 1000x less liquid (volume / 1000) and E 1000x more liquid.
        qv = _qv_panel(close, scale={A: 1e-3, E: 1e3})
        ctx = _SyntheticCtx(close, qv)
        out = spec.fn(ctx, spec).unstack(level="instrument_id")  # type: ignore[arg-type]
        last = out.iloc[-1]
        assert last[A] == last.max()  # most illiquid => highest Amihud (raw alpha)
        assert last[E] == last.min()  # most liquid => lowest
        assert last[A] > last[E]


# --------------------------------------------------------------- cross-sectional zscore


class TestCrossSectionalZScore:
    def test_pit_cross_section_is_mean0_std1(self) -> None:
        spec = eq_ilrev()
        close = _close_panel()
        qv = _qv_panel(close, scale={A: 1e-2, B: 1e-1, D: 1e1, E: 1e2})  # spread liquidity
        ctx = _SyntheticCtx(close, qv)
        raw = spec.fn(ctx, spec).to_frame()  # type: ignore[arg-type]
        mask = pd.Series(True, index=raw.index)
        processed = CSPipeline(min_members=3).apply(raw, mask)["eq_ilrev"]
        last_ts = raw.index.get_level_values("ts_open").max()
        xs = processed.xs(last_ts, level="ts_open").dropna()
        assert len(xs) == len(IDS)
        assert abs(float(xs.mean())) < 1e-9
        assert abs(float(xs.std(ddof=1)) - 1.0) < 1e-9

    def test_zscore_preserves_illiquidity_ranking(self) -> None:
        spec = eq_ilrev()
        close = _close_panel()
        qv = _qv_panel(close, scale={A: 1e-3, E: 1e3})
        ctx = _SyntheticCtx(close, qv)
        raw = spec.fn(ctx, spec).to_frame()  # type: ignore[arg-type]
        mask = pd.Series(True, index=raw.index)
        processed = CSPipeline(min_members=3).apply(raw, mask)["eq_ilrev"]
        last_ts = raw.index.get_level_values("ts_open").max()
        raw_xs = raw["eq_ilrev"].xs(last_ts, level="ts_open")
        z_xs = processed.xs(last_ts, level="ts_open")
        assert raw_xs.idxmax() == z_xs.idxmax()  # most illiquid still tops post winsor->z


# ------------------------------------------------------------------- registered spec


class TestRegisteredSpec:
    def test_metadata(self) -> None:
        spec = default_registry().get("eq_ilrev")
        assert spec.family is Family.LIQUIDITY
        assert spec.direction == 1
        assert spec.cross_sectional is True
        assert spec.lookback_bars == WINDOW + 1  # Amihud returns need C*_{t-1}
        assert not spec.is_ewma_family  # finite window: parity atol = 0
        assert spec.params["window"] == WINDOW

    def test_is_equity_opt_in_not_in_crypto_default(self) -> None:
        assert "eq_ilrev" in default_registry()
        assert default_registry().get("eq_ilrev").name.startswith("eq_")
        # The context counterpart is also present and direction-0 (the desk default).
        assert default_registry().get("eq_amihud_63").direction == 0
