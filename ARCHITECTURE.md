# Runa production architecture

## Runtime

`app.py` is the only production entry point. It composes the Telegram product
runtime explicitly and starts the Starlette/Cloud Run webhook server. Runtime
behaviour must not be installed through `sitecustomize` or import-time patches.

## Request orchestration

1. Starlette accepts a Telegram update.
2. `telegram_updates` atomically claims its `update_id` across Cloud Run.
3. An in-process per-user lock preserves message order.
4. PTB refreshes `context.user_data` from `telegram_user_state` in Neon.
5. The handler completes while the Cloud Run request still owns CPU.
6. User state is persisted before the HTTP response is returned.
7. The update is marked `done` and retained for seven days.

Cloud Run is intentionally limited to one instance while per-user ordering uses
an in-process lock. If the service is later scaled horizontally, replace that
lock with a database-backed queue or an ordered task service before raising the
instance limit.

## Durable state

- `telegram_user_state`: pending questions, payment flow flags, relationship
  flow and paginated spread pages.
- `telegram_updates`: global webhook idempotency and abandoned-claim recovery.
- `scheduled_deliveries`: per-user delivery status for resumable broadcasts.
- `telegram_file_cache`: reusable Telegram `file_id` values for image delivery.

## Scheduled work

Cloud Scheduler calls `POST /tasks/scheduled` with
`X-Runa-Scheduler-Secret`. Each delivery is claimed independently. A retry
skips completed users and resumes failed or abandoned recipients.

## Performance

- blocking database calls on interactive hot paths run through
  `asyncio.to_thread`;
- Telegram images reuse `file_id` after the first upload;
- stale Neon SSL connections are health-checked and replaced;
- update and three-rune spread logs expose stage timings.

## Ruflo decision

Ruflo is an agent-development meta-harness. The production bot needs ordered
webhook processing, durable transactional state and Telegram delivery
idempotency. Those guarantees belong in the Python application and PostgreSQL,
not in an additional Node/MCP agent layer. Ruflo is therefore not a runtime
dependency for Runa.
