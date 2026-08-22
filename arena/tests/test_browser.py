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
import stat
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
MIB = 1024 * 1024


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


def execute(base, session, script, arguments=None):
    return request(
        base,
        "POST",
        "/session/{0}/execute/sync".format(session),
        {"script": script, "args": arguments or []},
    )["value"]


def find_element(base, session, selector):
    value = request(
        base,
        "POST",
        "/session/{0}/element".format(session),
        {"using": "css selector", "value": selector},
    )["value"]
    return value.get("element-6066-11e4-a52e-4f735466cecf") or value["ELEMENT"]


def select_client(base, client):
    session, _player, frame = client
    if frame is not None:
        request(base, "POST", "/session/{0}/frame".format(session), {"id": None})
        frame_element = find_element(
            base, session, "iframe:nth-of-type({0})".format(frame + 1)
        )
        request(
            base,
            "POST",
            "/session/{0}/frame".format(session),
            {"id": {"element-6066-11e4-a52e-4f735466cecf": frame_element}},
        )
    return session


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


def send_client_turn(base, client, key):
    session = select_client(base, client)
    canvas = find_element(base, session, "#canvas")
    send_turn_action(base, session, canvas, key)


def capture_canvas(base, session):
    execute(
        base,
        session,
        """
Module['arenaCapturedFrame'] = null;
Module['arenaCaptureRequested'] = true;
return true;
""",
    )
    data_url = wait_for(
        lambda: execute(
            base,
            session,
            "return Module['arenaCapturedFrame'] || null;",
        ),
        5,
        "upstream frame capture before clear",
    )
    prefix = "data:image/png;base64,"
    if not isinstance(data_url, str) or not data_url.startswith(prefix):
        raise RuntimeError("canvas did not return a PNG data URL")
    png = base64.b64decode(data_url[len(prefix):], validate=True)
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
    dominant_count = max(colors.values()) if colors else 0
    non_dominant = total - dominant_count
    luminance_range = max(luminance) - min(luminance) if luminance else 0
    result = {
        "width": width,
        "height": height,
        "sampleCount": total,
        "distinctColors": len(colors),
        "colorEntropyBits": round(entropy, 4),
        "luminanceRange": luminance_range,
        "nonDominantSamples": non_dominant,
    }
    if len(colors) < 3 or non_dominant < 64 or entropy < 0.1 or luminance_range < 20:
        raise RuntimeError("canvas screenshot is blank or near-uniform: {0}".format(result))
    return result


def summarize_frame_metrics(metrics):
    gaps = sorted(float(value) for value in metrics.get("gaps", []))
    p95_rank = max(0, int(math.ceil(0.95 * len(gaps))) - 1)
    initial_heap = int(metrics.get("initialHeapBytes", 0))
    heap = int(metrics.get("heapBytes", initial_heap))
    return {
        "sampleCount": len(gaps),
        "p95GapMs": round(gaps[p95_rank], 3) if gaps else None,
        "maxGapMs": round(max(gaps), 3) if gaps else None,
        "severeGapCount": sum(value > 750 for value in gaps),
        "initialHeapBytes": initial_heap,
        "heapBytes": heap,
        "heapGrowthBytes": max(0, heap - initial_heap),
        "sampleOverflow": bool(metrics.get("sampleOverflow", False)),
    }


def frame_metrics_pass(metrics):
    return (
        metrics.get("sampleCount", 0) >= 20 and
        not metrics.get("sampleOverflow", True) and
        metrics.get("p95GapMs") is not None and metrics["p95GapMs"] <= 250 and
        metrics.get("severeGapCount", 2) <= 1 and
        metrics.get("maxGapMs") is not None and metrics["maxGapMs"] <= 3500 and
        metrics.get("heapBytes", 257 * MIB) <= 256 * MIB and
        metrics.get("heapGrowthBytes", 33 * MIB) <= 32 * MIB
    )


