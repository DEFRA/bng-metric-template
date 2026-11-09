"""The width of each text column: declared in the template, wide enough for
every value a drop-down offers, and written by set_text_widths.py.

TEXT_LIMITS in gpkg_common.py is the template's one list of the limits. The template
declares each as TEXT(n), which GDAL, and so QGIS, reads as the field width.
"""

import contextlib
import csv
import io
import re
import sqlite3
import sys
import unittest
import urllib.parse
import xml.etree.ElementTree as ET
from unittest import mock

from tests import support
from tests.test_project_xml import (NULL_VALUE, VALUE_MAP, VALUE_RELATION,
                                    read_project_xml, value_map_values,
                                    widget_options)

# support puts the converter modules on sys.path.
import gpkg_common
import old_to_new

if str(support.TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(support.TOOLS_DIR))

import set_text_widths  # noqa: E402

TOOL = support.TOOLS_DIR / "set_text_widths.py"
NO_CHANGE = "no change needed"
WIDTH = re.compile(r"TEXT\((\d+)\)\Z")
NO_LIMIT = ("feature_uuid", "parent_uuid", "parent_geom")


def declared_types(gpkg):
    """{(table, column): declared type} for every column of every layer."""
    conn = support.connect_read_only(gpkg)
    try:
        return {(table, row[1]): row[2]
                for table in sorted(gpkg_common.feature_table_names(conn))
                for row in conn.execute(
                    f"PRAGMA table_info({gpkg_common.quote_ident(table)})")}
    finally:
        conn.close()


def declared_width(declared):
    match = WIDTH.match(declared)
    return int(match.group(1)) if match else None


class TemplateWidthsTest(unittest.TestCase):
    """The template's GeoPackage declares the limit of each text column."""

    @classmethod
    def setUpClass(cls):
        cls.types = declared_types(support.SERVICE_GPKG)

    def test_every_text_column_declares_its_limit(self):
        text = {key: kind for key, kind in self.types.items()
                if kind.upper().startswith("TEXT")}
        self.assertTrue(text)
        for (table, column), kind in text.items():
            with self.subTest(table=table, column=column):
                self.assertIn(column, gpkg_common.TEXT_LIMITS)
                self.assertEqual(gpkg_common.text_type(column), kind)

    def test_refs_hold_99_and_comments_999(self):
        for (table, column), kind in self.types.items():
            if column in ("Habitat Ref", "Parent Ref"):
                with self.subTest(table=table, column=column):
                    self.assertEqual("TEXT(99)", kind)
            if column == "Comment":
                with self.subTest(table=table, column=column):
                    self.assertEqual("TEXT(999)", kind)

    def test_the_lineage_columns_have_no_limit(self):
        for (table, column), kind in self.types.items():
            if column in NO_LIMIT:
                with self.subTest(table=table, column=column):
                    self.assertEqual("TEXT", kind)

    def test_other_types_are_unchanged(self):
        """Survey Date stays a date, and sizes stay REAL."""
        self.assertEqual("DATE",
                         self.types[("Red Line Boundary", "Survey Date")])
        for (table, column), kind in self.types.items():
            if column in ("Area", "Length", "Baseline Length"):
                with self.subTest(table=table, column=column):
                    self.assertEqual("REAL", kind)

    def test_a_width_is_still_text_affinity(self):
        """SQLite does not enforce a width, so a 1.0 reader reads TEXT."""
        conn = sqlite3.connect(":memory:")
        conn.execute('CREATE TABLE t ("Comment" TEXT(999))')
        long = "x" * 2000
        conn.execute("INSERT INTO t VALUES (?)", (long,))
        try:
            self.assertEqual((long, "text"), conn.execute(
                'SELECT "Comment", typeof("Comment") FROM t').fetchone())
        finally:
            conn.close()

    def test_convert_from_legacy_declares_the_same_types(self):
        """A file that Convert from legacy creates matches the template."""
        for table, spec in old_to_new.STAGED_LAYERS.items():
            for column, kind in spec["columns"]:
                with self.subTest(table=table, column=column):
                    self.assertEqual(self.types[(table, column)], kind)


