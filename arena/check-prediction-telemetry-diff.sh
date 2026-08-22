#!/bin/sh
set -eu

base=be8d43c08adcd4618966c5914bce8092e4dbdec5
expected_gcycle_diff=f154cf13781b6ff8fdcd796a5b314451503be6e3a876ec5fa4531177e3405b34

test "$(git rev-parse 'arena-arm1-be8d43c0^{}')" = "$base"
git merge-base --is-ancestor "$base" HEAD
test -z "$(git diff --name-only "$base"...HEAD -- \
  src/engine/eGrid.cpp src/engine/eWall.cpp src/engine/eLagCompensation.cpp \
  src/tron/gArena.cpp src/tron/gCycleMovement.cpp src/tron/gSpawn.cpp src/tron/gWall.cpp)"

actual_gcycle_diff=$(
  git diff --no-ext-diff --unified=3 "$base" -- src/tron/gCycle.cpp | sha256sum | awk '{print $1}'
)
test "$actual_gcycle_diff" = "$expected_gcycle_diff"
