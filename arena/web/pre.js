/* Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt. */
Module['canvas'] = document.getElementById('canvas');
Module['thisProgram'] = '/arena-web/bin/armagetronad_main';
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

Module['preRun'] = Module['preRun'] || [];
Module['preRun'].push(function() {
  FS.mkdirTree('/user/var');
  FS.writeFile('/user/var/user.cfg',
    'FIRST_USE 0\nPLAYER_1 ' + arenaPlayer + '\nBIG_BROTHER 0\nSOUND_QUALITY 0\n');
});
Module['arguments'] = [
  '--datadir', '/data',
  '--configdir', '/data/config',
  '--userdatadir', '/user',
  '--userconfigdir', '/user/config',
  '--vardir', '/user/var',
  '--resourcedir', '/data/resource'
];
