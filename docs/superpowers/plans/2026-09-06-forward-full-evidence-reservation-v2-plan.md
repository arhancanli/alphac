# Forward full-evidence reservation v2: stage 1 + stage 2 implementation plan

> Steps use checkbox (`- [ ]`) syntax. All four tasks spend zero identity and change nothing in
> force: each adds an unwired, independently tested function to
> `src/alphaforge/validation/trial_reservation.py`. Nothing here reserves ordinal 230 or edits
> `config/sleeve_admission_contract.json`.

**Spec:** `docs/superpowers/specs/2026-09-06-forward-full-evidence-reservation-v2-design.md`, sections 2(a)-(b), section 5 items 1-3.

**Scope:** stage 1 (diagnostic class + validator support) and stage 2 (seriality guard fix + waiver) only, drafted as new standalone functions and proven against real sealed data. Neither `_validate_forward_epoch_serial_completion` (line 284) nor `validate_reservation` (line 469) calls them until Task 4, gated on owner approval. Stage 3 onward is a stub at the end.

---

### Task 1: Diagnostic evidence class definition and validator support

**Files:** create `tests/unit/test_trial_accounting_diagnostic_class.py`; modify `src/alphaforge/validation/trial_reservation.py`.

- [ ] **Step 1: write the failing test.** Import `DIAGNOSTIC_SCENARIO_CLASSES` and `DIAGNOSTIC_SCENARIO_REQUIRED_FIELDS` from `alphaforge.validation.trial_reservation`. Assert `DIAGNOSTIC_SCENARIO_CLASSES == frozenset({"cost_stress_scenarios", "execution_stress_scenarios", "capacity_scenarios"})` (the three list names in `config/forward_full_evidence_reservation_v2_template.json`'s `diagnostic_scenarios` block). Assert `DIAGNOSTIC_SCENARIO_REQUIRED_FIELDS == frozenset({"scenario_id", "assumptions", "assumptions_sha256", "result", "result_sha256", "primary_decision_path_sha256"})` (first five from `config/sleeve_admission_contract.json`'s `execution_evidence_policy.scenario_manifest_required_fields` minus `status`; `primary_decision_path_sha256` is new). Assert `_validate_diagnostic_scenarios(payload, sealed_primary_decision_path_sha256="abc...")` raises `ReservationError` matching `"does not match the sealed primary decision path"` on a scenario whose `primary_decision_path_sha256` differs from the bound value, and returns `{"diagnostic_scenario_count": N}` when every scenario matches.
- [ ] **Step 2: run, confirm it fails for the right reason.** `uv run pytest tests/unit/test_trial_accounting_diagnostic_class.py -q`. Expected: `ImportError: cannot import name 'DIAGNOSTIC_SCENARIO_CLASSES'`.
- [ ] **Step 3: implement.** In `trial_reservation.py` (after line 372, before line 469), add the two frozenset constants and a pure function `_validate_diagnostic_scenarios(payload: dict[str, Any], *, sealed_primary_decision_path_sha256: str) -> dict[str, Any]`. `payload.get("diagnostic_scenarios")` absent is valid (`{"diagnostic_scenario_count": 0}`); if present, it is a dict keyed by a subset of `DIAGNOSTIC_SCENARIO_CLASSES`, each value a list of scenario dicts with exactly `DIAGNOSTIC_SCENARIO_REQUIRED_FIELDS`, `assumptions_sha256`/`result_sha256` checked with `_matches_canonical_sha256` imported from `alphaforge.validation.sleeve_admission` (line 275), any `primary_decision_path_sha256` mismatch raising `ReservationError`. Add no call site; this task only defines the function.
- [ ] **Step 4: run to green.** `uv run pytest tests/unit/test_trial_accounting_diagnostic_class.py -q`.
- [ ] **Step 5: register the mutation.** Add to `MUTATIONS` in `scripts/mutation_ledger.py`: guard `"test_trial_accounting_diagnostic_class.py"`, target `REPO / "src/alphaforge/validation/trial_reservation.py"`, `_replace('!= sealed_primary_decision_path_sha256', '== sealed_primary_decision_path_sha256')`, expect `"CAUGHT"`. This test has none of `discover_guards`'s four substrings (`artifacts/`, `meridian`, `config/sleeve`, `glassbox`), so it is registered explicitly rather than by the substring rule (spec item 8). Verify: `uv run python3 scripts/mutation_ledger.py --only test_trial_accounting_diagnostic_class.py`.
- [ ] **Step 6: commit.** First line: `trial-reservation: draft the diagnostic evidence class and its validator, unwired`.

