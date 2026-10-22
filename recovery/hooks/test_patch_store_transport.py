import importlib.util
import json
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).parent
SPEC = importlib.util.spec_from_file_location('store_transport', ROOT / 'patch-store-transport.py')
PATCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCHER)


def fixture():
    # Small independent transport fixture; no vendor bundle or private data.
    return '''const BOX_STORE_MANIFEST_REL_PATH = "manifest.json";
const SandBoxStoreSyncError = Error;
const classifyConditionalPutStatus = status => status === 409 ? "concurrent-write" : status === 412 ? "already-stored" : "ok";
const fetchAgentStoreObjectFromUrl = async (url, key) => ({url, key});
''' + PATCHER.CLASS + '''
  async cached(cached2, key) { return await fetchAgentStoreObjectFromUrl(cached2.url, key); }
  async read(url2, key) { return fetchAgentStoreObjectFromUrl(url2, key); }
  async immutable(putOnce) {
''' + PATCHER.CONDITIONAL + '''
    if (classifyConditionalPutStatus(response.status) === "already-stored") return;
    if (!response.ok) throw new Error("immutable rejected");
  }
  async mutable(putOnce) {
''' + PATCHER.MUTABLE + '''
    if (response.status === 409 || response.status === 412) throw new Error("conflict");
    if (!response.ok) throw new Error("mutable rejected");
    return response.headers.get("etag");
  }
};
''' + PATCHER.END + '\n// retained suffix\n'


class StoreTransportTests(unittest.TestCase):
    def test_idempotent_and_scoped(self):
        original = fixture()
        modified = PATCHER.patch(original, '/reviewed/reader.cjs')
        self.assertEqual(PATCHER.patch(modified, '/reviewed/reader.cjs'), modified)
        self.assertEqual(original.split(PATCHER.CLASS)[0], modified.split(PATCHER.MARKER)[0])
        self.assertTrue(modified.endswith(PATCHER.END + '\n// retained suffix\n'))
        self.assertEqual(modified.count('await response.body?.cancel();'), 4)

    def test_refuse_drift_and_partial_install(self):
        for original in (fixture().replace(PATCHER.MUTABLE, ''), fixture() + PATCHER.CLASS,
                         fixture() + PATCHER.END,
                         fixture().replace('cached2.url, key', 'cached2.url, other')):
            with self.assertRaises(ValueError):
                PATCHER.patch(original, '/reviewed/reader.cjs')
        modified = PATCHER.patch(fixture(), '/reviewed/reader.cjs')
        for altered in (modified.replace('await response.body?.cancel();', '', 1),
                        modified + PATCHER.MARKER):
            with self.assertRaises(ValueError):
                PATCHER.patch(altered, '/reviewed/reader.cjs')
        with self.assertRaises(ValueError):
            PATCHER.patch(modified, '/different/reader.cjs')

    def test_reader_path_validation_and_quoting(self):
        for path in ('relative.cjs', '', '/bad\x00path'):
            with self.assertRaises(ValueError):
                PATCHER.patch(fixture(), path)
        path = '/reviewed/a"b\\c.cjs'
        self.assertIn('require(' + json.dumps(path) + ')', PATCHER.patch(fixture(), path))

    def test_earlier_bundler_comment_is_not_a_second_class_boundary(self):
        original = PATCHER.END + '\n' + fixture()
        result = PATCHER.patch(original, '/reviewed/reader.cjs')
        self.assertTrue(result.startswith(PATCHER.END + '\n'))
        self.assertEqual(PATCHER.patch(result, '/reviewed/reader.cjs'), result)

    def test_native_status_and_retry_semantics(self):
        code = PATCHER.patch(fixture(), '/reviewed/reader.cjs') + r'''
(async () => {
  const store = new SandBoxStoreServiceObjectStore();
  for (const method of ["immutable", "mutable"]) {
    for (const statuses of [[200], [412], [403], [500], [409, 200], [409, 412], [409, 409]]) {
      let calls = 0, released = 0, failed = false;
      const put = async () => {
        if (calls !== released) throw new Error("retry leaked a response");
        const status = statuses[calls++];
        return {status, ok: status >= 200 && status < 300,
          body: {cancel: async () => { released++; }}, headers: new Headers({etag: '"same"'})};
      };
      try { const result = await store[method](put); if (method === "mutable" && result !== '"same"') throw new Error("etag changed"); }
      catch { failed = true; }
      const final = statuses.at(-1);
      const expectedFailure = method === "immutable" ? ![200, 412].includes(final) : final !== 200;
      if (calls !== statuses.length || released !== calls || failed !== expectedFailure) throw new Error("status semantics changed");
    }
  }
  const ordinary = await store.read("https://store.test/blob", "working-state/blobs/hash");
  if (ordinary.key !== "working-state/blobs/hash") throw new Error("nonmanifest reader changed");
})().catch(error => { console.error(error.message); process.exitCode = 1; });
'''
        subprocess.run(['node', '-e', code], check=True, capture_output=True, text=True)

    def test_manifest_dispatch_and_missing_object(self):
        code = '''const Module = require("node:module");
const previous = Module._load;
let missing = false, calls = 0;
Module._load = function(path, ...args) {
  if (path === "/reviewed/reader.cjs") return {fetch: async url => {
    calls++; return missing ? new Response(null, {status:404}) : new Response(new Uint8Array([1,2,3]));
  }};
  return previous.call(this, path, ...args);
};
''' + PATCHER.patch(fixture(), '/reviewed/reader.cjs') + '''
(async () => {
 const store = new SandBoxStoreServiceObjectStore();
 if ((await store.read("https://store.test/manifest", "manifest.json")).join() !== "1,2,3") throw new Error("manifest bytes changed");
 missing = true;
 if (await store.cached({url:"https://store.test/missing"}, "manifest.json") !== null) throw new Error("404 changed");
 if (calls !== 2) throw new Error("wrong reader");
})().catch(error => { console.error(error.message); process.exitCode=1; });
'''
        subprocess.run(['node', '-e', code], check=True, capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()
