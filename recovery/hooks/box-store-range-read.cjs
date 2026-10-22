'use strict';

// Read-only recovery for large presigned store objects on unstable connections.
// Every range is pinned to one strong ETag; native manifest parsing and writes
// remain the caller's responsibility.
function createReader({ fetch = globalThis.fetch, chunkBytes = 8 * 1024 * 1024,
  maxBytes = 1024 * 1024 * 1024, timeoutMs = 30000, concurrency = 2, attempts = 3,
  onProgress = () => {} } = {}) {
  for (const n of [chunkBytes, maxBytes, timeoutMs, concurrency, attempts]) {
    if (!Number.isSafeInteger(n) || n < 1) throw new Error('Invalid store read limit');
  }
  if (chunkBytes > maxBytes || concurrency > 8 || attempts > 4) throw new Error('Invalid store read limit');
  return async function read(url, options = {}) {
    const target = new URL(url);
    if (target.protocol !== 'https:' || !target.hostname.endsWith('.amazonaws.com') ||
      target.username || target.password || (target.port && target.port !== '443') || target.hash) {
      throw new Error('Expected a presigned HTTPS store object');
    }
    if (Object.keys(options).some(k => k !== 'signal')) throw new Error('Store reader accepts only an abort signal');
    const stop = new AbortController();
    const signal = options.signal ? AbortSignal.any([options.signal, stop.signal]) : stop.signal;
    async function part(start, end, expected) {
      for (let attempt = 1; ; attempt++) {
        signal.throwIfAborted();
        let response;
        try {
          response = await fetch(target.href, { redirect: 'error',
            signal: AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]),
            headers: { range: `bytes=${start}-${end}`, 'accept-encoding': 'identity',
              ...(expected ? { 'if-match': expected.etag } : {}) } });
          if ([408, 429, 500, 502, 503, 504].includes(response.status)) {
            await response.body?.cancel();
            if (attempt < attempts) continue;
            throw new Error('Store range read retries exhausted');
          }
          if (!expected && response.status === 404) {
            await response.body?.cancel();
            return { missing: true };
          }
          if (response.status !== 206) throw new Error('Store range request was not honored');
          const encoding = response.headers.get('content-encoding');
          if (encoding && encoding !== 'identity') throw new Error('Unexpected store content encoding');
          const etag = response.headers.get('etag');
          if (!etag || !/^"[^"\r\n]+"$/.test(etag)) throw new Error('Store range has no strong ETag');
          const range = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(response.headers.get('content-range') || '');
          if (!range) throw new Error('Store range has no exact length');
          const [first, last, total] = range.slice(1).map(Number);
          if (![first, last, total].every(Number.isSafeInteger) || total < 1 || total > maxBytes ||
            first !== start || last !== Math.min(end, total - 1) || last < first ||
            (expected && (total !== expected.total || etag !== expected.etag))) {
            throw new Error('Store object changed or range is invalid');
          }
          const length = last - first + 1;
          if (Number(response.headers.get('content-length')) !== length) throw new Error('Store range length mismatch');
          // Consume at most the declared range, including when a server lies
          // about Content-Length; do not buffer an unbounded response first.
          const body = new Uint8Array(length);
          const reader = response.body?.getReader();
          if (!reader) throw new Error('Store range body is missing');
          let offset = 0;
          try {
            for (;;) {
              const next = await reader.read();
              if (next.done) break;
              if (offset + next.value.byteLength > length) throw new Error('Store range body is oversized');
              body.set(next.value, offset); offset += next.value.byteLength;
            }
          } finally {
            try { await reader.cancel(); } catch { /* Preserve the original transport error. */ }
            reader.releaseLock();
          }
          if (offset !== length) throw new Error('Store range body is truncated');
          return { body, etag, total, headers: response.headers };
        } catch (error) {
          try { await response?.body?.cancel(); } catch { /* Response may already be closed. */ }
          if (signal.aborted) throw signal.reason;
          // A malformed response, 412 or version change must never be retried
          // against a different object. Only transient transport failures retry.
          if (attempt >= attempts || !['TypeError', 'TimeoutError', 'AbortError'].includes(error?.name)) throw error;
        }
      }
    }
    try {
      const first = await part(0, chunkBytes - 1);
      if (first.missing) return new Response(null, { status: 404 });
      const body = new Uint8Array(first.total);
      body.set(first.body);
      let next = first.body.length;
      let received = next;
      onProgress({ received, total: first.total });
      async function worker() {
        while (next < first.total) {
          const start = next; next += chunkBytes;
          const result = await part(start, Math.min(start + chunkBytes - 1, first.total - 1), first);
          body.set(result.body, start); received += result.body.length;
          onProgress({ received, total: first.total });
        }
      }
      const workers = Array.from({ length: concurrency }, () => worker().catch(error => { stop.abort(error); throw error; }));
      const results = await Promise.allSettled(workers);
      const failure = results.find(x => x.status === 'rejected');
      if (failure) throw failure.reason;
      const headers = new Headers(first.headers);
      headers.delete('content-range'); headers.set('content-length', String(first.total));
      return new Response(body, { status: 200, headers });
    } catch (error) { stop.abort(error); throw error; }
  };
}

module.exports = { createReader, fetch: createReader() };
