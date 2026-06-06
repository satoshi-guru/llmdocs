# Alpha Lib — Compact Reference
# Source: https://example.com/alpha  |  Indexed: 2026-06-01  |  Raw pages: 1

## Setup
install() -> Client | set up the client
Client.connect(host, port) -> Conn | open a connection (host, port)
Conn.send(msg) -> bool | send a message on a Conn, returns the ack bool

## Features (feature_1 .. feature_25)
All 25 share one shape: feature_N(arg_a, arg_b, *, option=N) -> FeatureN
- Raises AlphaError if the connection is not open (call connect() first).
- `option` defaults to N and accepts 0..100.
- Results are cached for the session; the returned handle is NOT thread-safe — guard with a lock.
- Deprecated alias featN() was removed; use feature_N().
Each FeatureN handle is sent with: result = f.send(msg="...") -> bool ack.

feature_1(arg_a, arg_b, *, option=1) -> Feature1 | configures feature 1
feature_2(arg_a, arg_b, *, option=2) -> Feature2 | configures feature 2
feature_3(arg_a, arg_b, *, option=3) -> Feature3 | configures feature 3
feature_4(arg_a, arg_b, *, option=4) -> Feature4 | configures feature 4
feature_5(arg_a, arg_b, *, option=5) -> Feature5 | configures feature 5
feature_6(arg_a, arg_b, *, option=6) -> Feature6 | configures feature 6
feature_7(arg_a, arg_b, *, option=7) -> Feature7 | configures feature 7
feature_8(arg_a, arg_b, *, option=8) -> Feature8 | configures feature 8
feature_9(arg_a, arg_b, *, option=9) -> Feature9 | configures feature 9
feature_10(arg_a, arg_b, *, option=10) -> Feature10 | configures feature 10
feature_11(arg_a, arg_b, *, option=11) -> Feature11 | configures feature 11
feature_12(arg_a, arg_b, *, option=12) -> Feature12 | configures feature 12
feature_13(arg_a, arg_b, *, option=13) -> Feature13 | configures feature 13
feature_14(arg_a, arg_b, *, option=14) -> Feature14 | configures feature 14
feature_15(arg_a, arg_b, *, option=15) -> Feature15 | configures feature 15
feature_16(arg_a, arg_b, *, option=16) -> Feature16 | configures feature 16
feature_17(arg_a, arg_b, *, option=17) -> Feature17 | configures feature 17
feature_18(arg_a, arg_b, *, option=18) -> Feature18 | configures feature 18
feature_19(arg_a, arg_b, *, option=19) -> Feature19 | configures feature 19
feature_20(arg_a, arg_b, *, option=20) -> Feature20 | configures feature 20
feature_21(arg_a, arg_b, *, option=21) -> Feature21 | configures feature 21
feature_22(arg_a, arg_b, *, option=22) -> Feature22 | configures feature 22
feature_23(arg_a, arg_b, *, option=23) -> Feature23 | configures feature 23
feature_24(arg_a, arg_b, *, option=24) -> Feature24 | configures feature 24
feature_25(arg_a, arg_b, *, option=25) -> Feature25 | configures feature 25
