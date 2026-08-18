-- =============================================================================
-- ReelSummarize — full database schema (Postgres / Supabase)
-- =============================================================================
-- Single file to create a fresh database: run once in Supabase SQL Editor or psql.
-- Idempotent where possible (IF NOT EXISTS / IF NOT EXISTS columns).
-- For rollback or partial migrations, use the individual phase*.sql files instead.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Phase 1 — baseline (content_items, jobs, locations, bookmarks)
-- -----------------------------------------------------------------------------
create table if not exists content_items (
  id uuid primary key default gen_random_uuid(),
  owner_user_id text not null,
  source_url text not null,
  source_platform text not null default 'unknown',
  source_type text not null default 'reel',
  status text not null default 'queued',
  title_original text,
  title_generated text,
  summary_text text,
  thumbnail_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists extraction_jobs (
  id uuid primary key default gen_random_uuid(),
  content_id uuid not null references content_items(id) on delete cascade,
  status text not null default 'queued',
  stage text not null default 'queued',
  progress_percent int not null default 0,
  attempt int not null default 0,
  max_attempts int not null default 3,
  error_code text,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists locations (
  id uuid primary key default gen_random_uuid(),
  content_id uuid not null references content_items(id) on delete cascade,
  name text not null,
  display_name text,
  lat double precision not null,
  lng double precision not null
);

create table if not exists bookmarks (
  owner_user_id text not null,
  content_id uuid not null references content_items(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (owner_user_id, content_id)
);

create index if not exists idx_content_items_owner_created on content_items(owner_user_id, created_at desc);
create index if not exists idx_content_items_status on content_items(status);
create index if not exists idx_extraction_jobs_content_created on extraction_jobs(content_id, created_at desc);
create index if not exists idx_locations_content on locations(content_id);

-- -----------------------------------------------------------------------------
-- Phase 1 — enrichment columns + updated_at triggers
-- -----------------------------------------------------------------------------
alter table if exists content_items
  add column if not exists summary_method text,
  add column if not exists likes_count bigint,
  add column if not exists comments_count bigint,
  add column if not exists views_count bigint;

create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_content_items_updated_at on content_items;
create trigger trg_content_items_updated_at
before update on content_items
for each row execute function set_updated_at();

drop trigger if exists trg_extraction_jobs_updated_at on extraction_jobs;
create trigger trg_extraction_jobs_updated_at
before update on extraction_jobs
for each row execute function set_updated_at();

-- -----------------------------------------------------------------------------
-- Phase 1 — menu_items
-- -----------------------------------------------------------------------------
create table if not exists menu_items (
  id uuid primary key default gen_random_uuid(),
  content_id uuid not null references content_items(id) on delete cascade,
  location_id uuid references locations(id) on delete set null,
  name text not null,
  item_type text,
  currency text,
  price_value numeric,
  price_display text,
  price_confidence numeric,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_menu_items_content on menu_items(content_id);
create index if not exists idx_menu_items_location on menu_items(location_id);

-- -----------------------------------------------------------------------------
-- Phase 1 — trigram indexes (requires pg_trgm)
-- -----------------------------------------------------------------------------
create extension if not exists pg_trgm;

create index if not exists idx_content_items_title_trgm
  on content_items using gin (title_generated gin_trgm_ops);

create index if not exists idx_content_items_summary_trgm
  on content_items using gin (summary_text gin_trgm_ops);

-- -----------------------------------------------------------------------------
-- Phase 1 — job lease / retry (queue workers)
-- -----------------------------------------------------------------------------
alter table if exists extraction_jobs
  add column if not exists locked_until timestamptz,
  add column if not exists next_retry_at timestamptz;

create index if not exists idx_extraction_jobs_lease
  on extraction_jobs(status, next_retry_at, locked_until, created_at);

-- -----------------------------------------------------------------------------
-- Phase 2 — collections
-- -----------------------------------------------------------------------------
create table if not exists collections (
  id uuid primary key default gen_random_uuid(),
  owner_user_id text not null,
  name text not null,
  description text,
  cover_image_url text,
  collection_type text not null default 'custom',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists collection_items (
  collection_id uuid not null references collections(id) on delete cascade,
  content_id uuid not null references content_items(id) on delete cascade,
  added_at timestamptz not null default now(),
  primary key (collection_id, content_id)
);

create index if not exists idx_collections_owner_updated on collections(owner_user_id, updated_at desc);
create index if not exists idx_collection_items_content on collection_items(content_id);

drop trigger if exists trg_collections_updated_at on collections;
create trigger trg_collections_updated_at
before update on collections
for each row execute function set_updated_at();

-- -----------------------------------------------------------------------------
-- Phase 2 — search_documents (optional FTS helper table)
-- -----------------------------------------------------------------------------
create table if not exists search_documents (
  content_id uuid primary key references content_items(id) on delete cascade,
  owner_user_id text not null,
  search_text text not null default '',
  updated_at timestamptz not null default now()
);

create index if not exists idx_search_documents_owner on search_documents(owner_user_id);
create index if not exists idx_search_documents_trgm on search_documents using gin (search_text gin_trgm_ops);

-- -----------------------------------------------------------------------------
-- Phase 2 — map + detail enrichment columns
-- -----------------------------------------------------------------------------
alter table if exists locations
  add column if not exists rating numeric,
  add column if not exists review_count int,
  add column if not exists place_category text,
  add column if not exists image_url text;

alter table if exists content_items
  add column if not exists semantic_tags text[],
  add column if not exists mood_tags text[],
  add column if not exists curator_insight text;

-- -----------------------------------------------------------------------------
-- Phase 2 — smart views (optional)
-- -----------------------------------------------------------------------------
create or replace view v_smart_reels as
select * from content_items where source_type = 'reel';

create or replace view v_smart_posts as
select * from content_items where source_type = 'post';

create or replace view v_smart_recent_ready as
select * from content_items where status = 'ready';

-- -----------------------------------------------------------------------------
-- Phase 2 — model audit JSON on content_items
-- -----------------------------------------------------------------------------
alter table if exists content_items
  add column if not exists model_response_json jsonb;

-- -----------------------------------------------------------------------------
-- Phase 2 — summarization prompt snapshot JSON
-- -----------------------------------------------------------------------------
alter table if exists content_items
  add column if not exists summary_prompt_json jsonb;

-- -----------------------------------------------------------------------------
-- Phase 2 — locations: geocoded flag + nullable lat/lng (names without coords)
-- -----------------------------------------------------------------------------
alter table if exists locations
  add column if not exists geocoded boolean not null default true;

alter table if exists locations
  alter column lat drop not null,
  alter column lng drop not null;

comment on column locations.geocoded is 'false when lat/lng could not be resolved; name/display still shown in UI';

-- =============================================================================
-- Done.
-- =============================================================================