---

### Task 2: Seriality guard closure-disposition check and waiver schema

**Files:** create `tests/unit/test_seriality_waiver.py`; modify `src/alphaforge/validation/trial_reservation.py`.

- [ ] **Step 1: write the failing test.** In `tmp_path`, build a synthetic packet (`schema: "canli.alphac-identity-trial-packet.v2"`, `complete: true`, `missing_sections: []`, `content_hash` computed as `_observed_content_hash` does at line 81, `required_sections.admission_or_kill_decision.evidence` holding one item whose `path` ends `_admission_closure.json` plus its `sha256` and `content_hash`) and a matching closure (`decision.disposition: "INCOMPLETE"`, self-consistent hash). Assert `_validate_prior_identity_admission_disposition(tmp_path, "test_identity", packet)` raises `ReservationError` matching `"neither ADMIT nor KILL"` with no waiver present. Write a waiver at `artifacts/research/seriality_waivers/test_identity.json` with `waived_packet_content_hash` equal to the packet's `content_hash`; assert the call now returns normally. A third case sets `waived_packet_content_hash` to a stale hash and asserts `ReservationError` matching `"waiver does not match the sealed packet"` (spec item 3's mutation case).
- [ ] **Step 2: run, confirm it fails for the right reason.** `uv run pytest tests/unit/test_seriality_waiver.py -q`. Expected: import failure naming `_validate_prior_identity_admission_disposition`.
- [ ] **Step 3: implement.** Add constants `SERIALITY_WAIVER_DIR: Final[Path] = Path("artifacts/research/seriality_waivers")` and `SERIALITY_WAIVER_SCHEMA: Final[str] = "canli.alphac-seriality-waiver.v1"` after line 45. Add `_closure_path_from_packet(packet)`: reads `packet["required_sections"]["admission_or_kill_decision"]["evidence"]`, returns the first entry's `path` ending `_admission_closure.json` (the convention in `artifacts/research/trial_packets/da5f5f47f99f9bd2.json`). Add `_validate_prior_identity_admission_disposition(repo, identity, packet)`: locate and hash-check the closure with `_observed_content_hash`, read `closure["decision"]["disposition"]`; if not `{"ADMIT", "KILL"}`, require `repo / SERIALITY_WAIVER_DIR / f"{identity}.json"` (missing raises `ReservationError`), with `schema == SERIALITY_WAIVER_SCHEMA`, `waived_hypothesis_key == identity`, `waived_packet_content_hash == packet["content_hash"]` (else `"waiver does not match the sealed packet"`), `content_hash == _observed_content_hash(waiver)`, `reason` length `>= 12` (the `sleeve_admission.py:618` convention), `authorized_by` starting `"Arhan Canli, owner,"`. Place both after line 362; do not edit `_validate_forward_epoch_serial_completion`'s body or call either function from it or from `validate_reservation`.
- [ ] **Step 4: run to green.** `uv run pytest tests/unit/test_seriality_waiver.py -q`.
- [ ] **Step 5: register the mutation.** Add to `MUTATIONS`: guard `"test_seriality_waiver.py"`, target `REPO / "src/alphaforge/validation/trial_reservation.py"`, `_replace('waiver.get("waived_packet_content_hash") != packet["content_hash"]', 'waiver.get("waived_packet_content_hash") == packet["content_hash"]')`, expect `"CAUGHT"`. Verify: `uv run python3 scripts/mutation_ledger.py --only test_seriality_waiver.py`.
- [ ] **Step 6: commit.** First line: `trial-reservation: draft the seriality closure-disposition check and waiver schema, unwired`.

