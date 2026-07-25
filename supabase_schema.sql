-- Run this once in the Supabase project's SQL editor (Project -> SQL Editor -> New query).
-- Stores one row per guess submitted, used to compute the global "% of players who got it right"
-- shown on the answer reveal. Streaks are tracked client-side (localStorage), not here.

create table if not exists public.answers (
  id bigint generated always as identity primary key,
  question_id text not null,
  is_correct boolean not null,
  created_at timestamptz not null default now()
);

create index if not exists answers_question_id_idx on public.answers (question_id);

alter table public.answers enable row level security;

-- Anonymous visitors may record a guess...
create policy "anon can insert answers"
  on public.answers
  for insert
  to anon
  with check (true);

-- ...and may read aggregate results (no personal data is stored, so open read is fine).
create policy "anon can read answers"
  on public.answers
  for select
  to anon
  using (true);
