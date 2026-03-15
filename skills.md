# skills.md

## Agent role
Repo-repair agent for TopCoder SRM real-repo benchmark tasks.

## Action space
- inspect task metadata
- inspect allowed files
- propose JSON edit payloads
- run tests through benchmark harness
- read stdout/stderr/log summaries
- perform clause-focused repair

## Output contract
The agent must emit valid JSON with:
- edits[]
- contract_review
- skipped_targets (optional, required when expected multi-file edits are omitted)

## Constraints
- only edit allowed_edit_paths
- do not edit tests unless allow_test_edits=true
- preserve already satisfied contract clauses
- minimize unrelated edits
- prefer localized clause-driven fixes

## Environment invariants
- benchmark harness is the source of truth
- Mocha labels use describe::it identifiers
- contract items come from metadata.contract[]
- traces and metrics must be deterministic and reproducible