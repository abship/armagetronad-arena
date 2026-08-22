#!/usr/bin/env python3
"""Small stdlib checks for the native/browser parity ledger."""

import importlib.util
import json
import pathlib
import tempfile
import unittest


ARENA = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("arena_parity", ARENA / "parity.py")
PARITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PARITY)


class ParityTests(unittest.TestCase):
    def build_inputs(self, root):
        for relative in PARITY.BUILD_PATHS.values():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(relative.encode("ascii"))
        for relative in ("arena/config/arena.cfg", "arena/config/native-parity.cfg",
                         "arena/config/parity-server.cfg",
                         "arena/resource/Arena/parity/forced_left-1.0.0.aamap.xml"):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((relative + "\n").encode("ascii"))

    def record(self, index=0, browser=None, raw=None):
        canonical = {"events": PARITY.EXPECTED_EVENTS, "loser": "role1",
                     "winner": "role2"}
        raw = raw or {name: str(position % 10) * 64
                      for position, name in enumerate(sorted(PARITY.RAW_PATHS))}
        return {
            "schema": PARITY.SCHEMA, "trial": index, "sourceCommit": "a" * 40,
            "attempt": 1,
            "buildSha256": {
                name: str(position + 1) * 64
                for position, name in enumerate(PARITY.BUILD_PATHS)
            },
            "configSha256": "c" * 64,
            "inputSchedule": PARITY.INPUT_SCHEDULE,
            "inputScheduleSha256": PARITY.hashlib.sha256(
                PARITY.INPUT_SCHEDULE.encode("ascii")).hexdigest(),
            "nativeInput": {"role1KeyDown": 1, "role1KeyUp": 1,
                            "role1AcceptedTurns": 1, "role2AcceptedTurns": 0},
            "nativeSetupInput": {"role1KeyDown": 1, "role1KeyUp": 1,
                                 "role1AcceptedTurns": 1, "role2AcceptedTurns": 0},
            "nativeBoundary": {"setupNewMatch": 1, "measuredNewMatch": 2},
            "browserBoundary": {"setupNewMatch": 1, "measuredNewMatch": 2},
            "rawSha256": raw,
            "browser": "chrome" if index % 2 == 0 else "firefox",
            "nativeCanonical": canonical,
            "browserCanonical": canonical if browser is None else browser,
            "nativeServer": {"fresh": True, "gameEnd": True,
                             "logSha256": raw["native/ladderlog.txt"],
                             "recordingSha256": raw["native/match.aarec"]},
            "browserServer": {"fresh": True, "gameEnd": True,
                              "logSha256": raw["browser/ladderlog.txt"],
                              "recordingSha256": raw["browser/match.aarec"]},
        }

    def write_raw(self, evidence, index=0):
        raw_dir = evidence / "raw" / "trial-{0:03d}".format(index)
        values = {}
        for name in PARITY.RAW_PATHS:
            path = raw_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if name in ("native/input-role1.log", "native/setup-input-role1.log"):
                data = "KEY 1 97 0 1\nKEY 0 97 0 1\nACTION CYCLE_TURN_LEFT 1 1 1\n"
            elif name in ("native/input-role2.log", "native/setup-input-role2.log"):
                data = ""
            elif name == "browser/states.json":
                data = json.dumps([
                    {"player": "role1",
                     "setupInputState": {"input": {
                         "keyDown": 1, "keyUp": 1, "sdlKeyDown": 1,
                         "sdlKeyUp": 1, "acceptedActions": 1}},
                     "finalState": {"input": {
                         "keyDown": 1, "keyUp": 1, "sdlKeyDown": 1,
                         "sdlKeyUp": 1, "acceptedActions": 1}}},
                    {"player": "role2",
                     "setupInputState": {"input": {
                         "keyDown": 0, "keyUp": 0, "sdlKeyDown": 0,
                         "sdlKeyUp": 0, "acceptedActions": 0}},
                     "finalState": {"input": {
                         "keyDown": 0, "keyUp": 0, "sdlKeyDown": 0,
                         "sdlKeyUp": 0, "acceptedActions": 0}}},
                ]) + "\n"
            elif name.endswith("boundary.json"):
                data = '{"measuredNewMatch":2,"setupNewMatch":1}\n'
            elif name.endswith("ladderlog.txt"):
                data = ("PLAYER_ENTERED role1 0.0.0.0\nPLAYER_ENTERED role2 0.0.0.0\n"
                        "NEW_MATCH setup\nDEATH_SUICIDE role1\n"
                        "NEW_MATCH controlled\nDEATH_SUICIDE role1\n"
                        "ROUND_WINNER role2 role2\nDEATH_SUICIDE role2\n"
                        "MATCH_WINNER role2 10\nGAME_END 0\n")
            elif name.endswith("server-console.log"):
                data = "Resetting scores and starting new match after this round.\n"
            else:
                data = name + "\n"
            path.write_text(data, encoding="ascii")
            values[name] = PARITY.file_sha256(path)
        return values

    def test_canonical_equality_ignores_object_order(self):
        self.assertEqual(PARITY.canonical_json({"b": 2, "a": [1]}),
                         PARITY.canonical_json({"a": [1], "b": 2}))

    def test_shard_is_bounded(self):
        self.assertEqual(list(PARITY.shard_indices(2, 10, 100)), list(range(2, 100, 10)))
        with self.assertRaises(ValueError):
            list(PARITY.shard_indices(10, 10, 100))

    def test_input_manifest_is_bound_to_exact_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            self.build_inputs(root)
            path = root / "INPUT-MANIFEST.json"
            path.write_bytes(PARITY.canonical_json(
                PARITY.expected_input_manifest(root, "a" * 40)) + b"\n")
            manifest = PARITY.validate_input_manifest(path, root, "a" * 40)
            self.assertEqual(manifest["inputSchedule"], PARITY.INPUT_SCHEDULE)
            (root / PARITY.BUILD_PATHS["webWasm"]).write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "differs"):
                PARITY.validate_input_manifest(path, root, "a" * 40)

    def test_verify_rejects_mismatch_and_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = pathlib.Path(temporary)
            (evidence / "trials").mkdir()
            raw = self.write_raw(evidence)
            (evidence / "trials" / "trial-000.json").write_text(json.dumps(self.record(raw=raw)))
            self.assertEqual(len(PARITY.verify(evidence, [0], "a" * 40)), 1)
            (evidence / "trials" / "trial-000.json").write_text(
                json.dumps(self.record(browser={"events": [], "winner": "role1"}, raw=raw)))
            with self.assertRaisesRegex(ValueError, "differs"):
                PARITY.verify(evidence, [0], "a" * 40)
            with self.assertRaisesRegex(ValueError, "union"):
                PARITY.verify(evidence, [1], "a" * 40)

    def test_verify_rehashes_raw_input_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = pathlib.Path(temporary)
            (evidence / "trials").mkdir()
            raw = self.write_raw(evidence)
            (evidence / "trials" / "trial-000.json").write_text(json.dumps(self.record(raw=raw)))
            (evidence / "raw/trial-000/native/input-role1.log").write_text("", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "digest differs"):
                PARITY.verify(evidence, [0], "a" * 40)

    def test_verify_rejects_extra_browser_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = pathlib.Path(temporary)
            (evidence / "trials").mkdir()
            raw = self.write_raw(evidence)
            states_path = evidence / "raw/trial-000/browser/states.json"
            states = json.loads(states_path.read_text(encoding="utf-8"))
            states[0]["finalState"]["input"]["keyDown"] = 4
            states_path.write_text(json.dumps(states) + "\n", encoding="ascii")
            raw["browser/states.json"] = PARITY.file_sha256(states_path)
            (evidence / "trials" / "trial-000.json").write_text(
                json.dumps(self.record(raw=raw)), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "browser input proof differs"):
                PARITY.verify(evidence, [0], "a" * 40)

    def test_authoritative_result_rejects_extra_player(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "ladderlog.txt"
            path.write_text("PLAYER_ENTERED role1 x\nPLAYER_ENTERED role2 x\n"
                            "PLAYER_ENTERED extra x\nNEW_MATCH setup\n"
                            "NEW_MATCH controlled\nDEATH_SUICIDE role1\n"
                            "ROUND_WINNER role2 x\nMATCH_WINNER role2 x\nGAME_END x\n")
            with self.assertRaisesRegex(ValueError, "exact 1v1"):
                PARITY.authoritative_result(
                    path, {"setupNewMatch": 1, "measuredNewMatch": 2})

    def test_authoritative_result_rejects_reversed_result_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "ladderlog.txt"
            path.write_text("PLAYER_ENTERED role1 x\nPLAYER_ENTERED role2 x\n"
                            "NEW_MATCH setup\nDEATH_SUICIDE role1\nNEW_MATCH controlled\n"
                            "MATCH_WINNER role2 x\nDEATH_SUICIDE role1\n"
                            "ROUND_WINNER role2 x\nGAME_END x\n")
            with self.assertRaisesRegex(ValueError, "event order"):
                PARITY.authoritative_result(
                    path, {"setupNewMatch": 1, "measuredNewMatch": 2})

    def test_authoritative_result_rejects_unexpected_setup_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "ladderlog.txt"
            path.write_text("PLAYER_ENTERED role1 x\nPLAYER_ENTERED role2 x\n"
                            "NEW_MATCH setup\nDEATH_SUICIDE role2\n"
                            "NEW_MATCH controlled\nDEATH_SUICIDE role1\n"
                            "ROUND_WINNER role2 x\nMATCH_WINNER role2 x\nGAME_END x\n")
            with self.assertRaisesRegex(ValueError, "setup result"):
                PARITY.authoritative_result(
                    path, {"setupNewMatch": 1, "measuredNewMatch": 2})

    def test_authoritative_result_accepts_bounded_pre_admission_round(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "ladderlog.txt"
            path.write_text(
                "PLAYER_ENTERED role1 x\nNEW_MATCH prelude\n"
                "PLAYER_ENTERED role2 x\nDEATH_SUICIDE role1\n"
                "NEW_MATCH setup\nDEATH_SUICIDE role1\nROUND_WINNER role2 x\n"
                "MATCH_WINNER role2 x\nNEW_MATCH controlled\n"
                "DEATH_SUICIDE role1\nROUND_WINNER role2 x\n"
                "MATCH_WINNER role2 x\nGAME_END x\n")
            self.assertEqual(
                PARITY.authoritative_result(
                    path, {"setupNewMatch": 2, "measuredNewMatch": 3})["winner"],
                "role2")

    def test_authoritative_result_rejects_unbounded_prelude(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "ladderlog.txt"
            path.write_text(
                "PLAYER_ENTERED role1 x\nNEW_MATCH prelude\n"
                "PLAYER_ENTERED role2 x\nDEATH_SUICIDE role2\n"
                "NEW_MATCH setup\nDEATH_SUICIDE role1\n"
                "NEW_MATCH controlled\nDEATH_SUICIDE role1\n"
                "ROUND_WINNER role2 x\nMATCH_WINNER role2 x\nGAME_END x\n")
            with self.assertRaisesRegex(ValueError, "pre-admission"):
                PARITY.authoritative_result(
                    path, {"setupNewMatch": 2, "measuredNewMatch": 3})

    def test_authoritative_result_rejects_boolean_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "ladderlog.txt"
            path.write_text("PLAYER_ENTERED role1 x\nPLAYER_ENTERED role2 x\n")
            with self.assertRaisesRegex(ValueError, "boundary"):
                PARITY.authoritative_result(
                    path, {"setupNewMatch": True, "measuredNewMatch": 2})

    def test_record_rejects_retry_and_schedule_drift(self):
        retry = self.record()
        retry["attempt"] = 2
        with self.assertRaisesRegex(ValueError, "retry"):
            PARITY.validate_record(retry, 0, "a" * 40)
        drift = self.record()
        drift["inputSchedule"] = "role1:none;role2:none"
        with self.assertRaisesRegex(ValueError, "schedule differs"):
            PARITY.validate_record(drift, 0, "a" * 40)


if __name__ == "__main__":
    unittest.main()
