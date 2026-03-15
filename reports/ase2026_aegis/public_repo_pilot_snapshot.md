# Public Repo Pilot Benchmark — Snapshot

> **Engineering note**: This is a seeded-repair pilot benchmark built on the
> `data/public_repos/` acquisition pool.  It does **not** replace the Topcoder
> recovery funnel.  Its purpose is to validate CGCS harness instrumentation
> with real repos before the Topcoder corpus is fully available.

## Pipeline Funnel

| Stage | Input | Output |
|---|---|---|
| Subset selection | 82 seed repos | 10 pilot repos |
| Workspace validation | 10 repos | 10 ok |
| Task generation | 10 valid repos | 10 tasks |
| Pilot run | 10 tasks × 0 strategies | 0 runs |
| Eval pack | 0 successful runs | 0 eval items |

## Language Distribution (Selected Subset)

| Language | Count |
|---|---|
| java | 2 |
| javascript | 2 |
| python | 4 |
| typescript | 2 |

## Trace Quality

| Metric | Count |
|---|---|
| Rounds total | 0 |
| Rounds with contract items | 0 |
| Rounds with active clause | 0 |
| Rounds ready for strict dataset | 0 |

## Eval Items

| Metric | Count |
|---|---|
| Total eval items | 0 |
| Non-placeholder payloads | 0 |
| With contract items | 0 |
| Splits | {} |

## Notes

- Mutations injected per task: 1
- Strategies evaluated: 
- Pilot run status: 0/0 runs succeeded
