#!/usr/bin/env python3
"""Serve Arena artifacts without logging credential-bearing query strings.

Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
"""

import argparse
import functools
import http.server
import sys
import urllib.parse


class RedactingHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args):
        path = urllib.parse.urlsplit(self.path).path
        sys.stderr.write("{0} {1} {2}\n".format(self.address_string(), self.command, path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--directory", required=True)
    args = parser.parse_args()
    handler = functools.partial(RedactingHandler, directory=args.directory)
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
