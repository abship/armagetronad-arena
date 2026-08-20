# Arena transport feasibility bounds

The browser transport preserves the upstream datagram API: one WebSocket
binary message is one UDP datagram in either direction, with no payload
transformation or message coalescing.

The Arena ceiling is 2,048 bytes. Stable source receives into a 2,000-element
`unsigned short` array in `src/network/nNetwork.cpp`, but also declares
`serverMaxAcceptedSize=2000` and describes `MTU 1400` as the rough safe packet
size. The Arena bound follows issue #319's conservative 2 KiB plan instead of
exposing the UDP theoretical 65,507-byte maximum.

Both sides reject larger datagrams. The browser additionally caps queued input
and output at 32 messages and 32 KiB, rejects stale controls after one second,
and closes on WebSocket `bufferedAmount` backlog. The relay rate-limits complete
messages and never splits or joins them.

Authentication uses a server-minted HMAC ticket with a maximum five-minute
lifetime. The ticket carries the authoritative `(session, player)` identity,
travels in a WebSocket subprotocol, is removed from browser history after
startup, is never written to evidence, and can be used only once. The relay
also permits only one live connection per `(session, player)` slot.

The feasibility static server strips query strings from request logs. Browser
failure diagnostics record only bounded, ticket-redacted state and screenshots;
they never retain the credential-bearing startup URL.

The Emscripten client bypasses the native interactive welcome/first-use UI and
enters the Arena auto-connect seam directly. Native startup remains unchanged.
