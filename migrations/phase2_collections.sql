-- Phase 2: user collections and membership

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
