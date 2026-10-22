#!/usr/bin/env python3
"""Enable Node's native proxy support for supervised Computer host children."""
import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import tempfile

MARKER = '/* openbot-host-egress-v1 */'
ANCHOR = '''        ...process.env,
        SAND_PACKAGED: "1",
        SAND_DATA_ROOT: AGENT_DATA_ROOT,'''
REPLACEMENT = '''        ...process.env,
        ...openbotHostEgressEnvironment(process.env),
        SAND_PACKAGED: "1",
        SAND_DATA_ROOT: AGENT_DATA_ROOT,'''
HELPER = r'''
/* openbot-host-egress-v1 */
export function openbotHostEgressEnvironment(env) {
  // Respect an operator's explicit proxy policy. The platform loopback CONNECT
  // service is a fallback for otherwise unconfigured host children only.
  if (["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]
      .some(key => typeof env[key] === "string" && env[key].trim()) ||
      env.NODE_USE_ENV_PROXY === "0") return {};
  const address = env.SAND_EGRESS_TUNNEL_PROXY_ADDR;
  if (typeof address !== "string" || !address) return {};
  const match = /^(127\.0\.0\.1|localhost|\[::1\]):([0-9]{1,5})$/.exec(address);
  if (!match || Number(match[2]) < 1 || Number(match[2]) > 65535) {
    throw new Error("Invalid configured Computer egress listener");
  }
  const proxy = "http://" + address;
  const bypass = ["localhost", "127.0.0.1", "::1", env.NO_PROXY, env.no_proxy]
    .filter(value => typeof value === "string" && value.trim()).join(",");
  return {
    NODE_USE_ENV_PROXY: "1",
    HTTP_PROXY: proxy, HTTPS_PROXY: proxy,
    http_proxy: proxy, https_proxy: proxy,
    NO_PROXY: bypass, no_proxy: bypass,
  };
}
'''


def patch(source):
    if MARKER in source:
        if source.count(MARKER) != 1 or source.count(REPLACEMENT) != 1 or HELPER not in source:
            raise ValueError('Existing Computer egress patch has drifted')
        return source
    if source.count(ANCHOR) != 1 or 'openbotHostEgressEnvironment' in source:
        raise ValueError('Unsupported supervisor launch code; original preserved')
    return source.replace(ANCHOR, REPLACEMENT, 1) + HELPER


def install(target, node, apply=False, *, transform=None, backup_label='egress'):
    if not re.fullmatch(r'[a-z0-9-]+', backup_label):
        raise ValueError('Invalid backup label')
    if target.is_symlink() or not target.is_file():
        raise ValueError('Patch target must be a regular file')
    original = target.read_bytes()
    modified = (transform or patch)(original.decode('utf-8')).encode('utf-8')
    digest = hashlib.sha256(original).hexdigest()
    if modified == original:
        return {'changed': False, 'installed': True, 'sha256': digest}
    stat = target.stat()
    staged = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.mjs', delete=False) as stream:
            staged = pathlib.Path(stream.name)
            os.fchmod(stream.fileno(), stat.st_mode & 0o777)
            stream.write(modified)
            stream.flush()
            os.fsync(stream.fileno())
        subprocess.run([node, '--check', str(staged)], check=True, capture_output=True)
        if not apply:
            return {'changed': True, 'installed': False, 'syntaxValid': True}
        if target.is_symlink() or target.read_bytes() != original:
            raise ValueError('Supervisor changed during preparation; original preserved')
        backup = target.with_name(target.name + '.pre-openbot-' + backup_label + '-' + digest[:16])
        if backup.exists() or backup.is_symlink():
            if backup.is_symlink() or not backup.is_file() or backup.read_bytes() != original:
                raise ValueError('Backup conflicts with original supervisor')
        else:
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
        if os.geteuid() == 0:
            os.chown(staged, stat.st_uid, stat.st_gid)
        os.replace(staged, target)
        staged = None
        fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return {'changed': True, 'installed': True, 'syntaxValid': True,
                'backup': str(backup), 'sha256': hashlib.sha256(modified).hexdigest()}
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--supervisor', type=pathlib.Path, default=pathlib.Path('/usr/local/bin/sand-supervisor.mjs'))
    parser.add_argument('--node', default='/exec-daemon/node')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(args.supervisor, args.node, args.apply)))


if __name__ == '__main__':
    main()
