## Problem Summary
Create an ETL blueprint to check the payment sent status, including schema definitions, pipeline steps, validation queries, and sample outputs. The implementation must avoid unnecessary changes to existing functions and adhere to the provided design assets.
## Source Data and Schemas
- Define staging + warehouse schemas.
## Pipeline Skeleton (Python)
```python
def etl_process():
    extract_data()
    transform_data()
    load_data()
```
## Transformation Steps
The ETL pipeline will extract payment data from the source database, transform it by removing unnecessary links and separators, and load the cleaned data into the target database. The pipeline will run daily with a recovery plan in case of failures.
## SQL / Validation Snippets
- Provide CTEs/queries validating row counts and invariants.
## Test Strategy & Validation Queries
- {'name': 'Check for null values in payment status', 'column': 'status', 'threshold': 'No null values allowed'}
- {'name': 'Check for duplicates in payment IDs', 'column': 'payment_id', 'threshold': 'No duplicates allowed'}
## Sample Outputs
- Provide sample before/after rows or aggregates.
## Acceptance Checklist
- Pipeline scheduled
- DQ alerts configured
- Backfill validated