class DropDownsFitTest(unittest.TestCase):
    """Every value a drop-down offers fits the width of its column."""

    @classmethod
    def setUpClass(cls):
        root = ET.fromstring(read_project_xml(support.SERVICE_PROJECT))
        cls.maplayers = list(root.iter("maplayer"))
        cls.sources = {element.findtext("id"): element.findtext("datasource")
                       for element in cls.maplayers}
        cls.types = declared_types(support.SERVICE_GPKG)

    def csv_values(self, layer_id, column):
        source = self.sources[layer_id]
        path = urllib.parse.unquote(source.split("?")[0][len("file:"):])
        csv_path = support.SERVICE_TEMPLATE_DIR / path
        with open(csv_path, encoding="utf-8-sig", newline="") as handle:
            return [row[column] for row in csv.DictReader(handle)
                    if row.get(column)]

    def offered(self):
        """(layer, field, values) for each drop-down of a data layer."""
        for element in self.maplayers:
            layer = element.findtext("layername")
            for field in element.iterfind("fieldConfiguration/field"):
                widget = field.find("editWidget")
                kind = widget.get("type")
                if kind == VALUE_MAP:
                    values = [value for value in value_map_values(widget)
                              if value != NULL_VALUE]
                elif kind == VALUE_RELATION:
                    options = widget_options(widget)
                    values = self.csv_values(options["Layer"],
                                             options["Key"])
                else:
                    continue
                yield layer, field.get("name"), values

    def test_every_value_offered_fits_its_column(self):
        checked = 0
        for layer, field, values in self.offered():
            declared = self.types.get((layer, field))
            if declared is None:
                continue
            width = declared_width(declared)
            with self.subTest(layer=layer, field=field):
                self.assertIsNotNone(width, f"{field} declares no width")
                too_long = [value for value in values if len(value) > width]
                self.assertEqual([], too_long)
                checked += 1
        self.assertGreater(checked, 50)

    def test_every_drop_down_list_value_fits_its_column(self):
        """The longest value of every list a drop-down reads, too, with no
        filter: a filter could hide a long value from the check above."""
        longest = {}
        for _layer, field, values in self.offered():
            if values and field in gpkg_common.TEXT_LIMITS:
                longest[field] = max(longest.get(field, 0),
                                     *(len(value) for value in values))
        for field, length in longest.items():
            with self.subTest(field=field):
                self.assertLessEqual(length, gpkg_common.TEXT_LIMITS[field])


class SetTextWidthsTest(support.TempDirTestCase):
    """development/tools/set_text_widths.py on a copy of the template."""

    def plain_copy(self, name):
        """A copy of the template's GeoPackage with every width taken off."""
        gpkg = support.copy_to(support.SERVICE_GPKG, self.tmp, name)
        conn = sqlite3.connect(gpkg, isolation_level=None)
        if hasattr(conn, "setconfig"):
            conn.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, False)
        (version,) = conn.execute("PRAGMA schema_version").fetchone()
        conn.execute("PRAGMA writable_schema = ON")
        conn.execute("UPDATE sqlite_master SET sql = "
                     "replace(replace(replace(sql, 'TEXT(999)', 'TEXT'), "
                     "'TEXT(255)', 'TEXT'), 'TEXT(99)', 'TEXT') "
                     "WHERE type = 'table'")
        conn.execute(f"PRAGMA schema_version = {version + 1}")
        conn.execute("PRAGMA writable_schema = OFF")
        conn.close()
        return gpkg

    def run_tool(self, *args):
        return support.run_python(TOOL, *map(str, args))

    def test_the_template_needs_no_change(self):
        result = self.run_tool("--check", support.SERVICE_GPKG)
        self.assertEqual(0, result.returncode, support.describe(result))
        self.assertIn(NO_CHANGE, result.stdout)

    def test_check_names_each_change_and_writes_nothing(self):
        gpkg = self.plain_copy("check.gpkg")
        before = gpkg.read_bytes()
        result = self.run_tool("--check", gpkg)
        self.assertEqual(1, result.returncode, support.describe(result))
        self.assertIn("Area Habitats Baseline: 'Habitat Ref' TEXT -> TEXT(99)",
                      result.stdout)
        self.assertEqual(before, gpkg.read_bytes())

    def test_it_declares_every_width_and_keeps_everything_else(self):
        gpkg = self.plain_copy("write.gpkg")
        before = self.snapshot(gpkg)
        result = self.run_tool(gpkg)
        self.assertEqual(0, result.returncode, support.describe(result))
        self.assertEqual(declared_types(support.SERVICE_GPKG),
                         declared_types(gpkg))
        self.assertEqual(before, self.snapshot(gpkg))
        again = self.run_tool(gpkg)
        self.assertIn(NO_CHANGE, again.stdout)
        self.assertEqual([], [p.name for p in self.tmp.glob(".set_text*")])

    def test_rows_are_kept(self):
        gpkg = self.plain_copy("rows.gpkg")
        long_comment = "c" * 1500
        support.insert_feature(
            gpkg, "Area Habitats Baseline", None,
            {"Habitat Ref": "R" * 120, "Comment": long_comment})
        self.assertEqual(0, self.run_tool(gpkg).returncode)
        (row,) = support.read_rows(gpkg, "Area Habitats Baseline")
        self.assertEqual(("R" * 120, long_comment),
                         (row["Habitat Ref"], row["Comment"]))

    def test_a_text_column_not_in_the_list_stops_it(self):
        gpkg = self.plain_copy("unknown.gpkg")
        conn = sqlite3.connect(gpkg)
        conn.execute('ALTER TABLE "Hedgerows Baseline" ADD COLUMN "Notes" TEXT')
        conn.commit()
        conn.close()
        before = gpkg.read_bytes()
        result = self.run_tool(gpkg)
        self.assertEqual(1, result.returncode, support.describe(result))
        self.assertIn("'Notes' is not in TEXT_LIMITS", result.stderr)
        self.assertEqual(before, gpkg.read_bytes())

    @staticmethod
    def snapshot(gpkg):
        """Everything but the CREATE TABLE text of the feature tables."""
        conn = support.connect_read_only(gpkg)
        try:
            tables = gpkg_common.feature_table_names(conn)
            master = conn.execute(
                "SELECT type, name, tbl_name, rootpage, "
                "CASE WHEN type = 'table' AND name IN (%s) THEN NULL "
                "ELSE sql END FROM sqlite_master ORDER BY name"
                % ",".join("?" * len(tables)), sorted(tables)).fetchall()
            system = {
                name: conn.execute(
                    f"SELECT * FROM {gpkg_common.quote_ident(name)}").fetchall()
                for name in ("gpkg_contents", "gpkg_geometry_columns",
                             "gpkg_extensions", "gpkg_metadata",
                             "gpkg_metadata_reference", "gpkg_ogr_contents",
                             "gpkg_spatial_ref_sys")}
            check = conn.execute("PRAGMA integrity_check").fetchall()
            return master, system, check
        finally:
            conn.close()


