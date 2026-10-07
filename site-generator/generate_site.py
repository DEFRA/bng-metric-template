"""Build a small synthetic BNG site in the BNG Service template.

    python3 site-generator/generate_site.py --habitats 20 --area-ha 6 \\
        --centre 455920.7,285323.1 --scheme housing --seed 7

Writes to site-generator/output/<name>/:

    bng-service/                   the BNG Service template, filled
    legacy-ne-baseline/            the Natural England template, baseline
    legacy-ne-post-intervention/   the Natural England template, post-intervention
    The_Statutory_Metric_...xlsm   the macro-enabled metric, on-site tabs filled

The same inputs always give the same GeoPackages, to the byte.
"""

import argparse
import os
import re
import shutil
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'scale-test-nsip', 'generator'))
sys.path.insert(0, os.path.join(ROOT, 'plugin', 'bng_template_convert'))

from gpkg_common import (register_spatial_functions,               # noqa: E402
                         update_layer_extent)
from dropdown_check import check_site, report                      # noqa: E402
import site_mesh                                                    # noqa: E402
import site_plan as plan                                            # noqa: E402
import site_outputs as outputs                                      # noqa: E402
import site_writers as writers                                      # noqa: E402

TEMPLATE_DIR = os.path.join(ROOT, 'templates', 'bng-service')
TEMPLATE_ASSETS = ('BNG Service Habitat Mapping.qgz', 'CSV References',
                   'HOW TO USE THIS TEMPLATE.md')
PRISTINE = os.path.join(TEMPLATE_DIR, 'Layers', 'BNG Service Layers.gpkg')
GPKG_NAME = os.path.join('Layers', 'BNG Service Layers.gpkg')
OUTPUT_DIR = os.path.join(HERE, 'output')
BNG_SERVICE_FOLDER = 'bng-service'

# Open country, away from any city, so a default site looks plausible.
DEFAULT_CENTRE = (455920.7, 285323.1)
BNG_MAX_EASTING = 700000
BNG_MAX_NORTHING = 1300000
MIN_HABITATS, MAX_HABITATS = 1, 50
MAX_TREES = 50
MAX_HEDGEROWS = 10
MIN_AREA_HA, MAX_AREA_HA = 0.05, 500.0
SQ_M_PER_HECTARE = 10000
AREA_TOLERANCE_SQ_M = 0.01

LAYERS = ['Area Habitats Baseline', 'Area Habitats Post-Intervention',
          'Hedgerows Baseline', 'Hedgerows Post-Intervention',
          'Individual Trees Baseline', 'Individual Trees Post-Intervention',
          'Red Line Boundary']


def parse_centre(text):
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*', text)
    if not match:
        raise argparse.ArgumentTypeError('use EASTING,NORTHING, e.g. 530000,180000')
    easting, northing = float(match[1]), float(match[2])
    if not (0 <= easting <= BNG_MAX_EASTING and 0 <= northing <= BNG_MAX_NORTHING):
        raise argparse.ArgumentTypeError('that point is outside the British National Grid')
    return (int(easting) if easting.is_integer() else easting,
            int(northing) if northing.is_integer() else northing)


def bounded(kind, low, high):
    def parse(text):
        value = kind(text)
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f'must be from {low} to {high}')
        return value
    return parse


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description='Build a small synthetic BNG site, baseline and '
                    'post-intervention, in the BNG Service template.')
    parser.add_argument('--habitats', type=bounded(int, MIN_HABITATS, MAX_HABITATS),
                        default=20, help='baseline habitat parcels, 1 to 50 '
                                         '(default 20)')
    parser.add_argument('--area-ha', type=bounded(float, MIN_AREA_HA, MAX_AREA_HA),
                        default=5.0, help='site area in hectares (default 5)')
    parser.add_argument('--centre', type=parse_centre, default=DEFAULT_CENTRE,
                        help='EASTING,NORTHING of the site centre in the British '
                             'National Grid (default 455920.7,285323.1)')
    parser.add_argument('--trees', type=bounded(int, 0, MAX_TREES), default=3,
                        help='baseline trees (default 3)')
    parser.add_argument('--hedgerows', type=bounded(int, 0, MAX_HEDGEROWS),
                        default=1, help='baseline hedgerows (default 1)')
    parser.add_argument('--landscape', choices=sorted(plan.LANDSCAPES),
                        default='pastoral', help='what the land is now '
                                                 '(default pastoral)')
    parser.add_argument('--scheme', choices=sorted(plan.SCHEMES),
                        default='housing', help='what is built (default housing)')
    parser.add_argument('--seed', type=bounded(int, 0, 2 ** 31 - 1), default=1,
                        help='changes the layout and the choices (default 1)')
    parser.add_argument('--name', help='site name, also the output folder name')
    parser.add_argument('--out', help='output folder (default '
                                      'site-generator/output/<name>)')
    parser.add_argument('--no-legacy', action='store_true',
                        help='leave out the filled Natural England templates')
    parser.add_argument('--no-metric', action='store_true',
                        help='leave out the filled Statutory Metric workbook')
    return parser.parse_args(argv)


