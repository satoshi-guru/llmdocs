# Beta Lib — Compact Reference
# Source: https://example.com/beta  |  Indexed: 2026-06-08  |  Raw pages: 1

Beta is an HTTP job-queue API. configure() once, then create queues and push/pull jobs.
Every non-2xx raises BetaError (BetaAuthError=401, BetaNotFound=404). Job ids are opaque.

## Setup
configure(token, *, base_url="https://api.example.com") -> Client | auth client; lazy (no network until first call); BetaAuthError if token rejected

## Queues
create_queue(name, *, max_retries=5) -> Queue | POST /queues; name [a-z0-9-]{1,64}; max_retries 0..20; BetaError if name exists
get_queue(name) -> Queue | GET /queues/{name}; BetaNotFound if missing
stats(name) -> Stats | GET /queues/{name}/stats; {ready, in_flight, dead, oldest_age_s}; cheap to poll
delete_queue(name) -> bool | DELETE /queues/{name}; idempotent (missing queue still True)

## Jobs
enqueue(name, payload, *, priority=0, delay_s=0) -> Job | POST /queues/{name}/jobs; payload=JSON; priority -100..100 (higher first); delay_s 0..900
dequeue(name, *, wait_s=30) -> Job | None | GET /queues/{name}/jobs/next; long-poll wait_s 0..60; None when empty; job is in-flight (30s lease) until ack/nack/fail/extend
ack(id) -> bool | POST /jobs/{id}/ack; idempotent; BetaError only if job never in-flight
nack(id, *, requeue=True) -> bool | POST /jobs/{id}/nack; requeue back to queue or drop; counts against max_retries
fail(id, reason) -> None | POST /jobs/{id}/fail; straight to dead-letter, bypasses retries
extend(id, *, by_s=30) -> str | POST /jobs/{id}/extend; renew lease by_s 1..300; returns new ISO deadline
get_job(id) -> Job | GET /jobs/{id}; any state; {id, payload, state, attempts}; BetaNotFound if unknown

## Gotchas
- configure() first or every call raises BetaAuthError.
- dequeue -> None is normal (empty queue), not an error — loop.
- ack/nack/extend need an in-flight job; after the lease expires the handle is stale (BetaError) and the job is re-delivered.
- priority orders ready jobs only; in-flight/delayed jobs are not reordered.
