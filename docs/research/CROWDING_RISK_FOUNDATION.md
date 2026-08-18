# Point-in-time crowding and stressed capacity

AlphaForge now has a coverage-aware crowding gate in the shared pre-trade path. It keeps
institutional ownership, short interest, borrow utilization, fund flows, and liquidation time as
separate observables rather than compressing them into an attractive but unauditable score.

## Enforced behavior

- Every observation has explicit availability and validity timestamps.
- Missing required metrics produce `UNASSESSABLE`; they are not imputed from current data.
- Each limit breach is named independently.
- Liquidation days use a configured daily ADV participation ceiling and are repeated under an
  explicit ADV haircut.
- `BLOCK` and `UNASSESSABLE` reject new risk in the shared pre-trade checker.
- Reduce-only orders remain permitted.

## Evidence boundary

The arithmetic and pre-trade gate are implemented and tested. Historical ownership and mapped
fund-flow coverage are not yet available across the traded universe, thresholds are not empirically
calibrated to unwind losses, and correlated portfolio liquidation is not modeled. Therefore this
does not claim that any historical or current sleeve passed a crowding test.

The deterministic stress cases and source hashes are published at
[`/glassbox/crowding_risk_contract.json`](/glassbox/crowding_risk_contract.json).
