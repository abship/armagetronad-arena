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
