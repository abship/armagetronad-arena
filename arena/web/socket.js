/*
 * One WebSocket binary message is one Armagetron UDP datagram, unchanged.
 * Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
 */
(function(module) {
  'use strict';

  var MAX_DATAGRAM = 2048;
  var MAX_OUTGOING_QUEUE_COUNT = 32;
  var MAX_INCOMING_QUEUE_COUNT = 128;
  var MAX_QUEUE_BYTES = 32768;
  var HIGH_BUFFERED_BYTES = 16384;
  var MAX_BUFFERED_BYTES = 32768;
  var MAX_AGE_MS = 1000;
  var nextId = 1;
  var sockets = {};

  function now() {
    return module['arenaTransportNow'] ? module['arenaTransportNow']() : Date.now();
  }

  function fail(socket, code, reason) {
    socket.failed = true;
    socket.failureReason = reason;
    if (socket.backpressureTimer) {
      clearTimeout(socket.backpressureTimer);
      socket.backpressureTimer = 0;
    }
    if (socket.ws && socket.ws.readyState < WebSocket.CLOSING) {
      socket.ws.close(code, reason);
    }
  }

  function checkBackpressure(socket, additional) {
    var amount = socket.ws.bufferedAmount + additional;
    if (amount > MAX_BUFFERED_BYTES) {
      fail(socket, 4008, 'relay backlog');
      return false;
    }
    if (amount > HIGH_BUFFERED_BYTES && !socket.backpressureTimer) {
      socket.backpressureTimer = setTimeout(function() {
        socket.backpressureTimer = 0;
        if (socket.ws && socket.ws.bufferedAmount > HIGH_BUFFERED_BYTES) {
          fail(socket, 4008, 'stale relay backlog');
        }
      }, MAX_AGE_MS);
    }
    return true;
  }

  function open(socket) {
    var url = module['arenaRelayURL'];
    var ticket = module['arenaRelayTicket'];
    if (!url || !ticket) {
      socket.failed = true;
      return false;
    }
    var ws = socket.ws = new WebSocket(url, [
      'arena-datagram-v1',
      'arena-auth-' + ticket
    ]);
    ws.binaryType = 'arraybuffer';
    ws.onopen = function() {
      if (ws.protocol !== 'arena-datagram-v1') {
        fail(socket, 4002, 'relay protocol not selected');
        return;
      }
      var pending = socket.outgoing;
      socket.outgoing = [];
      socket.outgoingBytes = 0;
      for (var index = 0; index < pending.length; ++index) {
        if (now() - pending[index].queuedAt > MAX_AGE_MS ||
            !checkBackpressure(socket, pending[index].data.length)) {
          fail(socket, 4008, 'stale relay control');
          return;
        }
        ws.send(pending[index].data);
        socket.sentDatagrams += 1;
        socket.sentBytes += pending[index].data.length;
      }
    };
    ws.onmessage = function(event) {
      if (!(event.data instanceof ArrayBuffer)) {
        fail(socket, 4003, 'binary datagrams required');
        return;
      }
      var datagram = new Uint8Array(event.data);
      if (datagram.length > MAX_DATAGRAM) {
        fail(socket, 4009, 'datagram too large');
        return;
      }
      if (socket.incoming.length >= MAX_INCOMING_QUEUE_COUNT ||
          socket.incomingBytes + datagram.length > MAX_QUEUE_BYTES) {
        fail(socket, 4008, 'receive backlog');
        return;
      }
      socket.incoming.push({ data: datagram, queuedAt: now() });
      socket.incomingBytes += datagram.length;
      socket.receivedDatagrams += 1;
      socket.receivedBytes += datagram.length;
    };
    ws.onerror = function() {
      socket.failed = true;
      if (!socket.failureReason) socket.failureReason = 'websocket error';
    };
    ws.onclose = function(event) {
      socket.failed = true;
      if (!socket.failureReason) {
        socket.failureReason = 'websocket close ' + event.code +
          (event.reason ? ': ' + event.reason : '');
      }
    };
    return true;
  }

  module['arenaSocketTransport'] = {
    'create': function() {
      var id = nextId++;
      sockets[id] = {
        incoming: [],
        incomingBytes: 0,
        outgoing: [],
        outgoingBytes: 0,
        ws: null,
        failed: false,
        failureReason: null,
        backpressureTimer: 0,
        sentDatagrams: 0,
        sentBytes: 0,
        receivedDatagrams: 0,
        receivedBytes: 0
      };
      return id;
    },

    'send': function(id, datagram) {
      var socket = sockets[id];
      if (!socket || socket.failed || datagram.length > MAX_DATAGRAM) return -1;
      if (!socket.ws && !open(socket)) return -1;
      if (socket.ws.readyState === WebSocket.OPEN) {
        if (!checkBackpressure(socket, datagram.length)) return -1;
        socket.ws.send(datagram);
        socket.sentDatagrams += 1;
        socket.sentBytes += datagram.length;
        return datagram.length;
      }
      if (socket.ws.readyState !== WebSocket.CONNECTING ||
          socket.outgoing.length >= MAX_OUTGOING_QUEUE_COUNT ||
          socket.outgoingBytes + datagram.length > MAX_QUEUE_BYTES) {
        fail(socket, 4008, 'send backlog');
        return -1;
      }
      socket.outgoing.push({ data: datagram, queuedAt: now() });
      socket.outgoingBytes += datagram.length;
      return datagram.length;
    },

    'receive': function(id) {
      var socket = sockets[id];
      if (!socket || !socket.incoming.length) return null;
      var queued = socket.incoming.shift();
      socket.incomingBytes -= queued.data.length;
      if (now() - queued.queuedAt > MAX_AGE_MS) {
        fail(socket, 4008, 'stale relay control');
        return null;
      }
      return queued.data;
    },

    'ready': function(id) {
      return !!(sockets[id] && sockets[id].incoming.length);
    },

    'close': function(id) {
      var socket = sockets[id];
      if (!socket) return;
      fail(socket, 1000, 'socket closed');
      delete sockets[id];
    },

    'status': function() {
      var status = {
        count: 0,
        open: 0,
        failed: 0,
        failureReason: null,
        sentDatagrams: 0,
        sentBytes: 0,
        receivedDatagrams: 0,
        receivedBytes: 0
      };
      Object.keys(sockets).forEach(function(id) {
        var socket = sockets[id];
        status.count += 1;
        if (socket.failed) {
          status.failed += 1;
          if (!status.failureReason) status.failureReason = socket.failureReason;
        }
        if (socket.ws && socket.ws.readyState === WebSocket.OPEN) status.open += 1;
        status.sentDatagrams += socket.sentDatagrams;
        status.sentBytes += socket.sentBytes;
        status.receivedDatagrams += socket.receivedDatagrams;
        status.receivedBytes += socket.receivedBytes;
      });
      return status;
    },

    '_socketForTest': function(id) { return sockets[id]; }
  };
})(Module);
