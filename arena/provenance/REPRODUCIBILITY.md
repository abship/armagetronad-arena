# ARM-1 reproducibility and corresponding source

`./arena/reproducibility-check.sh --platform linux/amd64` creates two fresh
detached worktrees at the same candidate commit. Each worktree performs clean,
uncached native and web builds through the digest-pinned builders in
`arena/pins.env`. The check compares every declared native, web, and release
file byte for byte.

`./arena/package-release.sh --platform linux/amd64` assembles the release
directory from verified build outputs. It includes:

- the native dedicated server and its GPL copy;
- the upstream C++ Wasm client files, symbols, and GPL copy;
- a `git archive` of every tracked file at the exact candidate commit;
- the corresponding Git blob inventory, stable tag/base, source tree, image
  pins, Emscripten version, Dockerfile hashes, and artifact checksums.

The source archive is compressed with `gzip -n`, so its header contains no
wall-clock timestamp. The build containers receive the pinned
`SOURCE_DATE_EPOCH`; compilation is serialized and uses fixed source/build path
maps. Docker image IDs are deliberately excluded from the byte comparison:
they describe image configuration metadata, not distributed program bytes.

The manual `Arena same-source reproducibility` workflow retains both build
packages, the comparison manifests, and the final exact-source release
directory. Publication as a GitHub release is deferred until every other
ARM-1 acceptance gate and exact-SHA review passes.
