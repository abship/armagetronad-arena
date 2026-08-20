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
