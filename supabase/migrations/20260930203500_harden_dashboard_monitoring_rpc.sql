-- Run the public dashboard RPC with caller permissions. Anonymous access is
-- limited to the exact read-only columns and rows displayed by the dashboard.
alter function public.dashboard_monitoring() security invoker;

revoke execute on function public.dashboard_monitoring() from authenticated;
grant execute on function public.dashboard_monitoring() to anon, service_role;

grant select (run_type, status, started_at, finished_at)
on public.pipeline_runs
to anon;

grant select (metric_scope, accuracy, drift_score, calculated_at)
on public.metric_snapshots
to anon;

drop policy if exists dashboard_read_pipeline_runs on public.pipeline_runs;
create policy dashboard_read_pipeline_runs
on public.pipeline_runs
for select
to anon
using (true);

drop policy if exists dashboard_read_personal_metrics on public.metric_snapshots;
create policy dashboard_read_personal_metrics
on public.metric_snapshots
for select
to anon
using (metric_scope = 'competition_personal');
