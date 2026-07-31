-- ====================================================================
-- ArcticBlue Event Tracker — manual organiser grouping
--
-- WHY: "Also from this organiser" groups events by the registrable domain of
-- their URL (terrapinn.com, web-summit.com …). That catches most families, but
-- not all of them:
--
--   * an organiser running several brands on different domains
--     (Millennium Alliance assemblies, the AIAI summit series)
--   * an event whose page lives on a venue or ticketing domain
--   * an event we know about but have not added yet, so it cannot be grouped
--     with anything
--
-- This column lets Angela say "these belong together" by hand. The domain rule
-- keeps working exactly as before; org_group is an ADDITIONAL way in, never a
-- replacement — an event is a sibling if it shares the domain OR the group.
--
--   org_group  text   a shared key, e.g. 'millennium-alliance'
--
-- The key is derived from the anchor event: its domain if it has one, else a
-- slug of its name. Both events get the value written, so the link is explicit
-- on each side and survives either one being edited.
--
-- Deliberately NOT added:
--
--   a join table. A single shared key is enough for "these are the same
--   organiser" and keeps the sibling lookup a filter rather than a join. An
--   event belongs to exactly one organiser family, so there is no many-to-many
--   to model.
--
-- Idempotent — safe to run more than once. Run in the Supabase SQL editor for
-- project efkvhlmfdwlobvdmvqiq. Until it runs, "Also from this organiser"
-- behaves exactly as it does today (domain grouping only); the linking
-- controls report the app's standard migration-pending warning and change
-- nothing else.
-- ====================================================================

alter table public.event_state   add column if not exists org_group text;
alter table public.manual_events add column if not exists org_group text;

-- Sibling lookup filters on this, so index it.
create index if not exists event_state_org_group_idx   on public.event_state   (org_group);
create index if not exists manual_events_org_group_idx on public.manual_events (org_group);

-- Sanity: confirm the column exists on both tables.
select table_name, column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and table_name in ('event_state', 'manual_events')
  and column_name = 'org_group'
order by table_name;
