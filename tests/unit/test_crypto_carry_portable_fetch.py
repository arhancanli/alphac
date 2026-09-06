from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/fetch_crypto_carry_archives_portable.py"


def _module():
    spec = importlib.util.spec_from_file_location("crypto_carry_fetch", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _zip(path: Path, name: str, text: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, text)


def test_normalizers_preserve_archive_semantics_and_add_declared_lag(tmp_path: Path) -> None:
    module = _module()
    bar = tmp_path / "bar.zip"
    funding = tmp_path / "funding.zip"
    _zip(
        bar,
        "bar.csv",
        "1640995200000,1,2,0.5,1.5,10,1640998799999,15,3,4,6,0\n",
    )
    _zip(
        funding,
        "funding.csv",
        "calc_time,funding_interval_hours,last_funding_rate\n"
        "1640995200006,8,0.00010000\n",
    )
    bars = module._normalize_ohlcv([bar], "BTCUSDT", 1640995200000, 1641081600000)
    rates = module._normalize_funding([funding], "BTCUSDT", 1640995200000, 1641081600000)
    assert bars.iloc[0]["close"] == 1.5
    assert bars.iloc[0]["n_trades"] == 3
    assert rates.iloc[0]["rate"] == 0.0001
    assert rates.iloc[0]["funding_interval_hours"] == 8
    assert rates.iloc[0]["available_at"] - rates.iloc[0]["ts_funding"] == pd.Timedelta(
        minutes=5
    )


def test_regional_endpoint_is_official_bucket_path_style() -> None:
    module = _module()
    branded = "https://data.binance.vision/data/futures/um/example.zip"
    assert module._regional(branded) == (
        "https://s3.ap-northeast-1.amazonaws.com/data.binance.vision/"
        "data/futures/um/example.zip"
    )


def test_acquisition_failure_is_preserved_as_data(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    task = module.ArchiveTask(
        "funding",
        "ICPUSDT",
        "2021-07",
        "https://data.binance.vision/missing.zip",
        "https://data.binance.vision/missing.zip.CHECKSUM",
    )
    monkeypatch.setattr(module, "_acquire", lambda *_: (_ for _ in ()).throw(FileNotFoundError()))
    result = module._acquire_safe(task, tmp_path)
    assert result["passes"] is False
    assert result["symbol"] == "ICPUSDT"
    assert result["month"] == "2021-07"
    assert result["error_type"] == "FileNotFoundError"
