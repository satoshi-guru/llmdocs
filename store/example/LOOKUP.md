alpha-lib | install() -> Client | set up the client
alpha-lib | connect(host, port) -> Conn | open a connection
alpha-lib | send(msg) -> bool | send a message, returns ack
alpha-lib | feature_1(arg_a, arg_b, *, option=1) -> Feature1 | configures feature 1; AlphaError if not connected
alpha-lib | feature_2(arg_a, arg_b, *, option=2) -> Feature2 | configures feature 2; AlphaError if not connected
alpha-lib | feature_3(arg_a, arg_b, *, option=3) -> Feature3 | configures feature 3; AlphaError if not connected
alpha-lib | feature_4(arg_a, arg_b, *, option=4) -> Feature4 | configures feature 4; AlphaError if not connected
alpha-lib | feature_5(arg_a, arg_b, *, option=5) -> Feature5 | configures feature 5; AlphaError if not connected
alpha-lib | feature_6(arg_a, arg_b, *, option=6) -> Feature6 | configures feature 6; AlphaError if not connected
alpha-lib | feature_7(arg_a, arg_b, *, option=7) -> Feature7 | configures feature 7; AlphaError if not connected
alpha-lib | feature_8(arg_a, arg_b, *, option=8) -> Feature8 | configures feature 8; AlphaError if not connected
alpha-lib | feature_9(arg_a, arg_b, *, option=9) -> Feature9 | configures feature 9; AlphaError if not connected
alpha-lib | feature_10(arg_a, arg_b, *, option=10) -> Feature10 | configures feature 10; AlphaError if not connected
alpha-lib | feature_11(arg_a, arg_b, *, option=11) -> Feature11 | configures feature 11; AlphaError if not connected
alpha-lib | feature_12(arg_a, arg_b, *, option=12) -> Feature12 | configures feature 12; AlphaError if not connected
alpha-lib | feature_13(arg_a, arg_b, *, option=13) -> Feature13 | configures feature 13; AlphaError if not connected
alpha-lib | feature_14(arg_a, arg_b, *, option=14) -> Feature14 | configures feature 14; AlphaError if not connected
alpha-lib | feature_15(arg_a, arg_b, *, option=15) -> Feature15 | configures feature 15; AlphaError if not connected
alpha-lib | feature_16(arg_a, arg_b, *, option=16) -> Feature16 | configures feature 16; AlphaError if not connected
alpha-lib | feature_17(arg_a, arg_b, *, option=17) -> Feature17 | configures feature 17; AlphaError if not connected
alpha-lib | feature_18(arg_a, arg_b, *, option=18) -> Feature18 | configures feature 18; AlphaError if not connected
alpha-lib | feature_19(arg_a, arg_b, *, option=19) -> Feature19 | configures feature 19; AlphaError if not connected
alpha-lib | feature_20(arg_a, arg_b, *, option=20) -> Feature20 | configures feature 20; AlphaError if not connected
alpha-lib | feature_21(arg_a, arg_b, *, option=21) -> Feature21 | configures feature 21; AlphaError if not connected
alpha-lib | feature_22(arg_a, arg_b, *, option=22) -> Feature22 | configures feature 22; AlphaError if not connected
alpha-lib | feature_23(arg_a, arg_b, *, option=23) -> Feature23 | configures feature 23; AlphaError if not connected
alpha-lib | feature_24(arg_a, arg_b, *, option=24) -> Feature24 | configures feature 24; AlphaError if not connected
alpha-lib | feature_25(arg_a, arg_b, *, option=25) -> Feature25 | configures feature 25; AlphaError if not connected
beta-lib | configure(token, *, base_url=...) -> Client | auth client; lazy; BetaAuthError if rejected
beta-lib | create_queue(name, *, max_retries=5) -> Queue | POST /queues; BetaError if name exists
beta-lib | get_queue(name) -> Queue | GET /queues/{name}; BetaNotFound if missing
beta-lib | stats(name) -> Stats | GET /queues/{name}/stats; {ready,in_flight,dead,oldest_age_s}
beta-lib | delete_queue(name) -> bool | DELETE /queues/{name}; idempotent
beta-lib | enqueue(name, payload, *, priority=0, delay_s=0) -> Job | POST /queues/{name}/jobs; priority -100..100; delay_s 0..900
beta-lib | dequeue(name, *, wait_s=30) -> Job | None | long-poll 0..60; None when empty; 30s in-flight lease
beta-lib | ack(id) -> bool | POST /jobs/{id}/ack; idempotent
beta-lib | nack(id, *, requeue=True) -> bool | POST /jobs/{id}/nack; counts against max_retries
beta-lib | fail(id, reason) -> None | POST /jobs/{id}/fail; straight to dead-letter
beta-lib | extend(id, *, by_s=30) -> str | POST /jobs/{id}/extend; renew lease 1..300; new ISO deadline
beta-lib | get_job(id) -> Job | GET /jobs/{id}; {id,payload,state,attempts}; BetaNotFound if unknown
