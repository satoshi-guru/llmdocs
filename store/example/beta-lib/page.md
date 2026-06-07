---
title: "Beta Lib"
url: https://example.com/beta
---

# Beta Lib

Beta is a small HTTP job-queue API. Every call is authenticated; configure a client
once with a token, then create queues, enqueue jobs, and pull them for processing.
This page documents the endpoints, their parameters, and the return shapes.

All responses are JSON. Any 4xx/5xx response raises `BetaError` (subclass: `BetaAuthError`
for 401, `BetaNotFound` for 404). Job ids are opaque strings — never parse them.

## Setup

### configure(token, *, base_url="https://api.example.com")
Create an authenticated client. The token is sent as `Authorization: Bearer <token>`
on every request. Returns a `Client`. Raises `BetaAuthError` if the token is rejected
on the first call (configure itself is lazy and does not hit the network).

```python
client = beta.configure("sk-...")
```

## Queues

### POST /queues — create_queue(name, *, max_retries=5)
Create a queue. `name` must match `[a-z0-9-]{1,64}`. `max_retries` is the number of
times a failed job is re-delivered before it is dead-lettered (0..20, default 5).
Returns a `Queue`. Raises `BetaError` if a queue with that name already exists.

### GET /queues/{name} — get_queue(name)
Fetch an existing queue. Returns a `Queue`. Raises `BetaNotFound` if it does not exist.

### GET /queues/{name}/stats — stats(name)
Return a `Stats` object: `{ready, in_flight, dead, oldest_age_s}`. Cheap; safe to poll.

### DELETE /queues/{name} — delete_queue(name)
Delete a queue and all of its jobs. Returns `True`. Idempotent: deleting a missing
queue still returns `True` (does not raise).

## Jobs

### POST /queues/{name}/jobs — enqueue(name, payload, *, priority=0, delay_s=0)
Add a job. `payload` is any JSON-serializable value. `priority` is -100..100 — higher
runs sooner (default 0). `delay_s` holds the job invisible for N seconds before it
becomes ready (0..900, default 0). Returns a `Job` with a fresh `id`.

### GET /queues/{name}/jobs/next — dequeue(name, *, wait_s=30)
Long-poll for the next ready job. Blocks up to `wait_s` seconds (0..60, default 30).
Returns a `Job`, or `None` if the queue stays empty for the whole wait. A returned job
is *in-flight* (invisible to other consumers) until you `ack`/`nack`/`fail` it or its
visibility lease expires (lease = 30s, renewed by `extend`).

### POST /jobs/{id}/ack — ack(id)
Mark an in-flight job done and remove it. Returns `True`. Idempotent — acking an
already-acked job returns `True`. Raises `BetaError` only if the job was never in-flight.

### POST /jobs/{id}/nack — nack(id, *, requeue=True)
Negative-ack: release the job back to the queue (`requeue=True`) or drop it
(`requeue=False`). Returns `True`. Re-delivery counts against `max_retries`.

### POST /jobs/{id}/fail — fail(id, reason)
Permanently fail a job: send it straight to the dead-letter set with `reason`
attached, bypassing remaining retries. Returns `None`.

### POST /jobs/{id}/extend — extend(id, *, by_s=30)
Renew the visibility lease on an in-flight job by `by_s` seconds (1..300) to keep
working past the default 30s lease. Returns the new lease deadline as an ISO string.

### GET /jobs/{id} — get_job(id)
Fetch a job by id regardless of state. Returns a `Job` (`{id, payload, state, attempts}`).
Raises `BetaNotFound` if the id is unknown.

## Notes

- Always `configure()` first; every other call raises `BetaAuthError` without a client.
- `dequeue` returning `None` is normal (empty queue), not an error — loop and retry.
- `ack`/`nack`/`extend` only work while a job is in-flight; after the lease expires the
  job is re-delivered and the old in-flight handle is stale (`BetaError`).
- `priority` orders *ready* jobs only; an in-flight or delayed job is not reordered.
