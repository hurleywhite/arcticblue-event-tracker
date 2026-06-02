-- ════════════════════════════════════════════════════════════════════
-- ArcticBlue Event Tracker — Multi-tag pipeline status (status_tags)
--
-- WHY (read before running):
--   Until now each event carried ONE status (event_state.status /
--   manual_events.status) drawn from a big grouped vocabulary. We are
--   simplifying that into a small, fixed 5-stage pipeline that an event can
--   hold SEVERAL of at once — e.g. an event can be both "Submitted" AND
--   "Meeting held" AND "Booked" simultaneously:
--
--       Identified → Submitted → Meeting held → Booked → Declined
--
--   This migration adds a `status_tags text[]` array to both tables and
--   seeds it (best-effort) from the existing single `status`. The old
--   `status` column is KEPT (not dropped) so nothing Angela typed is lost —
--   the app now treats status_tags as the primary pipeline and still lets
--   her record the granular legacy status as an optional detail.
--
-- Idempotent: ADDs use IF NOT EXISTS; the backfill only fills rows whose
--   status_tags is still empty ('{}'), so re-running never clobbers tags a
--   human has since edited. Safe to re-run.
--
-- Run in the Supabase SQL editor for project efkvhlmfdwlobvdmvqiq
-- ("AB Event Tracker [Hurley's Org]").
-- ════════════════════════════════════════════════════════════════════

-- ── 1 · Add the array column to both tables ─────────────────────────
alter table public.event_state
  add column if not exists status_tags text[] not null default '{}';

alter table public.manual_events
  add column if not exists status_tags text[] not null default '{}';

-- ── 2 · Best-effort backfill from the legacy single `status` ────────
-- One stage per legacy value, by priority (first match wins). This is just
-- a sensible starting point — the app's multi-select lets a human add more
-- stages afterward. Only touches rows whose status_tags is still empty.
--
-- A short SQL helper expression, inlined per table so we don't need to
-- create a function (keeps this migration self-contained / re-runnable).

update public.event_state
set status_tags =
  case
    when status ~* 'book|self submitted|attending|confirmed'                                   then array['Booked']
    when status ~* 'not accept|declin|\mskip\M|passing|we.ll pass|no opening|date conflict|sponsorship only|don.?t call'
                                                                                                then array['Declined']
    when status ~* 'intro meeting|received intro|in contact|cc.?d on mtg|\mmeeting\M'           then array['Meeting held']
    when status ~* 'submit|application|finish submission'                                       then array['Submitted']
    when status is not null and length(btrim(status)) > 0                                       then array['Identified']
    else '{}'::text[]
  end
where status_tags = '{}'::text[];

update public.manual_events
set status_tags =
  case
    when status ~* 'book|self submitted|attending|confirmed'                                   then array['Booked']
    when status ~* 'not accept|declin|\mskip\M|passing|we.ll pass|no opening|date conflict|sponsorship only|don.?t call'
                                                                                                then array['Declined']
    when status ~* 'intro meeting|received intro|in contact|cc.?d on mtg|\mmeeting\M'           then array['Meeting held']
    when status ~* 'submit|application|finish submission'                                       then array['Submitted']
    when status is not null and length(btrim(status)) > 0                                       then array['Identified']
    else '{}'::text[]
  end
where status_tags = '{}'::text[];

-- ── 3 · Sanity report ──────────────────────────────────────────────
-- (a) Confirm the columns exist on both tables.
select table_name, column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and column_name  = 'status_tags'
  and table_name in ('event_state', 'manual_events')
order by table_name;
-- Expected: 2 rows, data_type = 'ARRAY'.

-- (b) Distribution of seeded stages across both tables.
select 'event_state'  as tbl, unnest(status_tags) as stage, count(*)
from public.event_state  where cardinality(status_tags) > 0 group by 2
union all
select 'manual_events' as tbl, unnest(status_tags) as stage, count(*)
from public.manual_events where cardinality(status_tags) > 0 group by 2
order by tbl, stage;
