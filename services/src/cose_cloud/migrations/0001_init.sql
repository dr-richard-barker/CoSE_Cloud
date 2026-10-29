-- CoSE Cloud schema v1. Plain Postgres (no extensions beyond citext), so it runs on a CoSE HQ server and on
-- Amazon RDS alike. Org isolation is enforced by the API on every query (the org comes from the session, never
-- from the client or the agent); docs/DATA_MODEL.md describes each table.

create extension if not exists citext;

-- ------------------------------------------------------------------ accounts (ported from the draft's Supabase
-- profiles/moderation tables; login and permissions are API code here instead of Supabase auth + RLS)
create table orgs (
  id          bigserial primary key,
  slug        text not null unique check (slug ~ '^[a-z0-9][a-z0-9-]{1,39}$'),
  name        text not null,
  created_at  timestamptz not null default now()
);

create table users (
  id             bigserial primary key,
  email          citext not null unique,
  display_name   text,
  password_hash  text,                       -- argon2id; null = cannot sign in with a password
  banned         boolean not null default false,
  created_at     timestamptz not null default now()
);

create table platform_admins (user_id bigint primary key references users(id) on delete cascade);

create table memberships (
  org_id   bigint not null references orgs(id) on delete cascade,
  user_id  bigint not null references users(id) on delete cascade,
  role     text not null check (role in ('viewer', 'analyst', 'admin')),
  primary key (org_id, user_id)
);

create table identities (                   -- external sign-in (Google etc.), M2
  provider  text not null,
  subject   text not null,
  user_id   bigint not null references users(id) on delete cascade,
  primary key (provider, subject)
);

create table sessions (
  token_sha256  text primary key,            -- the cookie holds the token; only its hash is stored
  user_id       bigint not null references users(id) on delete cascade,
  org_id        bigint not null references orgs(id) on delete cascade,
  created_at    timestamptz not null default now(),
  expires_at    timestamptz not null
);
create index sessions_expires on sessions (expires_at);

create table hidden_content (                -- moderation: hide a catalog source/item or a device from an org's views
  id         bigserial primary key,
  org_id     bigint not null references orgs(id) on delete cascade,
  kind       text not null check (kind in ('catalog_source', 'catalog_item', 'device')),
  ref        text not null,
  reason     text,
  hidden_by  bigint references users(id),
  created_at timestamptz not null default now(),
  unique (org_id, kind, ref)
);

-- Plan flags only. Prices are not decided and do not live in code or data (Market_Research software_suite.md).
create table entitlements (
  org_id               bigint primary key references orgs(id) on delete cascade,
  tier                 text not null default 'free' check (tier in ('free', 'pro', 'institutional')),
  features             jsonb not null default '{}'::jsonb,
  llm_mode             text not null default 'off' check (llm_mode in ('hosted', 'local', 'off')),
  llm_monthly_cap_usd  numeric(10, 2),        -- hosted spend cap; null with llm_mode hosted = no hosted calls
  updated_at           timestamptz not null default now()
);

create table platform_settings (key text primary key, value jsonb not null);

-- ------------------------------------------------------------------ registry (DATA_INTEGRATION_SPEC.md §3.6)
create table sites (
  id        bigserial primary key,
  org_id    bigint not null references orgs(id) on delete cascade,
  name      text not null,
  kind      text not null default 'lab' check (kind in ('lab', 'container', 'station', 'field', 'hq')),
  timezone  text not null default 'America/Chicago',
  unique (org_id, name)
);

create table devices (
  device_uuid       text primary key check (device_uuid ~ '^[A-Za-z0-9._-]{1,64}$'),
  org_id            bigint not null references orgs(id) on delete restrict,
  site_id           bigint references sites(id),
  product           text not null,
  variant           text,
  label             text,
  data_origin       text not null check (data_origin in ('hardware', 'simulator', 'replay')),
  sim_meta          jsonb,                  -- simulator: scenario, seed, epoch, Care-Agent version
  fitted_sensors    text[],
  x509_fingerprint  text,
  calibration_ids   text[],
  first_seen        timestamptz,
  last_seen         timestamptz,
  created_at        timestamptz not null default now()
);
create index devices_org on devices (org_id);

create table experiments (
  id           text primary key check (id ~ '^[A-Za-z0-9._-]{1,80}$'),
  org_id       bigint not null references orgs(id) on delete cascade,
  product      text not null,
  device_uuid  text references devices(device_uuid),
  title        text not null,
  crop         text,
  started_at   timestamptz not null,
  ended_at     timestamptz,
  data_origin  text not null check (data_origin in ('hardware', 'simulator', 'replay')),
  protocol     jsonb not null default '{}'::jsonb,
  miappe       jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);
create index experiments_device on experiments (device_uuid, started_at);

-- ------------------------------------------------------------------ device data
create table messages (
  id                 bigserial primary key,
  device_uuid        text not null references devices(device_uuid),
  leaf               text not null,
  ts                 timestamptz not null,
  received_at        timestamptz not null,
  seq                bigint,
  shape              text not null check (shape in ('envelope', 'xseed_fw', 'xseed_contract', 'raw')),
  schema_uri         text,
  provenance         text not null check (provenance in ('measured', 'simulated', 'replay')),
  experiment_id      text,
  payload_device_id  text,
  mode               text,
  ingest_path        text not null check (ingest_path in ('live', 'backfill', 'replay')),
  body               jsonb not null,
  sha256             text not null,
  unique (device_uuid, leaf, sha256)          -- a QoS 1 redelivery is the same bytes: stored once
);
create index messages_ts_brin on messages using brin (ts);
create index messages_device_ts on messages (device_uuid, leaf, ts);

