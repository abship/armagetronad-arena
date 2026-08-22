# Native/browser parity contract

`./arena/test-native-parity.sh --matches 100` runs 100 indexed native-client
matches and 100 matching browser-client matches. CI partitions indices 0 through
99 across ten shards; each shard still invokes the literal 100-match command and
the final job requires the exact union with no missing, duplicate, extra, or
retried index.

Each index uses two separate fresh authoritative dedicated servers with the
same Arena configuration:

- native arm: two regular upstream Linux clients connect directly over UDP;
- browser arm: two upstream C++ Wasm clients use the authenticated binary
  datagram relay, split evenly between Chrome and Firefox.

The test-only native client is built from the same source under
`--enable-arena-native-parity`. That flag only replaces the regular interactive
welcome/menu with environment-supplied auto-connect. Input remains the ordinary
SDL path under isolated Xvfb displays. This image does not replace or modify the
production linux/amd64 dedicated artifact.

Both arms use the versioned schedule
`role1:wait(200ms),a(120ms),a(120ms),a(120ms);role2:none`: after both local
objects are live, role1 first travels straight for 200 ms. Each `a` is then
held for 120 ms and the next begins immediately after release. The three left
turns close a small upstream trail loop. The harness requires all three role1 turns
to be delivered and accepted, exactly one entry for
each role, exactly one role1 suicide before the sole authoritative role2 match
winner, no role2 suicide, and exactly one
`GAME_END`. The canonical event/winner result must match per index. Raw ladder
logs, recordings, browser state, and relay datagram evidence are retained.
Every record binds the exact source commit plus native-client, native-server,
Wasm, configuration, and input-schedule hashes from one verified build-input
manifest. The aggregator re-hashes every raw file and independently parses the
native SDL/accepted-action evidence before accepting an index.

The parity gate is unshaped. Deterministic shaped loss, transport abuse,
cross-browser rendering, live-frame cadence, and memory remain independent
required gates so timing loss does not get confused with native/Wasm semantic
parity.
