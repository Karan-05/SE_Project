# CGCS Repair Skill Pack

This skill pack captures the core heuristics needed to repair Topcoder SRM repositories with Contract-Graph Counterexample Satisfaction (CGCS).

## Pillars
1. **Clause focus** – always target the currently active clause and explicitly reference its ID and description.
2. **Regression guards** – never regress clauses listed in `regression_guard_ids`; confirm their behavior verbatim before any edit.
3. **Witness synthesis** – translate failing witness data into concrete acceptance criteria (status codes, payload fields, aggregation math).
4. **Payload hygiene** – emit deterministic JSON edit payloads that modify only the allowed implementation files; explain skipped targets when required.
5. **Traceability** – note which clause/witness combination each code change addresses so that graders can map edits to discharge outcomes.
