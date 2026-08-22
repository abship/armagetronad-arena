# ARM-1 build architecture decision

Evidence was inspected on 2026-08-20 from `abship/arena-platform` main commit
`883c45a798c396228bcb9d84f7a07ebb8043a39f`:

- `.github/workflows/ci.yml` says the only self-hosted runner is Windows and its
  platform-specific tools are the x64 releases.
- `packages/studio-sandbox/runtime/provenance.json` records the established
  reproducible Emscripten builder platform as `linux/amd64`.
- `railway.runtime.json` uses Nixpacks and does not declare an arm64 production
  target.

Therefore `./arena/build-native.sh` defaults to `linux/amd64`. An explicit
`--platform linux/arm64` build is additional local feasibility evidence only and
does not satisfy the production-native gate.

Both supported architectures resolve directly to image manifests, not mutable
tags. The exact Debian and Emscripten manifest digests are recorded in
`arena/pins.env`.

## Runtime gate

The disposable local Docker Desktop runtime repeatedly stalled before the
native server process started. That is host-environment evidence only: it does
not pass or fail the production target. The authoritative runtime gate is the
pinned `ubuntu-24.04` GitHub Actions job in
`.github/workflows/arena-feasibility.yml`, which builds and runs the
`linux/amd64` server, relay, and static Wasm client, then drives two real Chrome
clients and two real Firefox clients through W3C WebDriver.

That Linux job must show real turn-key actions, bidirectional datagram traffic,
nonblank canvas screenshots, and authoritative `PLAYER_ENTERED`,
`MATCH_WINNER`, and `GAME_END` server evidence before its runtime gate is
reported as passed. Safari remains a separate required macOS run and is not
implied by a green Linux job.

## Current feasibility result

Linux/amd64 run `32538237257` at source head
`fc0e4ba5bfa4af1009e1c94f6eefd36d7745e31c` passed the exact-base and
forbidden-diff guard, pinned native and full upstream Wasm builds, all
relay/auth/abuse tests, and the Chrome plus Firefox runtime gate. In each
browser, two upstream C++ clients rendered nonblank 1280 by 720 canvas frames,
accepted real W3C turn actions, exchanged datagrams in both directions, and
completed an authoritative match with `PLAYER_ENTERED`, `MATCH_WINNER`, and
`GAME_END` evidence. The retained artifact is `9466285334`, with artifact
digest
`01dcd6f693f2c21bdbd57148c1fd3926d569722a461ef1201d52e9db523fd4aa`.

This passes the Linux runtime gate only. Safari 1v1, 100-match native-client
parity, the approved shaped-loss/frame/memory plan, same-source
reproducibility, final release publication, and independent exact-SHA review
remain separate ARM-1 gates. The Draft PR remains unmerged.

## Safari interoperability topology

SafariDriver permits one active automation session per Mac. The Safari lane
therefore runs two visible, same-origin iframe documents inside one driver
session. Each document loads its own upstream C++ Wasm module, canvas, socket,
ticket, player identity, and client state. The harness switches frame context
and re-finds the canvas before every state read, render capture, and W3C input;
all Linux render, input, traffic, and authoritative-result assertions remain in
force.

The hosted Apple-silicon `macos-15`/`arm64` runner runs a same-source native
dedicated server only for this Safari loopback interoperability proof.
`arena/build-native-macos.sh` fails closed on the exact recorded runner image,
architecture, Safari, Xcode, pkgconf, Python, and SDK libxml2 versions. It does
not redefine or replace the pinned linux/amd64 production-native artifact.
