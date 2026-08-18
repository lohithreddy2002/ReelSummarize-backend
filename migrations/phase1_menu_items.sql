-- Phase 1: menu_items (canonical extraction target; optional until extraction writes rows)

create table if not exists menu_items (
  id uuid primary key default gen_random_uuid(),
  content_id uuid not null references content_items(id) on delete cascade,
  location_id uuid references locations(id) on delete set null,
  name text not null,
  item_type text,
  currency text,
  price_value numeric,
  price_display text,
  price_confidence numeric,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_menu_items_content on menu_items(content_id);
create index if not exists idx_menu_items_location on menu_items(location_id);
