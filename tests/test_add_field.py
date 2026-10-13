"""development/tools/add_field.py: adding a column to the template.

The table is rebuilt to put the column in place, so a failed rebuild must
leave the table as it was, and a bad layer name must change nothing.
"""

import contextlib
import io
import sqlite3
import sys
import unittest

from tests import support

if str(support.TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(support.TOOLS_DIR))

import add_field  # noqa: E402

TABLE = "habitats"
TRIGGER = (f'CREATE TRIGGER "{TABLE}_count" AFTER INSERT ON "{TABLE}" '
           "BEGIN SELECT 1; END")
TREE_TABLE = "Individual Trees Post-Intervention"


def make_table(path, columns):
    conn = sqlite3.connect(path)
    try:
        conn.execute(f'CREATE TABLE "{TABLE}" ({columns})')
        conn.execute(TRIGGER)
        conn.commit()
    finally:
        conn.close()


def schema(path):
    conn = sqlite3.connect(path)
    try:
        return [(kind, name, sql) for kind, name, sql in conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY name")]
    finally:
        conn.close()


def column_names(path, table=TABLE):
    conn = sqlite3.connect(path)
    try:
        return add_field.column_names(conn, table)
    finally:
        conn.close()


class AddColumnTest(support.TempDirTestCase):

    def gpkg(self, name, columns):
        path = self.tmp / f"{name}.gpkg"
        make_table(path, columns)
        return path

    def test_puts_the_column_after_its_anchor_and_keeps_the_triggers(self):
        path = self.gpkg("plain", '"fid" INTEGER PRIMARY KEY, "a" TEXT, '
                                  '"b" TEXT')
        self.assertTrue(add_field.add_column(path, TABLE, "Comment", "a",
                                             "TEXT"))
        self.assertEqual(["fid", "a", "Comment", "b"], column_names(path))
        self.assertIn(("trigger", f"{TABLE}_count", TRIGGER), schema(path))

    def test_running_twice_changes_nothing(self):
        path = self.gpkg("twice", '"fid" INTEGER PRIMARY KEY, "a" TEXT')
        add_field.add_column(path, TABLE, "Comment", "a", "TEXT")
        before = schema(path)
        self.assertFalse(add_field.add_column(path, TABLE, "Comment", "a",
                                              "TEXT"))
        self.assertEqual(before, schema(path))

    def test_a_create_that_fails_leaves_the_table_as_it_was(self):
        # The new column lands inside the CHECK list: invalid SQL.
        path = self.gpkg("check", '"fid" INTEGER PRIMARY KEY, '
                                  "\"a\" TEXT CHECK(\"a\" IN ('x','y')), "
                                  '"b" TEXT')
        before = schema(path)
        with self.assertRaises(sqlite3.Error):
            add_field.add_column(path, TABLE, "Comment", "a", "TEXT")
        self.assertEqual(before, schema(path))

    def test_a_column_put_in_the_wrong_place_is_undone(self):
        # The new column lands inside the default's text: valid SQL, but
        # no new column.
        path = self.gpkg("default", '"fid" INTEGER PRIMARY KEY, '
                                    "\"a\" TEXT DEFAULT 'x,y', \"b\" TEXT")
        before = schema(path)
        with self.assertRaises(SystemExit):
            add_field.add_column(path, TABLE, "Comment", "a", "TEXT")
        self.assertEqual(before, schema(path))


class LayerNamesTest(support.TempDirTestCase):

    def test_an_unknown_layer_changes_neither_file(self):
        project = support.copy_to(support.SERVICE_PROJECT, self.tmp)
        gpkg = support.copy_to(support.SERVICE_GPKG, self.tmp)
        project_bytes = project.read_bytes()
        gpkg_bytes = gpkg.read_bytes()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            status = add_field.main([
                str(project), "Notes", "--gpkg", str(gpkg),
                "--layer", TREE_TABLE, "--like", "No Such Layer",
                "--after", "Comment"])
        self.assertEqual(1, status)
        self.assertIn("no such layer: No Such Layer", stderr.getvalue())
        self.assertEqual(project_bytes, project.read_bytes())
        self.assertEqual(gpkg_bytes, gpkg.read_bytes())


if __name__ == "__main__":
    unittest.main()
