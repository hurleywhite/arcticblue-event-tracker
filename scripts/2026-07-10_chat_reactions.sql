-- Chat message reactions (👍 👎 ❤️ …) for the event Discussion threads.
-- Stored as a small jsonb on each event_chat row, e.g. {"👍": ["Thor"], "👎": ["Jerome"]}.
--
-- Two parts, both idempotent — safe to run (or re-run) in the Supabase SQL
-- editor for project efkvhlmfdwlobvdmvqiq:
--   1. the `reactions` column, and
--   2. an UPDATE policy on event_chat. The original event_chat migration left
--      UPDATE unavailable ("there's no edit-message UI"), so a reaction write
--      (which is an UPDATE) was silently blocked by RLS — the reaction appeared
--      to do nothing. This opens UPDATE under the same open trust model as
--      insert/delete (light sanity checks on author/body).

alter table public.event_chat
  add column if not exists reactions jsonb not null default '{}'::jsonb;

-- Allow updates (reactions) — open, matching the rest of the chat table.
drop policy if exists event_chat_update on public.event_chat;
create policy event_chat_update on public.event_chat for update
  using (true)
  with check (
    length(trim(author)) > 0 and length(author) <= 100 and
    length(trim(body))   > 0 and length(body)   <= 2000
  );

-- Sanity: should now list select / insert / update / delete policies.
select policyname, cmd from pg_policies where tablename = 'event_chat' order by cmd;