create table metrics (
  product       text not null,
  key           text not null,
  label         text not null,
  unit          text not null,
  kind          text not null check (kind in ('gauge', 'state', 'flag')),
  null_meaning  text not null check (null_meaning in ('read_failed', 'not_valid')),
  primary key (product, key)
);

create table readings (
  device_uuid  text not null references devices(device_uuid),
  metric       text not null,
  ts           timestamptz not null,
  value        double precision,
  quality      text not null check (quality in ('ok', 'read_failed', 'not_valid')),
  provenance   text not null check (provenance in ('measured', 'simulated', 'replay')),
  message_id   bigint not null references messages(id),
  primary key (device_uuid, metric, ts),
  check ((quality = 'ok') = (value is not null))
);
create index readings_ts_brin on readings using brin (ts);

-- A reading's provenance must match its device's registered origin: a simulator can only ever produce
-- simulated readings, whatever reaches the database.
create function check_provenance() returns trigger language plpgsql as $$
declare origin text;
begin
  select data_origin into origin from devices where device_uuid = new.device_uuid;
  if new.provenance is distinct from (case origin when 'hardware' then 'measured'
                                                  when 'simulator' then 'simulated'
                                                  when 'replay' then 'replay' end) then
    raise exception 'provenance % does not match device % (data_origin %)', new.provenance, new.device_uuid, origin;
  end if;
  return new;
end $$;
create trigger readings_provenance before insert or update on readings
  for each row execute function check_provenance();
create trigger messages_provenance before insert or update on messages
  for each row execute function check_provenance();

create table ingest_rejects (
  id               bigserial primary key,
  received_at      timestamptz not null default now(),
  topic            text not null,
  reason           text not null,
  detail           text,
  payload_bytes    integer not null,
  payload_excerpt  text
);

-- ------------------------------------------------------------------ past experiments (metadata and links only)
create table catalog_sources (
  id             bigserial primary key,
  org_id         bigint not null references orgs(id) on delete cascade,
  kind           text not null check (kind in ('ec5', 'github', 'cyverse', 'youtube', 'osdr')),
  slug           text not null,
  title          text not null,
  url            text,
  licence        text,
  provenance     jsonb not null default '{}'::jsonb,
  last_harvest   timestamptz,
  last_error     text,
  item_count     integer not null default 0,
  unique (org_id, kind, slug)
);

create table catalog_items (
  id           bigserial primary key,
  source_id    bigint not null references catalog_sources(id) on delete cascade,
  external_id  text not null,
  title        text not null,
  species      text,
  captured_at  timestamptz,
  uploaded_at  timestamptz,
  fields       jsonb not null default '[]'::jsonb,
  media_url    text,
  thumb_url    text,
  media_kind   text check (media_kind in ('image', 'video', 'none')),
  lat          double precision,
  lon          double precision,
  unique (source_id, external_id)
);
create index catalog_items_species on catalog_items (lower(species));

-- ------------------------------------------------------------------ CoSE_Agent
create table conversations (
  id          uuid primary key,
  org_id      bigint not null references orgs(id) on delete cascade,
  user_id     bigint not null references users(id) on delete cascade,
  edition     text not null,
  title       text,
  created_at  timestamptz not null default now()
);

-- What was sent to and returned by the model, append-only, in the provider's own content format.
create table conversation_messages (
  id               bigserial primary key,
  conversation_id  uuid not null references conversations(id) on delete cascade,
  role             text not null check (role in ('user', 'assistant')),
  provider         text not null,
  content          jsonb not null,
  created_at       timestamptz not null default now()
);
create index conversation_messages_conv on conversation_messages (conversation_id, id);

-- What the user saw: one row per question.
create table conversation_turns (
  id               bigserial primary key,
  conversation_id  uuid not null references conversations(id) on delete cascade,
  question         text not null,
  reply            jsonb not null,
  created_at       timestamptz not null default now()
);

create table datasets (
  id               uuid primary key,
  org_id           bigint not null references orgs(id) on delete cascade,
  conversation_id  uuid references conversations(id) on delete set null,
  query            jsonb not null,
  provenance       text[] not null,
  rows             jsonb not null,
  created_at       timestamptz not null default now()
);

create table chart_artifacts (
  id               uuid primary key,
  org_id           bigint not null references orgs(id) on delete cascade,
  conversation_id  uuid references conversations(id) on delete set null,
  spec             jsonb not null,
  provenance       text[] not null,
  created_at       timestamptz not null default now()
);

-- Every model call, reserved before it is made (worst case) and settled after (actual). A crashed call leaves
-- its reservation in place, which errs on the side of spending less.
create table usage_ledger (
  id                  bigserial primary key,
  org_id              bigint not null references orgs(id) on delete cascade,
  user_id             bigint references users(id) on delete set null,
  conversation_id     uuid references conversations(id) on delete set null,
  provider            text not null,
  requested_model     text not null,
  served_model        text,
  input_tokens        integer not null default 0,
  output_tokens       integer not null default 0,
  cache_write_tokens  integer not null default 0,
  cache_read_tokens   integer not null default 0,
  cost_usd            numeric(12, 6) not null,
  pricing_src         text not null,
  kind                text not null check (kind in ('reserve', 'actual')),
  created_at          timestamptz not null default now()
);
create index usage_ledger_org_month on usage_ledger (org_id, created_at);
