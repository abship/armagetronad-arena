/* Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt. */
'use strict';

var fs = require('fs');
var vm = require('vm');
var assert = require('assert');
var replaced = null;
var writes = [];
var errors = [];
var context = {
  Module: {},
  URLSearchParams: URLSearchParams,
  document: { getElementById: function() { return {}; } },
  window: {
    __arenaRecordError: function(value) { errors.push(String(value)); },
    console: { error: function() {} },
    location: {
      search: '?relay=wss%3A%2F%2Frelay.invalid%2Fsocket&ticket=short-lived-ticket&player=Arena_1',
      pathname: '/client/',
      hash: '#view'
    },
    history: {
      replaceState: function(_state, _title, url) { replaced = url; }
    }
  },
  FS: {
    mkdirTree: function() {},
    writeFile: function(path, value) { writes.push([path, value]); }
  }
};
vm.runInNewContext(
  fs.readFileSync(__dirname + '/../web/pre.js', 'utf8'), context,
  { filename: 'pre.js' }
);
assert.strictEqual('wss://relay.invalid/socket', context.Module.arenaRelayURL);
assert.strictEqual('short-lived-ticket', context.Module.arenaRelayTicket);
assert.strictEqual('/arena-web/bin/armagetronad_main', context.Module.thisProgram);
assert.ok(!replaced.includes('ticket='));
assert.ok(replaced.includes('relay='));
context.Module.preRun[0]();
assert.strictEqual('/user/var/user.cfg', writes[0][0]);
assert.ok(writes[0][1].includes('PLAYER_1 Arena_1'));
assert.ok(writes[0][1].includes('KEYBOARD 276 PLAYER_BIND CYCLE_TURN_LEFT 1'));
assert.ok(writes[0][1].includes('KEYBOARD 275 PLAYER_BIND CYCLE_TURN_RIGHT 1'));
assert.ok(writes[0][1].includes('SOUND_QUALITY 0'));
assert.ok(!writes[0][1].includes('short-lived-ticket'));
context.Module.printErr('diagnostic assertion');
assert.deepStrictEqual(['diagnostic assertion'], errors);
console.log('browser ticket bootstrap tests: pass');
