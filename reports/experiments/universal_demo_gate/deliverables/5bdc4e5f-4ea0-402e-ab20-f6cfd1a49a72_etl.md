## Problem Summary
Design an ETL pipeline to track payment statuses by consolidating payment data from various sources into a structured format. The pipeline will include data validation checks and sample outputs to ensure data integrity.
## Source Data and Schemas
- PAYMENT_STATUS(payment_id STRING, user_id STRING, status ENUM('Pending', 'Completed', 'Failed'), updated_at TIMESTAMP)
- DQ_CHECKS(payment_id STRING, check_type STRING, status BOOLEAN, created_at TIMESTAMP)
## Pipeline Skeleton (Python)
```python
def extract_payment_data():
    # Pseudocode for extracting payment data
    return payment_data

def transform_payment_data(payment_data):
    # Pseudocode for transforming data to target schema
    return transformed_data

def load_to_warehouse(transformed_data):
    # Pseudocode for loading data into the warehouse
    pass

# Main ETL process
payment_data = extract_payment_data()
transformed_data = transform_payment_data(payment_data)
load_to_warehouse(transformed_data)
```
## Transformation Steps
Extract payment data from source systems (e.g., MySQL, API), transform the data to match the target schema, and load it into a data warehouse for reporting. The pipeline will run daily and include data quality checks.
## Test Strategy & Validation Queries
- Check for NULL values in payment_id and user_id
- Ensure status values are within defined ENUM
- Validate updated_at timestamps are not in the future
- Test: python scripts/test_etl.py --validate_schema
- Test: python scripts/check_data_quality.py --check DQ_CHECKS
## Sample Outputs
- Provide sample before/after rows or aggregates.
## Acceptance Checklist
- Pipeline scheduled
- DQ alerts configured
- Backfill validated