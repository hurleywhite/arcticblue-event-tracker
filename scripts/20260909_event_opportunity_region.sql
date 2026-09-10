-- Preserve legacy region so calendar trip-stacking can compare nearby hubs.
alter table public.event_opportunities add column if not exists region text;

update public.event_opportunities o
set region = coalesce(o.region, m.region)
from public.manual_events m
where o.source_table = 'manual_events'
  and o.source_key = m.id::text
  and o.region is null;
