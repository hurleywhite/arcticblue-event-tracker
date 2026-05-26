-- ════════════════════════════════════════════════════════════════════
-- ArcticBlue Event Tracker — Hard-enforce no duplicate manual events
--
-- Run AFTER the ingest SQL (2026-05-26_ingest_angela_events.sql).
-- Three steps:
--   1. Collapse any existing duplicates (keep the row with the lowest id,
--      because that's typically the first one inserted — but merge in any
--      richer ops fields from the newer rows before deleting them).
--   2. Add a unique index on lower(name) so future duplicates are
--      rejected at the database level (Postgres error 23505).
--   3. Quick sanity report.
--
-- Safe to re-run.
-- ════════════════════════════════════════════════════════════════════

-- ── 1. Merge richer fields from the newer duplicates into the keeper ──
-- For each duplicate group (same lower(name)), the lowest-id row is the
-- keeper. Pull non-null values from any duplicate into the keeper so we
-- don't lose data on the delete below.
update public.manual_events keeper
set
  status              = coalesce(keeper.status,              dupes.status),
  submission_status   = coalesce(keeper.submission_status,   dupes.submission_status),
  speaker             = coalesce(keeper.speaker,             dupes.speaker),
  notes               = coalesce(keeper.notes,               dupes.notes),
  poc_name            = coalesce(keeper.poc_name,            dupes.poc_name),
  poc_email           = coalesce(keeper.poc_email,           dupes.poc_email),
  poc_linkedin        = coalesce(keeper.poc_linkedin,        dupes.poc_linkedin),
  additional_contacts = coalesce(keeper.additional_contacts, dupes.additional_contacts),
  speaking_fee        = coalesce(keeper.speaking_fee,        dupes.speaking_fee),
  paid                = coalesce(keeper.paid,                dupes.paid),
  start_date          = coalesce(keeper.start_date,          dupes.start_date),
  end_date            = coalesce(keeper.end_date,            dupes.end_date),
  location            = coalesce(keeper.location,            dupes.location),
  region              = coalesce(keeper.region,              dupes.region),
  url                 = coalesce(keeper.url,                 dupes.url),
  why                 = coalesce(keeper.why,                 dupes.why)
from (
  select
    lower(name)             as name_lower,
    min(id)                 as keeper_id,
    -- aggregate first-non-null from the newer duplicates per column
    (array_agg(status              order by id desc) filter (where status              is not null))[1] as status,
    (array_agg(submission_status   order by id desc) filter (where submission_status   is not null))[1] as submission_status,
    (array_agg(speaker             order by id desc) filter (where speaker             is not null))[1] as speaker,
    (array_agg(notes               order by id desc) filter (where notes               is not null))[1] as notes,
    (array_agg(poc_name            order by id desc) filter (where poc_name            is not null))[1] as poc_name,
    (array_agg(poc_email           order by id desc) filter (where poc_email           is not null))[1] as poc_email,
    (array_agg(poc_linkedin        order by id desc) filter (where poc_linkedin        is not null))[1] as poc_linkedin,
    (array_agg(additional_contacts order by id desc) filter (where additional_contacts is not null))[1] as additional_contacts,
    (array_agg(speaking_fee        order by id desc) filter (where speaking_fee        is not null))[1] as speaking_fee,
    (array_agg(paid                order by id desc) filter (where paid                is not null))[1] as paid,
    (array_agg(start_date          order by id desc) filter (where start_date          is not null))[1] as start_date,
    (array_agg(end_date            order by id desc) filter (where end_date            is not null))[1] as end_date,
    (array_agg(location            order by id desc) filter (where location            is not null))[1] as location,
    (array_agg(region              order by id desc) filter (where region              is not null))[1] as region,
    (array_agg(url                 order by id desc) filter (where url                 is not null))[1] as url,
    (array_agg(why                 order by id desc) filter (where why                 is not null))[1] as why
  from public.manual_events
  group by lower(name)
  having count(*) > 1
) dupes
where keeper.id = dupes.keeper_id;

-- ── 2. Delete the duplicates (everything except the lowest-id row per name) ──
delete from public.manual_events m
where m.id > (
  select min(m2.id) from public.manual_events m2
  where lower(m2.name) = lower(m.name)
);

-- ── 3. Unique index on lower(name) — rejects future duplicates ──
create unique index if not exists manual_events_name_lower_uniq
  on public.manual_events (lower(name));

-- ── 4. Sanity report ──
select count(*)                              as total_rows,
       count(distinct lower(name))           as unique_names,
       (count(*) - count(distinct lower(name))) as residual_dups
from public.manual_events;
