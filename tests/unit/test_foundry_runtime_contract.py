from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "config" / "foundry_runtime_contract.json"
RESEARCH_FIREWALL = ROOT / "deploy" / "foundry" / "host" / "research.nft"
HOLDOUT_FIREWALL = ROOT / "deploy" / "foundry" / "host" / "holdout.nft"
PROXY = ROOT / "deploy" / "foundry" / "host" / "squid-foundry.conf"


def test_every_runtime_component_denies_broker_write_access() -> None:
    contract = json.loads(RUNTIME.read_text(encoding="utf-8"))
    assert contract["status"] == "FROZEN_NOT_DEPLOYED"
    assert contract["defaults"] == {
        "rootless": True,
        "read_only_root": True,
        "read_only_tmpfs": False,
        "no_new_privileges": True,
        "drop_capabilities": "all",
        "seccomp": "runtime-default-or-stricter",
        "host_docker_socket": False,
        "interactive_shell": False,
        "environment_host": False,
    }
    assert all(
        component["broker_write_access"] is False
        for component in contract["components"].values()
    )


def test_worker_has_bounded_resources_and_no_general_internet_network() -> None:
    contract = json.loads(RUNTIME.read_text(encoding="utf-8"))
    worker = contract["components"]["worker"]
    assert worker["network"] == ["postgres_private", "data_gateway_loopback"]
    assert worker["quota"] == {
        "cpu_millis": 1500,
        "memory_mebibytes": 2048,
        "process_limit": 256,
        "disk_mebibytes": 8192,
        "wall_seconds": 3600,
    }


def test_migration_validation_and_publication_database_roles_are_separate() -> None:
    contract = json.loads(RUNTIME.read_text(encoding="utf-8"))
    assert contract["components"]["migration_operator"] == {
        "unix_user": "foundrymigrator",
        "database_role": "foundry_migrator",
        "network": ["postgres_private"],
        "secrets": ["ephemeral_migration_database_dsn"],
        "disabled_after_first_migration": True,
        "broker_write_access": False,
    }
    assert contract["components"]["validator"]["database_role"] == "foundry_validator"
    assert (
        contract["components"]["sanitizer_publisher"]["database_role"]
        == "foundry_publisher"
    )


def test_host_firewalls_are_deny_default_and_keep_holdout_separate() -> None:
    research = RESEARCH_FIREWALL.read_text(encoding="utf-8")
    holdout = HOLDOUT_FIREWALL.read_text(encoding="utf-8")
    assert research.count("policy drop") == 3
    assert holdout.count("policy drop") == 3
    assert 'meta skuid "foundryworker"' in research
    assert 'tcp dport { 53, 443 } accept' not in research.split(
        'meta skuid "foundryworker"', maxsplit=1
    )[1].split("\n\n", maxsplit=1)[0]
    assert "10.44.0.0/20" not in holdout


def test_proxy_is_https_allowlist_and_does_not_allow_alpaca() -> None:
    proxy = PROXY.read_text(encoding="utf-8")
    assert "http_access allow CONNECT approved_sources" in proxy
    assert "http_access deny all" in proxy
    assert "alpaca" not in proxy.casefold()
