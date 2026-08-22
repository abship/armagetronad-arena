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

The exact candidate `1fd170fed09b783cc629c59cecc19a01d40e0fbb` passed
the following source-bound gates:

- Linux/amd64 run `32551855431`, artifact `9470397328`, digest
  `2ee6d7090b0dbbe6e70607a88ac1d2c66f8be7e2225567f37e9df7c9051a468a`:
  pinned native and full upstream Wasm builds, relay/auth/abuse tests, Chrome
  and Firefox 1v1, and deterministic shaped loss in both directions for each
  browser session. All four clients retained nonblank 1280 by 720 frames,
  accepted real W3C turns, exchanged datagrams in both directions, met the
  documented live-frame and linear-memory bounds, and produced authoritative
  `PLAYER_ENTERED`, `MATCH_WINNER`, and `GAME_END` evidence.
- Safari run `32551855462`, artifact `9470371744`, digest
  `293246d8b2c70c5d53a0dc47e24cc59c9095585322db058a2039afc9ba0a4fec`:
  both upstream Wasm clients passed the same render, input, traffic,
  frame/memory, and authoritative-result assertions on the pinned macOS lane.
- Reproducibility run `32551855432`, artifact `9470416666`, digest
  `b6886b51dd1899fe18f2d50cca1c7eb02e4db589a4ea564824bef4a7fe43be7c`:
  two clean linux/amd64 builds matched byte for byte for native, web, and
  complete release packages.

Independent exact-SHA review passed with an empty forbidden-gameplay diff.
The remaining ARM-1 gates are the approved 100-match native-client parity
contract and final immutable GPL/reproducibility release publication. The
Draft PR remains unmerged.

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
