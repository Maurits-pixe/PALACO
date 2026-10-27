"""Regression tests for the PVS-001 workspace boundary."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkspaceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        shutil.copyfile(ROOT / "Cargo.toml", self.root / "Cargo.toml")
        (self.root / "tools").mkdir()
        shutil.copyfile(
            ROOT / "tools/pvs001_workspace_integrity.py",
            self.root / "tools/pvs001_workspace_integrity.py",
        )
        for name in ("docs", "tests", "evidence", ".github"):
            (self.root / name).symlink_to(ROOT / name, target_is_directory=True)
        for source in (ROOT / "crates").glob("*/Cargo.toml"):
            crate = self.root / "crates" / source.parent.name
            (crate / "src").mkdir(parents=True)
            shutil.copyfile(source, crate / "Cargo.toml")
            (crate / "src/lib.rs").touch()

    def check(self, expected_status, message):
        result = subprocess.run(
            [sys.executable, str(self.root / "tools/pvs001_workspace_integrity.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, expected_status, result.stdout + result.stderr)
        self.assertIn(message, result.stdout)

    def replace(self, relative_path, old, new):
        path = self.root / relative_path
        content = path.read_text()
        self.assertIn(old, content)
        path.write_text(content.replace(old, new))

    def test_current_workspace_accepts_independently_versioned_extension(self):
        self.check(0, "PVS-001: PASS")

    def test_unknown_or_duplicate_member_is_rejected(self):
        for name in ("palaco-unknown", "palaco-la"):
            with self.subTest(name=name):
                path = self.root / "Cargo.toml"
                original = path.read_text()
                path.write_text(original.replace("\n]", f'\n  "crates/{name}",\n]', 1))
                self.check(1, "workspace members mismatch")
                path.write_text(original)

    def test_missing_extension_member_is_rejected(self):
        self.replace("Cargo.toml", '  "crates/palaco-la",\n', "")
        self.check(1, "workspace members mismatch")

    def test_foundation_inheritance_remains_required(self):
        self.replace(
            "crates/palaco-foundation/Cargo.toml",
            "version.workspace = true",
            'version = "1.0.0"',
        )
        self.check(1, "missing: version.workspace = true")

    def test_missing_extension_source_or_manifest_is_rejected(self):
        (self.root / "crates/palaco-la/src/lib.rs").unlink()
        self.check(1, "missing crates/palaco-la/src/lib.rs")
        (self.root / "crates/palaco-la/Cargo.toml").unlink()
        self.check(1, "missing crates/palaco-la/Cargo.toml")

    def test_extension_metadata_and_unsafe_policy_are_checked(self):
        path = self.root / "crates/palaco-la/Cargo.toml"
        original = path.read_text()
        for old, new, message in (
            ('name = "palaco-la"', 'name = "other"', "package name"),
            ('edition = "2024"', 'edition = "2021"', "package edition"),
            ('rust-version = "1.90"', 'rust-version = "1.89"', "package rust-version"),
            ("publish = false", "publish = true", "package publish"),
            ('unsafe_code = "forbid"', 'unsafe_code = "allow"', "must forbid unsafe_code"),
        ):
            with self.subTest(field=old):
                path.write_text(original.replace(old, new))
                self.check(1, message)
                path.write_text(original)


if __name__ == "__main__":
    unittest.main()
