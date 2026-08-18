-- Phase 2: read-only analytics-oriented views (not user-scoped; use API filters for per-user smart stacks)

create or replace view v_smart_reels as
select * from content_items where source_type = 'reel';

create or replace view v_smart_posts as
select * from content_items where source_type = 'post';

create or replace view v_smart_recent_ready as
select * from content_items where status = 'ready';
