# ETL/Data Pipeline for Topcoder Identity Service Fix

## Problem Summary
The Topcoder Identity Service is being revised to ensure that the UserController aligns with the existing Java implementation. The main objective is to fix discrepancies in API functionalities, particularly around permission checks, user registration, and profile management. This involves migrating from Java/MySQL to TypeScript/Postgres while maintaining existing functionalities such as Redis caching and Kafka event handling.

## Source Data and Schemas
### Source Schema (MySQL)
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL,
    password VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    role VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Destination Schema (Postgres)
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    role VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Invariants
1. **Unique Constraints**: `username` and `email` must be unique across the `users` table.
2. **Non-nullable Fields**: `username`, `password`, and `email` cannot be null.
3. **Data Type Consistency**: Ensure that data types remain consistent between source and destination schemas.

## Transformation Steps
1. **Data Extraction**: Pull data from the MySQL `users` table.
2. **Data Cleaning**: Validate and sanitize user data (e.g., password strength, email format).
3. **Data Transformation**: Map fields from MySQL to Postgres schema.
4. **Data Loading**: Insert cleaned and transformed data into the Postgres `users` table.

## SQL or Code Snippets
### Pseudo-Code for ETL Process
```python
import psycopg2
import mysql.connector

# Connect to MySQL
mysql_conn = mysql.connector.connect(user='user', password='password', host='mysql_host', database='identity_service')
mysql_cursor = mysql_conn.cursor()

# Connect to Postgres
pg_conn = psycopg2.connect("dbname='identity_service' user='user' password='password' host='pg_host'")
pg_cursor = pg_conn.cursor()

# Extract
mysql_cursor.execute("SELECT * FROM users")
users = mysql_cursor.fetchall()

# Transform and Load
for user in users:
    # Data cleaning and transformation
    username, password, email, role = user[1], user[2], user[3], user[4]
    # Insert into Postgres
    pg_cursor.execute("INSERT INTO users (username, password, email, role) VALUES (%s, %s, %s, %s)", (username, password, email, role))

# Commit and close
pg_conn.commit()
mysql_conn.close()
pg_conn.close()
```

## Validation Queries
### SQL Assertions
```sql
-- Check for unique usernames
SELECT username, COUNT(*) FROM users GROUP BY username HAVING COUNT(*) > 1;

-- Check for unique emails
SELECT email, COUNT(*) FROM users GROUP BY email HAVING COUNT(*) > 1;

-- Check for non-nullable fields
SELECT * FROM users WHERE username IS NULL OR password IS NULL OR email IS NULL;
```

## Sample Outputs
###