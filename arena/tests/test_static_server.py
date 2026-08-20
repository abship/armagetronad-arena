#!/usr/bin/env python3
"""Verify static request evidence never retains the Arena ticket.

Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
"""

import contextlib
import functools
import http.server
import importlib.util
import io
import pathlib
import tempfile
import threading
import unittest
import urllib.request


ARENA_DIR = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("arena_static_server", ARENA_DIR / "static_server.py")
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


class StaticServerTest(unittest.TestCase):
    def test_query_ticket_is_redacted_from_request_log(self):
        secret = "credential-that-must-not-appear"
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory, "index.html").write_text("ok", encoding="utf-8")
            handler = functools.partial(SERVER.RedactingHandler, directory=directory)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with contextlib.redirect_stderr(output):
                    url = "http://127.0.0.1:{0}/index.html?ticket={1}".format(
                        server.server_port, secret
                    )
                    with urllib.request.urlopen(url, timeout=2) as response:
                        self.assertEqual(b"ok", response.read())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
        self.assertNotIn(secret, output.getvalue())
        self.assertIn("GET /index.html", output.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
