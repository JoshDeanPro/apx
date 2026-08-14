-- OpenPower initial schema.
-- Small, RLS-enforced, owner-scoped. Every table a normal user can reach
-- through Supabase's REST/client APIs is locked down with RLS; FastAPI's
-- service-role access still performs its own explicit ownership checks
-- (RLS is not a substitute for that in privileged server code paths).

create extension if not exists "pgcrypto";

-- One row per authenticated human (Supabase auth.users), created on first login.
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.profiles enable row level security;
create policy "profiles_select_own" on public.profiles for select using (id = auth.uid());
create policy "profiles_update_own" on public.profiles for update using (id = auth.uid());
create policy "profiles_insert_own" on public.profiles for insert with check (id = auth.uid());

-- Devices: self-hosted devices, Macs, PCs, servers, phones, etc.
create table public.devices (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  type text not null default 'unknown',
  profile jsonb not null default '{}',
  roles text[] not null default '{}',
  status text not null default 'disconnected',
  last_seen timestamptz,
  axp_version text,
  buddy_os_version text,
  capabilities jsonb not null default '{}',
  settings jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.devices enable row level security;
create policy "devices_owner_all" on public.devices for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());

-- Agent profiles: Claude, Codex, custom agents. Identity is generic;
-- provider/runtime is just metadata.
create table public.agent_profiles (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  provider text,
  device_id uuid references public.devices(id) on delete set null,
  status text not null default 'inactive',
  permissions jsonb not null default '{}',
  last_seen timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.agent_profiles enable row level security;
create policy "agent_profiles_owner_all" on public.agent_profiles for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());

-- OpenPower Agent Identity: the durable "agent:<provider>:<device>"-style
-- principal an AgentProfile can be given. One identity per agent.
create table public.agent_identities (
  id uuid primary key default gen_random_uuid(),
  agent_id uuid not null unique references public.agent_profiles(id) on delete cascade,
  owner_id uuid not null references auth.users(id) on delete cascade,
  identity_key text not null unique,
  status text not null default 'active' check (status in ('active', 'disabled', 'revoked')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.agent_identities enable row level security;
create policy "agent_identities_owner_all" on public.agent_identities for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());

-- Agent-requested enrollment: an agent asking for an OpenPower identity,
-- subject to the owner's enrollment policy (require approval / auto-approve / disabled).
create table public.agent_enrollment_requests (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  agent_name text not null,
  device_id uuid references public.devices(id) on delete set null,
  requested_permissions jsonb not null default '{}',
  status text not null default 'pending' check (status in ('pending', 'approved', 'denied')),
  created_at timestamptz not null default now(),
  decided_at timestamptz
);

alter table public.agent_enrollment_requests enable row level security;
create policy "agent_enrollment_owner_all" on public.agent_enrollment_requests for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());

-- Agent credential metadata only. The secret itself is never stored --
-- only a hash/fingerprint the API can verify against, plus lifecycle
-- timestamps. Written by the service role (FastAPI) after hashing;
-- readable by the owner as metadata only.
create table public.agent_credentials (
  id uuid primary key default gen_random_uuid(),
  agent_id uuid not null references public.agent_profiles(id) on delete cascade,
  owner_id uuid not null references auth.users(id) on delete cascade,
  credential_id text not null unique,
  secret_hash text not null,
  created_at timestamptz not null default now(),
  last_used_at timestamptz,
  expires_at timestamptz,
  rotated_at timestamptz,
  revoked_at timestamptz
);

alter table public.agent_credentials enable row level security;
-- Owners may see credential metadata but the hash column is never selected
-- by the web/app client; only FastAPI's service-role connection reads it,
-- for verification during agent authentication.
create policy "agent_credentials_owner_read" on public.agent_credentials for select using (owner_id = auth.uid());

-- Prompt library.
create table public.prompts (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  description text,
  content text not null default '',
  tags text[] not null default '{}',
  version integer not null default 1,
  scope text not null default 'private',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.prompts enable row level security;
create policy "prompts_owner_all" on public.prompts for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());

-- Per-user settings: background agent/AXP, wake word, agent enrollment policy.
create table public.user_settings (
  user_id uuid primary key references auth.users(id) on delete cascade,
  voice_activation boolean not null default false,
  wake_word text not null default 'Hey OpenPower',
  run_buddy_background boolean not null default false,
  run_axp_background boolean not null default false,
  start_on_boot boolean not null default false,
  agent_enrollment_mode text not null default 'require_approval'
    check (agent_enrollment_mode in ('require_approval', 'auto_approve_trusted', 'disabled')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.user_settings enable row level security;
create policy "user_settings_owner_all" on public.user_settings for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Connected services (Cloudflare, OpenAI, Supabase, MCP servers, etc).
-- Credential references only -- no secret values live here.
create table public.service_connections (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  provider text not null,
  status text not null default 'needs_setup' check (status in ('connected', 'needs_setup', 'offline', 'available')),
  config jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.service_connections enable row level security;
create policy "service_connections_owner_all" on public.service_connections for all using (owner_id = auth.uid()) with check (owner_id = auth.uid());

-- Append-only security audit log. Users may read their own events; only
-- the service role (FastAPI) inserts. Never contains credential values.
create table public.audit_events (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  actor text not null,
  event_type text not null,
  target text,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

alter table public.audit_events enable row level security;
create policy "audit_events_owner_read" on public.audit_events for select using (owner_id = auth.uid());
-- No insert/update/delete policy for the authenticated role: writes only
-- happen through the service-role connection from FastAPI.

-- Keep updated_at fresh without trusting client-supplied values.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger set_updated_at before update on public.profiles for each row execute function public.set_updated_at();
create trigger set_updated_at before update on public.devices for each row execute function public.set_updated_at();
create trigger set_updated_at before update on public.agent_profiles for each row execute function public.set_updated_at();
create trigger set_updated_at before update on public.agent_identities for each row execute function public.set_updated_at();
create trigger set_updated_at before update on public.prompts for each row execute function public.set_updated_at();
create trigger set_updated_at before update on public.user_settings for each row execute function public.set_updated_at();
create trigger set_updated_at before update on public.service_connections for each row execute function public.set_updated_at();

-- New auth.users row -> matching profile + default settings row.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id) values (new.id);
  insert into public.user_settings (user_id) values (new.id);
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
