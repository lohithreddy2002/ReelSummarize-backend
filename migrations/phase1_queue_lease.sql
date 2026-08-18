-- Phase 1: job lease / retry fields for Postgres-backed queue workers

alter table if exists extraction_jobs
  add column if not exists locked_until timestamptz,
  add column if not exists next_retry_at timestamptz;

create index if not exists idx_extraction_jobs_lease
  on extraction_jobs(status, next_retry_at, locked_until, created_at);
