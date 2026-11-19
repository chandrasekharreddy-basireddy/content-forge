-- Content Forge: the runs table, for Supabase (Postgres).
--
-- Run this once, in the Supabase SQL editor, before setting SUPABASE_URL and
-- SUPABASE_KEY in .env. The app writes one row per pipeline run.
--
-- The same columns exist in the local SQLite database (pipeline/store.py), so
-- Power BI can read either source with the same queries.

create table if not exists public.runs (
    id            text primary key,
    doc_name      text not null,
    created_at    timestamptz not null default now(),
    status        text not null,
    words         integer not null default 0,
    chunks        integer not null default 0,
    outputs_count integer not null default 0,
    avg_score     numeric(3, 2),
    cost_inr      numeric(12, 6) not null default 0,
    tokens_in     integer not null default 0,
    tokens_out    integer not null default 0,
    duration_ms   integer not null default 0,
    depth         text,
    payload       jsonb not null
);

-- The dashboard filters by date and groups by status, so index both.
create index if not exists runs_created_at_idx on public.runs (created_at desc);
create index if not exists runs_status_idx on public.runs (status);

-- Row level security: the app writes with the service key, which bypasses RLS,
-- but turning RLS on means the anon key cannot read the table by accident.
alter table public.runs enable row level security;

-- Optional: let an authenticated user read their own dashboard data.
-- Uncomment if you later add per-user accounts.
-- create policy "read runs" on public.runs
--     for select to authenticated using (true);

-- A view for the dashboard, so Power BI has one obvious table to point at.
create or replace view public.run_summary as
select
    date_trunc('day', created_at) as run_day,
    status,
    depth,
    count(*)                      as runs,
    sum(outputs_count)            as outputs,
    round(avg(avg_score), 2)      as avg_score,
    round(sum(cost_inr), 4)       as cost_inr,
    round(avg(duration_ms) / 1000.0, 1) as avg_seconds
from public.runs
group by 1, 2, 3;
