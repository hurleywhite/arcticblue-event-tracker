-- Deep outreach targets cache for api/briefing.py (deep_targets mode).
-- The "Find outreach targets" button generates named, budget-owning decision-
-- makers + a drafted opener per person. This stores the result so opening the
-- panel again doesn't regenerate (and re-spend) until you click Regenerate.
--
-- Safe to run more than once. Until this runs, generation still works on demand
-- (the server's cache write just no-ops on the missing column).

alter table public.event_state   add column if not exists targets_json          jsonb;
alter table public.event_state   add column if not exists targets_generated_at  timestamptz;

alter table public.manual_events add column if not exists targets_json          jsonb;
alter table public.manual_events add column if not exists targets_generated_at  timestamptz;
