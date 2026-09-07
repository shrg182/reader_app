const { test } = require('node:test');
const assert = require('node:assert/strict');
const Queue = require('../../src/reader_app/static/progress.js');
function harness(storage = new Map(), key = 'account:book') {
  const requests = [], timers = [];
  const queue = new Queue({ key, storage: {
    getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  }, send: value => new Promise((resolve, reject) => requests.push({ value, resolve, reject })),
  status: message => { queue.message = message; }, schedule: fn => timers.push(fn), cancel() {} });
  return { queue, storage, requests, timers };
}
const settle = () => new Promise(resolve => setImmediate(resolve));
test('position survives closing before the debounce or a failed request and syncs after reopening', async () => {
  const h = harness();
  h.queue.update(0.4, 2, 1);
  const reopened = harness(h.storage);
  assert.equal(reopened.queue.pending.progress, 0.4);
  reopened.queue.flush();
  reopened.requests[0].reject(new Error('offline'));
  await settle();
  assert.equal(h.storage.size, 1);
  reopened.timers[0]();
  reopened.requests[1].resolve({});
  await settle();
  assert.equal(h.storage.size, 0);
  assert.equal(reopened.queue.message, 'Position synced');
});
test('requests serialize and retain newer backwards movement', async () => {
  const h = harness();
  h.queue.update(0.8, null, null); h.queue.flush();
  h.queue.update(0, null, null); h.queue.flush();
  assert.equal(h.requests.length, 1);
  h.requests[0].resolve({});
  await settle();
  assert.equal(h.requests[1].value.progress, 0);
  assert.equal(h.storage.size, 1);
  h.requests[1].resolve({});
  await settle();
  assert.equal(h.storage.size, 0);
});
test('acknowledgment from another tab cannot erase a newer local record', async () => {
  const h = harness();
  h.queue.update(0.2, null, null); h.queue.flush();
  const other = harness(h.storage);
  other.queue.update(0.5, null, null);
  h.requests[0].resolve({});
  await settle();
  assert.equal(harness(h.storage).queue.pending.progress, 0.5);
  assert.equal(harness(h.storage, 'another-account:book').queue.pending, null);
});
test('malformed local data is ignored and blocked storage does not prevent server saves', async () => {
  const h = harness(new Map([['account:book', '{bad']]));
  assert.equal(h.queue.pending, null);
  h.queue.storage.setItem = () => { throw new Error('blocked'); };
  h.queue.update(0.5, null, null); h.queue.flush();
  h.requests[0].resolve({});
  await settle();
  assert.equal(h.queue.message, 'Position synced');
});
