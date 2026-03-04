# ETL/Data Pipeline Design for Payment Status Check

## Problem Summary
The goal is to design an ETL pipeline that checks the payment sent status for transactions. The pipeline will extract data from a source database, transform it to meet the requirements, and load it into a destination database for reporting and analysis. The transformation will also include removing unnecessary elements from the UI as specified in the F2F requirements.

## Source Data and Schemas

### Source Schema
**Table: `transactions`**
| Column Name       | Data Type   | Description                        |
|-------------------|-------------|------------------------------------|
| `transaction_id`  | INT         | Unique identifier for the transaction |
| `user_id`         | INT         | Identifier for the user            |
| `amount`          | DECIMAL     | Amount of the transaction          |
| `payment_status`  | VARCHAR(20) | Status of the payment (e.g., 'Paid', 'Pending', 'Failed') |
| `created_at`      | TIMESTAMP   | Timestamp of when the transaction was created |

### Destination Schema
**Table: `payment_statuses`**
| Column Name       | Data Type   | Description                        |
|-------------------|-------------|------------------------------------|
| `transaction_id`  | INT         | Unique identifier for the transaction |
| `user_id`         | INT         | Identifier for the user            |
| `amount`          | DECIMAL     | Amount of the transaction          |
| `is_paid`         | BOOLEAN     | Indicates if the payment is sent   |
| `created_at`      | TIMESTAMP   | Timestamp of when the transaction was created |

## Transformation Steps
1. **Extract** data from the `transactions` table.
2. **Transform** the `payment_status` column to a boolean `is_paid` column:
   - If `payment_status` is 'Paid', set `is_paid` to TRUE.
   - Otherwise, set `is_paid` to FALSE.
3. **Load** the transformed data into the `payment_statuses` table.

## SQL or Code Snippets

```sql
-- Extract and Transform
INSERT INTO payment_statuses (transaction_id, user_id, amount, is_paid, created_at)
SELECT 
    transaction_id,
    user_id,
    amount,
    CASE 
        WHEN payment_status = 'Paid' THEN TRUE
        ELSE FALSE
    END AS is_paid,
    created_at
FROM transactions;
```

## Validation Queries

```sql
-- Validate that all transactions have been loaded
SELECT COUNT(*) FROM transactions;

-- Validate that the number of paid transactions matches the count in the destination
SELECT COUNT(*) FROM payment_statuses WHERE is_paid = TRUE;

-- Validate that the schema of the destination table matches the expected schema
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'payment_statuses';
```

## Sample Outputs

| transaction_id | user_id | amount | is_paid | created_at          |
|----------------|---------|--------|---------|---------------------|
| 1              | 101     | 100.00 | TRUE    | 2023-10-01 10:00:00 |
| 2              | 102     | 50.00  | FALSE   | 2023-10-01 11:00:00 |
| 3              | 103     | 75.00  |