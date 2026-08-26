from __future__ import annotations

import pytest

from alphaforge.foundry.database import (
    CredentialBoundaryError,
    DatabaseContractError,
    FoundryDatabase,
    assert_no_broker_credentials,
)


@pytest.mark.parametrize(
    "name",
    [
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "BROKER_WRITE_TOKEN",
        "PAPER_BROKER_CREDENTIAL",
    ],
)
def test_foundry_refuses_broker_credential_environment_keys(name: str) -> None:
    with pytest.raises(CredentialBoundaryError, match=name):
        assert_no_broker_credentials({name: "value-never-read-or-logged"})


def test_foundry_accepts_only_its_database_credential() -> None:
    database = FoundryDatabase.from_environment(
        {"FOUNDRY_DATABASE_DSN": "postgresql://example.invalid/foundry"}
    )
    assert isinstance(database, FoundryDatabase)


def test_foundry_requires_a_database_dsn() -> None:
    with pytest.raises(DatabaseContractError, match="FOUNDRY_DATABASE_DSN"):
        FoundryDatabase.from_environment({})
