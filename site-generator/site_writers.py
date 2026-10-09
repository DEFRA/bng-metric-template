"""Turn the site plan into rows in the BNG Service template.

The rows follow the same rules as the NSIP corridor's, and use its column
lists: post-intervention area habitats tile their parent exactly, and
hedgerows and trees can fall short of their parent but never exceed it.
"""

import math
import os
import sys
import uuid
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scale-test-nsip', 'generator'))

import corridor_linear as lin                                      # noqa: E402
import corridor_scenario as sc                                     # noqa: E402
import gpkg_write as gw                                            # noqa: E402
from corridor_mesh import line_length, ring_area                   # noqa: E402
from corridor_parcels import parcel_ring, trace_ring               # noqa: E402
from corridor_writers import (AREA_BASELINE, AREA_PI,              # noqa: E402
                              BASELINE_SIGNIFICANCE, HABITAT_BASE_COLS,
                              HABITAT_PI_COLS, HEDGE_BASE_COLS,
                              HEDGE_DISTINCTIVENESS, HEDGE_PI_COLS,
                              REDLINE_COLS, TREE_BASE_COLS, TREE_BASELINE,
                              TREE_PI, TREE_PI_COLS, connected_components,
                              insert_many)
import site_plan as plan                                           # noqa: E402

SQ_M_PER_HECTARE = 10000
ON_SITE = 'N/A'
SURVEY_DATE = '2026-05-18'
SURVEY_DETAILS = ('UKHab walkover, condition assessed to Statutory '
                  'Biodiversity Metric criteria')
MAPPED_BY = 'Site generator'
COMPANY = 'Synthetic test data, not a real site'
BASE_MAP = 'OS MasterMap Topography'
TREE_OFFSET_FRACTION = 0.15
TREE_OFFSET_MAX_M = 3.0
# Trees closer than this share a canopy, and read as one on the plan.
TREE_SPACING_FRACTION = 0.25
TREE_PLACEMENT_TRIES = 12


