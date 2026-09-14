"""Evaluate NYSE quotes at the unchanged 60 clocks and freshness limits."""

import audit_share_class_quotes as audit

audit.DIRECTORY = audit.DIRECTORY.parent / "share-class-quotes-nyse"
audit.PAIRS = [("BRK A", "BRK B")]

if __name__ == "__main__":
    audit.main()
