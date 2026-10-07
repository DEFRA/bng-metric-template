"""The Natural England templates and the Statutory Metric, filled from a site.

Each is a copy of the clean file in this repository, filled in place, so a
user gets the files they would otherwise have to prepare by hand:

  * the Natural England QGIS template twice, once for the baseline and once
    for the post-intervention stage, each with its own GeoPackage filled;
  * the macro-enabled Statutory Metric, with the on-site tabs filled.

The legacy rows come from the plugin's own conversion. They are copied into
the template's GeoPackage rather than replacing it, so the copy keeps the
styles, spatial indexes and layers the template ships with.
"""

import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, os.path.join(ROOT, 'scale-test-nsip', 'generator'))
sys.path.insert(0, os.path.join(ROOT, 'plugin', 'bng_template_convert'))

import gpkg_write as gw                                           # noqa: E402
from gpkg_common import (blob_geometry, register_spatial_functions,  # noqa: E402
                         update_layer_extent)
import new_to_old                                                 # noqa: E402
import to_metric                                                  # noqa: E402

LEGACY_TEMPLATE_DIR = os.path.join(ROOT, 'templates', 'legacy-ne')
LEGACY_GPKG = os.path.join('Layers', 'Net Gain Habitat Mapping Layers.gpkg')
LEGACY_STAGES = (('legacy-ne-baseline', 'Baseline'),
                 ('legacy-ne-post-intervention', 'Post-intervention'))
METRIC_NAME = 'The_Statutory_Metric_Macro_Enabled_1.0.4.xlsm'
METRIC_TEMPLATE = os.path.join(ROOT, 'reference', METRIC_NAME)
NOT_TEMPLATE_FILES = shutil.ignore_patterns(
    '*.backup-*', '*.gpkg-shm', '*.gpkg-wal', '.DS_Store')


def write_legacy_templates(staged_gpkg, target):
    """Write both filled copies of the Natural England template.

    Returns the folders written, and the conversion's warnings.
    """
    with tempfile.TemporaryDirectory() as scratch:
        report = new_to_old.convert(staged_gpkg, scratch, carry_lineage=False,
                                    dry_run=False)
        folders = []
        for folder, stage in LEGACY_STAGES:
            destination = os.path.join(target, folder)
            shutil.rmtree(destination, ignore_errors=True)
            shutil.copytree(LEGACY_TEMPLATE_DIR, destination,
                            ignore=NOT_TEMPLATE_FILES)
            converted = os.path.join(
                scratch, f'{new_to_old.LEGACY_LAYERS_STEM} - {stage}.gpkg')
            _fill_template_gpkg(os.path.join(destination, LEGACY_GPKG),
                                converted)
            folders.append(destination)
    return folders, report.warnings


def _geometry_columns(conn, schema):
    return {table: (column, kind) for table, column, kind in conn.execute(
        f'SELECT table_name, column_name, geometry_type_name '
        f'FROM {schema}.gpkg_geometry_columns')}


def _columns(conn, schema, table):
    return [row[1] for row in conn.execute(
        f'PRAGMA {schema}.table_info("{table}")')]


def _as_declared(blob, kind):
    """A single-part multipolygon written as the polygon the layer declares."""
    if blob is None or kind != 'POLYGON':
        return blob
    type_name, coordinates = blob_geometry(blob)
    if type_name == 'Polygon':
        return blob
    if type_name != 'MultiPolygon' or len(coordinates) != 1:
        raise ValueError(f'cannot store a {type_name} of {len(coordinates)} '
                         'parts in a polygon layer')
    rings = coordinates[0]
    points = [point for ring in rings for point in ring]
    return gw.blob(gw.wkb_polygon(rings), gw.envelope_of(points))


def _fill_template_gpkg(template_gpkg, converted_gpkg):
    """Copy every legacy row into the template's own GeoPackage."""
    conn = sqlite3.connect(template_gpkg)
    # The template's spatial-index triggers call ST_* functions.
    register_spatial_functions(conn)
    conn.execute('ATTACH DATABASE ? AS source', (converted_gpkg,))
    target_geometry = _geometry_columns(conn, 'main')
    source_geometry = _geometry_columns(conn, 'source')
    for table, (source_column, _) in sorted(source_geometry.items()):
        if table not in target_geometry:
            raise ValueError(f'the Natural England template has no {table} layer')
        target_column, kind = target_geometry[table]
        shared = [name for name in _columns(conn, 'main', table)
                  if name not in ('fid', target_column)
                  and name in _columns(conn, 'source', table)]
        quoted = ', '.join(f'"{name}"' for name in shared)
        rows = conn.execute(
            f'SELECT "{source_column}", {quoted} FROM source."{table}" '
            'ORDER BY fid').fetchall()
        conn.executemany(
            f'INSERT INTO main."{table}" ("{target_column}", {quoted}) '
            f'VALUES ({", ".join("?" * (len(shared) + 1))})',
            [(_as_declared(row[0], kind), *row[1:]) for row in rows])
        update_layer_extent(conn, table, target_column)
    conn.commit()
    conn.execute('DETACH DATABASE source')
    conn.execute('VACUUM')
    conn.close()


def write_metric(staged_gpkg, target):
    """Fill a copy of the macro-enabled metric. Returns (paths, warnings)."""
    out = os.path.join(target, METRIC_NAME)
    for stale in [name for name in os.listdir(target)
                  if name.startswith(METRIC_NAME.rsplit('.', 1)[0])]:
        os.remove(os.path.join(target, stale))
    report = to_metric.convert(staged_gpkg, METRIC_TEMPLATE, out)
    return report.paths or [out], report.warnings
