# ALPHAC Foundry v1 deployment runbook

**Owner:** Arhan Canli

**Current status:** Designed and locally verified, not provisioned

This directory turns the frozen Foundry threat model into a reviewed deployment target. It does not
claim that DigitalOcean resources exist or that any deployment acceptance test has passed.

## Boundaries that may not change during deployment

1. Use a dedicated DigitalOcean principal. The existing API Optimizer database and deployer
   contexts are not Foundry credentials and must not be broadened or reused.
2. Do not place an Alpaca, exchange order, live signing or execution-node credential on either
   Foundry host.
3. Keep the research and holdout VPCs unpeered.
4. Keep both application Droplets private. The optional bastion is temporary, operator-CIDR bound
   and destroyed at the end of the maintenance window.
5. Do not change the public status from `DESIGN_FROZEN_NOT_DEPLOYED` until every acceptance receipt
   in `config/foundry_deployment_manifest.json` exists and verifies.
6. A failed research gate is a kill, not a reason to edit the gate.

## 1. Prerequisites

The provisioning principal needs only the DigitalOcean scopes required to create and inspect the
project, VPCs, private Droplets, firewalls, Managed PostgreSQL and Spaces buckets. It must not have
access to the ALPHAC live host or broker secrets.

Provide credentials through process environment variables supported by the DigitalOcean Terraform
provider. Never put them in a `.tfvars` file, shell history, Git, Terraform output or a receipt.

Use a protected Terraform backend before the first real plan. The state contains infrastructure
metadata and Managed PostgreSQL credentials. A local unencrypted state file is not an acceptable
production backend.

## 2. Review and plan

```bash
cd deploy/foundry/terraform
cp terraform.tfvars.example terraform.tfvars
# Set only the globally unique bucket prefix. Keep the bastion disabled.
terraform init
terraform fmt -check -recursive
terraform validate
terraform plan -out=foundry.tfplan
terraform show -json foundry.tfplan > foundry-plan.private.json
```

The plan is private. Review it for exactly two unpeered VPCs, two private application Droplets, one
private PostgreSQL cluster, three private versioned buckets and no execution resource. Confirm that
`public_networking = false` remains set on both application Droplets.

Creating the resources spends money and is a separate apply decision. Record the reviewed plan hash,
reviewer, UTC time and exact provider lock hash before applying it.

## 3. Apply core infrastructure

Apply the saved plan only, then export a redacted resource inventory. Terraform outputs the state
`PROVISIONED_UNVERIFIED`; this is intentionally not an operational status.

The cloud-init payload installs rootless Podman prerequisites, separate locked Unix identities,
host nftables rules and the explicit HTTPS proxy allowlist. It does not deploy an application,
container image, database password, Spaces key, holdout object or broker credential.

## 4. Issue application credentials

Issue each credential independently after the infrastructure exists:

| Principal | Scope |
|---|---|
| `researchd` | Foundry database role and no object or broker key |
| Worker | Worker database role and no direct public-internet key |
| Data gateway | Approved provider credentials and research-bucket read/write |
| Validator | Research-bucket read only |
| Publisher | Sanitized publication bucket write only |
| Public adapter | Sanitized publication bucket read only |
| Holdout worker | Holdout bucket only, issued for one authorized consumption |
| Evidence signer | Signing operation only, unavailable to workers |

Application Spaces keys are not Terraform resources because their secret values would enter the main
Terraform state. Record key identifiers, grants, creation times and rotation dates in the private
scope inventory. Never record values.

Before installation, run the environment-name boundary check from the exact service account. A
Foundry process must refuse startup if an Alpaca or broker credential variable is present.

## 5. Migrate and bind PostgreSQL

Create the `foundry_researchd`, `foundry_worker` and `foundry_status` database users outside Git.
Apply migrations as the narrow database owner:

```bash
psql "$FOUNDRY_DATABASE_ADMIN_DSN" -v ON_ERROR_STOP=1 \
  -f deploy/foundry/sql/001_core.sql
psql "$FOUNDRY_DATABASE_ADMIN_DSN" -v ON_ERROR_STOP=1 \
  -f deploy/foundry/sql/002_privileges.sql
FOUNDRY_DATABASE_DSN="$FOUNDRY_DATABASE_ADMIN_DSN" \
  uv run af foundry bind-contract \
  --activated-by "deployment-receipt:<private receipt hash>"
```

Binding is insert-only. A lifecycle or policy hash mismatch fails closed and requires a reviewed
migration. Do not update the binding row in place.

## 6. Build and install pinned images

Build from a reviewed commit, scan the image, sign it, push it under a Foundry repository namespace
and record the immutable registry digest. Production Quadlets use the digest, `Pull=never`, a
read-only root, no writable temporary filesystem unless declared, all capabilities dropped,
`no-new-privileges`, seccomp and service-level CPU, memory, process and wall-time limits.

Never mount a Docker or Podman socket. Never turn a prompt or unpublished generated code into a
production entry point.

## 7. Prove negative connectivity first

Run probes from the worker, validator, publisher and holdout identities. At minimum, preserve proof
that:

1. Worker access to public internet and Alpaca order endpoints fails.
2. Every Foundry identity fails to reach the ALPHAC execution host.
3. Holdout fails to reach the research VPC and database.
4. Worker fails to read publisher, signer and holdout credentials.
5. The data gateway reaches only the approved proxy destinations.
6. PostgreSQL accepts only the research Droplet and enforces role tests.

A DNS failure counts as denied connectivity but must be distinguished from a firewall rejection in
the private receipt. Never probe an order endpoint with an authenticated request.

## 8. Migrate one killed trial

Choose an existing complete killed identity. Import its immutable identity and packet references as
legacy migration data without assigning a new Foundry identity ordinal. Run its declared clean replay
in a pinned worker, validate artifact hash equality, sanitize the complete packet and publish the
negative outcome. This migration may not reopen the identity or spend a new hypothesis.

Do not accept new outcome-bearing research until this path completes.

## 9. Restore drill

Restore a logical PostgreSQL export and content-addressed objects into an isolated recovery project.
Rebind only if hashes match, replay the migrated killed trial and compare its sanitized packet hash.
Record recovery point, recovery time, database checks, object checks and replay result.

## 10. Public status

The status adapter uses only `foundry_status`. Export through:

```bash
FOUNDRY_DATABASE_DSN="$FOUNDRY_STATUS_DATABASE_DSN" \
  uv run af foundry export-public-status \
  --output /var/lib/foundry/public/foundry-status.json \
  --restore-status PASS
```

The sanitizer constructs the allowlist, validates timestamps and hashes, rejects secret-like output
and writes a content hash. It never serializes private hypotheses, holdout values, provider details,
licensed rows or credentials.

## 11. Acceptance

Foundry v1 is operational only when every receipt required by the deployment manifest exists, hashes
cleanly and points to the same infrastructure, contract, policy, source commit and image digest. A
partially complete deployment remains `PROVISIONED_UNVERIFIED` or `DESIGN_FROZEN_NOT_DEPLOYED` on the
public surface.
