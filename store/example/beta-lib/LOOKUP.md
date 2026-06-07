# Beta Lib — LOOKUP (grep tier: one line per API; `grep -i <symbol>`)
beta-lib | configure(token, *, base_url=...) -> Client | auth client; lazy; BetaAuthError if token rejected
beta-lib | create_queue(name, *, max_retries=5) -> Queue | POST /queues; name [a-z0-9-]{1,64}; max_retries 0..20; BetaError if exists
beta-lib | get_queue(name) -> Queue | GET /queues/{name}; BetaNotFound if missing
beta-lib | stats(name) -> Stats | GET /queues/{name}/stats; {ready,in_flight,dead,oldest_age_s}
beta-lib | delete_queue(name) -> bool | DELETE /queues/{name}; idempotent, missing queue still True
beta-lib | enqueue(name, payload, *, priority=0, delay_s=0) -> Job | POST /queues/{name}/jobs; priority -100..100 higher first; delay_s 0..900
beta-lib | dequeue(name, *, wait_s=30) -> Job | None | GET /queues/{name}/jobs/next; long-poll 0..60; None when empty; 30s in-flight lease
beta-lib | ack(id) -> bool | POST /jobs/{id}/ack; idempotent; BetaError only if never in-flight
beta-lib | nack(id, *, requeue=True) -> bool | POST /jobs/{id}/nack; requeue or drop; counts against max_retries
beta-lib | fail(id, reason) -> None | POST /jobs/{id}/fail; straight to dead-letter, bypasses retries
beta-lib | extend(id, *, by_s=30) -> str | POST /jobs/{id}/extend; renew lease 1..300; returns new ISO deadline
beta-lib | get_job(id) -> Job | GET /jobs/{id}; any state; {id,payload,state,attempts}; BetaNotFound if unknown
