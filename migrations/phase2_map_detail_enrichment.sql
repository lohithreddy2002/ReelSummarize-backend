-- Phase 2: map pins and detail card enrichment

alter table if exists locations
  add column if not exists rating numeric,
  add column if not exists review_count int,
  add column if not exists place_category text,
  add column if not exists image_url text;

alter table if exists content_items
  add column if not exists semantic_tags text[],
  add column if not exists mood_tags text[],
  add column if not exists curator_insight text;
