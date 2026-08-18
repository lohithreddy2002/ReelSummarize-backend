-- Phase 1 enrichment columns and updated_at trigger helper.

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
