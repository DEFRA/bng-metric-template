"""Paths, imports and helpers shared by the test modules.

Every test works on copies in a temporary folder. Nothing here writes under
templates/ or reference/.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# The scripts under test are run from the repository, as their READMEs say.
# Bytecode is not written, so a test run leaves no __pycache__ behind.
sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO_ROOT / "plugin"
PACKAGE_DIR = PLUGIN_DIR / "bng_template_convert"
NSIP_GENERATOR_DIR = REPO_ROOT / "scale-test-nsip" / "generator"
SITE_GENERATOR = REPO_ROOT / "site-generator" / "generate_site.py"
DROPDOWN_CHECK = NSIP_GENERATOR_DIR / "dropdown_check.py"
TOOLS_DIR = REPO_ROOT / "development" / "tools"

TEMPLATES_DIR = REPO_ROOT / "templates"
SERVICE_TEMPLATE_DIR = TEMPLATES_DIR / "bng-service"
SERVICE_GPKG = SERVICE_TEMPLATE_DIR / "Layers" / "BNG Service Layers.gpkg"
SERVICE_PROJECT = SERVICE_TEMPLATE_DIR / "BNG Service Habitat Mapping.qgz"
LEGACY_TEMPLATE_DIR = TEMPLATES_DIR / "legacy-ne"
CSV_REFERENCES = "CSV References"

REFERENCE_DIR = REPO_ROOT / "reference"
METRIC_XLSX = REFERENCE_DIR / "The_Statutory_Metric_Macro_Disabled_1.0.4.xlsx"
METRIC_XLSM = REFERENCE_DIR / "The_Statutory_Metric_Macro_Enabled_1.0.4.xlsm"
GIS_IMPORT_TOOL = REFERENCE_DIR / "GIS Import Tool.xlsb"

# The converter modules run as plain scripts, the way build_plugin.py and the
# generators import them. The NSIP generator folder supplies gpkg_write and
# dropdown_check.
for folder in (PACKAGE_DIR, NSIP_GENERATOR_DIR):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import gpkg_common  # noqa: E402
import gpkg_write  # noqa: E402

SCRIPT_TIMEOUT_S = 300
SERVICE_SITE_FOLDER = "bng-service"
SERVICE_GPKG_IN_SITE = Path("Layers") / "BNG Service Layers.gpkg"


def run_python(*args, cwd=REPO_ROOT):
    """Run a Python script or `-c` snippet. Returns the CompletedProcess."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, *[str(arg) for arg in args]],
        cwd=cwd, env=env, capture_output=True, text=True,
        timeout=SCRIPT_TIMEOUT_S, check=False)


def describe(result):
    """The output of a finished script, for a failure message."""
    return (f"exit {result.returncode}\n--- stdout\n{result.stdout}"
            f"\n--- stderr\n{result.stderr}")


def generate_site(out_dir, *args):
    """Run the small-site generator into `out_dir`. Returns the folder."""
    result = run_python(SITE_GENERATOR, "--out", out_dir, *args)
    if result.returncode != 0:
        raise AssertionError(f"site generator failed: {describe(result)}")
    return Path(out_dir)


def site_gpkg(site_dir):
    """The BNG Service GeoPackage inside a generated site folder."""
    return Path(site_dir) / SERVICE_SITE_FOLDER / SERVICE_GPKG_IN_SITE


def copy_to(source, folder, name=None):
    """Copy one file into `folder`. Returns the new path."""
    target = Path(folder) / (name or Path(source).name)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def connect_read_only(gpkg):
    return sqlite3.connect(gpkg_common.read_only_uri(gpkg), uri=True)


def feature_tables(gpkg):
    conn = connect_read_only(gpkg)
    try:
        return gpkg_common.feature_table_names(conn)
    finally:
        conn.close()


def columns(gpkg, table):
    conn = connect_read_only(gpkg)
    try:
        return [row[1] for row in conn.execute(
            f"PRAGMA table_info({gpkg_common.quote_ident(table)})")]
    finally:
        conn.close()


def read_rows(gpkg, table):
    """Every row of a table, as dicts, in fid order."""
    conn = connect_read_only(gpkg)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(
            f"SELECT * FROM {gpkg_common.quote_ident(table)} ORDER BY fid")]
    finally:
        conn.close()


def by_ref(rows, ref_column):
    return {row[ref_column]: row for row in rows}


def open_for_writing(gpkg):
    """A connection that can write to a template copy, triggers and all."""
    conn = sqlite3.connect(gpkg)
    gpkg_common.register_spatial_functions(conn)
    return conn


def update(gpkg, table, values, where_column, where_value):
    """Set `values` on the rows of `table` whose column matches."""
    assignments = ", ".join(
        f"{gpkg_common.quote_ident(name)} = ?" for name in values)
    conn = open_for_writing(gpkg)
    try:
        conn.execute(
            f"UPDATE {gpkg_common.quote_ident(table)} SET {assignments} "
            f"WHERE {gpkg_common.quote_ident(where_column)} = ?",
            [*values.values(), where_value])
        conn.commit()
    finally:
        conn.close()


def insert_feature(gpkg, table, geometry, values):
    """Add one feature, with its geometry in the `geom` column."""
    names = ["geom", *values]
    quoted = ", ".join(gpkg_common.quote_ident(name) for name in names)
    marks = ", ".join("?" for _ in names)
    conn = open_for_writing(gpkg)
    try:
        conn.execute(
            f"INSERT INTO {gpkg_common.quote_ident(table)} ({quoted}) "
            f"VALUES ({marks})", [geometry, *values.values()])
        conn.commit()
    finally:
        conn.close()


def line(points):
    return gpkg_write.line_blob(points)


def make_gpkg_with_tables(path, tables):
    """An empty GeoPackage holding the given (name, geometry type) tables."""
    conn = sqlite3.connect(path)
    try:
        source = connect_read_only(SERVICE_GPKG)
        srs_rows = gpkg_common.read_srs_rows(source)
        source.close()
        gpkg_common.create_gpkg_system_tables(conn, srs_rows)
        for table, kind in tables:
            gpkg_common.create_feature_table(
                conn, table, "geom", kind, [("Habitat Ref", "TEXT")])
        conn.commit()
    finally:
        conn.close()
    return Path(path)


def make_old_named_gpkg(path):
    """A GeoPackage with the table names from before the 1.5.0 rename."""
    return make_gpkg_with_tables(path, (
        ("Red Line Boundary", "POLYGON"),
        ("Habitats Baseline", "POLYGON"),
        ("Habitats Post-Intervention", "POLYGON"),
        ("Trees Baseline", "POINT"),
        ("Trees Post-Intervention", "POINT")))


def make_redline_only_gpkg(path):
    """A GeoPackage with a red line but none of the habitat tables."""
    return make_gpkg_with_tables(path, (("Red Line Boundary", "POLYGON"),))


def make_partial_gpkg(path):
    """A current GeoPackage that holds the area habitat tables only."""
    return make_gpkg_with_tables(path, (
        ("Red Line Boundary", "POLYGON"),
        ("Area Habitats Baseline", "POLYGON"),
        ("Area Habitats Post-Intervention", "POLYGON")))


class TempDirTestCase(unittest.TestCase):
    """A test class with one temporary folder, removed after its tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        holder = tempfile.TemporaryDirectory(prefix="bng-template-tests-")
        cls.addClassCleanup(holder.cleanup)
        cls.tmp = Path(holder.name)