---

### Task 3: Prove today's real sealed state against the drafted function

**Files:** modify `tests/unit/test_validate_forward_trial_reservation.py`.

- [ ] **Step 1: write the failing test.** Add `test_prior_identity_admission_disposition_blocks_the_sealed_incomplete_v1_state(tmp_path)`: copy `ROOT / "artifacts/research/trial_packets/da5f5f47f99f9bd2.json"` and `ROOT / "artifacts/research/crypto_carry_portable_v1_admission_closure.json"` byte for byte into `tmp_path` at the same relative paths (replaying the exact packet, per item 2), then call `_validate_prior_identity_admission_disposition(tmp_path, "da5f5f47f99f9bd2", json.loads(the copied packet))` with no waiver; assert `ReservationError`. Real data: `complete: true`, closure `decision.disposition: "INCOMPLETE"`, closure `content_hash: "sha256:ac2ef258f30ee20dc8a915866cbc72e52c3f5ae93a21fb336cdd627406c0d451"`. Add `test_a_valid_seriality_waiver_unblocks_the_sealed_incomplete_v1_state`, additionally writing `artifacts/research/seriality_waivers/da5f5f47f99f9bd2.json` with `waived_packet_content_hash` equal to the packet's real `content_hash` (`"sha256:9ba408cb3c1d9accd91eddd25a079995a8d42aa6b7456dd6afd22539917ce40a"`); assert the call returns normally.
- [ ] **Step 2: run, confirm it fails for the right reason.** `uv run pytest tests/unit/test_validate_forward_trial_reservation.py -k sealed_incomplete_v1_state -q`. Expected: import failure until Task 2 lands.
- [ ] **Step 3: implement.** No production code changes; import `_validate_prior_identity_admission_disposition` at the top of the test file, alongside `ReservationError`/`validate_reservation`.
- [ ] **Step 4: run to green.** `uv run pytest tests/unit/test_validate_forward_trial_reservation.py -q`.
- [ ] **Step 5: register the mutation.** This file already has a `MUTATIONS` entry (guard `"test_validate_forward_trial_reservation.py"`, target `CONTRACT`, breaks the v7 schema string). No new registration needed; confirm `uv run pytest tests/unit/test_mutation_coverage.py -q` passes.
- [ ] **Step 6: commit.** First line: `trial-reservation: prove the sealed crypto_carry_portable_v1 state still blocks and a waiver unblocks it`.

---

### Task 4 (OWNER CHECKPOINT): wire the drafted functions into the in-force validator

- [ ] **Step 1: STOP.** Do not proceed without explicit, recorded owner approval. State: "Stages 1-2 are drafted and tested against real sealed data. `validate_reservation` is unchanged: the complete-but-INCOMPLETE v1 packet still does not block the next reservation (completeness alone unblocks it, line 342). Wiring changes what ordinal 230 must satisfy. Proceed, or stop?" If not approved, stop; leave the repository as Task 3 left it.
- [ ] **Step 2 (only if approved): write the failing end-to-end test.** Add `test_full_validate_reservation_blocks_ordinal_230_without_waiver_once_wired` to `tests/unit/test_validate_forward_trial_reservation.py`, replaying the Task 3 fixture inside a full `validate_reservation` call (governance epoch at ordinal 230, per `_governance_fixture`). Assert `ReservationError`.
- [ ] **Step 3: run, confirm it fails for the right reason.** `uv run pytest tests/unit/test_validate_forward_trial_reservation.py -k once_wired -q`. Expected: FAIL, no exception raised.
- [ ] **Step 4: implement the wiring.** In `_validate_forward_epoch_serial_completion` (line 284), inside the loop verifying each prior packet (lines 326-356), call `_validate_prior_identity_admission_disposition(repo, identity, packet)` right after the existing completeness checks, for every identity in `forward_keys`. Nothing else in `validate_reservation` changes; `_validate_diagnostic_scenarios` stays unwired, since no reservation yet declares `diagnostic_scenarios` (stage 3+).
- [ ] **Step 5: run to green.** `uv run pytest tests/unit/test_validate_forward_trial_reservation.py -q`.
- [ ] **Step 6: confirm the mutation ledger still holds.** `uv run python3 scripts/mutation_ledger.py --only test_validate_forward_trial_reservation.py`, expect `CAUGHT`; the new end-to-end test adds coverage to the same guard file, not a new ledger row.
- [ ] **Step 7: commit.** First line: `trial-reservation: wire the seriality closure-disposition check into the in-force validator (owner-approved)`.

