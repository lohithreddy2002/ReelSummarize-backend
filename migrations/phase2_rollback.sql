-- Rollback helpers for Phase 2 (run manually if needed)

drop view if exists v_smart_recent_ready;
drop view if exists v_smart_posts;
drop view if exists v_smart_reels;

alter table if exists content_items
  drop column if exists summary_prompt_json,
  drop column if exists curator_insight,
  drop column if exists mood_tags,
  drop column if exists semantic_tags;

alter table if exists locations
  drop column if exists geocoded,
  drop column if exists image_url,
  drop column if exists place_category,
  drop column if exists review_count,
  drop column if exists rating;

drop table if exists search_documents;

drop table if exists collection_items;
drop table if exists collections;
