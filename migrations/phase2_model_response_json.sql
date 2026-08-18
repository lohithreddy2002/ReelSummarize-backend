-- Phase 2.1: store raw LLM/model response payload for future use/auditing

alter table if exists content_items
  add column if not exists model_response_json jsonb;

