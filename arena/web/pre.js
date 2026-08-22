/* Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt. */
Module['canvas'] = document.getElementById('canvas');
Module['thisProgram'] = '/arena-web/bin/armagetronad_main';
// Test captures are live-cycle-only unless the Safari single-context
// preflight explicitly asks for one startup renderer frame.
Module['arenaCaptureRequireAlive'] = true;
// Arena's upstream renderer uses only texture unit 0. Bound legacy GL
// emulation explicitly because Safari can report zero units during startup.
Module['GL_MAX_TEXTURE_IMAGE_UNITS'] = 1;
var arenaPreviousPrintErr = Module['printErr'];
Module['printErr'] = function(value) {
  if (window.__arenaRecordError) window.__arenaRecordError(value);
  if (arenaPreviousPrintErr) arenaPreviousPrintErr(value);
  else if (window.console && window.console.error) window.console.error(value);
};
var arenaSearch = new URLSearchParams(window.location.search);
var arenaRelayURL = arenaSearch.get('relay');
if (arenaRelayURL && /^wss?:\/\//.test(arenaRelayURL)) {
  Module['arenaRelayURL'] = arenaRelayURL;
}
var arenaRelayTicket = arenaSearch.get('ticket');
if (arenaRelayTicket && /^[A-Za-z0-9_.-]+$/.test(arenaRelayTicket)) {
  Module['arenaRelayTicket'] = arenaRelayTicket;
  arenaSearch.delete('ticket');
  var arenaCleanQuery = arenaSearch.toString();
  window.history.replaceState(null, '', window.location.pathname +
    (arenaCleanQuery ? '?' + arenaCleanQuery : '') + window.location.hash);
}

var arenaPlayer = (arenaSearch.get('player') || 'ArenaPlayer')
  .replace(/[^A-Za-z0-9_-]/g, '')
  .slice(0, 16) || 'ArenaPlayer';

var arenaInputStatus = Module['arenaInputStatus'] = {
  keyDown: 0,
  keyUp: 0,
  lastKey: '',
  lastCode: '',
  lastKeyCode: 0,
  sdlKeyDown: 0,
  sdlKeyUp: 0,
  lastSDLKey: 0,
  lastSDLBound: false,
  playerActions: 0,
  acceptedActions: 0,
  lastAction: '',
  lastActionPlayer: 0,
  lastActionValue: 0,
  lastActionAccepted: false,
  localPlayerPresent: false,
  localObjectPresent: false,
  localObjectAlive: false
};
function arenaRecordKey(event) {
  if (event.type === 'keydown') arenaInputStatus.keyDown += 1;
  else arenaInputStatus.keyUp += 1;
  arenaInputStatus.lastKey = String(event.key || '').slice(0, 32);
  arenaInputStatus.lastCode = String(event.code || '').slice(0, 32);
  arenaInputStatus.lastKeyCode = Number(event.keyCode || 0);
}
document.addEventListener('keydown', arenaRecordKey, true);
document.addEventListener('keyup', arenaRecordKey, true);

Module['preRun'] = Module['preRun'] || [];
Module['preRun'].push(function() {
  FS.mkdirTree('/user/var');
  FS.writeFile('/user/var/user.cfg',
    'FIRST_USE 0\nPLAYER_1 ' + arenaPlayer +
    // Emscripten 6.0.7 SDL1 maps arrows to scancode | (1 << 10).
    '\nKEYBOARD 1104 PLAYER_BIND CYCLE_TURN_LEFT 1' +
    '\nKEYBOARD 1103 PLAYER_BIND CYCLE_TURN_RIGHT 1' +
    // Character keys map directly across W3C Actions and Emscripten SDL1.
    '\nKEYBOARD 97 PLAYER_BIND CYCLE_TURN_LEFT 1' +
    '\nKEYBOARD 100 PLAYER_BIND CYCLE_TURN_RIGHT 1' +
    '\nBIG_BROTHER 0\nSOUND_QUALITY 0\n');
});
Module['arguments'] = [
  '--datadir', '/data',
  '--configdir', '/data/config',
  '--userdatadir', '/user',
  '--userconfigdir', '/user/config',
  '--vardir', '/user/var',
  '--resourcedir', '/data/resource'
];
