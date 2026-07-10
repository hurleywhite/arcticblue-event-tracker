-- Chat message reactions (👍 / 👎) for the event Discussion threads.
-- Stored as a small jsonb on each event_chat row: {"up": ["Thor"], "down": ["Jerome"]}.
-- The client degrades gracefully until this runs (thumbs buttons show, but a
-- click reports "reactions need a one-time migration" instead of saving).
--
-- Run once in the Supabase SQL editor.

alter table public.event_chat
  add column if not exists reactions jsonb not null default '{}'::jsonb;