def uid(seed, name):
    """A stable UUID, so a re-run with the same seed gives the same file."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'bng-site/{seed}/{name}'))


def path_points(mesh, nodes):
    """The polyline along a path of mesh nodes, with no repeated joints."""
    points = []
    for a, b in zip(nodes, nodes[1:]):
        kind, i, j, forward = plan.edge_between(a, b)
        piece = mesh.edge_line(kind, i, j)
        if not forward:
            piece = list(reversed(piece))
        points.extend(piece if not points else piece[1:])
    return points


def _pieces(mesh, cells, zone_of):
    """A parcel divided into the parts the development treats differently."""
    grouped = defaultdict(set)
    for cell in cells:
        grouped[zone_of[cell]].add(cell)
    pieces = []
    for zone, group in grouped.items():
        for component in connected_components(group):
            if trace_ring(mesh, component) is None:
                pieces += [(zone, {cell}) for cell in sorted(component)]
            else:
                pieces.append((zone, component))
    pieces.sort(key=lambda piece: min(piece[1]))
    return pieces


# -------------------------------------------------------------- area habitats

def _irreplaceable(habitat):
    """Irreplaceable Habitat as the template fills it.

    A habitat that allows one answer gets that answer. Where both are
    allowed the user chooses, and a small site says No: an irreplaceable
    parcel that is built over reads 'Any Loss Unacceptable' in the metric.
    """
    allowed = sc.IRREPLACEABLE.get(habitat, set())
    return next(iter(allowed)) if len(allowed) == 1 else 'No'


def write_area_habitats(conn, site):
    mesh, choose = site['mesh'], site['choose']
    parcels = site['parcels']
    areas = [abs(ring_area(parcel_ring(mesh, cells))) for cells in parcels]
    median = sorted(areas)[len(areas) // 2]
    largest = max(range(len(parcels)), key=lambda k: (areas[k], -k))
    base_rows, pi_rows = [], []
    retention = Counter()

    for index, cells in enumerate(parcels):
        seed = index + 1
        ref = f'AH-{seed:03d}'
        ring = parcel_ring(mesh, cells)
        area = areas[index]
        habitat = plan.baseline_habitat(
            site['landscape'], index == largest,
            len(parcels) < 3 or area >= median, choose, seed)
        condition = sc.condition_for(habitat, choose.roll(seed, 211))
        significance = BASELINE_SIGNIFICANCE
        distinctiveness = sc.DISTINCTIVENESS[habitat]
        irreplaceable = _irreplaceable(habitat)
        feature_uuid = uid(site['seed'], f'area/{ref}')
        blob = gw.polygon_blob(ring)
        base_rows.append((blob, ref, sc.BROAD[habitat], habitat,
                          distinctiveness, condition, significance,
                          irreplaceable, area / SQ_M_PER_HECTARE, None,
                          feature_uuid))

        pieces = _pieces(mesh, cells, site['zones'])
        for number, (zone, group) in enumerate(pieces, start=1):
            whole = len(pieces) == 1
            child_ring = ring if whole else parcel_ring(mesh, group)
            child_area = area if whole else abs(ring_area(child_ring))
            child_seed = seed * 31 + number
            kind, proposed, proposed_condition = plan.intervention(
                zone, site['scheme'], habitat, condition, choose, child_seed)
            retention[kind] += 1
            advance, delay = sc.timing_for(kind, choose.key(child_seed, 6600))
            pi_rows.append((
                gw.polygon_blob(child_ring), ref if whole else f'{ref}-{number}',
                ref, sc.BROAD[habitat], habitat, distinctiveness, condition,
                significance, irreplaceable, kind, sc.BROAD[proposed], proposed,
                sc.DISTINCTIVENESS[proposed], proposed_condition,
                significance if kind == sc.RETAINED
                else sc.strategic_significance(choose.key(child_seed, 909)),
                advance, delay, ON_SITE, child_area / SQ_M_PER_HECTARE,
                feature_uuid, gw.polygon_wkt(ring)))

    insert_many(conn, AREA_BASELINE, HABITAT_BASE_COLS, base_rows)
    insert_many(conn, AREA_PI, HABITAT_PI_COLS, pi_rows)
    return {'baseline': len(base_rows), 'post_intervention': len(pi_rows),
            **{kind.lower(): n for kind, n in sorted(retention.items())},
            'hectares': round(sum(areas) / SQ_M_PER_HECTARE, 4)}


# ------------------------------------------------------------------ hedgerows

def _hedge_proposal(hedge_type, condition, choose, seed):
    """Retained or enhanced, only ever as the template's lists allow."""
    if choose.roll(seed, 1307) >= 0.32:
        return 'Retained', hedge_type, condition
    target = lin.HEDGE_ENHANCEMENT.get(hedge_type)
    if (target and lin.hedge_can_become(hedge_type, 'Enhanced', target)
            and lin.hedge_condition_allowed(target, 'Good')):
        return 'Enhanced', target, 'Good'
    improved = 'Good' if condition == 'Moderate' else 'Moderate'
    if (condition != 'Good'
            and lin.hedge_can_become(hedge_type, 'Enhanced', hedge_type)
            and lin.hedge_condition_allowed(hedge_type, improved)):
        return 'Enhanced', hedge_type, improved
    return 'Retained', hedge_type, condition