def default_name(args):
    easting, northing = args.centre
    return (f'{args.scheme}-{args.landscape}-{args.habitats}p-'
            f'{args.area_ha:g}ha-{easting}-{northing}-seed{args.seed}')


def refresh_template(target):
    """Copy the template's project, lists and guide into the output folder."""
    os.makedirs(os.path.join(target, 'Layers'), exist_ok=True)
    for name in TEMPLATE_ASSETS:
        source = os.path.join(TEMPLATE_DIR, name)
        destination = os.path.join(target, name)
        if os.path.isdir(source):
            shutil.rmtree(destination, ignore_errors=True)
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)


def plan_site(args, name):
    choose = plan.Chooser(args.seed)
    mesh, cells, outline = site_mesh.build_site(
        args.habitats, args.area_ha * SQ_M_PER_HECTARE, args.centre, args.seed)
    parcels = plan.partition(cells, args.habitats, choose)
    owner = {cell: k for k, region in enumerate(parcels) for cell in region}
    zone_of = plan.zones(cells, args.scheme, choose)
    hedges = plan.build_hedges(args.hedgerows, cells, owner, choose)
    new_hedge = None
    if choose.roll(113) < plan.SCHEMES[args.scheme]['boundary_hedge']:
        busy = set().union(*map(plan.path_edges, hedges))
        new_hedge = plan.boundary_hedge(cells, zone_of, busy, choose)
    return {
        'seed': args.seed, 'choose': choose, 'mesh': mesh, 'cells': cells,
        'outline': outline, 'parcels': parcels, 'zones': zone_of,
        'hedges': hedges, 'new_hedge': new_hedge, 'trees': args.trees,
        'scheme': args.scheme, 'landscape': args.landscape,
        'centre': args.centre, 'name': name,
    }


def write_site(site, target):
    gpkg = os.path.join(target, GPKG_NAME)
    building = gpkg + '.building'
    shutil.copyfile(PRISTINE, building)
    conn = sqlite3.connect(building)
    register_spatial_functions(conn)
    # The template ships in WAL mode. Leaving it there means a read-only open
    # needs side files that are not written, so switch it off for the build.
    conn.execute('PRAGMA journal_mode = DELETE')
    totals = {
        'area habitats': writers.write_area_habitats(conn, site),
        'hedgerows': writers.write_hedgerows(conn, site),
        'trees': writers.write_trees(conn, site),
        'red line': writers.write_redline(conn, site),
    }
    for table in LAYERS:
        update_layer_extent(conn, table, 'geom')
    conn.commit()
    conn.execute('VACUUM')
    conn.close()
    os.replace(building, gpkg)
    for side in ('-shm', '-wal', '-journal'):
        try:
            os.remove(building + side)
        except FileNotFoundError:
            pass
    return gpkg, totals


def check_totals(args, site, totals):
    """Stop on anything the generator promised and did not deliver."""
    problems = []
    if totals['area habitats']['baseline'] != args.habitats:
        problems.append(f"{totals['area habitats']['baseline']} parcels, "
                        f"not {args.habitats}")
    redline = totals['red line']['hectares'] * SQ_M_PER_HECTARE
    parcels = totals['area habitats']['hectares'] * SQ_M_PER_HECTARE
    if abs(redline - parcels) > AREA_TOLERANCE_SQ_M:
        problems.append(f'parcels cover {parcels:.4f} sq m of a '
                        f'{redline:.4f} sq m red line')
    if len(site['hedges']) != args.hedgerows:
        problems.append(f"room for {len(site['hedges'])} of {args.hedgerows} "
                        'hedgerows; try fewer, more habitats, or another --seed')
    return problems


def main(argv=None):
    args = parse_args(argv)
    name = args.name or default_name(args)
    target = os.path.abspath(args.out or os.path.join(OUTPUT_DIR, name))
    service = os.path.join(target, BNG_SERVICE_FOLDER)
    refresh_template(service)
    site = plan_site(args, name)
    gpkg, totals = write_site(site, service)

    for layer, counts in totals.items():
        print(f'{layer:14s} {counts}')
    print(f'\nwritten {gpkg}')

    problems = check_totals(args, site, totals)
    invalid = check_site(service)
    if invalid:
        print("\nvalues the template's drop-downs would not offer:")
        report(invalid)
    for problem in problems:
        print(f'error: {problem}', file=sys.stderr)
    if invalid or problems:
        return 1
    print('every drop-down value is one the template offers')

    warnings = []
    if not args.no_legacy:
        folders, found = outputs.write_legacy_templates(gpkg, target)
        warnings += found
        for folder in folders:
            print(f'written {folder}')
    if not args.no_metric:
        paths, found = outputs.write_metric(gpkg, target)
        warnings += found
        for path in paths:
            print(f'written {path}')
    for warning in warnings:
        print(f'warning: {warning}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
