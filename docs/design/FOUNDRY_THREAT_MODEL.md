# ALPHAC Foundry Threat Model and Network Boundary

**Date:** 2026-08-26

**Owner:** Arhan Canli

**Status:** Design frozen, not deployed

**Applies to:** The proposed continuously available research controller, workers, data gateway,
holdout vault, validator, sanitizer and public status adapter

## 1. Claim boundary

This document defines the minimum security and governance boundary for Foundry. It does not claim
that the infrastructure has been provisioned, that the controls have been tested on DigitalOcean,
or that a strategy has passed through Foundry. Production status requires deployment receipts,
network tests, recovery tests and one complete replay packet.

## 2. Security objective

Foundry may continuously process approved research work without acquiring a path to place broker
orders, inspect a sealed holdout before authorization, exceed the hypothesis identity budget, publish
private data or mutate the live forward record.

The system is fail-closed. Losing a dependency can delay a job. It cannot relax a research gate or
promote a candidate.

## 3. Authoritative platform assumptions

The current DigitalOcean design relies only on documented platform properties:

1. A VPC provides a private network interface that is inaccessible from the public internet and
   other VPC networks by default.
2. Cloud Firewalls are stateful and block traffic that is not expressly permitted by a rule.
3. Cloud Firewall inbound and outbound rules are separate. The default outbound suggestions are
   broad, so this design replaces them with explicit destinations.
4. Managed PostgreSQL provides a private VPC hostname, TLS and trusted-source controls.
5. Spaces supports application-specific access keys with bucket-level permission scopes.
6. A private Droplet needs a VPC NAT gateway or another explicit gateway for outbound internet
   access. When a NAT gateway is the VPC default route, private Droplets use it automatically.
7. Terraform remote state in Spaces can use a versioned private bucket and an S3-compatible lock
   file, with credentials injected through environment variables.

Platform documentation:

1. <https://docs.digitalocean.com/products/networking/vpc/>
2. <https://docs.digitalocean.com/products/networking/firewalls/getting-started/quickstart/>
3. <https://docs.digitalocean.com/products/networking/firewalls/how-to/configure-rules/>
4. <https://docs.digitalocean.com/products/databases/postgresql/how-to/connect/>
5. <https://docs.digitalocean.com/products/databases/postgresql/how-to/secure/>
6. <https://docs.digitalocean.com/products/spaces/how-to/manage-access/>
7. <https://docs.digitalocean.com/products/droplets/details/private-droplets/>
8. <https://docs.digitalocean.com/products/spaces/reference/terraform-backend/>

Cloud controls and host controls are separate. A Cloud Firewall rule does not configure UFW or the
container runtime. Both layers require independent verification.

## 4. Protected assets

| Asset | Required property | Consequence of failure |
|---|---|---|
| Hypothesis identity registry | Complete, ordered and append-only | Hidden trials or understated deflation |
| Trial budget | Enforced before outcome access | Unbounded search and invalid significance |
| Point-in-time snapshots | Immutable and source-bound | Leakage or irreproducible results |
| Holdout | Sealed until one-shot authorization | Selection on the holdout |
| Research code and images | Reviewed and content-addressed | Arbitrary execution or irreproducible jobs |
| Trial artifacts | Complete and immutable | Selective publication or missing failures |
| Live broker credentials | Unreachable from Foundry | Unauthorized paper or future funded orders |
| Signing identity | Unavailable to general workers | Forged public evidence |
| Licensed data | Never exposed publicly | Contract breach and source loss |
| Public status | Sanitized and accurate | Secret leakage or false operational claims |

## 5. Trust zones

```text
Internet
   |
   +---- [Dedicated research NAT] ---- [Z2/Z3 private research VPC]
   |
   +---- [Dedicated holdout NAT] ----- [Z4 private holdout VPC]
   |
   v
[Z0 Public product] <----- sanitized bundle ----- [Z1 Publisher]
                                                   ^
                                                   |
                                             allowlisted artifacts
                                                   |
[Z2 researchd] ---> [Z3 Worker pool] ---> [Z3 Validator]
      |                    |                    |
      |                    v                    |
      +------------> [Data gateway] <-----------+
      |
      +------------> [Managed PostgreSQL]
      |
      +------------> [Spaces research buckets]
      |
      +---- human authorization ----> [Z4 Holdout vault]

[Z5 ALPHAC live execution] ---> Alpaca paper accounts

There is no route from Z0, Z1, Z2, Z3 or Z4 to Z5.
```

### Z0: public product

