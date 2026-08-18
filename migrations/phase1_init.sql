-- Phase 1 baseline schema for Supabase Postgres
-- Apply via Supabase SQL migrations workflow.

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
