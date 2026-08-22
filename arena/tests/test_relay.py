#!/usr/bin/env python3
"""Loopback proof that relay messages preserve UDP datagrams and reject abuse.

Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
"""

import importlib.util
import json
import os
import socket
import struct
import tempfile
import threading
import time
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = importlib.util.spec_from_file_location("arena_relay", os.path.join(ROOT, "relay.py"))
RELAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RELAY)
ORIGIN = "http://127.0.0.1:8000"


def receive_exact(connection, length):
    data = bytearray()
    while len(data) < length:
        chunk = connection.recv(length - len(data))
        if not chunk:
            raise ConnectionError("connection closed")
        data.extend(chunk)
    return bytes(data)


def send_frame(connection, payload, opcode=2):
    mask = b"\x11\x22\x33\x44"
    length = len(payload)
    if length < 126:
        header = bytes((0x80 | opcode, 0x80 | length))
    elif length <= 0xFFFF:
        header = bytes((0x80 | opcode, 0x80 | 126)) + struct.pack("!H", length)
    else:
        header = bytes((0x80 | opcode, 0x80 | 127)) + struct.pack("!Q", length)
    masked = bytes(value ^ mask[index & 3] for index, value in enumerate(payload))
    connection.sendall(header + mask + masked)


def receive_frame(connection):
    first, second = receive_exact(connection, 2)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", receive_exact(connection, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", receive_exact(connection, 8))[0]
    return first & 0x0F, receive_exact(connection, length)


class UDPRecorder:
    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", 0))
        self.messages = []
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    @property
    def address(self):
        return self.socket.getsockname()

    def _run(self):
        self.socket.settimeout(0.1)
        while self.running:
            try:
                payload, peer = self.socket.recvfrom(65536)
            except socket.timeout:
                continue
            self.messages.append(payload)
            self.socket.sendto(payload, peer)

    def close(self):
        self.running = False
        self.thread.join(timeout=1)
        self.socket.close()


class RelayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.secret = b"test-only-secret-material-32-bytes-long"
        cls.roster = tempfile.TemporaryDirectory()
        cls.udp = UDPRecorder()
        cls.server = RELAY.RelayServer(
            ("127.0.0.1", 0), cls.udp.address, cls.secret, [ORIGIN], 64, 2,
            max_nonces=64, roster_dir=cls.roster.name
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=1)
        cls.udp.close()
        cls.roster.cleanup()

    def ticket(self, nonce, session=None):
        return RELAY.mint_ticket(
            self.secret, "player", session or "session-" + nonce, nonce=nonce
        )

    def connect(self, ticket=None):
        connection = socket.create_connection(self.server.server_address, timeout=2)
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        protocols = RELAY.PROTOCOL
        if ticket:
            protocols += ", " + RELAY.AUTH_PREFIX + ticket
        request = (
            "GET /relay HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Key: " + key + "\r\n"
            "Sec-WebSocket-Version: 13\r\nOrigin: " + ORIGIN + "\r\n"
            "Sec-WebSocket-Protocol: " + protocols + "\r\n\r\n"
        )
        connection.sendall(request.encode("ascii"))
        response = bytearray()
        while b"\r\n\r\n" not in response:
            response.extend(connection.recv(4096))
        return connection, bytes(response)

    def wait_slot_released(self, session):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with self.server._lock:
                if (session, "player") not in self.server._active_slots:
                    return
            time.sleep(0.01)
        self.fail("relay did not release active session/player slot")

    def wait_roster_files(self, count):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            files = [
                name for name in os.listdir(self.roster.name)
                if name.isdigit()
            ]
            if len(files) == count:
                return files
            time.sleep(0.01)
        self.fail("relay roster file count did not become {0}".format(count))

    def test_binary_messages_are_complete_unchanged_datagrams(self):
        connection, response = self.connect(self.ticket("preserve"))
        self.assertIn(b"101 Switching Protocols", response)
        payloads = (b"\x00\xfffirst\x00", b"second-datagram")
        start = len(self.udp.messages)
        for payload in payloads:
            send_frame(connection, payload)
            opcode, echoed = receive_frame(connection)
            self.assertEqual(2, opcode)
            self.assertEqual(payload, echoed)
        self.assertEqual(list(payloads), self.udp.messages[start:start + 2])
        connection.close()

    def test_deterministic_loss_drops_only_selected_binary_datagrams(self):
        with tempfile.TemporaryDirectory() as roster, tempfile.NamedTemporaryFile() as evidence:
            udp = UDPRecorder()
            server = RELAY.RelayServer(
                ("127.0.0.1", 0), udp.address, self.secret, [ORIGIN], 64, 20,
                evidence_path=evidence.name, max_nonces=16, roster_dir=roster,
                drop_browser_to_native_every=2,
                drop_native_to_browser_every=2,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            original_server = self.server
            self.server = server
            try:
                connection, response = self.connect(self.ticket("shaped-loss"))
                self.assertIn(b"101 Switching Protocols", response)
                send_frame(connection, b"first")
                self.assertEqual((2, b"first"), receive_frame(connection))

                for payload in (b"drop-upstream", b"drop-downstream"):
                    send_frame(connection, payload)
                    connection.settimeout(0.2)
                    with self.assertRaises(socket.timeout):
                        receive_frame(connection)
                    connection.settimeout(2)
                    send_frame(connection, b"alive", opcode=9)
                    self.assertEqual((10, b"alive"), receive_frame(connection))

                send_frame(connection, b"fourth-dropped")
                connection.settimeout(0.2)
                with self.assertRaises(socket.timeout):
                    receive_frame(connection)
                connection.settimeout(2)
                send_frame(connection, b"fifth")
                self.assertEqual((2, b"fifth"), receive_frame(connection))
                connection.close()

                with open(evidence.name, encoding="utf-8") as source:
                    directions = [json.loads(line)["direction"] for line in source]
                self.assertEqual(2, directions.count("browser_to_native_dropped"))
                self.assertEqual(1, directions.count("native_to_browser_dropped"))
            finally:
                self.server = original_server
                server.shutdown()
                server.server_close()
                thread.join(timeout=1)
                udp.close()

    def test_missing_ticket_is_unauthorized(self):
        connection, response = self.connect()
        self.assertIn(b"401 Unauthorized", response)
        connection.close()

    def test_replayed_ticket_is_rejected(self):
        ticket = self.ticket("one-use")
        first, response = self.connect(ticket)
        self.assertIn(b"101 Switching Protocols", response)
        first.close()
        second, response = self.connect(ticket)
        self.assertIn(b"409 Conflict", response)
        second.close()

    def test_oversized_datagram_is_rejected(self):
        connection, response = self.connect(self.ticket("oversized"))
        self.assertIn(b"101 Switching Protocols", response)
        send_frame(connection, b"x" * 65)
        opcode, payload = receive_frame(connection)
        self.assertEqual(8, opcode)
        self.assertEqual(1009, struct.unpack("!H", payload[:2])[0])
        connection.close()

    def test_text_message_is_rejected(self):
        connection, response = self.connect(self.ticket("text"))
        self.assertIn(b"101 Switching Protocols", response)
        send_frame(connection, b"not-a-datagram", opcode=1)
        opcode, payload = receive_frame(connection)
        self.assertEqual(8, opcode)
        self.assertEqual(1003, struct.unpack("!H", payload[:2])[0])
        connection.close()

    def test_flood_is_rejected(self):
        connection, response = self.connect(self.ticket("flood"))
        self.assertIn(b"101 Switching Protocols", response)
        send_frame(connection, b"one")
        self.assertEqual((2, b"one"), receive_frame(connection))
        send_frame(connection, b"two")
        self.assertEqual((2, b"two"), receive_frame(connection))
        send_frame(connection, b"three")
        opcode, payload = receive_frame(connection)
        self.assertEqual(8, opcode)
        self.assertEqual(1008, struct.unpack("!H", payload[:2])[0])
        connection.close()

    def test_ping_flood_is_rejected_without_udp_traffic(self):
        connection, response = self.connect(self.ticket("ping-flood"))
        self.assertIn(b"101 Switching Protocols", response)
        start = len(self.udp.messages)
        for payload in (b"one", b"two"):
            send_frame(connection, payload, opcode=9)
            self.assertEqual((10, payload), receive_frame(connection))
        send_frame(connection, b"three", opcode=9)
        opcode, payload = receive_frame(connection)
        self.assertEqual(8, opcode)
        self.assertEqual(1008, struct.unpack("!H", payload[:2])[0])
        self.assertEqual(start, len(self.udp.messages))
        connection.close()

    def test_oversized_control_frame_is_rejected(self):
        connection, response = self.connect(self.ticket("large-ping"))
        self.assertIn(b"101 Switching Protocols", response)
        send_frame(connection, b"x" * 126, opcode=9)
        opcode, payload = receive_frame(connection)
        self.assertEqual(8, opcode)
        self.assertEqual(1002, struct.unpack("!H", payload[:2])[0])
        connection.close()

    def test_roster_file_tracks_authenticated_identity(self):
        connection, response = self.connect(self.ticket("roster", "roster-session"))
        self.assertIn(b"101 Switching Protocols", response)
        files = self.wait_roster_files(1)
        with open(os.path.join(self.roster.name, files[0]), encoding="ascii") as source:
            self.assertEqual(["player", "roster-session"], source.read().splitlines())
        connection.close()
        self.wait_roster_files(0)

    def test_distinct_ticket_duplicate_live_slot_is_rejected(self):
        session = "duplicate-live"
        first, response = self.connect(self.ticket("duplicate-a", session))
        self.assertIn(b"101 Switching Protocols", response)
        second, response = self.connect(self.ticket("duplicate-b", session))
        self.assertIn(b"409 Conflict", response)
        second.close()
        first.close()
        self.wait_slot_released(session)

    def test_fresh_ticket_reconnects_only_after_slot_release(self):
        session = "reconnect"
        first, response = self.connect(self.ticket("reconnect-a", session))
        self.assertIn(b"101 Switching Protocols", response)
        rejected = self.ticket("reconnect-b", session)
        second, response = self.connect(rejected)
        self.assertIn(b"409 Conflict", response)
        second.close()
        first.close()
        self.wait_slot_released(session)

        consumed, response = self.connect(rejected)
        self.assertIn(b"409 Conflict", response)
        consumed.close()
        reconnected, response = self.connect(self.ticket("reconnect-c", session))
        self.assertIn(b"101 Switching Protocols", response)
        reconnected.close()
        self.wait_slot_released(session)

    def test_expired_nonce_records_are_pruned(self):
        with self.server._lock:
            self.server._nonces["expired-fixture"] = int(time.time()) - 1
        identity = self.server.authenticate(self.ticket("prune"))
        try:
            with self.server._lock:
                self.assertNotIn("expired-fixture", self.server._nonces)
                self.assertLessEqual(len(self.server._nonces), self.server.max_nonces)
        finally:
            self.server.release(identity)

    def test_ticket_player_must_match_native_roster_syntax(self):
        ticket = RELAY.mint_ticket(self.secret, "not a player", "session")
        with self.assertRaises(RELAY.TokenError):
            RELAY.verify_ticket(self.secret, ticket)


if __name__ == "__main__":
    unittest.main(verbosity=2)
