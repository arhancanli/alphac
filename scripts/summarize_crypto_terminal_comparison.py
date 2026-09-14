"""Aggregate the seven frozen, reconciled scenario outputs without new strategy runs."""

import hashlib
import json
from pathlib import Path

import pandas as pd
from run_crypto_terminal_comparison import preflight

from alphaforge.validation.experiments import ExperimentUnion

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/analysis/crypto_terminal_comparison_20260913_attempt2"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def curve(arm):
    return pd.read_parquet(OUT / arm / "run/equity.parquet").set_index("ts").equity


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    rows, bindings = [], {}
    for scenario in protocol["arms"]:
        name = scenario["id"]
        preflight(name)
        directory = OUT / name
        closure = json.loads((directory / "closure.json").read_text())
        assert sha(ROOT / closure["packet"]) == closure["packet_sha256"]
        audit = json.loads((directory / "independent_audit.json").read_text())
        for source, digest in audit["source_sha256"].items():
            assert sha(ROOT / source) == digest
        meta = json.loads((directory / "run/walkforward.json").read_text())
        excess = json.loads((directory / "excess_benchmark_audit.json").read_text())
        assert excess["equity_sha256"] == sha(directory / "run/equity.parquet")
        if scenario["terminal"]:
            invariants = json.loads((directory / "terminal_invariants.json").read_text())
            assert invariants["status"] == "TERMINAL_LIFECYCLE_INVARIANTS_PASS"
            for source, digest in invariants["source_sha256"].items():
                assert sha(ROOT / source) == digest
        rows.append(
            {
                "arm": name,
                **{
                    k: meta["summary"][k]
                    for k in [
                        "total_return",
                        "sharpe",
                        "max_dd",
                        "max_dd_bar",
                        "fees_paid",
                        "funding_net",
                        "final_equity",
                    ]
                },
                "net_excess_sharpe_proxy": excess["net_excess_sharpe_DFF_proxy"],
                "hourly_accounting_max_error": max(
                    leg["max_abs_residual"] for leg in audit["legs"]
                ),
            }
        )
        for p in directory.rglob("*"):
            if p.is_file():
                bindings[str(p.relative_to(ROOT))] = sha(p)
    boundary = 1652369400000
    checks = []
    for low, high in [
        ("terminal_lower", "terminal_upper"),
        ("terminal_lower_cost_stress", "terminal_upper_cost_stress"),
        ("repaired_open_control", "terminal_lower"),
    ]:
        a, b = curve(low), curve(high)
        pd.testing.assert_series_equal(a[a.index < boundary], b[b.index < boundary])
        checks.append({"a": low, "b": high, "pre_terminal_equity_exact_equal": True})
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / "comparison.csv", index=False)
    union = ExperimentUnion.discover(ROOT / "var/experiments.jsonl", ROOT).n_hypotheses()
    report = {
        "status": "SEVEN_ARMS_MEASURED_RECONCILED",
        "experiment_union": union,
        "qualified": False,
        "hourly_snapshots_checked": 7 * 3024,
        "pre_boundary_checks": checks,
        "source_sha256": bindings,
        "comparison_sha256": sha(OUT / "comparison.csv"),
    }
    with (OUT / "comparison_verification.json").open("x") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(
        frame[["arm", "total_return", "net_excess_sharpe_proxy", "max_dd"]].to_string(index=False)
    )
    print("Union:", union, "; seven packets and input bindings verified.")


if __name__ == "__main__":
    main()
