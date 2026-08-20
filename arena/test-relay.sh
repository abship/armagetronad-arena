#!/bin/sh
# Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
node "$repo_dir/arena/tests/test_socket.js"
node "$repo_dir/arena/tests/test_pre.js"
python3 "$repo_dir/arena/tests/test_relay.py"
python3 "$repo_dir/arena/tests/test_static_server.py"
