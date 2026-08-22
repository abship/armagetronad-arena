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
`setup:start-new-match,wait(200ms),role1:a(120ms)x1;boundary:first-post-command-new-match,reset-input-evidence;measured:wait(200ms),role1:a(120ms)x1,role2:none`.
The setup turns end the upstream one-client startup round after both clients
connect; the existing `START_NEW_MATCH` console command makes the first
following `NEW_MATCH` the explicit measured boundary. Each arm records that
boundary as ordinal 2 or 3, depending on whether a role1-only pre-admission
round elapsed while the second client started. Input evidence is recorded and
then reset at that boundary. In the measured round role1 first travels straight
for 200 ms, then `a` is held for 120 ms. The parity-only `forced_left` map has
two symmetric, zone-free straight lanes in a large rim. An unsteered role2 is
safe for minutes, while the one accepted role1 turn reaches a static lane rail
with a wide timing margin. Thus client scheduler latency cannot choose the
winner, and absence of the action cannot produce the required result.

The harness requires all setup and measured turns to be delivered and accepted,
exactly one entry for each role, only the bounded optional pre-admission round,
the recorded setup and measured `NEW_MATCH` markers, a decisive
role1 suicide, an authoritative role2 round and match winner, and exactly one
`GAME_END` produced by upstream `QUIT`. A role2 cleanup suicide after the round
winner is normalized because upstream may destroy the surviving cycle before or
after writing `MATCH_WINNER`; it cannot precede the decisive round result. The
canonical event/winner result must match per index. Raw ladder
logs, recordings, browser state, and relay datagram evidence are retained.
Every record binds the exact source commit plus native-client, native-server,
Wasm, configuration, and input-schedule hashes from one verified build-input
manifest. The aggregator re-hashes every raw file and independently parses the
native SDL/accepted-action evidence before accepting an index.

The parity gate is unshaped. Deterministic shaped loss, transport abuse,
cross-browser rendering, live-frame cadence, and memory remain independent
required gates so timing loss does not get confused with native/Wasm semantic
parity.
