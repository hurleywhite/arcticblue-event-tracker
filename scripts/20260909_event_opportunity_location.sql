-- Preserve free-text location from legacy tracker rows so geography can be
-- classified even when city/country were never normalized.
alter table public.event_opportunities add column if not exists location text;

update public.event_opportunities o
set location = m.location,
    city = coalesce(o.city, m.city),
    country = coalesce(o.country, m.country)
from public.manual_events m
where o.source_table = 'manual_events'
  and o.source_key = m.id::text
  and o.location is null;
