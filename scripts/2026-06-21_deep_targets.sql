-- Deep outreach targets cache for api/briefing.py (deep_targets mode).
-- The "Find outreach targets" button generates named, budget-owning decision-
-- makers + a drafted opener per person. This stores the result so opening the
-- panel again doesn't regenerate (and re-spend) until you click Regenerate.
--
-- Safe to run more than once.
--
-- CORRECTION (2026-09-10): the line that used to sit here said generation
-- "still works on demand" and undersold this badly. api/briefing.py::_cron
-- SELECTS targets_json, so while the column is missing that query 400s and the
-- WHOLE nightly cron does nothing -- no Day-Of briefing, no target pre-cache --
-- while still reporting a clean run. On demand it does still work, but the
-- cache write no-ops, so every panel open re-spends OpenAI/Exa credit.
-- Superseded by scripts/2026-09-10_deep_targets.sql (same columns, full note).

alter table public.event_state   add column if not exists targets_json          jsonb;
alter table public.event_state   add column if not exists targets_generated_at  timestamptz;

alter table public.manual_events add column if not exists targets_json          jsonb;
alter table public.manual_events add column if not exists targets_generated_at  timestamptz;
