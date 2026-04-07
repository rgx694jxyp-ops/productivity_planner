-- Stripe webhook idempotency table
-- Ensures each Stripe event_id is processed at most once.

create table if not exists public.stripe_webhook_events (
  event_id text primary key,
  event_type text not null,
  received_at timestamptz not null default now()
);

alter table public.stripe_webhook_events
  add column if not exists received_at timestamptz;

alter table public.stripe_webhook_events
  alter column received_at set default now();

update public.stripe_webhook_events
set received_at = now()
where received_at is null;

alter table public.stripe_webhook_events
  alter column received_at set not null;

create index if not exists idx_stripe_webhook_events_received_at
  on public.stripe_webhook_events (received_at desc);
