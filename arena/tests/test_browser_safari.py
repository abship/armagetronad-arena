#!/usr/bin/env python3
"""Small Safari WebDriver helpers checks."""

import importlib.util
import pathlib
import unittest
from unittest import mock


SOURCE = pathlib.Path(__file__).with_name("test_browser.py")
SPEC = importlib.util.spec_from_file_location("arena_test_browser", SOURCE)
BROWSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROWSER)


class SafariHelpersTest(unittest.TestCase):
    def test_selects_requested_iframe(self):
        with mock.patch.object(BROWSER, "request") as request:
            self.assertEqual("session", BROWSER.select_client("http://driver", ("session", "safari1", 1)))
        self.assertEqual(
            [
                mock.call("http://driver", "POST", "/session/session/frame", {"id": None}),
                mock.call("http://driver", "POST", "/session/session/frame", {"id": 1}),
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

    def test_turn_reselects_frame_and_refinds_canvas(self):
        client = ("session", "safari2", 1)
        with mock.patch.object(BROWSER, "select_client", return_value="session") as select, \
             mock.patch.object(BROWSER, "find_element", return_value="fresh-canvas") as find, \
             mock.patch.object(BROWSER, "send_turn_action") as send:
            BROWSER.send_client_turn("http://driver", client, "d")
        select.assert_called_once_with("http://driver", client)
        find.assert_called_once_with("http://driver", "session", "#canvas")
        send.assert_called_once_with("http://driver", "session", "fresh-canvas", "d")


if __name__ == "__main__":
    unittest.main()
