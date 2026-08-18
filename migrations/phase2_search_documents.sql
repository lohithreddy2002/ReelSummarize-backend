-- Phase 2: optional denormalized search row (synced on content updates; query may use content_items directly)

create table if not exists search_documents (
  content_id uuid primary key references content_items(id) on delete cascade,
  owner_user_id text not null,
  search_text text not null default '',
  updated_at timestamptz not null default now()
);

create index if not exists idx_search_documents_owner on search_documents(owner_user_id);
create index if not exists idx_search_documents_trgm on search_documents using gin (search_text gin_trgm_ops);
