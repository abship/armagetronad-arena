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

Linux/amd64 run `32421697186` at source head `a26dc39c` passed the exact-base
and forbidden-diff guard, pinned native and full upstream Wasm builds, and all
relay/abuse tests. Two Chrome clients opened authenticated Arena sockets and
exchanged complete binary datagrams, but both upstream clients trapped before
`PLAYER_ENTERED`: one in `rConsole::DoPrint` while processing a network config
message, and one in `tCallback::Exec` from the render per-frame task with a
Wasm indirect-call signature mismatch. The server recorded both logins only as
spectators and then timed them out; no `MATCH_WINNER` was produced.

This repeated upstream C++ callback-ABI blocker exhausts the ARM-1 correction
limit. Chrome/Firefox gameplay, Safari, native parity, shaped-loss/frame/memory,
reproducibility, and release gates remain pending. ARM-1 feasibility is not a
PASS, and no TypeScript gameplay substitute is permitted.
