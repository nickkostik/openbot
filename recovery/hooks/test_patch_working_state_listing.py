import importlib.util
import pathlib
import unittest

FILE = pathlib.Path(__file__).with_name('patch-working-state-listing.py')
spec = importlib.util.spec_from_file_location('working_state_listing_patch', FILE)
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)
FIXTURE = '\n'.join([
    'var DURABLE_BLOB_LIST_CONCURRENCY = 16;',
    'DURABLE_BLOB_HEX_PREFIXES,',
    'max: DURABLE_BLOB_LIST_CONCURRENCY',
    'this.deps.listDurableBlobHexIds({',
    patcher.ANCHOR,
])


class ListingPatchTests(unittest.TestCase):
    def test_changes_only_the_known_policy_and_retains_v2_fence(self):
        result = patcher.patch(FIXTURE)
        self.assertEqual(result.replace(patcher.REPLACEMENT, patcher.ANCHOR), FIXTURE)
        self.assertIn('() => boxStoreSync.isV2Enabled,', result)
        self.assertEqual(patcher.patch(result), result)

    def test_refuses_unknown_code_missing_bounds_duplicate_anchor_and_drift(self):
        for source in ['', FIXTURE.replace('= 16;', '= 100;'),
                       FIXTURE + '\n' + patcher.ANCHOR,
                       patcher.patch(FIXTURE).replace(patcher.REPLACEMENT, patcher.MARKER)]:
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    patcher.patch(source)


if __name__ == '__main__':
    unittest.main()
