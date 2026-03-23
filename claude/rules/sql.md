---
globs: "*.sql,*.psql"
description: SQL conventions for PostgreSQL (Supabase), Spark SQL (Databricks), migrations
---

# SQL Rules

## Naming
- Tables: `snake_case` plural (`user_profiles`, `try_on_results`)
- Columns: `snake_case` singular (`created_at`, `user_id`, `is_active`)
- Primary keys: `id` (prefer UUID over serial for distributed systems)
- Foreign keys: `<referenced_table_singular>_id` (`user_id`, `photo_id`)
- Indexes: `idx_<table>_<columns>` (`idx_users_email`)
- Constraints: `chk_<table>_<rule>`, `uniq_<table>_<columns>`

## Query Safety
- ALWAYS use parameterized queries — never interpolate user input into SQL
- Use `LIMIT` on all unbounded queries — no full table scans in application code
- Use `SELECT <columns>` — never `SELECT *` in application queries (OK in ad-hoc/debug)
- Always include `WHERE` on `UPDATE` and `DELETE` — no unqualified mutations
- Use transactions for multi-statement writes

## PostgreSQL / Supabase
- Use Row Level Security (RLS) on all user-facing tables
- Prefer `jsonb` over `json` for stored JSON
- Use `timestamptz` not `timestamp` — always timezone-aware
- Index foreign keys and frequently-filtered columns
- Use `ON CONFLICT` (upsert) instead of check-then-insert patterns
- Prefer `EXISTS` over `IN` for subqueries on large tables
- Use `pg_trgm` extension for fuzzy text search, not `LIKE '%term%'`

## Migrations
- One migration per logical change — don't bundle unrelated schema changes
- Always include `DOWN` / rollback migration
- Never drop columns in the same deploy as the code change — deploy code first, then migrate
- Add columns as `NULL` first, backfill, then add `NOT NULL` constraint
- Test migrations against a copy of production data, not empty tables

## Spark SQL / Databricks
- Prefer `MERGE INTO` over delete-then-insert for upserts
- Use `OPTIMIZE` and `ZORDER BY` on frequently queried columns
- Partition by date or tenant for large tables
- Use `DESCRIBE HISTORY` to verify changes

## Security
- No inline credentials in connection strings — use environment variables
- Principle of least privilege — application users get only needed permissions
- Audit log sensitive operations (delete, schema change, permission grant)
- No `GRANT ALL` — be specific about privileges
- Escape identifiers with double quotes when they might conflict with reserved words
