from contextlib import redirect_stdout
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import warnings
import zipfile

from bundle import inspect, safe_name


class BundleTests(unittest.TestCase):
    def test_unsafe_paths_refused(self):
        for name in ('','../secret','/absolute','source/../../secret','source\\secret','folder/'):
            self.assertFalse(safe_name(name))
        self.assertTrue(safe_name('source/services/rio-accounts/src/lib.rs'))

    def test_duplicate_members_refused(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'overlay.zip'
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',UserWarning)
                with zipfile.ZipFile(path,'w') as archive:
                    archive.writestr('manifest.json','{}')
                    archive.writestr('manifest.json','{}')
            with self.assertRaises(ValueError): inspect(path)

    def test_traversal_member_refused_without_extraction(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'overlay.zip'
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('../escaped','fixture')
            with self.assertRaises(ValueError): inspect(path)
            self.assertFalse((Path(tmp).parent/'escaped').exists())

    def test_source_changed_bundle_refused(self):
        # Early manifest check must refuse source drift, before reading payloads.
        import json
        manifest={'schema':'pac-review-overlay/v1','baseHead':'fixture','sources':{},'members':{},
                  'purpose':'REVIEW_CANDIDATE_NOT_RELEASE','production':'HOLD','account1':'HOLD',
                  'rioServiceTests':'NOT_EXECUTED','signature':'UNSIGNED_LOCAL_OBSERVATION'}
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'overlay.zip'
            with zipfile.ZipFile(path,'w') as archive: archive.writestr('manifest.json',json.dumps(manifest))
            with patch('bundle.sources',return_value={'changed.py':'0'*64}):
                with self.assertRaises(ValueError): inspect(path)

if __name__=='__main__': unittest.main()
