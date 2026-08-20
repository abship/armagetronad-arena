#!/usr/bin/env python3
"""Authenticated WebSocket-message to UDP-datagram relay for Arena.

Copyright (C) 2026 Arena contributors

This program is free software; you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the Free
Software Foundation; either version 2 of the License, or (at your option)
any later version. See COPYING.txt.
"""

import argparse
import base64
import collections
import hashlib
import hmac
import json
import os
import secrets
import select
import socket
import socketserver
import ssl
import struct
import sys
import threading
import time


WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
PROTOCOL = "arena-datagram-v1"
AUTH_PREFIX = "arena-auth-"
MAX_TICKET_TTL = 300
PROTOCOL_MAX_DATAGRAM = 2048


def _b64encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def mint_ticket(secret, player, session, ttl=60, nonce=None, now=None):
    """Create a short-lived, one-use relay credential."""
    if ttl <= 0 or ttl > MAX_TICKET_TTL:
        raise ValueError("ticket ttl must be between 1 and 300 seconds")
    issued = int(time.time() if now is None else now)
    payload = json.dumps(
        {
            "exp": issued + int(ttl),
            "nonce": nonce or secrets.token_urlsafe(18),
            "player": player,
            "session": session,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded = _b64encode(payload)
    signature = _b64encode(hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest())
    return encoded + "." + signature


class TokenError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def verify_ticket(secret, ticket, now=None):
    try:
        encoded, signature = ticket.split(".", 1)
        expected = hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(signature)):
            raise TokenError(401, "invalid credential")
        payload = json.loads(_b64decode(encoded))
    except TokenError:
        raise
    except (ValueError, UnicodeError, json.JSONDecodeError):
        raise TokenError(401, "invalid credential")

    timestamp = int(time.time() if now is None else now)
    if payload.get("exp", 0) <= timestamp:
        raise TokenError(401, "expired credential")
    if payload.get("exp", 0) > timestamp + MAX_TICKET_TTL:
        raise TokenError(401, "credential lifetime too long")
    for key, maximum in (("nonce", 64), ("player", 32), ("session", 64)):
        value = payload.get(key)
        if not isinstance(value, str) or not value or len(value) > maximum:
            raise TokenError(401, "invalid credential")
    return payload


class RelayServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, udp_target, secret, allowed_origins, max_datagram,
                 max_rate, evidence_path=None, max_nonces=65536):
        self.udp_target = udp_target
        self.secret = secret
        self.allowed_origins = set(allowed_origins)
        self.max_datagram = max_datagram
        self.max_rate = max_rate
        self.max_nonces = max_nonces
        self.evidence_path = evidence_path
        self._nonces = {}
        self._active_slots = set()
        self._lock = threading.Lock()
        super().__init__(address, RelayHandler)

    def authenticate(self, ticket):
        timestamp = int(time.time())
        identity = verify_ticket(self.secret, ticket, timestamp)
        slot = (identity["session"], identity["player"])
        with self._lock:
            expired = [nonce for nonce, expiry in self._nonces.items() if expiry <= timestamp]
            for nonce in expired:
                del self._nonces[nonce]
            nonce = identity["nonce"]
            if nonce in self._nonces:
                raise TokenError(409, "credential already used")
            if len(self._nonces) >= self.max_nonces:
                raise TokenError(503, "credential state full")
            self._nonces[nonce] = identity["exp"]
            if slot in self._active_slots:
                raise TokenError(409, "session player slot already active")
            self._active_slots.add(slot)
        return identity

    def release(self, identity):
        with self._lock:
            self._active_slots.discard((identity["session"], identity["player"]))

    def record(self, direction, identity, datagram):
        if not self.evidence_path:
            return
        entry = json.dumps(
            {
                "direction": direction,
                "player": identity["player"],
                "session": identity["session"],
                "sha256": hashlib.sha256(datagram).hexdigest(),
                "size": len(datagram),
                "time_ns": time.time_ns(),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        with self._lock:
            with open(self.evidence_path, "a", encoding="utf-8") as output:
                output.write(entry + "\n")


class RelayHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.upgraded = False
        self.identity = None
        self.request.settimeout(5)
        try:
            identity = self._handshake()
            self.upgraded = True
            self._relay(identity)
        except TokenError as error:
            if not self.upgraded:
                self._http_error(error.status, str(error))
        except (ConnectionError, OSError, ValueError):
            return
        finally:
            if self.identity:
                self.server.release(self.identity)

    def _handshake(self):
        request = bytearray()
        while b"\r\n\r\n" not in request:
            chunk = self.request.recv(4096)
            if not chunk:
                raise ConnectionError("closed during handshake")
            request.extend(chunk)
            if len(request) > 16384:
                raise TokenError(431, "request headers too large")

        lines = bytes(request).split(b"\r\n")
        if not lines or not lines[0].startswith(b"GET "):
            raise TokenError(400, "WebSocket GET required")
        headers = {}
        for line in lines[1:]:
            if not line:
                break
            if b":" not in line:
                raise TokenError(400, "invalid header")
            name, value = line.split(b":", 1)
            headers[name.strip().lower()] = value.strip().decode("latin1")

        if headers.get(b"upgrade", "").lower() != "websocket" or headers.get(b"sec-websocket-version") != "13":
            raise TokenError(426, "WebSocket version 13 required")
        origin = headers.get(b"origin", "")
        if self.server.allowed_origins and origin not in self.server.allowed_origins:
            raise TokenError(403, "origin not allowed")

        protocols = [value.strip() for value in headers.get(b"sec-websocket-protocol", "").split(",")]
        ticket_protocol = next((value for value in protocols if value.startswith(AUTH_PREFIX)), "")
        if PROTOCOL not in protocols or not ticket_protocol:
            raise TokenError(401, "relay credential required")
        identity = self.server.authenticate(ticket_protocol[len(AUTH_PREFIX):])
        self.identity = identity

        key = headers.get(b"sec-websocket-key")
        if not key:
            raise TokenError(400, "WebSocket key required")
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode("ascii")).digest()).decode("ascii")
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: " + accept + "\r\n"
            "Sec-WebSocket-Protocol: " + PROTOCOL + "\r\n\r\n"
        )
        self.request.sendall(response.encode("ascii"))
        return identity

    def _relay(self, identity):
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            udp.connect(self.server.udp_target)
            udp.setblocking(False)
            self.request.settimeout(5)
            recent = collections.deque()
            while True:
                readable, _, _ = select.select((self.request, udp), (), (), 1)
                if self.request in readable:
                    datagram = self._read_binary_frame()
                    if datagram is None:
                        return
                    timestamp = time.monotonic()
                    while recent and recent[0] <= timestamp - 1:
                        recent.popleft()
                    if len(recent) >= self.server.max_rate:
                        self._close(1008, "rate limit")
                        return
                    recent.append(timestamp)
                    udp.send(datagram)
                    self.server.record("browser_to_native", identity, datagram)
                if udp in readable:
                    datagram = udp.recv(65536)
                    if len(datagram) > self.server.max_datagram:
                        self._close(1009, "native datagram too large")
                        return
                    self._send_frame(2, datagram)
                    self.server.record("native_to_browser", identity, datagram)
        finally:
            udp.close()

    def _read_exact(self, length):
        data = bytearray()
        while len(data) < length:
            chunk = self.request.recv(length - len(data))
            if not chunk:
                raise ConnectionError("WebSocket closed")
            data.extend(chunk)
        return bytes(data)

    def _read_binary_frame(self):
        first, second = self._read_exact(2)
        final = first & 0x80
        opcode = first & 0x0F
        masked = second & 0x80
        length = second & 0x7F
        if not final or first & 0x70 or not masked:
            self._close(1002, "invalid frame")
            return None
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        if length > self.server.max_datagram:
            self._close(1009, "datagram too large")
            return None
        mask = self._read_exact(4)
        payload = bytearray(self._read_exact(length))
        for index in range(length):
            payload[index] ^= mask[index & 3]
        if opcode == 8:
            return None
        if opcode == 9:
            self._send_frame(10, payload)
            return self._read_binary_frame()
        if opcode != 2:
            self._close(1003, "binary datagrams required")
            return None
        return bytes(payload)

    def _send_frame(self, opcode, payload):
        length = len(payload)
        if length < 126:
            header = bytes((0x80 | opcode, length))
        elif length <= 0xFFFF:
            header = bytes((0x80 | opcode, 126)) + struct.pack("!H", length)
        else:
            header = bytes((0x80 | opcode, 127)) + struct.pack("!Q", length)
        self.request.sendall(header + payload)

    def _close(self, code, reason):
        payload = struct.pack("!H", code) + reason.encode("utf-8")[:123]
        self._send_frame(8, payload)

    def _http_error(self, status, message):
        reasons = {400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
                   409: "Conflict", 426: "Upgrade Required", 431: "Request Header Fields Too Large",
                   503: "Service Unavailable"}
        body = (message + "\n").encode("utf-8")
        response = (
            "HTTP/1.1 {0} {1}\r\nConnection: close\r\n"
            "Content-Type: text/plain\r\nContent-Length: {2}\r\n\r\n"
        ).format(status, reasons.get(status, "Error"), len(body)).encode("ascii")
        self.request.sendall(response + body)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=8765)
    parser.add_argument("--udp-host", default="127.0.0.1")
    parser.add_argument("--udp-port", type=int, default=4534)
    parser.add_argument("--secret-env", default="ARENA_RELAY_SECRET")
    parser.add_argument("--allow-origin", action="append", default=[])
    parser.add_argument("--max-datagram", type=int, default=2048)
    parser.add_argument("--max-rate", type=int, default=256)
    parser.add_argument("--evidence")
    parser.add_argument("--tls-cert")
    parser.add_argument("--tls-key")
    parser.add_argument("--max-nonces", type=int, default=65536)
    parser.add_argument("--mint-ticket", action="store_true")
    parser.add_argument("--player")
    parser.add_argument("--session")
    parser.add_argument("--ttl", type=int, default=60)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.max_datagram <= 0 or args.max_datagram > PROTOCOL_MAX_DATAGRAM:
        raise SystemExit("--max-datagram must be between 1 and 2048 bytes")
    secret_value = os.environ.get(args.secret_env)
    if not secret_value or len(secret_value) < 32:
        raise SystemExit(args.secret_env + " must contain at least 32 characters")
    secret = secret_value.encode("utf-8")
    if args.mint_ticket:
        if not args.player or not args.session:
            raise SystemExit("--player and --session are required with --mint-ticket")
        print(mint_ticket(secret, args.player, args.session, args.ttl))
        return 0

    server = RelayServer(
        (args.listen_host, args.listen_port),
        (args.udp_host, args.udp_port),
        secret,
        args.allow_origin,
        args.max_datagram,
        args.max_rate,
        args.evidence,
        args.max_nonces,
    )
    if args.tls_cert or args.tls_key:
        if not args.tls_cert or not args.tls_key:
            raise SystemExit("--tls-cert and --tls-key must be supplied together")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.tls_cert, args.tls_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
