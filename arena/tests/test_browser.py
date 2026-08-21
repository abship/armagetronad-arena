#!/usr/bin/env python3
"""Drive two real upstream Wasm clients through a W3C WebDriver endpoint.

Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
"""

import argparse
import base64
import collections
import importlib.util
import json
import math
import os
import pathlib
import re
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib


ARENA_DIR = pathlib.Path(__file__).resolve().parents[1]
RELAY_SPEC = importlib.util.spec_from_file_location("arena_relay", ARENA_DIR / "relay.py")
RELAY = importlib.util.module_from_spec(RELAY_SPEC)
RELAY_SPEC.loader.exec_module(RELAY)


def redact(value):
    return re.sub(r"([?&]ticket=)[^&#\s]+", r"\1[redacted]", str(value))[:1000]


def request(base, method, path, payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    call = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(call, timeout=timeout) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError("WebDriver HTTP {0}: {1}".format(error.code, error.read().decode("utf-8", "replace")))
    if isinstance(body, dict) and body.get("value") and isinstance(body["value"], dict):
        error_name = body["value"].get("error")
        if error_name:
            raise RuntimeError("WebDriver {0}: {1}".format(error_name, body["value"].get("message", "")))
    return body


def create_session(base, browser):
    body = request(
        base,
        "POST",
        "/session",
        {
            "capabilities": {
                "alwaysMatch": {
                    "browserName": browser,
                    "pageLoadStrategy": "none",
                    "acceptInsecureCerts": False,
                }
            }
        },
        timeout=60,
    )
    return body["value"]["sessionId"]


def execute(base, session, script):
    return request(
        base,
        "POST",
        "/session/{0}/execute/sync".format(session),
        {"script": script, "args": []},
    )["value"]


def find_element(base, session, selector):
    value = request(
        base,
        "POST",
        "/session/{0}/element".format(session),
        {"using": "css selector", "value": selector},
    )["value"]
    return value.get("element-6066-11e4-a52e-4f735466cecf") or value["ELEMENT"]


def send_turn_action(base, session, canvas, key):
    request(base, "POST", "/session/{0}/element/{1}/click".format(session, canvas), {})
    request(
        base,
        "POST",
        "/session/{0}/actions".format(session),
        {
            "actions": [
                {
                    "type": "key",
                    "id": "arena-controls",
                    "actions": [
                        {"type": "keyDown", "value": key},
                        {"type": "pause", "duration": 120},
                        {"type": "keyUp", "value": key},
                    ],
                }
            ]
        },
    )
    request(base, "DELETE", "/session/{0}/actions".format(session))


def capture_canvas(base, session):
    screenshot = request(
        base,
        "GET",
        "/session/{0}/screenshot".format(session),
    )["value"]
    png = base64.b64decode(screenshot)
    return {"png": png, "render": inspect_png(png)}


def paeth(left, above, upper_left):
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def inspect_png(png):
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("canvas screenshot is not PNG")
    offset = 8
    header = None
    compressed = []
    while offset < len(png):
        length = struct.unpack(">I", png[offset:offset + 4])[0]
        chunk_type = png[offset + 4:offset + 8]
        chunk = png[offset + 8:offset + 8 + length]
        offset += length + 12
        if chunk_type == b"IHDR":
            header = struct.unpack(">IIBBBBB", chunk)
        elif chunk_type == b"IDAT":
            compressed.append(chunk)
        elif chunk_type == b"IEND":
            break
    if not header or not compressed:
        raise RuntimeError("canvas screenshot has incomplete PNG data")

    width, height, depth, color_type, compression, filtering, interlace = header
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type)
    if depth != 8 or not channels or compression or filtering or interlace:
        raise RuntimeError("unsupported canvas PNG format: {0}".format(header))
    stride = width * channels
    raw = zlib.decompress(b"".join(compressed))
    if len(raw) != height * (stride + 1):
        raise RuntimeError("canvas PNG has unexpected decoded size")

    rows = []
    cursor = 0
    previous = bytearray(stride)
    for _row_number in range(height):
        filter_type = raw[cursor]
        source = raw[cursor + 1:cursor + 1 + stride]
        cursor += stride + 1
        row = bytearray(stride)
        for index, value in enumerate(source):
            left = row[index - channels] if index >= channels else 0
            above = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                decoded = value
            elif filter_type == 1:
                decoded = value + left
            elif filter_type == 2:
                decoded = value + above
            elif filter_type == 3:
                decoded = value + ((left + above) // 2)
            elif filter_type == 4:
                decoded = value + paeth(left, above, upper_left)
            else:
                raise RuntimeError("unsupported PNG row filter: {0}".format(filter_type))
            row[index] = decoded & 255
        rows.append(row)
        previous = row

    sample_step = max(1, int(math.sqrt((width * height) / 20000.0)))
    colors = collections.Counter()
    luminance = []
    for y in range(0, height, sample_step):
        row = rows[y]
        for x in range(0, width, sample_step):
            pixel = x * channels
            if color_type == 0:
                red = green = blue = row[pixel]
                alpha = 255
            elif color_type == 2:
                red, green, blue = row[pixel:pixel + 3]
                alpha = 255
            elif color_type == 4:
                red = green = blue = row[pixel]
                alpha = row[pixel + 1]
            else:
                red, green, blue, alpha = row[pixel:pixel + 4]
            if alpha:
                colors[(red, green, blue)] += 1
                luminance.append((299 * red + 587 * green + 114 * blue) // 1000)
    total = sum(colors.values())
    entropy = -sum(
        (count / total) * math.log(count / total, 2) for count in colors.values()
    ) if total else 0.0
    luminance_range = max(luminance) - min(luminance) if luminance else 0
    result = {
        "width": width,
        "height": height,
        "sampleCount": total,
        "distinctColors": len(colors),
        "colorEntropyBits": round(entropy, 4),
        "luminanceRange": luminance_range,
    }
    if len(colors) < 8 or entropy < 0.1 or luminance_range < 20:
        raise RuntimeError("canvas screenshot is blank or near-uniform: {0}".format(result))
    return result


def browser_state(base, session):
    return execute(
        base,
        session,
        """
return (function() {
  var canvas = document.getElementById('canvas');
  var transport = (typeof Module !== 'undefined') && Module['arenaSocketTransport'];
  var transportStatus = null;
  var statusError = null;
  try {
    transportStatus = transport && transport['status'] ? transport['status']() : null;
  } catch (error) {
    statusError = String(error).slice(0, 256);
  }
  return {
    canvasWidth: canvas ? canvas.width : 0,
    canvasHeight: canvas ? canvas.height : 0,
    documentReadyState: document.readyState,
    errors: (window.__arenaErrors || []).slice(-16),
    input: (typeof Module !== 'undefined') ? (Module['arenaInputStatus'] || null) : null,
    modulePresent: typeof Module !== 'undefined',
    stage: (typeof Module !== 'undefined') ? (Module['arenaClientStage'] || 'runtime-startup') : null,
    statusError: statusError,
    ticketVisible: window.location.href.indexOf('ticket=') !== -1,
    transport: transportStatus,
    title: document.title
  };
})();
""",
    )


def wait_for(predicate, timeout, description):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except (RuntimeError, urllib.error.URLError) as error:
            last = redact(error)
        time.sleep(0.25)
    raise RuntimeError("timed out waiting for {0}; last={1!r}".format(description, last))


def wait_for_state(base, session, timeout, description, accept):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = browser_state(base, session)
            if accept(last):
                return last
        except (RuntimeError, urllib.error.URLError) as error:
            last = {"webdriverError": redact(error)}
        time.sleep(0.25)
    raise RuntimeError("timed out waiting for {0}; last={1!r}".format(description, last))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--webdriver-url", default="http://127.0.0.1:4444")
    parser.add_argument("--browser", required=True, choices=("chrome", "firefox", "safari"))
    parser.add_argument("--client-url", default="http://127.0.0.1:8000/armagetronad_main.html")
    parser.add_argument("--relay-url", default="ws://127.0.0.1:8765")
    parser.add_argument("--server-log", required=True)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--timeout", type=int, default=150)
    args = parser.parse_args()

    secret_value = os.environ.get("ARENA_RELAY_SECRET", "")
    if len(secret_value) < 32:
        raise SystemExit("ARENA_RELAY_SECRET must contain at least 32 characters")
    secret = secret_value.encode("utf-8")
    evidence_dir = pathlib.Path(args.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    server_log = pathlib.Path(args.server_log)
    initial_log_size = server_log.stat().st_size if server_log.exists() else 0
    sessions = []
    evidence = []

    try:
        for number in (1, 2):
            player = (args.browser + str(number))[:16]
            ticket = RELAY.mint_ticket(secret, player, args.browser + "-1v1")
            query = urllib.parse.urlencode(
                {"relay": args.relay_url, "ticket": ticket, "player": player}
            )
            session = create_session(args.webdriver_url, args.browser)
            sessions.append((session, player))
            request(
                args.webdriver_url,
                "POST",
                "/session/{0}/url".format(session),
                {"url": args.client_url + "?" + query},
                timeout=10,
            )

        for number, (session, player) in enumerate(sessions):
            state = wait_for_state(
                args.webdriver_url,
                session,
                45,
                player + " Wasm canvas and authenticated datagram socket",
                lambda value: value.get("transport") and
                value["transport"].get("open", 0) >= 1 and
                value.get("canvasWidth", 0) > 0 and
                not value.get("ticketVisible"),
            )
            canvas = find_element(args.webdriver_url, session, "#canvas")
            key_name = "KeyA" if number == 0 else "KeyD"
            evidence.append({
                "player": player,
                "action": key_name + "," + ("KeyD" if number == 0 else "KeyA"),
                "actionCount": 2,
                "canvasElement": canvas,
                "initialState": state,
            })

        players = [player for _, player in sessions]

        def server_result():
            if not server_log.exists():
                return None
            with server_log.open("r", encoding="utf-8", errors="replace") as source:
                source.seek(initial_log_size)
                return source.read()

        def players_ready():
            text = server_result()
            if text is None:
                return None
            lines = text.splitlines()
            ready = all(
                any("TEAM_PLAYER_ADDED" in line and player in line for line in lines)
                for player in players
            )
            return text if ready else None

        wait_for(players_ready, 45, "both authoritative team entries")

        def both_players_live():
            states = [browser_state(args.webdriver_url, session) for session, _ in sessions]
            return states if all(
                value.get("stage") == "game-live" and
                value.get("input") and
                value["input"].get("localPlayerPresent") and
                value["input"].get("localObjectPresent") and
                value["input"].get("localObjectAlive") and
                value.get("transport") and
                value["transport"].get("open", 0) >= 1 and
                value["transport"].get("failed", 0) == 0
                for value in states
            ) else None

        live_states = wait_for(
            both_players_live, 60, "both live controlled upstream cycles"
        )
        for index, state in enumerate(live_states):
            evidence[index]["preActionState"] = state

        # Act immediately while both upstream-controlled cycle objects are
        # alive. A nonnegative game timer also covers the dead/inter-round phase.
        send_turn_action(
            args.webdriver_url,
            sessions[1][0],
            evidence[1]["canvasElement"],
            "d",
        )
        time.sleep(0.35)
        send_turn_action(
            args.webdriver_url,
            sessions[1][0],
            evidence[1]["canvasElement"],
            "a",
        )
        send_turn_action(
            args.webdriver_url,
            sessions[0][0],
            evidence[0]["canvasElement"],
            "a",
        )
        time.sleep(1.5)
        send_turn_action(
            args.webdriver_url,
            sessions[0][0],
            evidence[0]["canvasElement"],
            "d",
        )

        for index, (session, player) in enumerate(sessions):
            capture = wait_for(
                lambda session=session: capture_canvas(args.webdriver_url, session),
                45,
                player + " rendered arena after W3C turn",
            )
            (evidence_dir / (player + ".png")).write_bytes(capture["png"])
            evidence[index]["actionRender"] = capture["render"]

        for session, player in sessions:
            wait_for_state(
                args.webdriver_url,
                session,
                15,
                player + " received W3C controls in the browser",
                lambda value: value.get("input") and
                value["input"].get("keyDown", 0) >= 2 and
                value["input"].get("keyUp", 0) >= 2 and
                value["input"].get("acceptedActions", 0) >= 1,
            )

        def authoritative_result():
            text = server_result()
            if text is None:
                return None
            lines = text.splitlines()
            entered = all(
                any("PLAYER_ENTERED" in line and player in line for line in lines)
                for player in players
            )
            finished = any(
                "MATCH_WINNER" in line and any(player in line for player in players)
                for line in lines
            )
            return text if entered and finished else None

        result = wait_for(authoritative_result, args.timeout, "authoritative live-client 1v1 winner")
        (evidence_dir / (args.browser + "-result.log")).write_text(result, encoding="utf-8")
        for index, (session, player) in enumerate(sessions):
            final_state = wait_for_state(
                args.webdriver_url,
                session,
                15,
                player + " bidirectional datagram traffic",
                lambda value: value.get("transport") and
                value["transport"].get("open", 0) >= 1 and
                value["transport"].get("failed", 0) == 0 and
                value["transport"].get("sentDatagrams", 0) > 0 and
                value["transport"].get("receivedDatagrams", 0) > 0,
            )
            evidence[index]["finalState"] = final_state
            del evidence[index]["canvasElement"]
        (evidence_dir / (args.browser + "-states.json")).write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(
            args.browser +
            ": two rendered upstream Wasm clients exchanged datagrams, accepted W3C turns, " +
            "and completed an authoritative 1v1"
        )
    except Exception:
        diagnostics = []
        for index, (session, player) in enumerate(sessions):
            try:
                diagnostic = {"player": player, "state": browser_state(args.webdriver_url, session)}
                if index < len(evidence):
                    diagnostic["action"] = evidence[index].get("action")
                    diagnostic["actionCount"] = evidence[index].get("actionCount")
                    diagnostic["actionRender"] = evidence[index].get("actionRender")
                diagnostics.append(diagnostic)
                screenshot = request(
                    args.webdriver_url, "GET", "/session/{0}/screenshot".format(session)
                )["value"]
                (evidence_dir / (player + "-failure.png")).write_bytes(base64.b64decode(screenshot))
            except Exception as diagnostic_error:
                diagnostics.append({"player": player, "diagnosticError": redact(diagnostic_error)})
        (evidence_dir / (args.browser + "-failure.json")).write_text(
            json.dumps(diagnostics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        raise
    finally:
        for session, _player in sessions:
            try:
                request(args.webdriver_url, "DELETE", "/session/{0}".format(session), timeout=10)
            except Exception:
                pass


if __name__ == "__main__":
    main()
