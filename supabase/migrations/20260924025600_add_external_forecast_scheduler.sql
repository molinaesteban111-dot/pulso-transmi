-- Reliable five-minute dispatcher for the forecast workflow.
-- The GitHub fine-grained token must exist in Vault as
-- `github_actions_token`; its value is never stored in this migration.

create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists pg_net;

grant usage on schema cron to postgres;
grant all privileges on all tables in schema cron to postgres;

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create or replace function private.dispatch_forecast_workflow()
returns bigint
language plpgsql
security definer
set search_path = ''
as $function$
declare
  github_token text;
  request_id bigint;
begin
  select decrypted_secret
    into github_token
    from vault.decrypted_secrets
   where name = 'github_actions_token'
   order by created_at desc
   limit 1;

  if github_token is null or github_token = '' then
    raise exception 'Vault secret github_actions_token is missing';
  end if;

  select net.http_post(
    url := 'https://api.github.com/repos/molinaesteban111-dot/pulso-transmi/actions/workflows/forecast-submission.yml/dispatches',
    body := jsonb_build_object(
      'ref', 'main',
      'inputs', jsonb_build_object(
        'action', 'forecast',
        'leaderboard_window', 'cumulative'
      )
    ),
    headers := jsonb_build_object(
      'Accept', 'application/vnd.github+json',
      'Authorization', 'Bearer ' || github_token,
      'X-GitHub-Api-Version', '2026-03-10',
      'Content-Type', 'application/json',
      'User-Agent', 'pulso-transmi-supabase-cron'
    ),
    timeout_milliseconds := 10000
  ) into request_id;

  return request_id;
end;
$function$;

revoke all on function private.dispatch_forecast_workflow()
  from public, anon, authenticated;
grant execute on function private.dispatch_forecast_workflow()
  to postgres, service_role;

do $block$
declare
  old_job_id bigint;
begin
  select jobid
    into old_job_id
    from cron.job
   where jobname = 'dispatch-pulso-transmi-forecast'
   limit 1;

  if old_job_id is not null then
    perform cron.unschedule(old_job_id);
  end if;

  perform cron.schedule(
    'dispatch-pulso-transmi-forecast',
    '1-59/5 * * * *',
    $cron$select private.dispatch_forecast_workflow();$cron$
  );
end;
$block$;
