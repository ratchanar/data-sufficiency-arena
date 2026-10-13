-- Run this SQL in Supabase: SQL Editor -> New query -> Run
create table if not exists public.submissions (
  id text primary key,
  room text not null,
  player text not null,
  score integer not null,
  total integer not null,
  attempted integer not null,
  elapsed_seconds integer not null,
  submitted_at timestamptz not null default now(),
  answers_json text
);

create index if not exists submissions_room_idx on public.submissions(room);

-- Classroom leaderboard uses the Supabase anon key from the Streamlit app.
-- Enable Row Level Security and use these simple classroom policies for a low-risk
-- score-only demo. Students can read results and submit/update score records.
alter table public.submissions enable row level security;

create policy "Allow classroom leaderboard reads"
on public.submissions for select
to anon, authenticated
using (true);

create policy "Allow classroom score submissions"
on public.submissions for insert
to anon, authenticated
with check (true);

create policy "Allow classroom score updates"
on public.submissions for update
to anon, authenticated
using (true)
with check (true);


-- Ensure the app's publishable/anon key can perform only the operations it needs.
grant select, insert, update on public.submissions to anon, authenticated;