Vercel or another public host serves sanitized, read-only artifacts. It has no DigitalOcean control
token, database credential, Spaces write key, broker key or signing key.

### Z1: publisher

The publisher receives an allowlisted artifact bundle. It can write only to the public publication
destination. It cannot read raw data, private hypotheses, holdout values or broker state directly.

### Z2: control plane

`researchd` owns queue policy, reservations, quotas, leases and state transitions. It does not run
strategy code and has no broker key. Its database role can write trial metadata and audit events but
cannot administer the database.

### Z3: workers, validator and data gateway

Workers run pinned, rootless images with per-job resources and temporary filesystems. The data
gateway is the only component allowed to fetch approved data sources. Validators receive artifacts,
not general host access.

### Z4: holdout vault

The holdout lives under separate credentials and an independent authorization path. General workers
cannot list or read it. A one-shot job receives a narrow object grant, writes a sealed result and loses
access. Consumption is recorded before values become available to the research controller.

### Z5: live execution

The existing ALPHAC live node owns broker write credentials and the forward record. It is a separate
security boundary and deployment principal. Foundry publishes candidates for human review. It never
sends orders or modifies live state.

## 6. Network policy matrix

Every unlisted connection is denied.

| Source | Destination | Allowed | Purpose |
|---|---|---:|---|
| Operator allowlist | Bastion or private administration path | Yes | Reviewed administration |
| Public internet | Research nodes | No | No public worker or controller ports |
| Research private hosts | Dedicated research NAT | Narrow | Approved updates and allowlisted proxy egress |
| Holdout private host | Dedicated holdout NAT | Narrow | Holdout object access only |
| Research VPC | Holdout NAT | No | Preserve separate egress and fault domains |
| Holdout VPC | Research NAT | No | Preserve separate egress and fault domains |
| `researchd` | Managed PostgreSQL private hostname | Yes | Queue, registry and audit transactions |
| Workers | Managed PostgreSQL private hostname | Narrow | Lease heartbeat and result metadata only |
| Workers | Data gateway | Yes | Approved snapshot reads |
| Workers | General internet | No | Prevent undeclared data and exfiltration |
| Data gateway | Allowlisted provider endpoints | Yes | Declared source acquisition |
| Workers | Research Spaces bucket | Scoped | Read snapshot, write job prefix |
| Validator | Research Spaces bucket | Read | Reproduce and inspect completed artifacts |
| Holdout worker | Holdout bucket | One-shot scoped | Consume one authorized holdout object |
| Publisher | Sanitized publication bucket | Write | Publish allowlisted public bundle |
| Public product | Sanitized publication bucket | Read | Serve public evidence |
| Any Foundry zone | ALPHAC live node | No | Preserve execution isolation |
| Any Foundry zone | Alpaca order endpoints | No | Foundry cannot submit broker orders |

DNS, time synchronization, operating-system updates and alert delivery require explicit host rules.
They must not be implemented as unrestricted outbound access.

## 7. Identity and secret separation

Use separate credentials for:

1. Infrastructure provisioning.
2. `researchd` database access.
3. Worker database access.
4. Research snapshot read and job-prefix write.
5. Validator read-only access.
6. Holdout one-shot access.
7. Publisher sanitized-bucket write.
8. Public artifact read.
9. Evidence signing.
10. ALPHAC live broker execution.

No credential is shared between Foundry and ALPHAC live execution. Spaces keys are scoped per
application and bucket. The deployment procedure must verify the current DigitalOcean access model
before creation because provider permission features can change.

Secrets never enter Git, container images, job payloads, public artifacts or logs. Secret values are
redacted before structured logging and scanned before publication.

## 8. Job containment

1. Rootless containers.
2. Read-only base image.
3. `no-new-privileges` enabled.
4. Seccomp profile and dropped Linux capabilities.
5. No host Docker socket.
6. CPU, memory, process, disk and wall-time limits.
7. Temporary writable job directory destroyed after artifact upload.
8. Pinned image digest and source commit recorded in every run.
9. No interactive shell in production workers.
10. No unreviewed model-generated code in a production queue.

The worker image may execute only a declared entry point with a signed job manifest. Strategy code is
reviewed before image build. A text prompt is never treated as executable authorization.

## 9. Research governance boundary

The machine-readable lifecycle is `config/foundry_trial_state_machine.json`.

Required ordering:

