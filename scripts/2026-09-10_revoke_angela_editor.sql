-- Angela has left ArcticBlue (2026-09-10). Remove her approved-editor access so
-- a magic-link to her mailbox can no longer manage target accounts or travel.
-- Run in the Supabase SQL editor for project efkvhlmfdwlobvdmvqiq (RLS blocks
-- this from the public key, so it must be run here). Idempotent.
delete from public.allowed_editors where email = 'angela@arcticblue.ai';
select email from public.allowed_editors order by email;
