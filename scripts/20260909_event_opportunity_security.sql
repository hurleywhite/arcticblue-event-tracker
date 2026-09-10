-- Security hardening for the opportunity rebuild.
-- These tables contain internal scoring, travel, target-account and contact data.

alter table public.event_candidates enable row level security;
alter table public.event_opportunities enable row level security;
alter table public.person_event_fit enable row level security;
alter table public.travel_windows enable row level security;
alter table public.target_accounts enable row level security;
alter table public.event_people enable row level security;
alter table public.event_contacts enable row level security;
alter table public.event_postmortems enable row level security;

-- The opportunity dashboard is served through a same-origin serverless endpoint
-- using the service role. Do not expose these tables directly to anon/auth users.
revoke all on table public.event_candidates from anon, authenticated;
revoke all on table public.event_opportunities from anon, authenticated;
revoke all on table public.person_event_fit from anon, authenticated;
revoke all on table public.travel_windows from anon, authenticated;
revoke all on table public.target_accounts from anon, authenticated;
revoke all on table public.event_people from anon, authenticated;
revoke all on table public.event_contacts from anon, authenticated;
revoke all on table public.event_postmortems from anon, authenticated;

grant all on table public.event_candidates to service_role;
grant all on table public.event_opportunities to service_role;
grant all on table public.person_event_fit to service_role;
grant all on table public.travel_windows to service_role;
grant all on table public.target_accounts to service_role;
grant all on table public.event_people to service_role;
grant all on table public.event_contacts to service_role;
grant all on table public.event_postmortems to service_role;

grant usage, select on all sequences in schema public to service_role;

revoke execute on function public.touch_event_opportunity_updated_at() from public, anon, authenticated;
grant execute on function public.touch_event_opportunity_updated_at() to service_role;
