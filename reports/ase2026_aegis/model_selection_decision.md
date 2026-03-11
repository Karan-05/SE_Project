# Model Selection Decision

**Selected headline method:** aegis_no_constraints (success 1.00, reward 60.24).

## Rationale
- Outperforms other AEGIS variants on success rate (1.00) and budgeted success (1.00).
- Offers balanced action diversity (entropy 1.61).

## Essential Components
- graph_memory
- calibration_head
- hierarchical_options

## Optional / Ablatable Components
- constraint_penalties

## Evidence Considered
- Comparisons against no-graph, no-calibration, no-constraints, and flat variants.
- Calibration/Brier metrics from calibration table.