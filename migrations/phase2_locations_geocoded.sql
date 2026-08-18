-- Allow storing place names when geocoding is disabled or fails; optional coordinates.

alter table if exists locations
  add column if not exists geocoded boolean not null default true;

alter table if exists locations
  alter column lat drop not null,
  alter column lng drop not null;

comment on column locations.geocoded is 'false when lat/lng could not be resolved; name/display still shown in UI';
