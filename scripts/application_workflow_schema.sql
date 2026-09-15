-- Private data is available only through the approved-editor server API.
create table if not exists public.event_integrations (
  key text primary key,
  config jsonb not null default '{}'::jsonb check (jsonb_typeof(config)='object'),
  updated_by text not null,
  updated_at timestamptz not null default now()
);
alter table public.event_integrations enable row level security;
revoke all on public.event_integrations from public, anon, authenticated;
grant all on public.event_integrations to service_role;

create table if not exists public.event_application_workspaces (
  event_key text primary key,
  source_table text not null check (source_table in ('manual_events','event_state')),
  source_key text not null,
  document jsonb not null default '{}'::jsonb check (jsonb_typeof(document)='object'),
  version integer not null default 1 check (version>0),
  updated_by text not null,
  updated_at timestamptz not null default now(),
  check (event_key=source_table||':'||source_key)
);
alter table public.event_application_workspaces enable row level security;
revoke all on public.event_application_workspaces from public, anon, authenticated;
grant all on public.event_application_workspaces to service_role;
comment on table public.event_integrations is 'Server-only credentials. Never return config to the browser.';
comment on table public.event_application_workspaces is 'Private event contacts and reviewed email drafts. No automatic sending.';
