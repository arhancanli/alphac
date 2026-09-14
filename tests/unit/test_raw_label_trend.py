from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from test_causal_trend import fixture_panel

from alphaforge.signals.raw_label_trend import RawLabelTrendSignalService
from alphaforge.validation.trend_observation import ObservationError, session_window
from alphaforge.validation.trend_price_bridge import Action, ActionSnapshot
from alphaforge.validation.trend_raw_label_provider import RawHoldingLabelProvider


def setup(mode="PROSPECTIVE", late=False):
    old, sessions, frame, mask, zs = fixture_panel()
    service = object.__new__(RawLabelTrendSignalService)
    service.__dict__.update(old.__dict__)
    symbols = list("ABCDEF")
    paired = pd.DataFrame(
        [
            {
                "symbol": s,
                "session_ms": int(t),
                "raw_volume": 1000.0,
                "price_disputed": False,
                **{
                    f"{p}_{f}": v
                    for p, v in [("raw", 100.0), ("signal", 1000.0)]
                    for f in ["open", "high", "low", "close"]
                },
            }
            for t in sessions
            for s in symbols
        ]
    )
    release = session_window(int(sessions[3]))[0]
    snaps = {
        s: ActionSnapshot(
            s,
            int(sessions[0]),
            int(sessions[-1]) + 86400000,
            release + 1 if late else int(sessions[0]),
            "a" * 64,
            True,
            (Action("div-" + s, s, int(sessions[3]), "dividend", float(i + 1)),),
        )
        for i, s in enumerate(symbols)
    }
    provider = RawHoldingLabelProvider(
        paired, instrument_symbols={s: s for s in symbols}, snapshots=snaps, mode=mode
    )
    service._raw_label_provider = provider
    return service, sessions, frame, mask, zs, paired, snaps


def test_raw_dividend_labels_release_only_at_exit_close():
    service, sessions, frame, _, _, _, _ = setup()
    index = frame.loc[[sessions[0]]].index
    release = session_window(int(sessions[3]))[0]
    provider = service._raw_label_provider
    assert provider.labels(index, horizon=2, as_of_ms=release - 1).isna().all()
    np.testing.assert_allclose(
        provider.labels(index, horizon=2, as_of_ms=release), np.arange(1, 7) / 100, atol=1e-15
    )


def test_feature_open_does_not_supply_labels_or_change_weights():
    service, sessions, frame, mask, zs, _, _ = setup()
    original = service._weights_from_panel(frame, mask, zs)
    changed = frame.copy()
    changed.open_px = np.geomspace(0.01, 1e9, len(frame))
    alternate = service._weights_from_panel(changed, mask, zs)
    pd.testing.assert_frame_equal(original.weights, alternate.weights, check_exact=True)
    # Feature-derived forecasts are held fixed: this tests label separation,
    # not an assertion that arbitrary feature changes leave a strategy unchanged.
    for t in sessions:
        selection = frame.index.get_level_values(0) <= t
        prefix = service._weights_from_panel(
            frame.loc[selection], mask.loc[selection], {n: z.loc[selection] for n, z in zs.items()}
        )
        np.testing.assert_array_equal(prefix.asof(t), original.asof(t))


def test_raw_dividend_changes_released_weights():
    service, sessions, frame, mask, _, _, _ = setup()
    ascending = pd.Series(np.tile(np.arange(6), len(sessions)), index=frame.index, dtype=float)
    zs = {"a": ascending, "b": -ascending, "c": ascending * 0}
    result = service._weights_from_panel(frame, mask, zs)
    np.testing.assert_array_equal(result.asof(sessions[2]), [1 / 3] * 3)
    np.testing.assert_allclose(result.asof(sessions[3]), [8 / 9, 1 / 18, 1 / 18], atol=1e-15)
    assert result.asof(sessions[3])["b"] < 0.1


def test_late_action_cannot_backfill_old_ic():
    service, _, frame, mask, zs, _, _ = setup(late=True)
    with pytest.raises(ObservationError, match="Late action"):
        service._weights_from_panel(frame, mask, zs)
    diagnostic, _, frame, mask, zs, _, _ = setup(mode="DIAGNOSTIC_CURRENT_VINTAGE", late=True)
    assert not diagnostic._weights_from_panel(frame, mask, zs).weights.empty
    assert diagnostic._raw_label_provider.binding["raw_label_mode"] == "DIAGNOSTIC_CURRENT_VINTAGE"


def test_missing_inception_is_nan_without_rephasing_and_disputes_fail():
    _service, sessions, frame, _, _, paired, snaps = setup()
    paired = paired[~((paired.symbol == "A") & (paired.session_ms == sessions[1]))]
    provider = RawHoldingLabelProvider(
        paired, instrument_symbols={s: s for s in "ABCDEF"}, snapshots=snaps, mode="PROSPECTIVE"
    )
    release = session_window(int(sessions[3]))[0]
    labels = provider.labels(frame.loc[[sessions[0]]].index, horizon=2, as_of_ms=release)
    assert np.isnan(labels.loc[(sessions[0], "A")])
    assert labels.notna().sum() == 5
    paired.loc[(paired.symbol == "B") & (paired.session_ms == sessions[3]), "price_disputed"] = True
    disputed = RawHoldingLabelProvider(
        paired, instrument_symbols={s: s for s in "ABCDEF"}, snapshots=snaps, mode="PROSPECTIVE"
    )
    with pytest.raises(ObservationError, match="Unresolved"):
        disputed.labels(frame.loc[[sessions[0]]].index, horizon=2, as_of_ms=release)
    assert provider.binding != disputed.binding


def test_snapshot_mapping_and_frame_mutations_do_not_change_provider():
    service, sessions, frame, _, _, paired, snaps = setup()
    before = service._raw_label_provider.binding
    paired.loc[:, "raw_open"] = 5.0
    snaps["A"] = replace(snaps["A"], actions=())
    release = session_window(int(sessions[3]))[0]
    labels = service._raw_label_provider.labels(
        frame.loc[[sessions[0]]].index, horizon=2, as_of_ms=release
    )
    assert labels.iloc[0] == pytest.approx(0.01)
    assert service._raw_label_provider.binding == before