def write_hedgerows(conn, site):
    mesh, choose, zone_of = site['mesh'], site['choose'], site['zones']
    clears = plan.SCHEMES[site['scheme']]['clears_hedges']
    base_rows, pi_rows = [], []
    counts = Counter()

    for index, nodes in enumerate(site['hedges']):
        seed = index + 1
        ref = f'HR-{seed:02d}'
        points = path_points(mesh, nodes)
        length = line_length(points)
        hedge_type = choose.pick(lin.HEDGE_TYPES, seed, 1301)
        condition = lin.hedge_condition(hedge_type, choose.roll(seed, 1303))
        significance = BASELINE_SIGNIFICANCE
        distinctiveness = HEDGE_DISTINCTIVENESS[hedge_type]
        feature_uuid = uid(site['seed'], f'hedge/{ref}')
        blob = gw.line_blob(points)
        base_rows.append((blob, ref, hedge_type, distinctiveness, condition,
                          significance, length, None, feature_uuid))

        survives = [not (clears and any(zone_of[c] == plan.CORE
                                        for c in plan.edge_cells(a, b)))
                    for a, b in zip(nodes, nodes[1:])]
        stretches = lin.runs(survives)
        if not stretches:
            counts['lost'] += 1
        for number, (start, end) in enumerate(stretches, start=1):
            child = path_points(mesh, nodes[start:end + 1])
            child_seed = seed * 37 + number
            kind, proposed, proposed_condition = _hedge_proposal(
                hedge_type, condition, choose, child_seed)
            counts[kind.lower()] += 1
            advance, delay = sc.timing_for(kind, choose.key(child_seed, 6600))
            pi_rows.append((
                gw.line_blob(child),
                ref if len(stretches) == 1 else f'{ref}-{number}', ref,
                hedge_type, distinctiveness, condition, significance, length,
                kind, proposed, HEDGE_DISTINCTIVENESS[proposed],
                proposed_condition,
                significance if kind == sc.RETAINED
                else lin.significance(choose.key(child_seed, 1305)),
                advance, delay, ON_SITE,
                line_length(child), feature_uuid, gw.line_wkt(points)))

    if site['new_hedge']:
        points = path_points(mesh, site['new_hedge'])
        proposed = choose.pick(lin.HEDGE_CREATED, 1417)
        advance, delay = sc.timing_for('Created', choose.key(1419))
        counts['created'] += 1
        pi_rows.append((
            gw.line_blob(points), 'HN-01', None, 'To be created', 'N/A', 'N/A',
            None, None, 'Created', proposed, HEDGE_DISTINCTIVENESS[proposed],
            'Good', lin.significance(choose.key(1421)), advance, delay,
            ON_SITE, line_length(points), None, None))

    insert_many(conn, 'Hedgerows Baseline', HEDGE_BASE_COLS, base_rows)
    insert_many(conn, 'Hedgerows Post-Intervention', HEDGE_PI_COLS, pi_rows)
    return {'baseline': len(base_rows), 'post_intervention': len(pi_rows),
            **dict(sorted(counts.items()))}


# ---------------------------------------------------------------------- trees

def _hedge_tree(mesh, hedge, choose, seed):
    """A point just off a hedge, and the cell it stands in."""
    edges = list(zip(hedge, hedge[1:]))
    a, b = edges[int(choose.roll(seed, 1801) * len(edges))]
    kind, i, j, _ = plan.edge_between(a, b)
    line = mesh.edge_line(kind, i, j)
    vertex = 1 + int(choose.roll(seed, 1803) * (len(line) - 2))
    before, here, after = line[vertex - 1], line[vertex], line[vertex + 1]
    dx, dy = after[0] - before[0], after[1] - before[1]
    norm = math.hypot(dx, dy)
    left = choose.roll(seed, 1805) < 0.5
    side = 1.0 if left else -1.0
    offset = min(TREE_OFFSET_MAX_M, TREE_OFFSET_FRACTION * mesh.cell_side_m)
    point = (here[0] - side * dy / norm * offset,
             here[1] + side * dx / norm * offset)
    # Walking an edge from its lower node, the cell on the left is the one
    # with the higher index across that edge.
    below, above = plan.edge_cells(a, b)
    if kind == 'A':
        cell = above if left else below
    else:
        cell = below if left else above
    return point, cell


def _cell_tree(mesh, cells, choose, seed):
    cell = cells[int(choose.roll(seed, 1811) * len(cells))]
    u = 0.3 + 0.4 * choose.roll(seed, 1813)
    v = 0.3 + 0.4 * choose.roll(seed, 1817)
    return mesh.cell_point(cell[0], cell[1], u, v), cell


def _spaced(place, placed, spacing):
    """The first placement, of several tries, clear of the trees placed."""
    for attempt in range(TREE_PLACEMENT_TRIES):
        point, cell = place(attempt)
        if all(math.hypot(point[0] - x, point[1] - y) >= spacing
               for x, y in placed):
            break
    placed.append(point)
    return point, cell