def browser_state(base, client):
    session = select_client(base, client)
    state = execute(
        base,
        session,
        """
return (function() {
  var canvas = document.getElementById('canvas');
  var gl = canvas && canvas.getContext('webgl');
  var glAttributes = gl && gl.getContextAttributes();
  var glStatus = null;
  try {
    glStatus = {
      available: !!gl,
      attributes: glAttributes,
      drawingBufferHeight: gl ? gl.drawingBufferHeight : 0,
      drawingBufferWidth: gl ? gl.drawingBufferWidth : 0,
      lost: gl ? gl.isContextLost() : null,
      maxTextureImageUnits: gl ? gl.getParameter(gl.MAX_TEXTURE_IMAGE_UNITS) : null,
      version: gl ? gl.getParameter(gl.VERSION) : null
    };
  } catch (error) {
    glStatus = {error: String(error).slice(0, 256)};
  }
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
    gl: glStatus,
    input: (typeof Module !== 'undefined') ? (Module['arenaInputStatus'] || null) : null,
    modulePresent: typeof Module !== 'undefined',
    preserveDrawingBuffer: !!(glAttributes && glAttributes.preserveDrawingBuffer),
    stage: (typeof Module !== 'undefined') ? (Module['arenaClientStage'] || 'runtime-startup') : null,
    statusError: statusError,
    ticketVisible: window.location.href.indexOf('ticket=') !== -1,
    transport: transportStatus,
    title: document.title
  };
})();
""",
    )
    metrics = execute(
        base,
        session,
        "return (typeof Module !== 'undefined' && Module['arenaFrameMetrics']) || null;",
    )
    if isinstance(state, dict) and isinstance(metrics, dict):
        state["frameMetrics"] = summarize_frame_metrics(metrics)
    return state


def arm_frame_metrics(base, client):
    session = select_client(base, client)
    return execute(
        base,
        session,
        """
Module['arenaFrameMetrics'] = {
  armed: true,
  gaps: [],
  sampleOverflow: false,
  initialHeapBytes: HEAPU8.buffer.byteLength,
  heapBytes: HEAPU8.buffer.byteLength
};
return true;
""",
    )


def reset_input_evidence(base, client):
    session = select_client(base, client)
    return execute(
        base,
        session,
        """
var status = Module['arenaInputStatus'];
if (!status) return false;
for (var key of ['keyDown', 'keyUp', 'sdlKeyDown', 'sdlKeyUp',
                 'acceptedActions', 'playerActions']) status[key] = 0;
status['lastKey'] = '';
status['lastCode'] = '';
status['lastKeyCode'] = 0;
status['lastSDLKey'] = 0;
status['lastSDLBound'] = false;
status['lastAction'] = '';
status['lastActionValue'] = 0;
status['lastActionPlayer'] = 0;
status['lastActionAccepted'] = false;
return true;
""",
    )


def send_server_command(path, command):
    if command not in ("START_NEW_MATCH", "QUIT"):
        raise ValueError("unsupported parity server command")
    if not stat.S_ISFIFO(path.stat().st_mode):
        raise RuntimeError("parity server control is not a FIFO")
    payload = (command + "\n").encode("ascii")
    descriptor = os.open(str(path), os.O_WRONLY | os.O_NONBLOCK)
    try:
        if os.write(descriptor, payload) != len(payload):
            raise RuntimeError("short parity server command write")
    finally:
        os.close(descriptor)


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


def wait_for_document(base, session, expected_url, timeout=15):
    return wait_for(
        lambda: execute(
            base,
            session,
            "return document.readyState === 'complete' && location.href === arguments[0];",
            [expected_url],
        ),
        timeout,
        "top-level document readiness",
    )


