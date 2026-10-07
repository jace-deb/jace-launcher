-- Jace Social database. Run this once in Supabase -> SQL Editor.
-- Every table has row level security ON with no policies: only the server
-- (secret key) can read or write. Players go through the API.

create table if not exists profiles (
  uuid        text primary key,              -- Minecraft UUID without dashes
  name        text not null,                 -- current Minecraft username
  inbox       text not null unique,          -- private live-notification channel
  activity    jsonb,                         -- what they're doing (launcher / playing / hosting)
  last_seen   timestamptz,                   -- null = signed out
  signed_up   timestamptz,                   -- null = added as a friend but never signed in
  created_at  timestamptz not null default now()
);

create table if not exists sessions (
  token_hash  text primary key,              -- sha256 of the bearer token
  uuid        text not null references profiles(uuid) on delete cascade,
  expires_at  timestamptz not null,
  created_at  timestamptz not null default now()
);
create index if not exists sessions_uuid on sessions(uuid);

create table if not exists auth_challenges (
  server_id   text primary key,
  created_at  timestamptz not null default now()
);

create table if not exists friendships (
  requester   text not null references profiles(uuid) on delete cascade,
  addressee   text not null references profiles(uuid) on delete cascade,
  status      text not null check (status in ('pending', 'accepted')),
  created_at  timestamptz not null default now(),
  primary key (requester, addressee),
  check (requester <> addressee)
);
-- one row per pair, whichever direction it was requested in
create unique index if not exists friendships_pair
  on friendships (least(requester, addressee), greatest(requester, addressee));
create index if not exists friendships_addressee on friendships(addressee);

create table if not exists messages (
  id          bigint generated always as identity primary key,
  sender      text not null references profiles(uuid) on delete cascade,
  recipient   text not null references profiles(uuid) on delete cascade,
  body        text not null check (char_length(body) between 1 and 500),
  created_at  timestamptz not null default now(),
  read_at     timestamptz
);
create index if not exists messages_pair on messages (least(sender, recipient), greatest(sender, recipient), id);
create index if not exists messages_unread on messages (recipient) where read_at is null;

alter table profiles        enable row level security;
alter table sessions        enable row level security;
alter table auth_challenges enable row level security;
alter table friendships     enable row level security;
alter table messages        enable row level security;

-- Access: only the server's secret key (service_role) may use these tables.
-- Works with "Automatically expose new tables" turned OFF (recommended), and
-- makes sure the public keys (anon / authenticated) can't touch anything.
grant usage on schema public to service_role;
grant select, insert, update, delete on profiles, sessions, auth_challenges, friendships, messages to service_role;
grant usage, select on all sequences in schema public to service_role;
revoke all on profiles, sessions, auth_challenges, friendships, messages from anon, authenticated;

-- Voice calls: see 002_calls.sql (also run that one).