1. Metadata-only feasibility.
2. Human-authored proposal.
3. Human-approved identity reservation.
4. Point-in-time snapshot freeze.
5. Bounded run.
6. Deterministic validation.
7. Separate holdout authorization.
8. One holdout consumption.
9. Paper shadow.
10. Admission or kill under the active contract.

Outcome access is forbidden before reservation and snapshot freeze. A failed gate cannot be changed
to pass through human approval. A human can close a trial, authorize a permitted transition or repair
infrastructure. A human cannot rewrite the recorded outcome.

## 10. Threat analysis

| Threat | Example | Required controls | Verification evidence |
|---|---|---|---|
| Hidden trial | Worker tests variants outside the ledger | Reservation required, bounded manifest, network-denied side path | Registry count equals run manifests |
| Holdout leakage | Worker reads the holdout during tuning | Separate bucket key, one-shot role, isolated state transition | Access log and consumption receipt |
| Broker pivot | Compromised worker submits an order | Separate VPC boundary, no key, outbound deny | Network test and secret inventory |
| Data exfiltration | Job uploads licensed rows | Outbound allowlist, sanitizer, field allowlist | Egress test and publication scan |
| Artifact substitution | Result bytes change after validation | Content hashes, immutable object naming, signed manifest | Clean replay and hash match |
| Queue privilege escalation | Job edits another trial | Per-job identity, row-level authorization, prefix-scoped objects | Negative authorization tests |
| Budget bypass | New run begins after tripwire | Transactional reservation against active budget | Concurrency and tripwire tests |
| Retry selection | Failed job retries with changed parameters | Retry binds same identity and manifest | Retry hash equality test |
| Publisher compromise | Public host gains private access | Push-only sanitized boundary, public host has no private credentials | Credential and network inventory |
| Signing-key theft | Worker signs false evidence | Dedicated signer, no general worker access | Key-access negative test |
| Operator error | Broad firewall permits all outbound | Infrastructure review and explicit network tests | Saved firewall export and probe report |
| False status | Public page says Foundry is live before deployment | Status token defaults to not deployed | Published contract and deployment receipt |

## 11. Audit events

Every transition writes an append-only event containing:

1. Public trial identifier.
2. Prior and next state.
3. Action.
4. Human or system actor identifier.
5. Authorization reference.
6. Source commit and image digest.
7. Data snapshot hash.
8. Job manifest hash.
9. Result artifact hash when present.
10. UTC timestamp.

Audit events never include a secret or licensed row. Corrections append a new event and retain the
superseded event.

## 12. Availability and recovery

Continuous availability means approved work can be queued at any time. It does not mean unlimited
outcome-bearing search.

Minimum recovery controls:

1. Managed PostgreSQL automated backups plus a tested logical export.
2. Versioned or content-addressed Spaces objects.
3. Daily queue and lease consistency check.
4. Worker loss handled through expiring leases and idempotent job startup.
5. Restore drill into an isolated environment.
6. Replay of one completed trial after restore.
7. Alert for stalled queue, stale heartbeat, failed sanitizer, failed replay and budget tripwire.

## 13. Deployment sequence

1. Export and preserve the current ALPHAC live firewall and secret inventory.
2. Create a dedicated, private, versioned and lock-enabled remote state backend.
3. Create separate research and holdout VPCs under a dedicated Foundry deployment principal.
4. Create one dedicated default-route NAT gateway per VPC and verify that the routes are not shared.
5. Provision private Managed PostgreSQL with trusted sources and TLS verification.
6. Create separate research, holdout and sanitized publication buckets and keys.
7. Provision `researchd`, data gateway, validator and one worker pool with no public service ports.
8. Apply Cloud Firewall and host firewall rules from the network matrix.
9. Run negative connectivity tests, especially Foundry to ALPHAC and Alpaca order endpoints.
10. Deploy the state machine in audit-only mode.
11. Migrate one existing killed trial without spending a new identity.
12. Reproduce it in a clean worker and publish only the sanitized packet.
13. Perform a restore drill.
14. Change status from `DESIGN_FROZEN_NOT_DEPLOYED` only after receipts prove each control.

## 14. Deployment acceptance evidence

Foundry v1 is deployed only when the repository contains or binds to:

1. Infrastructure manifest and reviewed plan output.
2. Cloud and host firewall exports.
3. Negative network-probe report.
4. Secret-scope inventory with values redacted.
5. Database migration and role tests.
6. Spaces permission tests for every application key.
7. Trial state-machine test results.
8. One complete migration, replay and sanitizer packet.
9. Backup restore and post-restore replay receipt.
10. Public status artifact that still discloses all remaining limitations.
