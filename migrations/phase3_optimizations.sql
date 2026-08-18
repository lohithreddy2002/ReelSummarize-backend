-- =============================================================================
-- Phase 3 — DB optimizations
-- Run once in Supabase SQL Editor or psql before deploying the updated backend.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- DB-3: Atomic job claim using FOR UPDATE SKIP LOCKED
--
-- Replaces the GET-25-rows + Python-filter + PATCH optimistic-lock retry loop
-- in claim_next_extraction_job.  A single function call is fully atomic and
-- has zero race conditions under concurrent workers.
-- -----------------------------------------------------------------------------
create or replace function claim_extraction_job(
    p_worker_id  text    default 'worker',
    p_lease_seconds int  default 300
)
returns setof extraction_jobs
language plpgsql
as $$
declare
    v_job  extraction_jobs;
    v_until timestamptz := now() + (p_lease_seconds || ' seconds')::interval;
begin
    -- 1. Try to claim the oldest eligible queued job
    select * into v_job
    from extraction_jobs
    where status = 'queued'
      and (next_retry_at is null or next_retry_at <= now())
    order by created_at asc
    limit 1
    for update skip locked;

    -- 2. Fall back to stale-leased processing jobs (lease expired, no worker)
    if not found then
        select * into v_job
        from extraction_jobs
        where status = 'processing'
          and locked_until < now()
        order by created_at asc
        limit 1
        for update skip locked;
    end if;

    if not found then
        return;
    end if;

    update extraction_jobs
    set
        status          = 'processing',
        stage           = 'leased',
        locked_until    = v_until,
        updated_at      = now()
    where id = v_job.id
    returning * into v_job;

    return next v_job;
end;
$$;

-- -----------------------------------------------------------------------------
-- DB-1: Single-query queue summary
--
-- Replaces 5–6 serial REST count requests in summarize_extraction_queue with
-- one RPC call that returns counts grouped by status + a long-running count.
-- -----------------------------------------------------------------------------
create or replace function extraction_queue_summary(
    stuck_minutes int default 90
)
returns json
language sql
stable
as $$
    select json_build_object(
        'jobs_by_status', (
            select coalesce(
                json_object_agg(status, cnt),
                '{}'::json
            )
            from (
                select status, count(*)::int as cnt
                from extraction_jobs
                group by status
            ) s
        ),
        'long_running_processing_count', (
            select count(*)::int
            from extraction_jobs
            where status = 'processing'
              and updated_at < now() - (stuck_minutes || ' minutes')::interval
        )
    )
$$;
