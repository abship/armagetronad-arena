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
EXPECTED_EVENTS = ["NEW_MATCH", "DEATH_SUICIDE", "ROUND_WINNER",
                   "MATCH_WINNER", "GAME_END"]
INPUT_SCHEDULE = ("setup:start-new-match,wait(200ms),role1:a(120ms)x1;"
                  "boundary:first-post-command-new-match,reset-input-evidence;"
                  "measured:wait(200ms),role1:a(120ms)x1,role2:none")
BUILD_PATHS = {
    "nativeClient": "build/native-parity/amd64/armagetronad",
    "nativeClientImage": "build/native-parity/amd64/image.tar",
    "nativeServer": "build/native/amd64/armagetronad-dedicated",
    "nativeServerImage": "build/native-parity/amd64/server-image.tar",
    "webData": "build/web/armagetronad_main.data",
    "webJs": "build/web/armagetronad_main.js",
    "webWasm": "build/web/armagetronad_main.wasm",
}
RAW_PATHS = {
    "native/ladderlog.txt", "native/match.aarec",
    "native/server-console.log",
    "native/setup-input-role1.log", "native/setup-input-role2.log",
    "native/input-role1.log", "native/input-role2.log",
    "native/boundary.json",
    "browser/ladderlog.txt", "browser/match.aarec", "browser/server-console.log",
    "browser/states.json", "browser/relay.jsonl", "browser/boundary.json",
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
                     "arena/config/parity-server.cfg",
                     "arena/resource/Arena/parity/forced_left-1.0.0.aamap.xml"):
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


def match_boundary(value):
    if (not isinstance(value, dict) or set(value) != {
            "setupNewMatch", "measuredNewMatch"}):
        raise ValueError("authoritative match boundary differs")
    setup = value["setupNewMatch"]
    measured = value["measuredNewMatch"]
    if (type(setup) is not int or type(measured) is not int or
            setup not in (1, 2) or measured != setup + 1):
        raise ValueError("authoritative match boundary differs")
    return setup, measured


def authoritative_result(path, boundary):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    entered = [line.split()[1] for line in lines if line.startswith("PLAYER_ENTERED ")]
    boundaries = [index for index, line in enumerate(lines) if line.startswith("NEW_MATCH ")]
    setup_ordinal, measured_ordinal = match_boundary(boundary)
    if (sorted(entered) != ["role1", "role2"] or
            len(boundaries) != measured_ordinal):
        raise ValueError("authoritative exact 1v1 role2 result differs")
    if setup_ordinal == 2:
        prelude = list(enumerate(lines[boundaries[0]:boundaries[1]], boundaries[0]))
        prelude_deaths = [(index, line.split()[0], line.split()[1])
                          for index, line in prelude if line.startswith("DEATH_")]
        prelude_score_entries = [(index, line.split()) for index, line in prelude
                                 if line.startswith(("ROUND_SCORE ",
                                                     "ROUND_SCORE_TEAM "))]
        prelude_scores = [score for _index, score in prelude_score_entries]
        role2_admissions = [index for index, line in prelude
                            if line.startswith("PLAYER_ENTERED role2 ")]
        deaths = [(event, player) for _index, event, player in prelude_deaths]
        aborted_without_death = (not deaths and prelude_scores == [
            ["ROUND_SCORE", "0", "role1", "role1"],
            ["ROUND_SCORE_TEAM", "0", "role1"],
        ] and len(role2_admissions) == 1 and
            role2_admissions[0] < prelude_score_entries[0][0])
        if ((deaths != [("DEATH_SUICIDE", "role1")] and
                not aborted_without_death) or
                any(line.startswith(("ROUND_WINNER ", "MATCH_WINNER ", "GAME_END "))
                    for _index, line in prelude)):
            raise ValueError("authoritative pre-admission result differs")
    setup_start = boundaries[setup_ordinal - 1]
    measured_start = boundaries[measured_ordinal - 1]
    setup = list(enumerate(lines[setup_start:measured_start], setup_start))
    setup_deaths = [(index, line.split()[0], line.split()[1]) for index, line in setup
                    if line.startswith("DEATH_")]
    setup_round_winners = [(index, line.split()[1]) for index, line in setup
                           if line.startswith("ROUND_WINNER ")]
    setup_match_winners = [(index, line.split()[1]) for index, line in setup
                           if line.startswith("MATCH_WINNER ")]
    if (not setup_deaths or setup_deaths[0][1:] != ("DEATH_SUICIDE", "role1") or
            len(setup_deaths) > 2 or
            any(event != "DEATH_SUICIDE" or player != "role2"
                for _index, event, player in setup_deaths[1:]) or
            len(setup_round_winners) > 1 or
            any(player != "role2" for _index, player in setup_round_winners) or
            len(setup_match_winners) > 1 or
            any(player != "role2" for _index, player in setup_match_winners)):
        raise ValueError("authoritative setup result differs")
    if setup_round_winners and not setup_deaths[0][0] < setup_round_winners[0][0]:
        raise ValueError("authoritative setup event order differs")
    if setup_deaths[1:] and (not setup_round_winners or
            not setup_round_winners[0][0] < setup_deaths[1][0]):
        raise ValueError("authoritative setup cleanup order differs")
    if setup_match_winners and (not setup_round_winners or
            not setup_round_winners[0][0] < setup_match_winners[0][0]):
        raise ValueError("authoritative setup winner order differs")
    segment = list(enumerate(lines[measured_start:], measured_start))
    deaths = [(index, line.split()[0], line.split()[1]) for index, line in segment
              if line.startswith("DEATH_")]
    round_winners = [(index, line.split()[1]) for index, line in segment
                     if line.startswith("ROUND_WINNER ")]
    match_winners = [(index, line.split()[1]) for index, line in segment
                     if line.startswith("MATCH_WINNER ")]
    game_ends = [index for index, line in segment if line.startswith("GAME_END ")]
    if (not deaths or deaths[0][1:] != ("DEATH_SUICIDE", "role1") or
            len(round_winners) != 1 or round_winners[0][1] != "role2" or
            len(match_winners) != 1 or match_winners[0][1] != "role2" or
            len(game_ends) != 1):
        raise ValueError("authoritative exact 1v1 role2 result differs")
    cleanup_deaths = deaths[1:]
    if (len(cleanup_deaths) > 1 or
            any(event != "DEATH_SUICIDE" or player != "role2"
                for _index, event, player in cleanup_deaths)):
        raise ValueError("authoritative exact 1v1 cleanup differs")
    if not (measured_start < deaths[0][0] < round_winners[0][0] <
            match_winners[0][0] < game_ends[0]):
        raise ValueError("authoritative exact 1v1 event order differs")
    if cleanup_deaths and not (round_winners[0][0] < cleanup_deaths[0][0] < game_ends[0]):
        raise ValueError("authoritative exact 1v1 cleanup order differs")
    return {"events": EXPECTED_EVENTS, "loser": "role1", "winner": "role2"}


