#!/usr/bin/env python3
"""Repair the installed ACP bridge without changing credentials or model defaults."""
import argparse
import hashlib
import json
import os
import pathlib
import stat
import subprocess
import tempfile
import time


SESSION_OPTIONS = '''      // OpenCode ACP selects models/effort through session options, not CLI flags.
      if (spec.sessionConfig) {
        let options = sess.configOptions || [];
        const setOption = async (category, value) => {
          const option = options.find(o => o.category === category);
          if (!option || option.type !== 'select') throw new Error(`${agent} did not advertise a ${category} session option`);
          const values = (option.options || []).flatMap(o => o.options || [o]).map(o => o.value);
          if (!values.includes(String(value))) throw new Error(`${agent} does not advertise ${category} '${value}'`);
          const changed = await request('session/set_config_option', { sessionId, configId: option.id, value: String(value) });
          options = changed?.configOptions || options;
          const confirmed = options.find(o => o.id === option.id);
          if (confirmed?.currentValue !== String(value)) throw new Error(`${agent} did not confirm ${category} '${value}'`);
        };
        if (model) await setOption('model', model);
        if (thinking) await setOption('thought_level', thinking);
      }
'''


def replace_once(source, before, after):
    if after in source:
        if source.count(after) != 1 or source.count(before) != after.count(before):
            raise ValueError('Installed ACP source contains conflicting patch versions')
        return source
    if source.count(before) != 1:
        raise ValueError('Installed ACP source differs; refusing an ambiguous patch')
    return source.replace(before, after, 1)


def patch_adapter(source):
    changes = [
        ("bin: '/drive/opencode-runtime/bin/opencode', args: ['acp'],\n    modelFlag: '-m', thinkingFlag: '--variant',",
         "bin: '/drive/opencode-runtime/bin/opencode', args: ['acp'],\n    sessionConfig: true, modelFlag: '-m', thinkingFlag: '--variant',"),
        ("    sessionConfig: true, modelFlag: '-m', thinkingFlag: '--variant',",
         "    sessionConfig: true, modelFlag: '-m', thinkingFlag: '--variant',\n    env: { OPENCODE_CONFIG: '/drive/acp-fleet/opencode-direct.json' },"),
        ("if (method === 'request_permission') {",
         "if (method === 'session/request_permission' || method === 'request_permission') {"),
        ("const ACP_LOAD_AGENTS = new Set(['omp', 'kimi', 'grok', 'cline']);",
         "const ACP_LOAD_AGENTS = new Set(['omp', 'kimi', 'grok', 'cline', 'opencode']);"),
        ("if (model && spec.modelFlag) args.push(spec.modelFlag, String(model));",
         "if (model && spec.modelFlag && !spec.sessionConfig) args.push(spec.modelFlag, String(model));"),
        ("if (thinking && spec.thinkingFlag) args.push(spec.thinkingFlag, String(thinking));",
         "if (thinking && spec.thinkingFlag && !spec.sessionConfig) args.push(spec.thinkingFlag, String(thinking));"),
        ("!['codex', 'cline'].includes(agent)", "!['codex', 'cline', 'opencode'].includes(agent)"),
        ("      // session/load replays history; return only this follow-up turn's output.",
         SESSION_OPTIONS + "      // session/load replays history; return only this follow-up turn's output."),
        ("return capResult(JSON.stringify({ agent: args.agent, ...(await listModels(args.agent)) }));",
         "return JSON.stringify({ agent: args.agent, ...(await listModels(args.agent)) });"),
        ("return capResult(JSON.stringify({ agent: args.agent, ...(await listSessions(args.agent)) }));",
         "return JSON.stringify({ agent: args.agent, ...(await listSessions(args.agent)) });"),
        ("    case 'opencode': {\n      const r = await runCmd(spec.bin, ['models']);",
         "    case 'opencode': {\n      const r = await runCmd(spec.bin, ['models'], { env: { ...process.env, ...spec.env } });"),
    ]
    for before, after in changes:
        source = replace_once(source, before, after)
    return source


def patch_server(source):
    source = replace_once(source,
        '  return { content: [{ type: "text", text }] };',
        '''  let value;
  try { value = typeof result === "string" ? JSON.parse(result) : result; } catch { value = null; }
  const failed = Boolean(value && (value.error || ["timeout", "cancelled", "error"].includes(value.status))) ||
    (typeof result === "string" && /^\\[(?:timeout|cancelled|error)(?:\\/|\\])/.test(result));
  return { content: [{ type: "text", text }], ...(failed ? { isError: true } : {}) };''')
    source = replace_once(source,
        '''      sessionId: z.string().describe("Past session id"),
      prompt: z.string().describe("Follow-up prompt"),''',
        '''      sessionId: z.string().describe("Past session id"),
      cwd: z.string().optional().describe("Session working directory; use the original prompt directory"),
      prompt: z.string().describe("Follow-up prompt"),''')
    source = replace_once(source,
        '''    async ({ agent, sessionId, prompt, timeout }) =>
      bridge({ action: "resume", agent, sessionId, prompt, timeout }),''',
        '''    async ({ agent, sessionId, cwd, prompt, timeout }) =>
      bridge({ action: "resume", agent, sessionId, cwd, prompt, timeout }),''')
    return source


def install(path, transform, backup, node):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError('ACP source must be an owned regular file')
    before = path.read_bytes()
    after = transform(before.decode('utf-8')).encode('utf-8')
    if before == after:
        return {'file': str(path), 'changed': False, 'sha256': hashlib.sha256(after).hexdigest()}
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.integrity-', suffix=path.suffix, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(after); stream.flush(); os.fchmod(stream.fileno(), info.st_mode & 0o777); os.fsync(stream.fileno())
        kind = 'module' if path.parent.name == 'src' else 'commonjs'
        subprocess.run([node, '--input-type=' + kind, '--check'], input=after,
                       check=True, capture_output=True, timeout=30)
        if path.read_bytes() != before:
            raise RuntimeError('ACP source changed concurrently')
        saved = backup / (path.parent.name + '-' + path.name)
        saved.write_bytes(before); saved.chmod(0o600)
        os.replace(name, path)
    finally:
        pathlib.Path(name).unlink(missing_ok=True)
    return {'file': str(path), 'changed': True, 'sha256': hashlib.sha256(after).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adapter', type=pathlib.Path, default=pathlib.Path('/drive/voice-agent/lib/acp.js'))
    parser.add_argument('--server', type=pathlib.Path, default=pathlib.Path('/drive/acp-fleet/src/server.js'))
    parser.add_argument('--node', default='/usr/bin/node')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    # Check both complete transformations before replacing either file.
    for path, transform in [(args.adapter, patch_adapter), (args.server, patch_server)]:
        transform(path.read_text(encoding='utf-8'))
    if not args.apply:
        print(json.dumps({'valid': True, 'written': False})); return
    direct = pathlib.Path('/drive/acp-fleet/opencode-direct.json')
    if not direct.is_file() or direct.is_symlink() or direct.stat().st_uid != os.getuid():
        raise RuntimeError('Install the owned direct ACP OpenCode configuration before applying the bridge patch')
    backup = args.adapter.parent / ('.acp-integrity-backup-' + str(time.time_ns()))
    backup.mkdir(mode=0o700)
    results = [install(path, transform, backup, args.node)
               for path, transform in [(args.adapter, patch_adapter), (args.server, patch_server)]]
    print(json.dumps({'backup': str(backup), 'installed': results, 'serviceRestarted': False}))


if __name__ == '__main__':
    main()
