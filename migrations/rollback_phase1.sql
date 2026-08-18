-- Full Phase 1 rollback (destructive). Apply after reversing optional follow-up migrations.
-- Order: dependents first.

drop index if exists idx_extraction_jobs_lease;
drop index if exists idx_content_items_summary_trgm;
drop index if exists idx_content_items_title_trgm;

drop table if exists menu_items cascade;

drop trigger if exists trg_extraction_jobs_updated_at on extraction_jobs;
drop trigger if exists trg_content_items_updated_at on content_items;
drop function if exists set_updated_at();

drop table if exists bookmarks cascade;
drop table if exists locations cascade;
drop table if exists extraction_jobs cascade;

drop table if exists content_items cascade;