def wait_for_state(base, client, timeout, description, accept):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = browser_state(base, client)
            if isinstance(last, dict) and accept(last):
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
    parser.add_argument("--server-console", type=pathlib.Path)
    parser.add_argument("--server-control", type=pathlib.Path)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--timeout", type=int, default=150)
    parser.add_argument("--parity-role-schedule", action="store_true")
    args = parser.parse_args()
    if ((args.parity_role_schedule and not (args.server_control and args.server_console)) or
            (not args.parity_role_schedule and (args.server_control or args.server_console))):
        parser.error("--parity-role-schedule requires --server-control/--server-console and vice versa")

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
    parity_boundary_new_match = None

    try:
        def make_client_url(number):
            player = ("role" + str(number)) if args.parity_role_schedule else (args.browser + str(number))[:16]
            ticket = RELAY.mint_ticket(secret, player, args.browser + ("-parity" if args.parity_role_schedule else "-1v1"))
            query = urllib.parse.urlencode(
                {
                    "relay": args.relay_url,
                    "ticket": ticket,
                    "player": "forged" + str(number),
                }
            )
            return player, args.client_url + "?" + query

        client_urls = [make_client_url(1)]
        if args.browser != "safari":
            client_urls.append(make_client_url(2))

        if args.browser == "safari":
            session = create_session(args.webdriver_url, args.browser)
            duel_host_url = urllib.parse.urljoin(args.client_url, ".")
            request(
                args.webdriver_url,
                "POST",
                "/session/{0}/url".format(session),
                {"url": duel_host_url},
                timeout=10,
            )
            wait_for_document(args.webdriver_url, session, duel_host_url)
            frame_count = execute(
                args.webdriver_url,
                session,
                """
document.body.replaceChildren();
document.body.style.cssText = 'display:flex;margin:0;background:#05070b';
for (var index = 0; index < arguments.length; ++index) {
  var frame = document.createElement('iframe');
  frame.src = arguments[index];
  frame.style.cssText = 'border:0;width:50vw;height:100vh';
  document.body.appendChild(frame);
}
return document.querySelectorAll('iframe').length;
""",
                [client_urls[0][1]],
            )
            if frame_count != 1:
                raise RuntimeError("Safari duel host did not create the first client frame")
            sessions = [(session, client_urls[0][0], 0)]
            wait_for_state(
                args.webdriver_url, sessions[0], 45,
                "first Safari client live WebGL context",
                lambda value: value.get("transport") and
                value["transport"].get("open", 0) >= 1 and
                value.get("gl") and value["gl"].get("available") and
                not value["gl"].get("lost") and
                value["gl"].get("drawingBufferWidth", 0) > 0 and
                value["gl"].get("drawingBufferHeight", 0) > 0,
            )
            execute(args.webdriver_url, session,
                    "Module['arenaCaptureRequireAlive'] = false; return true;")
            try:
                first_capture = wait_for(
                    lambda: capture_canvas(
                        args.webdriver_url, select_client(args.webdriver_url, sessions[0])
                    ),
                    15,
                    "first Safari client nonblank upstream preflight frame",
                )
            finally:
                execute(args.webdriver_url, session,
                        "Module['arenaCaptureRequireAlive'] = true; return true;")
            (evidence_dir / "safari1-preflight.png").write_bytes(first_capture["png"])
            client_urls.append(make_client_url(2))
            request(args.webdriver_url, "POST", "/session/{0}/frame".format(session), {"id": None})
            frame_count = execute(
                args.webdriver_url,
                session,
                """
var frame = document.createElement('iframe');
frame.src = arguments[0];
frame.style.cssText = 'border:0;width:50vw;height:100vh';
document.body.appendChild(frame);
return document.querySelectorAll('iframe').length;
""",
                [client_urls[1][1]],
            )
            if frame_count != 2:
                raise RuntimeError("Safari duel host did not create the second client frame")
            sessions.append((session, client_urls[1][0], 1))
        else:
            for player, url in client_urls:
                session = create_session(args.webdriver_url, args.browser)
                sessions.append((session, player, None))
                request(
                    args.webdriver_url,
                    "POST",
                    "/session/{0}/url".format(session),
                    {"url": url},
                    timeout=10,
                )

        for number, client in enumerate(sessions):
            session, player, _frame = client
            state = wait_for_state(
                args.webdriver_url, client,
                45,
                player + " Wasm canvas and authenticated datagram socket",
                lambda value: value.get("transport") and
                value["transport"].get("open", 0) >= 1 and
                value.get("canvasWidth", 0) > 0 and
                not value.get("ticketVisible"),
            )
            session = select_client(args.webdriver_url, client)
            find_element(args.webdriver_url, session, "#canvas")
            key_name = "KeyA" if number == 0 else "KeyD"
            evidence.append({
                "player": player,
                "action": ("KeyA,KeyA,KeyA" if args.parity_role_schedule and number == 0 else
                           "" if args.parity_role_schedule else
                           key_name + "," + ("KeyD" if number == 0 else "KeyA")),
                "actionCount": (3 if args.parity_role_schedule and number == 0 else
                                0 if args.parity_role_schedule else 2),
                "initialState": state,
            })

        players = [player for _session, player, _frame in sessions]

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
            states = [browser_state(args.webdriver_url, client) for client in sessions]
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
        if args.parity_role_schedule:
            baseline_new_matches = sum(
                line.startswith("NEW_MATCH ") for line in server_result().splitlines()
            )
            if baseline_new_matches != 1:
                raise RuntimeError("setup round NEW_MATCH count is not exact")
            send_server_command(args.server_control, "START_NEW_MATCH")
            wait_for(
                lambda: args.server_console.exists() and
                "Resetting scores and starting new match after this round" in
                args.server_console.read_text(encoding="utf-8", errors="replace"),
                15,
                "START_NEW_MATCH server acknowledgement",
            )
            time.sleep(0.20)
            send_client_turn(args.webdriver_url, sessions[0], "a")
            send_client_turn(args.webdriver_url, sessions[0], "a")
            send_client_turn(args.webdriver_url, sessions[0], "a")
            setup_states = []
            for index, client in enumerate(sessions):
                expected = 3 if index == 0 else 0
                setup_states.append(wait_for_state(
                    args.webdriver_url, client, 15,
                    client[1] + " exact setup controls",
                    lambda value, expected=expected: value.get("input") and
                    value["input"].get("keyDown", 0) == expected and
                    value["input"].get("keyUp", 0) == expected and
                    value["input"].get("sdlKeyDown", 0) == expected and
                    value["input"].get("sdlKeyUp", 0) == expected and
                    value["input"].get("acceptedActions", 0) == expected,
                ))
            wait_for(
                lambda: server_result() if sum(
                    line.startswith("NEW_MATCH ")
                    for line in server_result().splitlines()
                ) > baseline_new_matches else None,
                45,
                "post-admission NEW_MATCH boundary",
            )
            parity_boundary_new_match = baseline_new_matches + 1
            live_states = wait_for(
                both_players_live, 60, "both cycles live after setup boundary"
            )
            for index, client in enumerate(sessions):
                evidence[index]["setupInputState"] = setup_states[index]
                if not reset_input_evidence(args.webdriver_url, client):
                    raise RuntimeError("browser input evidence reset failed")
            live_states = wait_for(
                both_players_live, 15, "both controlled cycles after evidence reset"
            )
        for index, state in enumerate(live_states):
            evidence[index]["preActionState"] = state

        # Each capture is accepted only while that upstream cycle is alive.
        # Safari frame capture can outlast a round; retry across the next round
        # instead of sampling a valid but sparse dead/inter-round camera.
        for index, client in enumerate(sessions):
            _session, player, _frame = client
            capture = wait_for(
                lambda: capture_canvas(
                    args.webdriver_url, select_client(args.webdriver_url, client)
                ),
                45,
                player + " nonblank upstream frame at the render boundary",
            )
            (evidence_dir / (player + ".png")).write_bytes(capture["png"])
            evidence[index]["liveRender"] = capture["render"]

        for client in sessions:
            arm_frame_metrics(args.webdriver_url, client)

        # The parity schedule deliberately drives role1 into its own trail;
        # role2 receives no input, making the authoritative winner role2.
        if args.parity_role_schedule:
            time.sleep(0.20)
            send_client_turn(args.webdriver_url, sessions[0], "a")
            send_client_turn(args.webdriver_url, sessions[0], "a")
            send_client_turn(args.webdriver_url, sessions[0], "a")
        else:
            send_client_turn(args.webdriver_url, sessions[1], "d")
            time.sleep(0.35)
            send_client_turn(args.webdriver_url, sessions[1], "a")
            send_client_turn(args.webdriver_url, sessions[0], "a")
            time.sleep(1.5)
            send_client_turn(args.webdriver_url, sessions[0], "d")

        for index, client in enumerate(sessions):
            _session, player, _frame = client
            if args.parity_role_schedule and index == 0:
                input_pass = (lambda value: value.get("input") and
                              value["input"].get("keyDown", 0) == 3 and
                              value["input"].get("keyUp", 0) == 3 and
                              value["input"].get("sdlKeyDown", 0) == 3 and
                              value["input"].get("sdlKeyUp", 0) == 3 and
                              value["input"].get("acceptedActions", 0) == 3)
            elif args.parity_role_schedule:
                input_pass = (lambda value: value.get("input") and
                              value["input"].get("keyDown", 0) == 0 and
                              value["input"].get("keyUp", 0) == 0 and
                              value["input"].get("sdlKeyDown", 0) == 0 and
                              value["input"].get("sdlKeyUp", 0) == 0 and
                              value["input"].get("acceptedActions", 0) == 0)
            else:
                input_pass = (lambda value: value.get("input") and
                              value["input"].get("keyDown", 0) >= 2 and
                              value["input"].get("keyUp", 0) >= 2 and
                              value["input"].get("acceptedActions", 0) >= 1)
            wait_for_state(
                args.webdriver_url, client,
                15,
                player + " received W3C controls in the browser",
                input_pass,
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
            result_lines = lines
            if args.parity_role_schedule:
                boundaries = [index for index, line in enumerate(lines)
                              if line.startswith("NEW_MATCH ")]
                if len(boundaries) < parity_boundary_new_match:
                    return None
                result_lines = lines[boundaries[parity_boundary_new_match - 1]:]
            finished = any(
                "MATCH_WINNER" in line and
                ((args.parity_role_schedule and "role2" in line) or
                 (not args.parity_role_schedule and any(player in line for player in players)))
                for line in result_lines
            )
            return text if entered and finished else None

        result = wait_for(authoritative_result, args.timeout, "authoritative live-client 1v1 winner")
        (evidence_dir / (args.browser + "-result.log")).write_text(result, encoding="utf-8")
        winner_states = None
        if args.parity_role_schedule:
            winner_states = [browser_state(args.webdriver_url, client) for client in sessions]
            send_server_command(args.server_control, "QUIT")
        for index, client in enumerate(sessions):
            _session, player, _frame = client
            if winner_states is None:
                final_state = wait_for_state(
                    args.webdriver_url, client,
                    15,
                    player + " bidirectional datagram traffic",
                    lambda value: value.get("transport") and
                    value["transport"].get("open", 0) >= 1 and
                    value["transport"].get("failed", 0) == 0 and
                    value["transport"].get("sentDatagrams", 0) > 0 and
                    value["transport"].get("receivedDatagrams", 0) > 0 and
                    value.get("gl") and value["gl"].get("available") and
                    not value["gl"].get("lost") and
                    value.get("frameMetrics") and
                    frame_metrics_pass(value["frameMetrics"]),
                )
            else:
                final_state = winner_states[index]
                if not (isinstance(final_state, dict) and
                        final_state.get("transport") and
                        final_state["transport"].get("open", 0) >= 1 and
                        final_state["transport"].get("failed", 0) == 0 and
                        final_state["transport"].get("sentDatagrams", 0) > 0 and
                        final_state["transport"].get("receivedDatagrams", 0) > 0 and
                        final_state.get("gl") and final_state["gl"].get("available") and
                        not final_state["gl"].get("lost") and
                        final_state.get("frameMetrics") and
                        frame_metrics_pass(final_state["frameMetrics"])):
                    raise RuntimeError(player + " final result-bound state failed")
            evidence[index]["finalState"] = final_state
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
        for index, client in enumerate(sessions):
            session, player, _frame = client
            try:
                diagnostic = {"player": player, "state": browser_state(args.webdriver_url, client)}
                if index < len(evidence):
                    diagnostic["action"] = evidence[index].get("action")
                    diagnostic["actionCount"] = evidence[index].get("actionCount")
                    diagnostic["liveRender"] = evidence[index].get("liveRender")
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
        closed_sessions = set()
        for session, _player, _frame in sessions:
            if session in closed_sessions:
                continue
            closed_sessions.add(session)
            try:
                request(args.webdriver_url, "DELETE", "/session/{0}".format(session), timeout=10)
            except Exception:
                pass


if __name__ == "__main__":
    main()
