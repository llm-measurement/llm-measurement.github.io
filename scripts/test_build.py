# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Check root-file preservation across clean builds and asset cleanup."""
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import build


class BuildTests(unittest.TestCase):
    def test_verification_survives_rebuild_and_stale_asset_cleanup(self):
        source = build.ROOT
        name = "googled831a5845f87080c.html"
        expected = b"google-site-verification: googled831a5845f87080c.html"
        self.assertEqual((source / name).read_bytes(), expected)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("assets", "pages"):
                shutil.copytree(source / folder, root / folder)
            shutil.copyfile(source / name, root / name)
            with patch.object(build, "ROOT", root):
                build.build()
                verification = root / "docs" / name
                self.assertEqual(verification.read_bytes(), expected)
                stale_asset = root / "docs/assets/stale-test.txt"
                stale_asset.write_text("remove this generated test asset")
                build.build()
                self.assertFalse(stale_asset.exists())
                self.assertEqual(verification.read_bytes(), expected)
                shutil.rmtree(root / "docs")
                build.build()
                self.assertEqual(verification.read_bytes(), expected)


if __name__ == "__main__":
    unittest.main()
