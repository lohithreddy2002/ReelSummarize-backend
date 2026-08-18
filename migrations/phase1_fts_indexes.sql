-- Phase 1: full-text / trigram search support for feed search (Phase 2 will query these)

create extension if not exists pg_trgm;

create index if not exists idx_content_items_title_trgm
  on content_items using gin (title_generated gin_trgm_ops);

create index if not exists idx_content_items_summary_trgm
  on content_items using gin (summary_text gin_trgm_ops);
