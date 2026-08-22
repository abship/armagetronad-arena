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
        for relative in ("arena/config/arena.cfg", "arena/config/native-parity.cfg"):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((relative + "\n").encode("ascii"))

    def record(self, index=0, browser=None, raw=None):
        canonical = {"events": PARITY.EXPECTED_EVENTS, "winner": "role2"}
        raw = raw or {name: str(position % 10) * 64
                      for position, name in enumerate(sorted(PARITY.RAW_PATHS))}
        return {
            "schema": PARITY.SCHEMA, "trial": index, "sourceCommit": "a" * 40,
            "attempt": 1,
            "buildSha256": {"nativeClient": "b" * 64,
                            "nativeServer": "2" * 64, "webWasm": "3" * 64},
            "configSha256": "c" * 64,
            "inputSchedule": PARITY.INPUT_SCHEDULE,
            "inputScheduleSha256": PARITY.hashlib.sha256(
                PARITY.INPUT_SCHEDULE.encode("ascii")).hexdigest(),
            "nativeInput": {"role1KeyDown": 2, "role1KeyUp": 2,
                            "role1AcceptedTurns": 2, "role2AcceptedTurns": 0},
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
            if name == "native/input-role1.log":
                data = ("KEY 1 97 0 1\nKEY 0 97 0 1\nACTION CYCLE_TURN_LEFT 1 1 1\n") * 2
            elif name == "native/input-role2.log":
                data = ""
            elif name.endswith("ladderlog.txt"):
                data = ("PLAYER_ENTERED role1 0.0.0.0\nPLAYER_ENTERED role2 0.0.0.0\n"
                        "MATCH_WINNER role2 10\nGAME_END 0\n")
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

    def test_authoritative_result_rejects_extra_player(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "ladderlog.txt"
            path.write_text("PLAYER_ENTERED role1 x\nPLAYER_ENTERED role2 x\n"
                            "PLAYER_ENTERED extra x\nMATCH_WINNER role2 x\nGAME_END x\n")
            with self.assertRaisesRegex(ValueError, "exact 1v1"):
                PARITY.authoritative_result(path)

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
