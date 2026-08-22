#!/usr/bin/env python3
"""Fail-closed, stdlib-only aggregation for 100 native/browser parity trials."""

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess


SCHEMA = "arena-native-browser-parity-v1"
INPUT_SCHEMA = "arena-native-browser-parity-inputs-v1"
EXPECTED_EVENTS = ["PLAYER_ENTERED", "PLAYER_ENTERED", "DEATH_SUICIDE",
                   "MATCH_WINNER", "GAME_END"]
INPUT_SCHEDULE = "role1:wait(200ms),a(120ms),a(120ms),a(120ms);role2:none"
BUILD_PATHS = {
    "nativeClient": "build/native-parity/amd64/armagetronad",
    "nativeServer": "build/native/amd64/armagetronad-dedicated",
    "webWasm": "build/web/armagetronad_main.wasm",
}
RAW_PATHS = {
    "native/ladderlog.txt", "native/match.aarec",
    "native/input-role1.log", "native/input-role2.log",
    "browser/ladderlog.txt", "browser/match.aarec",
    "browser/states.json", "browser/relay.jsonl",
}


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def shard_indices(shard_index, shard_count, total):
    if shard_index < 0 or shard_count < 1 or total < 1 or shard_index >= shard_count:
        raise ValueError("invalid parity shard")
    return range(shard_index, total, shard_count)


def record_path(evidence_dir, index):
    return evidence_dir / "trials" / "trial-{0:03d}.json".format(index)


SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def config_sha256(repo_dir):
    digest = hashlib.sha256()
    for relative in ("arena/config/arena.cfg", "arena/config/native-parity.cfg",
                     "arena/config/parity-server.cfg"):
        digest.update((repo_dir / relative).read_bytes())
    return digest.hexdigest()


def expected_input_manifest(repo_dir, source_commit):
    return {
        "schema": INPUT_SCHEMA,
        "sourceCommit": source_commit,
        "buildSha256": {
            name: file_sha256(repo_dir / relative) for name, relative in BUILD_PATHS.items()
        },
        "configSha256": config_sha256(repo_dir),
        "inputSchedule": INPUT_SCHEDULE,
        "inputScheduleSha256": hashlib.sha256(INPUT_SCHEDULE.encode("ascii")).hexdigest(),
    }


def validate_input_manifest(path, repo_dir, source_commit):
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("invalid parity input manifest: {0}".format(error))
    expected = expected_input_manifest(repo_dir, source_commit)
    if canonical_json(manifest) != canonical_json(expected):
        raise ValueError("parity input manifest differs from exact source/build inputs")
    return manifest


def native_input_counts(path):
    lines = path.read_text(encoding="ascii", errors="strict").splitlines()
    return {
        "keyDown": sum(line == "KEY 1 97 0 1" for line in lines),
        "keyUp": sum(line == "KEY 0 97 0 1" for line in lines),
        "acceptedTurns": sum(
            line.startswith("ACTION CYCLE_TURN_LEFT 1 ") and
            len(line.split()) == 5 and float(line.split()[3]) > 0 and
            line.split()[4] == "1" for line in lines
        ),
    }


