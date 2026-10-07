-- Jace Social: voice calls. Run once in Supabase -> SQL Editor (after schema.sql).
-- Call setup messages (WebRTC offers/answers) between friends. The audio itself
-- goes directly between players (or through Cloudflare's TURN relay), never here.
create table if not exists call_signals (
  id          bigint generated always as identity primary key,
  call_id     text not null check (char_length(call_id) between 8 and 64),
  sender      text not null references profiles(uuid) on delete cascade,
  recipient   text not null references profiles(uuid) on delete cascade,
  kind        text not null check (kind in ('offer', 'answer', 'hangup')),
  sdp         text check (char_length(sdp) <= 20000),
  created_at  timestamptz not null default now()
);
create index if not exists call_signals_recipient on call_signals (recipient, id);

alter table call_signals enable row level security;
grant select, insert, delete on call_signals to service_role;
grant usage, select on all sequences in schema public to service_role;
revoke all on call_signals from anon, authenticated;
