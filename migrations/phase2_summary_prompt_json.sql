-- Phase 2: snapshot of system + user prompts sent for summarization (audit / reproducibility)

alter table if exists content_items
  add column if not exists summary_prompt_json jsonb;
