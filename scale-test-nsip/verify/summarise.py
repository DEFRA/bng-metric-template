#!/usr/bin/env python3
"""Report what the generated site contains, straight from the GeoPackage."""

import collections
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'plugin',
                                'bng_template_convert'))
from gpkg_common import blob_geometry            # noqa: E402

TARGET = os.path.join(HERE, '..', 'hs2-phase2a-subsection', 'Layers',
                      'BNG Service Layers.gpkg')


def vertex_count(coordinates):
    if not coordinates:
        return 0
    if not isinstance(coordinates[0], (list, tuple)):
        return 1
    return sum(vertex_count(part) for part in coordinates)


def main():
    conn = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else TARGET)
    print(f'{"layer":42s} {"rows":>7s} {"vertices":>10s}')
    total_vertices = 0
    for (table,) in conn.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type='features' "
            "ORDER BY table_name"):
        rows = conn.execute(f'SELECT geom FROM "{table}"').fetchall()
        vertices = sum(vertex_count(blob_geometry(blob)[1])
                       for (blob,) in rows if blob is not None)
        total_vertices += vertices
        print(f'{table:42s} {len(rows):7d} {vertices:10d}')
    print(f'{"TOTAL":42s} {"":7s} {total_vertices:10d}')

    print('\nbaseline area habitats')
    for habitat, count, hectares in conn.execute(
            'SELECT "Baseline Habitat Type", COUNT(*), SUM("Area") '
            'FROM "Area Habitats Baseline" GROUP BY 1 ORDER BY 3 DESC'):
        print(f'  {count:6d}  {hectares:10.2f} ha  {habitat}')

    print('\npost-intervention retention')
    for retention, count, hectares in conn.execute(
            'SELECT "Retention Category", COUNT(*), SUM("Area") '
            'FROM "Area Habitats Post-Intervention" GROUP BY 1 ORDER BY 3 DESC'):
        print(f'  {count:6d}  {hectares:10.2f} ha  {retention}')

    print('\nproposed area habitats')
    for habitat, count, hectares in conn.execute(
            'SELECT "Proposed Habitat Type", COUNT(*), SUM("Area") '
            'FROM "Area Habitats Post-Intervention" GROUP BY 1 ORDER BY 3 DESC'):
        print(f'  {count:6d}  {hectares:10.2f} ha  {habitat}')

    print('\nhedgerows, watercourses and trees')
    for label, sql in [
        ('hedgerow types', 'SELECT "Baseline Hedge Type", COUNT(*), '
                           'ROUND(SUM("Length")/1000, 2) FROM "Hedgerows Baseline" '
                           'GROUP BY 1 ORDER BY 3 DESC'),
        ('watercourse types', 'SELECT "Baseline River Type", COUNT(*), '
                              'ROUND(SUM("Length")/1000, 2) FROM "Watercourses Baseline" '
                              'GROUP BY 1 ORDER BY 3 DESC'),
        ('tree sizes', 'SELECT "Baseline Tree Size", COUNT(*), SUM("Count") '
                       'FROM "Individual Trees Baseline" GROUP BY 1 ORDER BY 2 DESC'),
    ]:
        print(f'  {label}')
        for name, count, measure in conn.execute(sql):
            print(f'    {count:6d}  {measure:9}  {name}')

    print('\ndistinctiveness bands present')
    bands = collections.Counter()
    for column, table in [('Baseline Distinctiveness', 'Area Habitats Baseline'),
                          ('Proposed Distinctiveness', 'Area Habitats Post-Intervention'),
                          ('Baseline Distinctiveness', 'Hedgerows Baseline'),
                          ('Baseline Distinctiveness', 'Watercourses Baseline')]:
        for (band,) in conn.execute(f'SELECT DISTINCT "{column}" FROM "{table}"'):
            bands[band] += 1
    print('   ', ', '.join(sorted(bands)))
    conn.close()


if __name__ == '__main__':
    main()
