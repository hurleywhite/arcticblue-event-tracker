-- Extend the original tracker records; do not copy or renumber events.
alter table public.event_state add column if not exists booking jsonb not null default '{}'::jsonb;
alter table public.manual_events add column if not exists booking jsonb not null default '{}'::jsonb;
alter table public.event_state add constraint event_state_booking_object check (jsonb_typeof(booking) = 'object');
alter table public.manual_events add constraint manual_events_booking_object check (jsonb_typeof(booking) = 'object');
alter table public.target_accounts add column if not exists city text;
alter table public.target_accounts add column if not exists executive_roles text;
-- Existing RLS and grants are preserved. Target accounts and travel remain
-- service-only behind the existing approved-editor API; no public policies.
comment on column public.event_state.booking is 'Booking decision, public evidence and recorded outcomes for the original catalog event. No private attendee lists.';
comment on column public.manual_events.booking is 'Booking decision, public evidence and recorded outcomes for the original manual event. No private attendee lists.';
