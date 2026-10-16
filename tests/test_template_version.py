"""The template version record, and the tool that writes it.

The BNG service reads the record to know which template, and which version,
a GeoPackage comes from. The template carries it, and so does every
GeoPackage the plugin and the generators make from it.
"""

import contextlib
import io
import sqlite3
import sys

from tests import support

if str(support.TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(support.TOOLS_DIR))

# support puts the converter modules on sys.path.
import gpkg_common  # noqa: E402
import new_to_old  # noqa: E402
import set_template_version  # noqa: E402

GDAL_URI = "http://gdal.org"
GDAL_METADATA = "<GDALMultiDomainMetadata/>"


def without_version(path):
    """A copy of the template with no version record."""
    conn = sqlite3.connect(path)
    try:
        conn.execute("DELETE FROM gpkg_metadata_reference")
        conn.execute("DELETE FROM gpkg_metadata")
        conn.commit()
    finally:
        conn.close()
    return path


def add_gdal_metadata(path):
    """Dataset metadata as GDAL writes it, which the record must not touch."""
    conn = sqlite3.connect(path)
    try:
        cursor = conn.execute(
            "INSERT INTO gpkg_metadata (md_scope, md_standard_uri, mime_type, "
            "metadata) VALUES ('dataset', ?, 'text/xml', ?)",
            (GDAL_URI, GDAL_METADATA))
        conn.execute(
            "INSERT INTO gpkg_metadata_reference (reference_scope, "
            "md_file_id) VALUES ('geopackage', ?)", (cursor.lastrowid,))
        conn.commit()
    finally:
        conn.close()


def metadata_rows(path):
    conn = support.connect_read_only(path)
    try:
        return conn.execute(
            "SELECT md_standard_uri, metadata FROM gpkg_metadata "
            "ORDER BY id").fetchall()
    finally:
        conn.close()


def run_tool(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = set_template_version.main([str(arg) for arg in args])
    return code, out.getvalue()


class RecordTest(support.TempDirTestCase):

    def copy(self, name):
        return support.copy_to(support.SERVICE_GPKG, self.tmp, name)

    def test_writing_again_keeps_one_record_and_other_metadata(self):
        path = self.copy("again.gpkg")
        add_gdal_metadata(path)
        conn = sqlite3.connect(path)
        try:
            gpkg_common.write_template_version(conn, "2.0")
            gpkg_common.write_template_version(conn, "2.1")
            conn.commit()
        finally:
            conn.close()
        self.assertEqual("2.1", support.template_version(path)["version"])
        uris = [uri for uri, _ in metadata_rows(path)]
        self.assertEqual(1, uris.count(gpkg_common.TEMPLATE_METADATA_URI))
        self.assertEqual(1, uris.count(GDAL_URI))

    def test_a_file_without_the_metadata_tables_gets_them(self):
        path = support.make_redline_only_gpkg(self.tmp / "bare.gpkg")
        self.assertIsNone(support.template_version(path))
        conn = sqlite3.connect(path)
        try:
            gpkg_common.write_template_version(conn)
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(gpkg_common.TEMPLATE_VERSION,
                         support.template_version(path)["version"])
        conn = support.connect_read_only(path)
        try:
            registered = conn.execute(
                "SELECT table_name FROM gpkg_extensions "
                "WHERE extension_name = 'gpkg_metadata' ORDER BY table_name"
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual([("gpkg_metadata",), ("gpkg_metadata_reference",)],
                         registered)

    def test_a_record_that_is_not_json_is_refused(self):
        path = self.copy("bad-json.gpkg")
        conn = sqlite3.connect(path)
        try:
            conn.execute("UPDATE gpkg_metadata SET metadata = 'version 1.0'")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            support.template_version(path)

    def test_two_records_are_refused(self):
        path = self.copy("two.gpkg")
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "INSERT INTO gpkg_metadata (md_scope, md_standard_uri, "
                "mime_type, metadata) SELECT md_scope, md_standard_uri, "
                "mime_type, metadata FROM gpkg_metadata")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaisesRegex(ValueError, "2 times"):
            support.template_version(path)

    def test_legacy_output_records_no_version(self):
        """Convert to legacy writes the Natural England layout, not this."""
        site = support.generate_site(
            self.tmp / "site", "--habitats", "4", "--area-ha", "1",
            "--seed", "3", "--no-legacy", "--no-metric")
        out = self.tmp / "legacy"
        new_to_old.convert(support.site_gpkg(site), out, carry_lineage=True,
                           dry_run=False)
        written = sorted(out.glob("*.gpkg"))
        self.assertTrue(written)
        for path in written:
            with self.subTest(file=path.name):
                self.assertIsNone(support.template_version(path))


class ToolTest(support.TempDirTestCase):

    def test_check_passes_on_the_template(self):
        code, out = run_tool("--check", support.SERVICE_GPKG)
        self.assertEqual(0, code, out)
        self.assertIn("no change needed", out)

    def test_check_fails_and_writes_nothing_without_a_record(self):
        path = without_version(support.copy_to(support.SERVICE_GPKG,
                                               self.tmp / "check"))
        before = path.read_bytes()
        code, out = run_tool("--check", path)
        self.assertEqual(1, code)
        self.assertIn("no template version recorded", out)
        self.assertEqual(before, path.read_bytes())

    def test_writes_the_record_once_and_then_changes_nothing(self):
        path = without_version(support.copy_to(support.SERVICE_GPKG,
                                               self.tmp / "write"))
        self.assertEqual(0, run_tool(path)[0])
        after = path.read_bytes()
        code, out = run_tool(path)
        self.assertEqual(0, code)
        self.assertIn("no change needed", out)
        self.assertEqual(after, path.read_bytes())
        self.assertEqual(gpkg_common.TEMPLATE_VERSION,
                         support.template_version(path)["version"])

    def test_replaces_an_older_version(self):
        path = support.copy_to(support.SERVICE_GPKG, self.tmp / "older")
        conn = sqlite3.connect(path)
        try:
            gpkg_common.write_template_version(conn, "0.9")
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(1, run_tool("--check", path)[0])
        self.assertEqual(0, run_tool(path)[0])
        self.assertEqual(gpkg_common.TEMPLATE_VERSION,
                         support.template_version(path)["version"])