---

## How the two stages interact with today's sealed state

Before Task 4 is approved, `validate_reservation` and `_validate_forward_epoch_serial_completion` are byte-identical to today. The sealed `crypto_carry_portable_v1` packet (`complete: true`, closure `decision.disposition: "INCOMPLETE"`, no waiver on disk) is not blocked by anything in Tasks 1-3, since none of it is called from the live path. This is deliberate and stated plainly rather than left implicit.

`test_prior_identity_admission_disposition_blocks_the_sealed_incomplete_v1_state` (Task 3) proves the drafted function rejects today's real state with no waiver. `test_a_valid_seriality_waiver_unblocks_the_sealed_incomplete_v1_state` (Task 3) proves a correctly shaped waiver, bound to the packet's real `content_hash`, makes it proceed. Only `test_full_validate_reservation_blocks_ordinal_230_without_waiver_once_wired` (Task 4, gated) proves the live path changes; until approved, reserving ordinal 230 today still passes the seriality check. The fix exists, tested, and inert.

**Waiver JSON shape** (spec section 2(b), `artifacts/research/seriality_waivers/<hypothesis_key>.json`):

```json
{
  "schema": "canli.alphac-seriality-waiver.v1",
  "waived_hypothesis_key": "da5f5f47f99f9bd2",
  "waived_packet_content_hash": "sha256:9ba408cb3c1d9accd91eddd25a079995a8d42aa6b7456dd6afd22539917ce40a",
  "reason": "Owner accepts the nine unfrozen evidence fields as a permanent evidentiary gap for this once-run identity and authorizes reserving the next ordinal without regrading v1.",
  "authorized_by": "Arhan Canli, owner, 2026-09-06",
  "content_hash": "sha256:<computed>"
}
```

This is illustrative, not a filed waiver; filing one is deferred past this plan. `content_hash` is computed exactly as `_observed_content_hash` (line 81) computes every hash in this file: drop the `content_hash` key, serialize with `json.dumps(sort_keys=True, separators=(",", ":"))`, SHA-256 the UTF-8 bytes, prefix with `"sha256:"`. `waived_packet_content_hash` must equal the sealed packet's own `content_hash`; a re-seal changes it and invalidates the waiver, which Task 2's stale-hash test proves.

## Next plan (stage 3 onward, not scheduled here)

Stage 3 covers spec sections 2(c)-(d): the pre-acceptance satisfiability audit (every frozen stress, capacity, and execution scenario must be provably able to FAIL, extending `audit_forward_full_evidence_reservation_v2_template.py`'s drift-detection pattern), authoring the nine frozen fields as real data, the runner and seal scripts in section 3's data flow, the `forward_full_evidence_reservation_v2_promotion.json` promotion record, and the `test_publish_pipeline_order.py` `EDGES` additions once those scripts exist. It follows spec section 5 items 4-7 and needs its own plan and owner checkpoints before ordinal 230 is spent.