def authoritative_result(path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    entered = [(index, line.split()[1]) for index, line in enumerate(lines)
               if line.startswith("PLAYER_ENTERED ")]
    winners = [(index, line.split()[1]) for index, line in enumerate(lines)
               if line.startswith("MATCH_WINNER ")]
    suicides = [(index, line.split()[1]) for index, line in enumerate(lines)
                if line.startswith("DEATH_SUICIDE ")]
    game_ends = [index for index, line in enumerate(lines) if line.startswith("GAME_END ")]
    if (sorted(player for _index, player in entered) != ["role1", "role2"] or
            [player for _index, player in suicides] != ["role1"] or
            [player for _index, player in winners] != ["role2"] or len(game_ends) != 1):
        raise ValueError("authoritative exact 1v1 role2 result differs")
    if not (max(index for index, _player in entered) < suicides[0][0] <
            winners[0][0] < game_ends[0]):
        raise ValueError("authoritative exact 1v1 event order differs")
    return {"events": EXPECTED_EVENTS, "loser": "role1", "winner": "role2"}


def browser_input_counts(path):
    try:
        states = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("invalid browser state evidence: {0}".format(error))
    if not isinstance(states, list) or len(states) != 2:
        raise ValueError("browser state identity set differs")
    by_player = {state.get("player"): state for state in states if isinstance(state, dict)}
    if set(by_player) != {"role1", "role2"}:
        raise ValueError("browser state identity set differs")
    result = {}
    for player, state in by_player.items():
        inputs = state.get("finalState", {}).get("input", {})
        result[player] = {
            "keyDown": inputs.get("keyDown"), "keyUp": inputs.get("keyUp"),
            "sdlKeyDown": inputs.get("sdlKeyDown"), "sdlKeyUp": inputs.get("sdlKeyUp"),
            "acceptedTurns": inputs.get("acceptedActions"),
        }
    return result


def validate_record(record, index, source_commit=None, input_manifest=None):
    if not isinstance(record, dict) or record.get("schema") != SCHEMA or record.get("trial") != index:
        raise ValueError("trial {0}: bad schema or index".format(index))
    if record.get("browser") != ("chrome" if index % 2 == 0 else "firefox"):
        raise ValueError("trial {0}: browser schedule differs".format(index))
    if not isinstance(record.get("sourceCommit"), str) or not GIT_SHA.fullmatch(record["sourceCommit"]):
        raise ValueError("trial {0}: source commit missing".format(index))
    if source_commit and record["sourceCommit"] != source_commit:
        raise ValueError("trial {0}: source commit differs".format(index))
    if record.get("attempt") != 1:
        raise ValueError("trial {0}: retry/attempt count differs".format(index))
    build_digests = record.get("buildSha256")
    if not isinstance(build_digests, dict) or set(build_digests) != {
            "nativeClient", "nativeServer", "webWasm"}:
        raise ValueError("trial {0}: build digest set differs".format(index))
    for name, digest in build_digests.items():
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError("trial {0}: {1} build digest missing".format(index, name))
    for name in ("configSha256", "inputScheduleSha256"):
        if not isinstance(record.get(name), str) or not SHA256.fullmatch(record[name]):
            raise ValueError("trial {0}: {1} missing".format(index, name))
    if record.get("inputSchedule") != INPUT_SCHEDULE:
        raise ValueError("trial {0}: input schedule differs".format(index))
    if record["inputScheduleSha256"] != hashlib.sha256(
            INPUT_SCHEDULE.encode("ascii")).hexdigest():
        raise ValueError("trial {0}: input schedule hash differs".format(index))
    if input_manifest:
        for name in ("buildSha256", "configSha256", "inputSchedule",
                     "inputScheduleSha256"):
            if record.get(name) != input_manifest.get(name):
                raise ValueError("trial {0}: {1} differs from input manifest".format(index, name))
    if record.get("nativeInput") != {
            "role1KeyDown": 3, "role1KeyUp": 3,
            "role1AcceptedTurns": 3, "role2AcceptedTurns": 0}:
        raise ValueError("trial {0}: native accepted input proof differs".format(index))
    raw_digests = record.get("rawSha256")
    if not isinstance(raw_digests, dict) or set(raw_digests) != RAW_PATHS:
        raise ValueError("trial {0}: raw evidence set differs".format(index))
    if any(not isinstance(value, str) or not SHA256.fullmatch(value)
           for value in raw_digests.values()):
        raise ValueError("trial {0}: raw evidence digest missing".format(index))
    for name in ("nativeServer", "browserServer"):
        server = record.get(name)
        if not isinstance(server, dict) or server.get("fresh") is not True or server.get("gameEnd") is not True:
            raise ValueError("trial {0}: {1} fresh/GAME_END missing".format(index, name))
        for digest in ("logSha256", "recordingSha256"):
            if not isinstance(server.get(digest), str) or not SHA256.fullmatch(server[digest]):
                raise ValueError("trial {0}: {1} {2} missing".format(index, name, digest))
    if (raw_digests["native/ladderlog.txt"] != record["nativeServer"]["logSha256"] or
            raw_digests["native/match.aarec"] != record["nativeServer"]["recordingSha256"] or
            raw_digests["browser/ladderlog.txt"] != record["browserServer"]["logSha256"] or
            raw_digests["browser/match.aarec"] != record["browserServer"]["recordingSha256"]):
        raise ValueError("trial {0}: server/raw digest linkage differs".format(index))
    if "nativeCanonical" not in record or "browserCanonical" not in record:
        raise ValueError("trial {0}: canonical result missing".format(index))
    try:
        native = canonical_json(record["nativeCanonical"])
        browser = canonical_json(record["browserCanonical"])
    except (TypeError, ValueError) as error:
        raise ValueError("trial {0}: non-canonical JSON: {1}".format(index, error))
    expected = canonical_json({"events": EXPECTED_EVENTS, "loser": "role1",
                               "winner": "role2"})
    if native != browser:
        raise ValueError("trial {0}: native/browser canonical result differs".format(index))
    if native != expected:
        raise ValueError("trial {0}: expected role2 authoritative result missing".format(index))
    return hashlib.sha256(native).hexdigest()


def verify(evidence_dir, indices, source_commit=None, input_manifest=None):
    results = {}
    expected_paths = {record_path(evidence_dir, index).name for index in indices}
    actual_paths = {path.name for path in (evidence_dir / "trials").glob("trial-*.json")}
    if actual_paths != expected_paths:
        raise ValueError("parity trial index union is not exact")
    for index in indices:
        path = record_path(evidence_dir, index)
        if not path.is_file():
            raise ValueError("trial {0}: evidence missing".format(index))
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            results[index] = validate_record(record, index, source_commit, input_manifest)
        except json.JSONDecodeError as error:
            raise ValueError("trial {0}: invalid JSON: {1}".format(index, error))
        raw_dir = evidence_dir / "raw" / "trial-{0:03d}".format(index)
        for relative in RAW_PATHS:
            raw_path = raw_dir / relative
            if not raw_path.is_file() or raw_path.is_symlink():
                raise ValueError("trial {0}: raw evidence missing: {1}".format(index, relative))
            if file_sha256(raw_path) != record["rawSha256"][relative]:
                raise ValueError("trial {0}: raw evidence digest differs: {1}".format(index, relative))
        role1 = native_input_counts(raw_dir / "native/input-role1.log")
        role2 = native_input_counts(raw_dir / "native/input-role2.log")
        if role1 != {"keyDown": 3, "keyUp": 3, "acceptedTurns": 3} or \
                role2 != {"keyDown": 0, "keyUp": 0, "acceptedTurns": 0}:
            raise ValueError("trial {0}: raw native input proof differs".format(index))
        browser_inputs = browser_input_counts(raw_dir / "browser/states.json")
        if browser_inputs != {
                "role1": {"keyDown": 3, "keyUp": 3, "sdlKeyDown": 3,
                          "sdlKeyUp": 3, "acceptedTurns": 3},
                "role2": {"keyDown": 0, "keyUp": 0, "sdlKeyDown": 0,
                          "sdlKeyUp": 0, "acceptedTurns": 0}}:
            raise ValueError("trial {0}: raw browser input proof differs".format(index))
        for arm, field in (("native", "nativeCanonical"), ("browser", "browserCanonical")):
            try:
                result = authoritative_result(raw_dir / arm / "ladderlog.txt")
            except ValueError as error:
                raise ValueError("trial {0}: {1}".format(index, error))
            if canonical_json(result) != canonical_json(record[field]):
                raise ValueError("trial {0}: raw {1} canonical result differs".format(index, arm))
    return results


def run_shard(command, evidence_dir, runtime_dir, shard_index, shard_count, total, timeout):
    runtime_dir.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({
        "ARENA_PARITY_EVIDENCE_DIR": str(evidence_dir),
        "ARENA_PARITY_RUNTIME_DIR": str(runtime_dir),
    })
    subprocess.run(command + ["--matches", str(total), "--shard-index", str(shard_index),
                              "--shard-count", str(shard_count)], check=True, env=environment,
                   timeout=timeout)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=pathlib.Path)
    parser.add_argument("--runtime-dir", type=pathlib.Path)
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=450)
    parser.add_argument("--source-commit")
    parser.add_argument("--input-manifest", type=pathlib.Path)
    parser.add_argument("--write-input-manifest", type=pathlib.Path)
    parser.add_argument("--verify-input-manifest", type=pathlib.Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("trial_command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    repo_dir = pathlib.Path(__file__).resolve().parents[1]
    source_commit = args.source_commit
    if source_commit is None:
        source_commit = subprocess.check_output(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"], text=True).strip()
    if not GIT_SHA.fullmatch(source_commit):
        parser.error("source commit must be a full lowercase SHA")
    if args.write_input_manifest:
        args.write_input_manifest.parent.mkdir(parents=True, exist_ok=True)
        args.write_input_manifest.write_bytes(canonical_json(
            expected_input_manifest(repo_dir, source_commit)) + b"\n")
        return
    if args.verify_input_manifest:
        try:
            validate_input_manifest(args.verify_input_manifest, repo_dir, source_commit)
        except ValueError as error:
            raise SystemExit(str(error))
        return
    if not args.evidence_dir or not args.input_manifest:
        parser.error("--evidence-dir and --input-manifest are required")
    try:
        indices = list(shard_indices(args.shard_index, args.shard_count, args.trials))
    except ValueError as error:
        parser.error(str(error))
    if args.timeout < 1:
        parser.error("timeout must be positive")
    if args.verify_only:
        if args.trial_command:
            parser.error("--verify-only does not accept a trial command")
    else:
        if not args.runtime_dir:
            parser.error("--runtime-dir is required when running trials")
        if not args.trial_command or args.trial_command[0] != "--":
            parser.error("pass the trial command after --")
        command = args.trial_command[1:]
        if not command:
            parser.error("trial command is empty")
        (args.evidence_dir / "trials").mkdir(parents=True, exist_ok=True)
        run_shard(command, args.evidence_dir, args.runtime_dir, args.shard_index,
                  args.shard_count, args.trials, args.timeout)
    try:
        input_manifest = validate_input_manifest(args.input_manifest, repo_dir, source_commit)
        digests = verify(args.evidence_dir, indices, source_commit, input_manifest)
    except ValueError as error:
        raise SystemExit(str(error))
    (args.evidence_dir / "summary-shard-{0:02d}.json".format(args.shard_index)).write_text(
        json.dumps({"schema": SCHEMA, "shardIndex": args.shard_index,
                    "shardCount": args.shard_count, "trials": len(indices),
                    "canonicalSha256": {str(i): digests[i] for i in indices}},
                   indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
