#!/usr/bin/env python3
"""Build a credential-free ACP overlay from existing model metadata."""
import argparse
import copy
import json
import os
import pathlib
import tempfile

FIELDS = ('name', 'attachment', 'reasoning', 'tool_call', 'structured_output',
          'temperature', 'interleaved', 'modalities', 'cost', 'limit', 'variants')
FAMILIES = {
    'go-plan': ('OpenCode Go account 1', 'https://opencode.ai/zen/go/v1', 'OPENCODE_GO_PLAN'),
    'go-plan-2': ('OpenCode Go account 2', 'https://opencode.ai/zen/go/v1', 'OPENCODE_GO_PLAN_2'),
    'nvidia-nim-1': ('NVIDIA account 1', 'https://integrate.api.nvidia.com/v1', 'NVIDIA1_KEY'),
    'nvidia-nim-2': ('NVIDIA account 2', 'https://integrate.api.nvidia.com/v1', 'NVIDIA2_KEY'),
}


def build(catalog):
    providers = {}
    for family, (name, base, key) in FAMILIES.items():
        original = catalog.get('provider', {}).get(family)
        if not original or not isinstance(original.get('models'), dict) or not original['models']:
            raise ValueError('Existing catalog is missing the direct family ' + family)
        models = {}
        for alias, model in original['models'].items():
            native = model.get('nativeId') or model.get('id', alias).removeprefix(family + '/')
            if not isinstance(native, str) or not native or native.startswith(family + '/'):
                raise ValueError('Cannot establish native model ID for ' + family + '/' + alias)
            models[alias] = {field: copy.deepcopy(model[field]) for field in FIELDS if field in model}
            models[alias]['id'] = native
        providers[family] = {'name': name, 'npm': '@ai-sdk/openai-compatible',
                             'options': {'baseURL': base, 'apiKey': '{env:' + key + '}'}, 'models': models}
    # The built-in OpenAI plugin consumes the saved subscription OAuth login,
    # refreshes it, and rewrites Responses requests to the Codex backend.
    # Do not put subscription bearer credentials into apiKey or the catalog.
    providers['openai'] = {'name': 'OpenAI subscription (direct OAuth)', 'models': {
        'gpt-6.1-sol': {'id': 'gpt-6.1-sol', 'name': 'GPT-6.1 Sol', 'reasoning': True,
                       'tool_call': True, 'attachment': True,
                       'modalities': {'input': ['text', 'image'], 'output': ['text']},
                       'limit': {'context': 258000, 'input': 258000, 'output': 65536},
                       'variants': {level: {'reasoningEffort': level}
                                    for level in ['low', 'medium', 'high', 'xhigh', 'max']}}
    }}
    approved = list(providers)
    # Explicitly replace the inherited disabled list. ModelHub disables the
    # built-in OpenAI provider in favour of its old proxy family.
    result = {'$schema': 'https://opencode.ai/config.json', 'provider': providers,
              'enabled_providers': approved,
              'disabled_providers': [p for p in catalog.get('disabled_providers', []) if p not in approved]}
    # Preserve defaults when they still select an approved direct family.
    for field in ['model', 'small_model']:
        selected = catalog.get(field)
        if selected:
            family, _, alias = selected.partition('/')
            if family not in providers or alias not in providers[family]['models']:
                raise ValueError('Existing ' + field + ' is not an approved direct model')
            result[field] = selected
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=pathlib.Path, default=pathlib.Path('/root/.config/opencode/opencode.json'))
    parser.add_argument('--output', type=pathlib.Path, default=pathlib.Path('/drive/acp-fleet/opencode-direct.json'))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    config = build(json.loads(args.catalog.read_text(encoding='utf-8')))
    if args.apply:
        if args.output.exists() and (args.output.is_symlink() or args.output.stat().st_uid != os.getuid()):
            raise RuntimeError('Refusing a foreign direct configuration')
        before = args.output.read_bytes() if args.output.exists() else None
        fd, name = tempfile.mkstemp(prefix='.opencode-direct-', dir=args.output.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(config, stream, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            if (args.output.read_bytes() if args.output.exists() else None) != before:
                raise RuntimeError('Direct configuration changed concurrently')
            if before is not None:
                backup = args.output.with_suffix('.json.backup')
                if not backup.exists():
                    with backup.open('xb') as stream:
                        os.fchmod(stream.fileno(), 0o600); stream.write(before)
            os.replace(name, args.output)
        finally:
            pathlib.Path(name).unlink(missing_ok=True)
    print(json.dumps({'written': args.apply, 'families': list(config['provider']),
                      'modelCounts': {p: len(v['models']) for p, v in config['provider'].items()},
                      'credentialsIncluded': False}))


if __name__ == '__main__':
    main()
