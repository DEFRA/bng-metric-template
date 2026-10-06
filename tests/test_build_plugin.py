"""The plugin zip: what build_plugin.py puts in it, and that it runs alone.

The build writes to a temporary folder rather than plugin/dist.
"""

import configparser
import contextlib
import importlib.util
import io
import re
import unittest
import zipfile

from tests import support

# support puts the converter modules on sys.path.
import reference_lists as rl

PACKAGE = "bng_template_convert"
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
SAMPLE_HABITAT = "Modified grassland"


def load_build_plugin():
    """build_plugin.py, imported as a module from its folder."""
    spec = importlib.util.spec_from_file_location(
        "build_plugin", support.PLUGIN_DIR / "build_plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metadata_version(text):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    return parser["general"]["version"], parser["general"]["changelog"]


class BuildPluginTest(support.TempDirTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.build = load_build_plugin()
        # An absolute DIST_DIR wins over the root it is joined to.
        cls.build.DIST_DIR = str(cls.tmp / "dist")
        with contextlib.redirect_stdout(io.StringIO()):
            cls.archive = support.Path(cls.build.build(cls.build.ROOT))
        with zipfile.ZipFile(cls.archive) as bundle:
            cls.names = set(bundle.namelist())
            cls.metadata = bundle.read(f"{PACKAGE}/metadata.txt").decode()
            bundle.extractall(cls.tmp / "installed")
        cls.installed = cls.tmp / "installed" / PACKAGE

    def test_zip_is_written_to_the_requested_folder(self):
        self.assertEqual(self.tmp / "dist" / f"{PACKAGE}.zip", self.archive)

    def test_zip_holds_every_plugin_file(self):
        for name in self.build.PLUGIN_FILES:
            with self.subTest(file=name):
                self.assertIn(f"{PACKAGE}/{name}", self.names)

    def test_zip_holds_the_guide(self):
        self.assertIn(f"{PACKAGE}/README.md", self.names)

    def test_zip_holds_every_drop_down_list_the_converter_reads(self):
        for template, relative in rl.reference_files():
            with self.subTest(template=template, list=relative):
                self.assertIn(
                    f"{PACKAGE}/{rl.BUNDLED_DIR}/{template}/{relative}",
                    self.names)

    def test_bundled_lists_are_the_template_lists(self):
        for template, relative in rl.reference_files():
            source = (support.TEMPLATES_DIR / template
                      / support.CSV_REFERENCES / relative)
            bundled = self.installed / rl.BUNDLED_DIR / template / relative
            with self.subTest(template=template, list=relative):
                self.assertEqual(source.read_bytes(), bundled.read_bytes())

    def test_metadata_version_matches_the_source_and_the_changelog(self):
        version, changelog = metadata_version(self.metadata)
        source = (support.PACKAGE_DIR / "metadata.txt").read_text()
        self.assertEqual(metadata_version(source)[0], version)
        self.assertRegex(version, VERSION)
        self.assertEqual(version, changelog.split()[0])

    def test_installed_plugin_reads_its_own_lists(self):
        """Outside the repository, the bundled copy is the only one."""
        snippet = (
            "import reference_lists as rl\n"
            "print(rl.list_folder(rl.SERVICE_TEMPLATE))\n"
            f"print(rl.AREA_CONDITION.legacy_form('Fairly Poor', "
            f"'{SAMPLE_HABITAT}'))\n")
        result = support.run_python("-c", snippet, cwd=self.installed)
        self.assertEqual(0, result.returncode, support.describe(result))
        folder, numbered = result.stdout.splitlines()
        self.assertTrue(support.Path(folder).resolve().is_relative_to(
            self.installed.resolve()), folder)
        self.assertEqual("4. Fairly Poor", numbered)

    def test_build_fails_when_a_list_is_missing(self):
        missing = [(rl.SERVICE_TEMPLATE, "Habitats/No such list.csv")]
        original = rl.reference_files
        self.build.reference_lists.reference_files = lambda: missing
        try:
            with self.assertRaisesRegex(SystemExit, "missing drop-down list"):
                self.build.bundled_lists(self.build.ROOT)
        finally:
            self.build.reference_lists.reference_files = original


if __name__ == "__main__":
    unittest.main()
