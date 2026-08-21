/* Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt. */
'use strict';

var fs = require('fs');
var vm = require('vm');
var assert = require('assert');
var now = 0;
var instances = [];

class FakeWebSocket {
  constructor(url, protocols) {
    this.url = url;
    this.protocols = protocols;
    this.readyState = FakeWebSocket.CONNECTING;
    this.bufferedAmount = 0;
    this.sent = [];
    this.closed = null;
    instances.push(this);
  }
  send(data) { this.sent.push(Uint8Array.from(data)); }
  close(code, reason) {
    if (code !== 1000 && (code < 3000 || code > 4999)) {
      throw new Error('browser rejected WebSocket close code ' + code);
    }
    this.closed = [code, reason];
    this.readyState = FakeWebSocket.CLOSED;
  }
  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.protocol = this.protocols[0];
    this.onopen();
  }
}
FakeWebSocket.CONNECTING = 0;
FakeWebSocket.OPEN = 1;
FakeWebSocket.CLOSING = 2;
FakeWebSocket.CLOSED = 3;

var context = {
  Module: {
    arenaRelayURL: 'wss://relay.invalid',
    arenaRelayTicket: 'test-ticket',
    arenaTransportNow: function() { return now; }
  },
  WebSocket: FakeWebSocket,
  Uint8Array: Uint8Array,
  ArrayBuffer: ArrayBuffer,
  Date: Date,
  setTimeout: setTimeout,
  clearTimeout: clearTimeout
};
vm.runInNewContext(
  fs.readFileSync(__dirname + '/../web/socket.js', 'utf8'), context,
  { filename: 'socket.js' }
);
var transport = context.Module.arenaSocketTransport;

function latest() { return instances[instances.length - 1]; }

(function preservesPendingMessageBoundaries() {
  var id = transport.create();
  var first = Uint8Array.from([0, 1, 255]);
  var second = Uint8Array.from([9, 8]);
  assert.strictEqual(3, transport.send(id, first));
  assert.strictEqual(2, transport.send(id, second));
  assert.strictEqual('arena-datagram-v1,arena-auth-test-ticket',
    Array.from(latest().protocols).join(','));
  latest().open();
  assert.deepStrictEqual(Array.from(latest().sent[0]), Array.from(first));
  assert.deepStrictEqual(Array.from(latest().sent[1]), Array.from(second));
  assert.strictEqual(2, transport.status().sentDatagrams);
  assert.strictEqual(5, transport.status().sentBytes);
  latest().onmessage({ data: Uint8Array.from([4, 3, 2, 1]).buffer });
  assert.strictEqual(1, transport.status().receivedDatagrams);
  assert.strictEqual(4, transport.status().receivedBytes);
  transport.close(id);
})();

(function rejectsOversizeAndText() {
  var id = transport.create();
  var instanceCount = instances.length;
  assert.strictEqual(-1, transport.send(id, new Uint8Array(2049)));
  assert.strictEqual(instanceCount, instances.length);
  transport.send(id, new Uint8Array([1]));
  latest().open();
  latest().onmessage({ data: new Uint8Array(2049).buffer });
  assert.strictEqual(4009, latest().closed[0]);
  assert.strictEqual('datagram too large', transport.status().failureReason);
  transport.close(id);

  id = transport.create();
  transport.send(id, new Uint8Array([1]));
  latest().open();
  latest().onmessage({ data: 'text' });
  assert.strictEqual(4003, latest().closed[0]);
  transport.close(id);
})();

(function capsIncomingBytes() {
  var id = transport.create();
  transport.send(id, new Uint8Array([1]));
  latest().open();
  for (var index = 0; index < 16; ++index) {
    latest().onmessage({ data: new Uint8Array(2048).buffer });
  }
  assert.strictEqual(32768, transport._socketForTest(id).incomingBytes);
  latest().onmessage({ data: new Uint8Array([1]).buffer });
  assert.strictEqual(4008, latest().closed[0]);
  transport.close(id);
})();

(function capsIncomingCount() {
  var id = transport.create();
  transport.send(id, new Uint8Array([1]));
  latest().open();
  for (var index = 0; index < 128; ++index) {
    latest().onmessage({ data: new Uint8Array([1]).buffer });
  }
  latest().onmessage({ data: new Uint8Array([2]).buffer });
  assert.strictEqual(4008, latest().closed[0]);
  transport.close(id);
})();

(function drainsAcceptedServerStateAfterSlowRoundTransition() {
  now = 0;
  var id = transport.create();
  transport.send(id, new Uint8Array([1]));
  latest().open();
  latest().onmessage({ data: Uint8Array.from([4, 3, 2, 1]).buffer });
  now = 1001;
  assert.deepStrictEqual(Array.from(transport.receive(id)), [4, 3, 2, 1]);
  assert.strictEqual(0, transport._socketForTest(id).incomingBytes);
  assert.strictEqual(0, transport.status().failed);
  transport.close(id);
})();

(function closesOnBufferedBackpressure() {
  var id = transport.create();
  transport.send(id, new Uint8Array([1]));
  latest().open();
  latest().bufferedAmount = 32768;
  assert.strictEqual(-1, transport.send(id, new Uint8Array([2])));
  assert.strictEqual(4008, latest().closed[0]);
  transport.close(id);
})();

(function closesInsteadOfFlushingStaleControls() {
  now = 0;
  var id = transport.create();
  transport.send(id, new Uint8Array([7]));
  now = 1001;
  latest().open();
  assert.strictEqual(0, latest().sent.length);
  assert.strictEqual(4008, latest().closed[0]);
  transport.close(id);
})();

(function checksBufferedAmountBeforePendingFlush() {
  now = 0;
  var id = transport.create();
  transport.send(id, new Uint8Array([7]));
  latest().bufferedAmount = 32768;
  latest().open();
  assert.strictEqual(0, latest().sent.length);
  assert.strictEqual(4008, latest().closed[0]);
  transport.close(id);
})();

console.log('browser datagram transport tests: pass');
