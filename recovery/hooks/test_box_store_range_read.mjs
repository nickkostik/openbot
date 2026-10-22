import assert from 'node:assert/strict';
import test from 'node:test';
import { createRequire } from 'node:module';
const { createReader } = createRequire(import.meta.url)('./box-store-range-read.cjs');
const url = 'https://owned.s3.us-east-1.amazonaws.com/manifest.json?X-Amz-Signature=private';
const data = Buffer.from('abcdefghijklmnopqrstuvwxyz');
function origin(change = () => {}) {
  const calls = [];
  return { calls, fetch: async (url, opts) => {
    calls.push({ url, opts });
    const [, a, b] = /^bytes=(\d+)-(\d+)$/.exec(opts.headers.range);
    const start = Number(a), end = Math.min(Number(b), data.length - 1);
    const init = { status: 206, headers: { etag: '"v1"', 'content-range': `bytes ${start}-${end}/${data.length}`,
      'content-length': String(end - start + 1) } };
    const override = await change(calls.length, init, opts);
    return override || new Response(data.subarray(start, end + 1), init);
  } };
}
test('reassembles exact bytes and pins later ranges to one version', async () => {
  const fake = origin(); const progress = [];
  const read = createReader({ fetch: fake.fetch, chunkBytes: 8, onProgress: p => progress.push(p) });
  const response = await read(url);
  assert.deepEqual(Buffer.from(await response.arrayBuffer()), data);
  assert.equal(response.status, 200); assert.equal(response.headers.get('content-range'), null);
  assert.equal(response.headers.get('content-length'), '26'); assert.equal(response.headers.get('etag'), '"v1"');
  assert.equal(fake.calls.length, 4); assert.equal(progress.at(-1).received, 26);
  for (const [i, call] of fake.calls.entries()) {
    assert.equal(call.url, url); assert.equal(call.opts.redirect, 'error');
    assert.equal(call.opts.headers['if-match'], i ? '"v1"' : undefined);
  }
});
test('preserves missing-object semantics', async () => {
  let cancelled = false;
  const read = createReader({ fetch: async () => new Response(new ReadableStream({
    cancel() { cancelled = true; },
  }), { status: 404 }) });
  assert.equal((await read(url)).status, 404);
  assert.equal(cancelled, true);
});
test('rejects non-store URLs and write options before network access', async () => {
  let calls = 0; const read = createReader({ fetch: async () => { calls++; } });
  for (const bad of ['http://owned.amazonaws.com/x', 'https://amazonaws.com.evil.test/x', 'https://u:p@x.amazonaws.com/x', 'https://x.amazonaws.com:8443/x']) await assert.rejects(read(bad));
  await assert.rejects(read(url, { method: 'PUT' })); assert.equal(calls, 0);
});
test('fails closed on weak/missing ETags, wrong bounds, encoding and excessive size', async () => {
  for (const headers of [{ etag: 'W/"v1"' }, { etag: '' }, { 'content-range': 'bytes 1-8/26' },
    { 'content-length': '9' }, { 'content-encoding': 'gzip' }, { 'content-range': 'bytes 0-7/2000000000' }]) {
    const fake = origin((_, init) => Object.assign(init.headers, headers) && undefined);
    await assert.rejects(createReader({ fetch: fake.fetch, chunkBytes: 8 })(url));
    assert.equal(fake.calls.length, 1);
  }
});
test('rejects a replacement version or a precondition failure without restarting', async () => {
  for (const status of [206, 412]) {
    const fake = origin((n, init) => { if (n > 1) { init.headers.etag = '"v2"'; init.status = status; } });
    await assert.rejects(createReader({ fetch: fake.fetch, chunkBytes: 8, concurrency: 1 })(url));
    assert.equal(fake.calls.length, 2);
  }
});
test('retries transient network resets and HTTP failures with the same version', async () => {
  for (const kind of ['network', '503']) {
    const fake = origin((n) => { if (n === 2) { if (kind === 'network') throw new TypeError('fetch failed'); return new Response(null, { status: 503 }); } });
    const response = await createReader({ fetch: fake.fetch, chunkBytes: 8, concurrency: 1 })(url);
    assert.deepEqual(Buffer.from(await response.arrayBuffer()), data); assert.equal(fake.calls.length, 5);
    assert.equal(fake.calls[1].opts.headers.range, fake.calls[2].opts.headers.range);
  }
});
test('enforces retry bounds and propagates cancellation', async () => {
  let count = 0;
  await assert.rejects(createReader({ fetch: async () => { count++; throw new TypeError('reset'); }, attempts: 2 })(url));
  assert.equal(count, 2);
  const stop = new AbortController(); stop.abort(new Error('cancelled'));
  await assert.rejects(createReader({ fetch: async () => { throw new Error('unexpected'); } })(url, { signal: stop.signal }), /cancelled/);
});
test('rejects short and oversized bodies instead of publishing partial data', async () => {
  for (const bytes of [Buffer.from('a'), Buffer.alloc(9)]) {
    const fake = origin((_, init) => new Response(bytes, init));
    await assert.rejects(createReader({ fetch: fake.fetch, chunkBytes: 8 })(url));
  }
});
test('cancels a locked oversized stream before rejecting', async () => {
  let cancelled = false;
  const fake = origin((_, init) => new Response(new ReadableStream({
    start(controller) { controller.enqueue(Buffer.alloc(9)); },
    cancel() { cancelled = true; },
  }), init));
  await assert.rejects(createReader({ fetch: fake.fetch, chunkBytes: 8 })(url), /oversized/);
  assert.equal(cancelled, true);
});