def write_trees(conn, site):
    mesh, choose, zone_of = site['mesh'], site['choose'], site['zones']
    scheme = plan.SCHEMES[site['scheme']]
    urban_landscape = site['landscape'] == 'urban-fringe'
    setting = 'Urban tree' if urban_landscape else 'Rural tree'
    all_cells = sorted(site['cells'])
    base_rows, pi_rows = [], []
    counts = Counter()
    placed = []
    spacing = TREE_SPACING_FRACTION * mesh.cell_side_m

    for index in range(site['trees']):
        seed = index + 1
        ref = f'TR-{seed:02d}'
        if site['hedges'] and choose.roll(seed, 1901) < 0.6:
            hedge = site['hedges'][index % len(site['hedges'])]
            point, cell = _spaced(
                lambda k: _hedge_tree(mesh, hedge, choose, seed * 100 + k),
                placed, spacing)
        else:
            point, cell = _spaced(
                lambda k: _cell_tree(mesh, all_cells, choose, seed * 100 + k),
                placed, spacing)
        size = choose.pick(lin.TREE_SIZES, seed, 1903)
        tree_type = choose.pick(lin.TREE_TYPES, seed, 1905)
        condition = choose.pick(lin.TREE_CONDITIONS, seed, 1907)
        significance = BASELINE_SIGNIFICANCE
        feature_uuid = uid(site['seed'], f'tree/{ref}')
        blob = gw.point_blob(point)
        base_rows.append((blob, ref, size, tree_type, setting, condition,
                          significance, 1,
                          lin.baseline_tree_note(choose.roll(seed, 1909)),
                          feature_uuid))
        if scheme['clears_trees'] and zone_of[cell] == plan.CORE:
            counts['lost'] += 1
            continue
        retention, proposed_condition, note = lin.tree_outcome(
            condition, choose.roll(seed, 1911))
        advance, delay = sc.timing_for(retention, choose.key(seed, 1913))
        counts[retention.lower()] += 1
        pi_rows.append((
            blob, ref, ref, size, tree_type, setting, condition, significance,
            retention, size, tree_type, setting, proposed_condition,
            significance, 'Existing', advance, delay, ON_SITE, 1, note,
            feature_uuid, gw.point_wkt(point)))

    planted = []
    low, high = scheme['street_trees']
    core_cells = [c for c in all_cells if zone_of[c] == plan.CORE]
    margin_cells = [c for c in all_cells if zone_of[c] == plan.MARGIN]
    if core_cells:
        planted += [(core_cells, True)] * (
            low + int(choose.roll(2001) * (high - low + 1)))
    if margin_cells:
        planted += [(margin_cells, urban_landscape)] * (
            1 + int(choose.roll(2003) * 2))
    for number, (cells, urban) in enumerate(planted, start=1):
        seed = 700 + number
        point, _ = _spaced(
            lambda k, cells=cells, seed=seed: _cell_tree(
                mesh, cells, choose, seed * 100 + k),
            placed, spacing)
        advance, delay = sc.timing_for('Created', choose.key(seed, 2005))
        counts['created'] += 1
        pi_rows.append((
            gw.point_blob(point), f'TN-{number:02d}', None, 'N/A', 'N/A', 'N/A',
            'N/A', None, 'Created',
            choose.pick([('Small', 0.74), ('Medium', 0.26)], seed, 2007),
            'Native', 'Urban tree' if urban else 'Rural tree',
            choose.pick(lin.PLANTED_TREE_CONDITIONS, seed, 2009),
            lin.tree_significance(choose.key(seed, 2011)), 'Newly Planted',
            advance, delay, ON_SITE, 1, None, None, None))

    insert_many(conn, TREE_BASELINE, TREE_BASE_COLS, base_rows)
    insert_many(conn, TREE_PI, TREE_PI_COLS, pi_rows)
    return {'baseline': len(base_rows), 'post_intervention': len(pi_rows),
            **dict(sorted(counts.items()))}


# ---------------------------------------------------------- red line boundary

def write_redline(conn, site):
    ring = site['outline']
    easting, northing = site['centre']
    insert_many(conn, 'Red Line Boundary', REDLINE_COLS, [(
        gw.polygon_blob(ring), site['name'],
        f'Centred on easting {easting}, northing {northing}', SURVEY_DATE,
        SURVEY_DETAILS, MAPPED_BY, COMPANY, BASE_MAP)])
    return {'hectares': round(abs(ring_area(ring)) / SQ_M_PER_HECTARE, 4)}
