-- ====================================================================
-- ArcticBlue Event Tracker -- Multi-tag pipeline status (status_tags)
--                            + manual_events missing-column repair
--
-- WHY (read before running):
--   1) Pipeline stages. Each event used to carry ONE status. We now want a
--      small fixed 5-stage pipeline an event can hold SEVERAL of at once:
--          Identified -> Submitted -> Meeting held -> Booked -> Declined
--      Stored as a status_tags text[] array on BOTH tables. The old single
--      `status` is KEPT as an optional detail and as a read-side fallback.
--
--   2) manual_events repair. The For-Angela "edit manual event" form writes
--      several columns that were never actually added to the manual_events
--      table (status, speaker, submission_status, poc_name/email/linkedin,
--      additional_contacts, notes, speaking_fee, paid). Saving an edited
--      manual event therefore failed with "column ... does not exist". This
--      migration adds them (all nullable) so manual editing works end to end.
--
-- Idempotent: every ADD uses IF NOT EXISTS; the backfill only fills rows
--   whose status_tags is still empty ('{}'), so re-running never clobbers
--   tags a human has since edited. Safe to re-run.
--
-- Run in the Supabase SQL editor for project efkvhlmfdwlobvdmvqiq
-- ("AB Event Tracker [Hurley's Org]").
-- ====================================================================

-- -- 1 . event_state: add the pipeline array --------------------------
alter table public.event_state
  add column if not exists status_tags text[] not null default '{}';

-- -- 2 . manual_events: add the pipeline array AND every column the
--        edit form writes but that this table was missing. All nullable
--        (except status_tags, which mirrors event_state). -------------
alter table public.manual_events add column if not exists status_tags         text[] not null default '{}';
alter table public.manual_events add column if not exists status              text;
alter table public.manual_events add column if not exists submission_status   text;
alter table public.manual_events add column if not exists speaker             text;
alter table public.manual_events add column if not exists poc_name            text;
alter table public.manual_events add column if not exists poc_email           text;
alter table public.manual_events add column if not exists poc_linkedin        text;
alter table public.manual_events add column if not exists additional_contacts text;
alter table public.manual_events add column if not exists notes               text;
alter table public.manual_events add column if not exists speaking_fee        text;
alter table public.manual_events add column if not exists paid                boolean;

-- -- 3 . Best-effort backfill of status_tags from the legacy single
--        `status`. One stage per legacy value, by priority (first match
--        wins). Only touches rows whose status_tags is still empty.
--        event_state.status has real data; manual_events.status is brand
--        new (all null) so its backfill is a harmless no-op today. The
--        CASE mirrors legacyToStages() in the app exactly. ------------
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

-- -- 4 . Sanity reports -----------------------------------------------
-- (a) Confirm status_tags exists on both tables (expect 2 rows, ARRAY).
select table_name, column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and column_name  = 'status_tags'
  and table_name in ('event_state', 'manual_events')
order by table_name;

-- (b) Confirm the repaired manual_events columns now exist (expect 11 rows).
select column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name   = 'manual_events'
  and column_name in (
    'status','status_tags','submission_status','speaker','poc_name',
    'poc_email','poc_linkedin','additional_contacts','notes',
    'speaking_fee','paid'
  )
order by column_name;

-- (c) Distribution of seeded stages across both tables.
select 'event_state'  as tbl, unnest(status_tags) as stage, count(*)
from public.event_state  where cardinality(status_tags) > 0 group by 2
union all
select 'manual_events' as tbl, unnest(status_tags) as stage, count(*)
from public.manual_events where cardinality(status_tags) > 0 group by 2
order by tbl, stage;
