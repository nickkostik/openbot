import importlib.util
import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location('patch_computer_egress', HERE / 'patch-computer-egress.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
NODE = shutil.which('node')
SOURCE = 'const AGENT_DATA_ROOT="/test"; const env = {\n' + module.ANCHOR + '\n};\n'


@unittest.skipUnless(NODE, 'Node is required')
class ComputerEgressTests(unittest.TestCase):
    def evaluate(self, env):
        code = module.HELPER.replace('export function', 'function')
        code += '\nconsole.log(JSON.stringify(openbotHostEgressEnvironment(' + json.dumps(env) + ')));'
        result = subprocess.run([NODE, '--input-type=module', '-e', code], capture_output=True, text=True)
        return result

    def test_native_proxy_and_loopback_bypass(self):
        result = self.evaluate({'SAND_EGRESS_TUNNEL_PROXY_ADDR': '127.0.0.1:8791', 'NO_PROXY': '.internal'})
        self.assertEqual(result.returncode, 0, result.stderr)
        env = json.loads(result.stdout)
        self.assertEqual(env['NODE_USE_ENV_PROXY'], '1')
        for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
            self.assertEqual(env[key], 'http://127.0.0.1:8791')
        self.assertIn('.internal', env['NO_PROXY'])
        self.assertIn('127.0.0.1', env['NO_PROXY'])
        self.assertEqual(env['NO_PROXY'], env['no_proxy'])

    def test_explicit_operator_policy_and_optout_are_preserved(self):
        for policy in [{'https_proxy': 'http://example.invalid:9000'}, {'NODE_USE_ENV_PROXY': '0'}, {}]:
            env = {'SAND_EGRESS_TUNNEL_PROXY_ADDR': '127.0.0.1:8791', **policy}
            if not policy:
                env = {}
            result = self.evaluate(env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {})

    def test_rejects_remote_and_malformed_proxies(self):
        for address in ['example.com:8791', 'http://127.0.0.1:8791', '127.0.0.1:0',
                        '127.0.0.1:65536', '127.0.0.1:8791/path', '127.0.0.1:8791\n', 'user@localhost:80']:
            self.assertNotEqual(self.evaluate({'SAND_EGRESS_TUNNEL_PROXY_ADDR': address}).returncode, 0)

    def test_ipv6_loopback(self):
        result = self.evaluate({'SAND_EGRESS_TUNNEL_PROXY_ADDR': '[::1]:8791'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['HTTPS_PROXY'], 'http://[::1]:8791')

    def test_patch_is_idempotent_and_refuses_drift(self):
        patched = module.patch(SOURCE)
        self.assertEqual(module.patch(patched), patched)
        for source in [SOURCE + SOURCE, 'unsupported', patched.replace('NODE_USE_ENV_PROXY: "1"', 'NODE_USE_ENV_PROXY: "0"')]:
            with self.assertRaises(ValueError):
                module.patch(source)

    def test_install_preserves_source_on_preview_and_backup_on_apply(self):
        with tempfile.TemporaryDirectory() as folder:
            target = pathlib.Path(folder) / 'supervisor.mjs'
            target.write_text(SOURCE)
            target.chmod(0o750)
            self.assertFalse(module.install(target, NODE)['installed'])
            self.assertEqual(target.read_text(), SOURCE)
            result = module.install(target, NODE, True)
            backup = pathlib.Path(result['backup'])
            self.assertEqual(backup.read_text(), SOURCE)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.stat().st_mode & 0o777, 0o750)
            self.assertFalse(module.install(target, NODE, True)['changed'])

    def test_syntax_error_and_symlink_preserve_original(self):
        with tempfile.TemporaryDirectory() as folder:
            target = pathlib.Path(folder) / 'supervisor.mjs'
            bad = SOURCE + '\n)invalid'
            target.write_text(bad)
            with self.assertRaises(subprocess.CalledProcessError):
                module.install(target, NODE, True)
            self.assertEqual(target.read_text(), bad)
            link = pathlib.Path(folder) / 'link.mjs'
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                module.install(link, NODE, True)


if __name__ == '__main__':
    unittest.main()
