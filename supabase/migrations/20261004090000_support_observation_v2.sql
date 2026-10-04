-- Phase final: preserve the mixed v1/v2 observation contract.
alter table public.observations
  add column if not exists schema_version integer not null default 1,
  add column if not exists quality text not null default 'observed',
  add column if not exists released_at timestamptz;

alter table public.observations
  drop constraint if exists observations_quality_check;

alter table public.observations
  add constraint observations_quality_check
  check (quality in ('observed', 'missing'));

alter table public.observations
  drop constraint if exists observations_schema_version_check;

alter table public.observations
  add constraint observations_schema_version_check
  check (schema_version in (1, 2));

comment on column public.observations.schema_version is 'Source observation contract version.';
comment on column public.observations.quality is 'observed or missing; missing is never interpreted as zero.';
comment on column public.observations.released_at is 'Time the source released the observation.';
