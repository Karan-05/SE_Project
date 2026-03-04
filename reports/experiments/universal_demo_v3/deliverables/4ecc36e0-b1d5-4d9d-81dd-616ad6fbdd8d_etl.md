## Problem Summary
## Project Overview
The Identity Service project is used  to validate username / password logins, lookuap roles, etc...  It's currently implemented in Java and targets MySQL/Informix.
We want to revise the project to use **TypeScript** and point to **Postgres** via **Prisma**, but **keep the functionalities untouched, such as redis cache, Kafka event bus, etc**.  

In previous challenges: [Topcode

## Source Data and Schemas
- Source: operational DB
- Fields: id, user_id, status, updated_at

## Transformation Steps
1. Ingest via CDC
2. Normalize enums
3. Aggregate daily metrics

## SQL or Code Snippets
```sql
SELECT user_id, COUNT(*) AS events FROM staging.events GROUP BY 1;
```

## Validation Queries
- Assert row counts match
- Spot check null ratios

## Sample Outputs
| user_id | events |
| --- | --- |
| 42 | 15 |


## Acceptance Checklist
- Schema versioned
- Data quality alerts configured
- Backfill validated