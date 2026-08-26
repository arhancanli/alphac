from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _module():
    path = REPO / "scripts/seal_sharadar_split_governance_policy.py"
    spec = importlib.util.spec_from_file_location("split_governance_policy_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_failed_event_has_one_conservative_governance_route() -> None:
    payload = _module().build()
    assert payload["decision"] == "ALL_FAILED_SPLIT_EVENTS_ROUTED_GLOBAL_GATE_REMAINS_CLOSED"
    assert payload["summary"]["events_routed"] == 473
    assert sum(payload["summary"]["routes"].values()) == 473
    assert payload["summary"]["global_split_gate_passed"] is False
    assert payload["summary"]["genuinely_unresolved"] == 2
    keys = {
        (row["instrument_id"], row["ex_date_ms"], row["stored_ratio"])
        for row in payload["events"]
    }
    assert len(keys) == 473


def test_only_exact_issuer_verified_events_are_executable() -> None:
    payload = _module().build()
    authorized = [row for row in payload["events"] if row["execution_authorized"]]
    assert {
        (row["instrument_id"], row["ex_date_ms"], row["stored_ratio"])
        for row in authorized
    } == {
        ("XUSE:CASH:ADTXUSD", 1663113600000, 0.02),
        ("XUSE:CASH:AMPEUSD", 1669075200000, 0.06667),
            ("XUSE:CASH:BNIUSD", 904694400000, 3.0),
            ("XUSE:CASH:BYNDQUSD", 994032000000, 0.06667),
            ("XUSE:CASH:CBUSD", 888883200000, 3.0),
            ("XUSE:CASH:CCILUSD", 892598400000, 1.5),
        ("XUSE:CASH:EPACUSD", 886464000000, 2.0),
        ("XUSE:CASH:EVHCUSD", 1480636800000, 0.334),
        ("XUSE:CASH:ETS1USD", 1130716800000, 0.125),
        ("XUSE:CASH:HAFCUSD", 1001289600000, 1.5),
        ("XUSE:CASH:GDWUSD", 945043200000, 3.0),
        ("XUSE:CASH:JAKKUSD", 941760000000, 1.5),
            ("XUSE:CASH:LNGUSD", 971827200000, 0.25),
            ("XUSE:CASH:MCLDQUSD", 933033600000, 2.0),
            ("XUSE:CASH:MCLDQUSD", 956620800000, 3.0),
            ("XUSE:CASH:NCI1USD", 891388800000, 1.5),
            ("XUSE:CASH:NWKCUSD", 992822400000, 0.06667),
            ("XUSE:CASH:ORIGUSD", 1506038400000, 0.00011),
            ("XUSE:CASH:CRGNUSD", 954460800000, 2.0),
            ("XUSE:CASH:ICIXUSD", 897955200000, 2.0),
            ("XUSE:CASH:OATSUSD", 884217600000, 1.5),
            ("XUSE:CASH:OATSUSD", 944092800000, 1.5),
            ("XUSE:CASH:SPCEUSD", 1718582400000, 0.05),
            ("XUSE:CASH:UTI1USD", 970531200000, 2.0),
            ("XUSE:CASH:XCEDQUSD", 985132800000, 0.1),
    }
    assert (
        payload["execution_contract"]["provider_confirmation_alone_authorizes_execution"]
        is False
    )
    assert payload["execution_contract"]["unlisted_or_nonmatching_event_action"] == (
        "ABORT_IF_EXPOSED"
    )


def test_issuer_verified_lifecycle_breaks_are_nonexecutable() -> None:
    payload = _module().build()
    rows = [
        row
        for row in payload["events"]
        if row["governance_route"]
        == "NON_EXECUTABLE_ISSUER_VERIFIED_LIFECYCLE_DISCONTINUITY"
    ]
    assert {row["ticker"] for row in rows} == {
        "BASXQ",
        "CIVI",
        "CQB",
        "EGLE2",
        "KEGX",
        "TDW",
    }
    assert all(row["execution_authorized"] is False for row in rows)


def test_incomplete_composite_mutations_remain_quarantined() -> None:
    payload = _module().build()
    rows = [
        row
        for row in payload["events"]
        if row["governance_route"] == "HARD_QUARANTINE_ISSUER_VERIFIED_COMPOSITE_ACTION"
    ]
    assert {row["ticker"] for row in rows} == {
        "ATNI",
        "CMO",
        "IHG",
        "ITT",
        "KMI1",
        "KSU",
        "NRF",
        "SBRA",
        "TYC",
        "T1",
        "RBAK",
        "SDH1",
    }
    assert all(row["execution_authorized"] is False for row in rows)


def test_issuer_conflicts_remain_hard_quarantined() -> None:
    payload = _module().build()
    rows = [
        row
        for row in payload["events"]
        if row["governance_route"] == "HARD_QUARANTINE_ISSUER_CONFLICT_OR_DATE_MISMATCH"
    ]
    assert {row["ticker"] for row in rows} == {
        "CDR",
        "DIAL1",
        "GEVA",
        "IPAR",
        "MHGVY",
        "NVEC",
        "NCI1",
        "PRTK",
        "USB",
        "PRGN1",
        "ABEV",
        "E",
        "EXMCQ",
        "AAWW",
        "ACL",
        "AZAA",
    }
    assert all(row["execution_authorized"] is False for row in rows)
