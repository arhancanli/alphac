# Historical research environments

The active `uv.lock` receives dependency security updates. Historical publication
manifests and legacy migration packets retain the lock digest they originally bound.
A runtime update does not retroactively reproduce those results.

`<sha256>/uv.lock.txt` preserves the exact original lock bytes. The text suffix keeps
this an archival artifact rather than an automatically selected package-manager lock.
The first archive was recovered from Git revision `c57be7b^:uv.lock`; its SHA-256 is
`5caca664242722a3a3112663d7a19b7b5000583e30ade3753e1b8ffdecfd6f06`.

The original environment includes versions superseded by the security update. It is
not a deployment recommendation. Verification reads and hashes it without installing
or executing packages. Never replace the active runtime lock with this archive.

`resolve_environment_binding` accepts only the root project definition and lockfile.
An unchanged root file is reported as `ACTIVE_FILE_MATCH`; a lock resolved from this
archive is reported as `HISTORICAL_ARCHIVE_ONLY`, alongside the different active digest.
The archive must have exactly the expected bytes and no symlinks. Source-code drift
and project-definition drift cannot use an archival fallback.

Publication integrity checks expose these receipts and continue to deny new result
reproduction. The original bundle files, SHA256SUMS and migration packet remain
unchanged. Foundry preflight can inspect an archival packet, but replay enqueueing
rechecks the actual workspace project/lock files and rejects archive-only resolution.
Changing a file after preflight also prevents enqueueing.

A historical replay requires a separate, disposable historical workspace with its
exact bound source, project, lock and private inputs. The CLI's `--repository-root`
selects that workspace. File matching alone does not prove dependencies were installed,
an image was built correctly, or any research ran. The existing image, private-snapshot,
no-network, quota and one-shot gates still apply. No replay or dependency installation
is performed by the archive resolver.
