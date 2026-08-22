#!/usr/bin/env python3
"""Small Safari WebDriver helpers checks."""

import importlib.util
import os
import pathlib
import tempfile
import unittest
from unittest import mock


SOURCE = pathlib.Path(__file__).with_name("test_browser.py")
SPEC = importlib.util.spec_from_file_location("arena_test_browser", SOURCE)
BROWSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROWSER)


class SafariHelpersTest(unittest.TestCase):
    def test_selects_requested_iframe(self):
        with mock.patch.object(BROWSER, "request") as request, \
             mock.patch.object(BROWSER, "find_element", return_value="frame-element") as find:
            self.assertEqual("session", BROWSER.select_client("http://driver", ("session", "safari1", 1)))
        find.assert_called_once_with("http://driver", "session", "iframe:nth-of-type(2)")
        self.assertEqual(
            [
                mock.call("http://driver", "POST", "/session/session/frame", {"id": None}),
                mock.call(
                    "http://driver", "POST", "/session/session/frame",
                    {"id": {"element-6066-11e4-a52e-4f735466cecf": "frame-element"}},
                ),
            ],
            request.call_args_list,
        )

    def test_execute_forwards_script_arguments(self):
        with mock.patch.object(BROWSER, "request", return_value={"value": True}) as request:
            self.assertTrue(BROWSER.execute("http://driver", "session", "return arguments[0]", ["client"]))
        self.assertEqual(
            mock.call(
                "http://driver", "POST", "/session/session/execute/sync",
                {"script": "return arguments[0]", "args": ["client"]},
            ),
            request.call_args,
        )

    def test_waits_for_top_level_document(self):
        with mock.patch.object(BROWSER, "execute", side_effect=[False, True]) as execute, \
             mock.patch.object(BROWSER.time, "sleep"):
            self.assertTrue(BROWSER.wait_for_document(
                "http://driver", "session", "http://client/"
            ))
        self.assertEqual(2, execute.call_count)
        execute.assert_called_with(
            "http://driver",
            "session",
            "return document.readyState === 'complete' && location.href === arguments[0];",
            ["http://client/"],
        )

    def test_wait_for_state_retries_transient_null(self):
        expected = {"transport": {"open": 1}}
        with mock.patch.object(BROWSER, "browser_state", side_effect=[None, expected]) as state, \
             mock.patch.object(BROWSER.time, "sleep"):
            self.assertEqual(
                expected,
                BROWSER.wait_for_state(
                    "http://driver", ("session", "player", None), 1,
                    "browser state", lambda value: value.get("transport"),
                ),
            )
        self.assertEqual(2, state.call_count)

    def test_frame_metric_thresholds(self):
        summary = BROWSER.summarize_frame_metrics({
            "gaps": list(range(1, 21)),
            "initialHeapBytes": 64 * BROWSER.MIB,
            "heapBytes": 80 * BROWSER.MIB,
        })
        self.assertEqual(19.0, summary["p95GapMs"])
        self.assertEqual(0, summary["severeGapCount"])
        self.assertTrue(BROWSER.frame_metrics_pass(summary))
        isolated_outlier = BROWSER.summarize_frame_metrics({
            "gaps": [16] * 99 + [3000],
            "initialHeapBytes": 64 * BROWSER.MIB,
            "heapBytes": 64 * BROWSER.MIB,
        })
        self.assertTrue(BROWSER.frame_metrics_pass(isolated_outlier))
        repeated_outliers = BROWSER.summarize_frame_metrics({
            "gaps": [16] * 98 + [1000, 3000],
            "initialHeapBytes": 64 * BROWSER.MIB,
            "heapBytes": 64 * BROWSER.MIB,
        })
        self.assertFalse(BROWSER.frame_metrics_pass(repeated_outliers))
        for field, value in (
            ("sampleCount", 19),
            ("p95GapMs", 251),
            ("severeGapCount", 2),
            ("maxGapMs", 3501),
            ("heapBytes", 257 * BROWSER.MIB),
            ("heapGrowthBytes", 33 * BROWSER.MIB),
            ("sampleOverflow", True),
        ):
            rejected = dict(summary)
            rejected[field] = value
            with self.subTest(field=field):
                self.assertFalse(BROWSER.frame_metrics_pass(rejected))

    def test_turn_reselects_frame_and_refinds_canvas(self):
        client = ("session", "safari2", 1)
        with mock.patch.object(BROWSER, "select_client", return_value="session") as select, \
             mock.patch.object(BROWSER, "find_element", return_value="fresh-canvas") as find, \
             mock.patch.object(BROWSER, "send_turn_action") as send:
            BROWSER.send_client_turn("http://driver", client, "d")
        select.assert_called_once_with("http://driver", client)
        find.assert_called_once_with("http://driver", "session", "#canvas")
        send.assert_called_once_with("http://driver", "session", "fresh-canvas", "d")

    def test_resets_only_browser_input_evidence(self):
        client = ("session", "role1", None)
        with mock.patch.object(BROWSER, "select_client", return_value="session") as select, \
             mock.patch.object(BROWSER, "execute", return_value=True) as execute:
            self.assertTrue(BROWSER.reset_input_evidence("http://driver", client))
        select.assert_called_once_with("http://driver", client)
        self.assertIn("acceptedActions", execute.call_args.args[2])

    def test_server_command_requires_fifo_and_writes_atomically(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "control"
            os.mkfifo(path)
            reader = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK)
            try:
                BROWSER.send_server_command(path, "START_NEW_MATCH")
                self.assertEqual(b"START_NEW_MATCH\n", os.read(reader, 128))
            finally:
                os.close(reader)
            path.unlink()
            path.write_text("not a fifo", encoding="ascii")
            with self.assertRaisesRegex(RuntimeError, "not a FIFO"):
                BROWSER.send_server_command(path, "QUIT")


if __name__ == "__main__":
    unittest.main()