class OverLimitTest(unittest.TestCase):
    """over_limit counts characters as the BNG service does."""

    def test_a_value_over_the_limit_is_named(self):
        self.assertEqual(99, gpkg_common.over_limit("Habitat Ref", "R" * 100))

    def test_a_value_at_the_limit_fits(self):
        self.assertIsNone(gpkg_common.over_limit("Habitat Ref", "R" * 99))

    def test_spaces_at_the_ends_do_not_count(self):
        self.assertIsNone(
            gpkg_common.over_limit("Habitat Ref", " " + "R" * 99 + "   "))
        self.assertIsNone(
            gpkg_common.over_limit("Comment", "c" * 999 + "\t\n "))

    def test_spaces_inside_the_value_count(self):
        self.assertEqual(
            99, gpkg_common.over_limit("Habitat Ref", "R" * 50 + " " + "R" * 49))

    def test_characters_not_bytes_are_counted(self):
        self.assertIsNone(gpkg_common.over_limit("Habitat Ref", "é" * 99))

    def test_a_column_with_no_limit_is_never_over(self):
        self.assertIsNone(gpkg_common.over_limit("feature_uuid", "u" * 5000))


class SetTextWidthsFailureTest(support.TempDirTestCase):
    """A failure in set_text_widths.py leaves the GeoPackage as it was and
    removes the temporary copy."""

    def setUp(self):
        super().setUp()
        self.gpkg = SetTextWidthsTest.plain_copy(self, "failure.gpkg")
        self.before = self.gpkg.read_bytes()

    def assert_left_as_it_was(self):
        self.assertEqual(self.before, self.gpkg.read_bytes())
        self.assertEqual([], [p.name for p in self.tmp.glob(".set_text*")])

    def test_an_error_during_the_rewrite_changes_nothing(self):
        """The UPDATEs of sqlite_master are made, then the next statement
        fails: the rewrite is rolled back and the copy is removed."""
        real_connect = sqlite3.connect

        class FailingConnection(sqlite3.Connection):
            def execute(self, sql, *args):
                if sql.startswith("PRAGMA schema_version ="):
                    raise sqlite3.OperationalError("injected failure")
                return super().execute(sql, *args)

        def connect(path, *args, **kwargs):
            return real_connect(path, *args, factory=FailingConnection,
                                **kwargs)

        with mock.patch.object(set_text_widths.sqlite3, "connect", connect), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(sqlite3.OperationalError,
                                        "injected failure"):
                set_text_widths.main([str(self.gpkg)])
        self.assert_left_as_it_was()

    def test_a_failed_verification_changes_nothing(self):
        """The rewritten copy fails its checks: the file is not replaced."""
        failure = ["integrity check: injected failure"]
        stderr = io.StringIO()
        with mock.patch.object(set_text_widths, "verify",
                               return_value=failure) as verify, \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(stderr):
            self.assertEqual(1, set_text_widths.main([str(self.gpkg)]))
        verify.assert_called_once()
        self.assertIn("integrity check: injected failure", stderr.getvalue())
        self.assertIn("nothing written", stderr.getvalue())
        self.assert_left_as_it_was()

    def test_a_width_not_declared_in_the_copy_changes_nothing(self):
        """The real verify finds a width the rewrite did not write."""
        real_rewrite = set_text_widths.rewrite_definitions

        def rewrite_all_but_one(path, new_sql):
            kept = dict(new_sql)
            kept.pop(sorted(kept)[0])
            real_rewrite(path, kept)

        stderr = io.StringIO()
        with mock.patch.object(set_text_widths, "rewrite_definitions",
                               rewrite_all_but_one), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(stderr):
            self.assertEqual(1, set_text_widths.main([str(self.gpkg)]))
        self.assertIn("not written: ", stderr.getvalue())
        self.assertIn("nothing written", stderr.getvalue())
        self.assert_left_as_it_was()


if __name__ == "__main__":
    unittest.main()
