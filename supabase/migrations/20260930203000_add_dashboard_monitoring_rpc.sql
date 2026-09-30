-- Expose only the read-only fields used by the public monitoring dashboard.
-- The underlying tables remain private and protected by RLS/grants.
create or replace function public.dashboard_monitoring()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select jsonb_build_object(
    'runs', coalesce(
      (
        select jsonb_agg(to_jsonb(recent) order by recent.started_at desc)
        from (
          select run_type, status, started_at, finished_at
          from public.pipeline_runs
          order by started_at desc
          limit 15
        ) as recent
      ),
      '[]'::jsonb
    ),
    'drift_history', coalesce(
      (
        select jsonb_agg(
          jsonb_build_object(
            'accuracy', historical.accuracy,
            'drift', historical.drift_score,
            'calculated_at', historical.calculated_at
          )
          order by historical.calculated_at asc
        )
        from (
          select accuracy, drift_score, calculated_at
          from public.metric_snapshots
          where metric_scope = 'competition_personal'
          order by calculated_at desc
          limit 24
        ) as historical
      ),
      '[]'::jsonb
    )
  );
$$;

revoke all on function public.dashboard_monitoring() from public;
grant execute on function public.dashboard_monitoring() to anon, authenticated, service_role;