def browser_input_counts(path, state_field):
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
        inputs = state.get(state_field, {}).get("input", {})
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
            "nativeClient", "nativeClientImage", "nativeServer",
            "nativeServerImage", "webData", "webJs", "webWasm"}:
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
            "role1KeyDown": 1, "role1KeyUp": 1,
            "role1AcceptedTurns": 1, "role2AcceptedTurns": 0}:
        raise ValueError("trial {0}: native accepted input proof differs".format(index))
    if record.get("nativeSetupInput") != {
            "role1KeyDown": 1, "role1KeyUp": 1,
            "role1AcceptedTurns": 1, "role2AcceptedTurns": 0}:
        raise ValueError("trial {0}: native setup input proof differs".format(index))
    for name in ("nativeBoundary", "browserBoundary"):
        try:
            match_boundary(record.get(name))
        except ValueError:
            raise ValueError("trial {0}: {1} differs".format(index, name))
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
        if role1 != {"keyDown": 1, "keyUp": 1, "acceptedTurns": 1} or \
                role2 != {"keyDown": 0, "keyUp": 0, "acceptedTurns": 0}:
            raise ValueError("trial {0}: raw native input proof differs".format(index))
        setup_role1 = native_input_counts(raw_dir / "native/setup-input-role1.log")
        setup_role2 = native_input_counts(raw_dir / "native/setup-input-role2.log")
        if setup_role1 != {"keyDown": 1, "keyUp": 1, "acceptedTurns": 1} or \
                setup_role2 != {"keyDown": 0, "keyUp": 0, "acceptedTurns": 0}:
            raise ValueError("trial {0}: raw native setup input proof differs".format(index))
        browser_inputs = browser_input_counts(raw_dir / "browser/states.json", "finalState")
        if browser_inputs != {
                "role1": {"keyDown": 1, "keyUp": 1, "sdlKeyDown": 1,
                          "sdlKeyUp": 1, "acceptedTurns": 1},
                "role2": {"keyDown": 0, "keyUp": 0, "sdlKeyDown": 0,
                          "sdlKeyUp": 0, "acceptedTurns": 0}}:
            raise ValueError("trial {0}: raw browser input proof differs".format(index))
        browser_setup_inputs = browser_input_counts(
            raw_dir / "browser/states.json", "setupInputState")
        if browser_setup_inputs != {
                "role1": {"keyDown": 1, "keyUp": 1, "sdlKeyDown": 1,
                          "sdlKeyUp": 1, "acceptedTurns": 1},
                "role2": {"keyDown": 0, "keyUp": 0, "sdlKeyDown": 0,
                          "sdlKeyUp": 0, "acceptedTurns": 0}}:
            raise ValueError("trial {0}: raw browser setup input proof differs".format(index))
        for arm in ("native", "browser"):
            console = (raw_dir / arm / "server-console.log").read_text(
                encoding="utf-8", errors="replace")
            if console.count("Resetting scores and starting new match after this round") != 1:
                raise ValueError("trial {0}: {1} reset acknowledgement differs".format(
                    index, arm))
        for arm, field in (("native", "nativeCanonical"), ("browser", "browserCanonical")):
            boundary = json.loads((raw_dir / arm / "boundary.json").read_text(
                encoding="ascii"))
            if boundary != record[arm + "Boundary"]:
                raise ValueError("trial {0}: raw {1} boundary differs".format(index, arm))
            try:
                result = authoritative_result(raw_dir / arm / "ladderlog.txt", boundary)
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
