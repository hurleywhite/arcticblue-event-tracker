-- Give manually-added events the same Save / Urgent / Hidden toggles the
-- catalog (event_state) events already have. manual_events previously had no
-- columns to store them, so those buttons didn't render on manual cards and you
-- couldn't hide a manual event (only delete it).
--
-- Safe + additive — run once in the Supabase SQL editor. Until this runs, the
-- buttons render but a click warns instead of saving (sbWriteRetry strips the
-- unknown column rather than erroring).
alter table public.manual_events add column if not exists hidden boolean default false;
alter table public.manual_events add column if not exists saved  boolean default false;
alter table public.manual_events add column if not exists urgent boolean default false;
