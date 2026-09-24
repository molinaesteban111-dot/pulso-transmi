-- pg_net is non-relocatable. Re-create it outside `public` as recommended by
-- the Supabase Security Advisor. Run only when net.http_request_queue is empty.

create schema if not exists extensions;
drop extension pg_net;
create extension pg_net with schema extensions;
