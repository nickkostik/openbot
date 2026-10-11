import copy
import importlib.util
import json
import pathlib
import unittest

spec = importlib.util.spec_from_file_location('direct', pathlib.Path(__file__).with_name('build-acp-opencode-direct.py'))
direct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(direct)


class DirectAcpCatalogTests(unittest.TestCase):
    def catalog(self):
        return {'provider': {p: {'options': {'baseURL': 'https://n5.gg/v1', 'apiKey': 'private-fixture-key'},
                               'models': {'model': {'id': p + '/model', 'nativeId': 'vendor/model' if p.startswith('nvidia') else 'model',
                                                    'reasoning': True, 'variants': {'max': {'reasoningEffort': 'max'}},
                                                    'headers': {'authorization': 'private-fixture-key'}}}}
                             for p in direct.FAMILIES},
                'disabled_providers': ['openai', 'unrelated'], 'model': 'go-plan-2/model', 'small_model': 'go-plan/model'}

    def test_native_ids_two_accounts_and_defaults_are_preserved_without_secrets(self):
        original = self.catalog(); before = copy.deepcopy(original)
        result = direct.build(original)
        self.assertEqual(original, before)
        self.assertEqual(result['model'], original['model'])
        self.assertEqual(result['small_model'], original['small_model'])
        self.assertEqual(result['provider']['go-plan']['models']['model']['id'], 'model')
        self.assertEqual(result['provider']['nvidia-nim-1']['models']['model']['id'], 'vendor/model')
        self.assertEqual(result['provider']['go-plan']['models']['model']['variants'], {'max': {'reasoningEffort': 'max'}})
        self.assertNotEqual(result['provider']['go-plan']['options']['apiKey'], result['provider']['go-plan-2']['options']['apiKey'])
        self.assertNotIn('openai', result['disabled_providers'])
        self.assertNotIn('n5.gg', json.dumps(result))
        self.assertNotIn('private-fixture-key', json.dumps(result))
        self.assertNotIn('apiKey', result['provider']['openai'].get('options', {}))

    def test_missing_family_and_unapproved_default_are_rejected(self):
        missing = self.catalog(); del missing['provider']['go-plan-2']
        with self.assertRaises(ValueError): direct.build(missing)
        stale = self.catalog(); stale['model'] = 'openai-codex-oauth/stale-model'
        with self.assertRaises(ValueError): direct.build(stale)


if __name__ == '__main__':
    unittest.main()
