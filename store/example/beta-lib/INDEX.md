# Beta Lib — Index
Source: https://example.com/beta
Pages: 1

## Sections
- Setup: configure(token, *, base_url)
- Queues: create_queue, get_queue, stats, delete_queue
- Jobs: enqueue, dequeue, ack, nack, fail, extend, get_job

## Function index
configure,
create_queue, get_queue, stats, delete_queue,
enqueue, dequeue, ack, nack, fail, extend, get_job

Cross-cutting: configure() first or BetaAuthError; every non-2xx raises BetaError
(BetaAuthError=401, BetaNotFound=404); job ids opaque; dequeue->None means empty (not error);
ack/nack/extend require an in-flight job (stale after the 30s lease expires).
