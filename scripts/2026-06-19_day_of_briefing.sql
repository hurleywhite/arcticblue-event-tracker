-- Day-Of Briefing feature — storage for "who's attending" + the cached brief.
--
-- attendees: persona keys (carlos|thor|verma|jerome|joe) actually GOING to the
--   event. Distinct from `interested`/Fits (suitability) — this is the trigger
--   that surfaces the Day-Of brief. Lives on both event tables. (An assigned
--   `speaker` who matches a persona also counts as attending — see briefing.)
-- speaker_topic: the talk/topic the ArcticBlue person is bringing. Drives a
--   targeted "recent news on this topic (last ~3 days)" pull in the brief.
-- briefing_json / briefing_generated_at: the cached, pre-generated brief so the
--   morning-of open is instant; regenerated on demand or when stale (>24h).
--
-- Safe + additive — run once in the Supabase SQL editor. Until it runs the
-- briefing route + UI degrade gracefully (no attendees -> no rail; writes that
-- target a missing column are stripped and warned, never error).
alter table public.event_state   add column if not exists attendees text[] default '{}';
alter table public.event_state   add column if not exists speaker_topic text;
alter table public.event_state   add column if not exists briefing_json jsonb;
alter table public.event_state   add column if not exists briefing_generated_at timestamptz;

alter table public.manual_events  add column if not exists attendees text[] default '{}';
alter table public.manual_events  add column if not exists speaker_topic text;
alter table public.manual_events  add column if not exists briefing_json jsonb;
alter table public.manual_events  add column if not exists briefing_generated_at timestamptz;
