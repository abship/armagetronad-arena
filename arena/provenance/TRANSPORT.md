# Arena transport feasibility bounds

The browser transport preserves the upstream datagram API: one WebSocket
binary message is one UDP datagram in either direction, with no payload
transformation or message coalescing.

The Arena ceiling is 2,048 bytes. Stable source receives into a 2,000-element
`unsigned short` array in `src/network/nNetwork.cpp`, but also declares
`serverMaxAcceptedSize=2000` and describes `MTU 1400` as the rough safe packet
size. The Arena bound follows issue #319's conservative 2 KiB plan instead of
exposing the UDP theoretical 65,507-byte maximum.

Both sides reject larger datagrams. The browser caps queued output at 32
messages and queued input at 128 messages, with a 32 KiB byte cap in either
direction. It rejects stale controls after one second and closes on WebSocket
`bufferedAmount` backlog. The relay rate-limits every inbound WebSocket frame,
including PING controls, and handles controls iteratively so they cannot bypass
the flood bound or grow the handler stack. It never splits or joins datagrams.

Authentication uses a server-minted HMAC ticket with a maximum five-minute
lifetime. The ticket carries the authoritative `(session, player)` identity,
travels in a WebSocket subprotocol, is removed from browser history after
startup, is never written to evidence, and can be used only once. The relay
also permits only one live connection per `(session, player)` slot.

For the Arena dedicated-server launch only, the relay atomically publishes the
signed player identity under its active UDP source port. The isolated native
roster hook reads that record and replaces the untrusted client-supplied name
before upstream roster, ladder, and winner handling. Missing or invalid active
records disconnect the native client. The relay removes each record when its
socket closes, bounding the directory by live connections. Without
`ARENA_ROSTER_DIR`, upstream native name handling is unchanged.

The feasibility static server strips query strings from request logs. Browser
failure diagnostics record only bounded, ticket-redacted state and screenshots;
they never retain the credential-bearing startup URL.

The Linux production-feasibility lane deterministically drops every 64th binary
datagram independently in each direction after authentication and all size/rate
validation. Dropped evidence retains only direction, identity, size, and digest.
PING controls are never shaped, and delivered datagrams are never delayed,
split, joined, reordered, or modified. Each real browser match must still pass
the existing rendering, input, bidirectional-traffic, and native-result gates.

The same harness arms bounded render-loop metrics only after both upstream
cycles are live. Every client must retain at least 20 swap-gap samples, p95 at
or below 250 ms, maximum gap at or below 750 ms, Wasm linear memory at or below
256 MiB, and growth after arming at or below 32 MiB. These are stall/leak bounds,
not a browser-process or GPU-memory claim.

The Emscripten client bypasses the native interactive welcome/first-use UI and
enters the Arena auto-connect seam directly. Native startup remains unchanged.
