"""Turn the corridor model into rows in the BNG Service template.

One writer per habitat type. Each returns a small dictionary of counts so the
generator can report what it produced.

Two rules shape the post-intervention side, and both come from how the staged
template reconciles a child against its parent:

  * area habitats must balance exactly, so every child is a union of its
    parent's own mesh cells and the children of a parcel tile it completely;
  * hedgerows and trees may fall short of their parent but never exceed it, so
    a hedge that the works remove is expressed by the surviving stretches
    alone, with the loss left as the residual.

Watercourses are the exception to both: a re-meandered channel leaves its old
line and gets longer, so a parent simply has to have at least one child.
"""

import uuid
from collections import defaultdict

import corridor_linear as lin
import corridor_scenario as sc
import gpkg_write as gw
from corridor_mesh import _hash01, line_length, ring_area
from corridor_parcels import build_parcels, parcel_ring, trace_ring

SITE_NAME = 'Rail scheme, Handsacre to Crewe: subsection C4'
LOCATION = 'Staffordshire and Cheshire East'
SURVEY_DATE = '2026-05-18'
SURVEY_DETAILS = ('UKHab Level 4 walkover, condition assessed to Statutory '
                  'Biodiversity Metric criteria')
MAPPED_BY = 'Corridor Ecology Team'
COMPANY = 'Synthetic test data, not a real scheme'
BASE_MAP = 'OS MasterMap Topography, May 2026'

# Densities rather than counts, so a shorter section of the scheme carries
# proportionally fewer features instead of the whole scheme's worth squeezed
# into it. The rates are the full corridor's, per 40 m station.
TREES_PER_STATION = 3600 / 1396
CREATED_HEDGE_ATTEMPTS_PER_STATION = 900 / 1396
CREATED_TREE_ATTEMPTS_PER_STATION = 1900 / 1396
SQ_M_PER_HECTARE = 10000
ON_SITE = 'N/A'
# Every baseline feature, and every post-intervention part of one, is Low.
# A feature created from nothing has no baseline part, and so no baseline
# significance.
BASELINE_SIGNIFICANCE = sc.SS_LOW
AREA_BASELINE = 'Area Habitats Baseline'
AREA_PI = 'Area Habitats Post-Intervention'
TREE_BASELINE = 'Individual Trees Baseline'
TREE_PI = 'Individual Trees Post-Intervention'


def uid(seed):
    """A stable UUID, so a re-run produces the same file."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'bng-scale-test/{seed}'))


def insert_many(conn, table, columns, rows):
    placeholders = ', '.join('?' * len(columns))
    quoted = ', '.join(f'"{name}"' for name in columns)
    conn.executemany(
        f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})', rows)


def connected_components(cells):
    remaining = set(cells)
    out = []
    while remaining:
        stack, group = [next(iter(remaining))], set()
        while stack:
            cell = stack.pop()
            if cell in group or cell not in remaining:
                continue
            group.add(cell)
            i, j = cell
            stack += [(i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)]
        remaining -= group
        out.append(group)
    return out


def zone_children(mesh, cells):
    """Divide a parcel into the pieces the works treat differently."""
    grouped = defaultdict(set)
    for cell in cells:
        grouped[sc.zone_of(mesh, *cell)].add(cell)
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

HABITAT_BASE_COLS = [
    'geom', 'Habitat Ref', 'Baseline Broad Habitat Type', 'Baseline Habitat Type',
    'Baseline Distinctiveness', 'Baseline Condition',
    'Baseline Strategic Significance', 'Irreplaceable Habitat', 'Area',
    'Comment', 'feature_uuid']
HABITAT_PI_COLS = [
    'geom', 'Habitat Ref', 'Parent Ref', 'Baseline Broad Habitat Type',
    'Baseline Habitat Type', 'Baseline Distinctiveness', 'Baseline Condition',
    'Baseline Strategic Significance', 'Irreplaceable Habitat',
    'Retention Category', 'Proposed Broad Habitat Type',
    'Proposed Habitat Type', 'Proposed Distinctiveness', 'Proposed Condition',
    'Proposed Strategic Significance', 'Habitat created in advance/years',
    'Delay in starting habitat creation/years', 'Spatial risk category',
    'Area', 'parent_uuid', 'parent_geom']

BATCH = 2000


def write_area_habitats(conn, mesh):
    parcels = build_parcels(mesh)
    base_rows, pi_rows = [], []
    counts = {'baseline': 0, 'post_intervention': 0, 'split': 0}
    baseline_area = 0.0

    for index, cells in enumerate(parcels):
        ring = parcel_ring(mesh, cells)
        area_sq_m = abs(ring_area(ring))
        baseline_area += area_sq_m
        seed = index + 1
        ref = f'AH-{seed:05d}'
        first = min(cells)
        habitat = sc.baseline_habitat(mesh, first[0], first[1], seed)
        broad = sc.BROAD[habitat]
        condition = sc.condition_for(habitat, _hash01(seed, 211))
        distinctiveness = sc.DISTINCTIVENESS[habitat]
        significance = BASELINE_SIGNIFICANCE
        irreplaceable = sc.is_irreplaceable(mesh, first[0], first[1], habitat)
        feature_uuid = uid(f'area/{ref}')
        blob = gw.polygon_blob(ring)
        wkt = gw.polygon_wkt(ring)

        base_rows.append((blob, ref, broad, habitat, distinctiveness, condition,
                          significance, irreplaceable,
                          area_sq_m / SQ_M_PER_HECTARE, None, feature_uuid))

        pieces = zone_children(mesh, cells)
        if len(pieces) > 1:
            counts['split'] += 1
        for number, (zone, group) in enumerate(pieces, start=1):
            child_ring = ring if len(pieces) == 1 else parcel_ring(mesh, group)
            child_area = area_sq_m if len(pieces) == 1 else abs(ring_area(child_ring))
            child_seed = seed * 31 + number
            retention, proposed, proposed_condition = sc.intervention(
                zone, habitat, condition, child_seed)
            proposed_broad = sc.BROAD[proposed]
            advance, delay = sc.timing_for(retention, child_seed)
            pi_ref = ref if len(pieces) == 1 else f'{ref}-{number}'
            pi_rows.append((
                gw.polygon_blob(child_ring), pi_ref, ref, broad, habitat,
                distinctiveness, condition, significance, irreplaceable,
                retention, proposed_broad, proposed,
                sc.DISTINCTIVENESS[proposed],
                proposed_condition,
                significance if retention == sc.RETAINED
                else sc.strategic_significance(child_seed),
                advance, delay, ON_SITE, child_area / SQ_M_PER_HECTARE,
                feature_uuid, wkt))

        if len(base_rows) >= BATCH:
            insert_many(conn, AREA_BASELINE, HABITAT_BASE_COLS, base_rows)
            insert_many(conn, AREA_PI, HABITAT_PI_COLS, pi_rows)
            counts['baseline'] += len(base_rows)
            counts['post_intervention'] += len(pi_rows)
            base_rows, pi_rows = [], []

    insert_many(conn, AREA_BASELINE, HABITAT_BASE_COLS, base_rows)
    insert_many(conn, AREA_PI, HABITAT_PI_COLS, pi_rows)
    counts['baseline'] += len(base_rows)
    counts['post_intervention'] += len(pi_rows)
    counts['baseline_ha'] = round(baseline_area / SQ_M_PER_HECTARE, 4)
    return counts


# ------------------------------------------------------------------ hedgerows

HEDGE_BASE_COLS = [
    'geom', 'Habitat Ref', 'Baseline Hedge Type', 'Baseline Distinctiveness',
    'Baseline Condition', 'Baseline Strategic Significance', 'Length',
    'Comment', 'feature_uuid']
HEDGE_PI_COLS = [
    'geom', 'Habitat Ref', 'Parent Ref', 'Baseline Hedge Type',
    'Baseline Distinctiveness', 'Baseline Condition',
    'Baseline Strategic Significance', 'Baseline Length', 'Retention Category',
    'Proposed Hedge Type', 'Proposed Distinctiveness', 'Proposed Condition',
    'Proposed Strategic Significance', 'Habitat created in advance/years',
    'Delay in starting habitat creation/years', 'Spatial risk category',
    'Length', 'parent_uuid', 'parent_geom']

HEDGE_DISTINCTIVENESS = {
    'Species-rich native hedgerow': 'Medium',
    'Native hedgerow - associated with bank or ditch': 'Medium',
    'Native hedgerow with trees': 'Medium',
    'Ecologically valuable line of trees': 'Medium',
    'Ecologically valuable line of trees - associated with bank or ditch': 'Medium',
    'Native hedgerow': 'Low',
    'Line of trees': 'Low',
    'Line of trees - associated with bank or ditch': 'Low',
    'Non-native and ornamental hedgerow': 'V.Low',
}


def write_hedgerows(conn, mesh):
    baseline = lin.build_hedgerows(mesh)
    base_rows, pi_rows = [], []
    counts = {'baseline': 0, 'post_intervention': 0, 'lost': 0, 'created': 0}
    kept_length = 0.0
    base_length = 0.0

    for index, edges in enumerate(baseline):
        seed = index + 1
        ref = f'HR-{seed:05d}'
        points = lin.joined(mesh, edges)
        length = line_length(points)
        base_length += length
        hedge_type = lin._pick(lin.HEDGE_TYPES, _hash01(seed, 1301))
        condition = lin.hedge_condition(hedge_type, _hash01(seed, 1303))
        significance = BASELINE_SIGNIFICANCE
        feature_uuid = uid(f'hedge/{ref}')
        blob = gw.line_blob(points)
        wkt = gw.line_wkt(points)
        distinctiveness = HEDGE_DISTINCTIVENESS[hedge_type]
        base_rows.append((blob, ref, hedge_type, distinctiveness, condition,
                          significance, length, None, feature_uuid))

        survives = [not lin.edge_destroyed(mesh, edge, seed) for edge in edges]
        stretches = lin.runs(survives)
        if not stretches:
            counts['lost'] += 1
            continue
        for number, (start, end) in enumerate(stretches, start=1):
            child_points = lin.joined(mesh, edges[start:end])
            child_length = line_length(child_points)
            kept_length += child_length
            child_seed = seed * 37 + number
            enhance = _hash01(child_seed, 1307) < 0.32
            target = lin.HEDGE_ENHANCEMENT.get(hedge_type) if enhance else None
            improved = 'Good' if condition == 'Moderate' else 'Moderate'
            if (target and lin.hedge_can_become(hedge_type, 'Enhanced', target)
                    and lin.hedge_condition_allowed(target, 'Good')):
                retention, proposed = 'Enhanced', target
                proposed_condition = 'Good'
            elif (enhance and condition != 'Good'
                  and lin.hedge_can_become(hedge_type, 'Enhanced', hedge_type)
                  and lin.hedge_condition_allowed(hedge_type, improved)):
                retention, proposed = 'Enhanced', hedge_type
                proposed_condition = improved
            else:
                retention, proposed, proposed_condition = ('Retained', hedge_type,
                                                           condition)
            advance, delay = sc.timing_for(retention, child_seed)
            pi_ref = ref if len(stretches) == 1 else f'{ref}-{number}'
            pi_rows.append((
                gw.line_blob(child_points), pi_ref, ref, hedge_type,
                distinctiveness, condition, significance, length, retention,
                proposed, HEDGE_DISTINCTIVENESS[proposed], proposed_condition,
                significance if retention == sc.RETAINED
                else lin.significance(child_seed),
                advance, delay, ON_SITE, child_length,
                feature_uuid, wkt))

    for extra in range(round(mesh.stations
                             * CREATED_HEDGE_ATTEMPTS_PER_STATION)):
        seed = 90000 + extra
        station = 2 + int(_hash01(seed, 1409) * (mesh.stations - 6))
        lane = 1 + int(_hash01(seed, 1411) * (mesh.lanes - 2))
        span = 3 + int(_hash01(seed, 1413) * 8)
        span = min(span, mesh.stations - station)
        edges = [('A', k, lane) for k in range(station, station + span)]
        if any(lin.edge_destroyed(mesh, edge, seed) for edge in edges):
            continue
        points = lin.joined(mesh, edges)
        proposed = lin._pick(lin.HEDGE_CREATED, _hash01(seed, 1417))
        advance, delay = sc.timing_for('Created', seed)
        counts['created'] += 1
        pi_rows.append((
            gw.line_blob(points), f'HN-{extra + 1:05d}', None, 'To be created',
            'N/A', 'N/A', None, None, 'Created', proposed,
            HEDGE_DISTINCTIVENESS[proposed], 'Good', lin.significance(seed),
            advance, delay, ON_SITE, line_length(points), None, None))

    insert_many(conn, 'Hedgerows Baseline', HEDGE_BASE_COLS, base_rows)
    insert_many(conn, 'Hedgerows Post-Intervention', HEDGE_PI_COLS, pi_rows)
    counts['baseline'] = len(base_rows)
    counts['post_intervention'] = len(pi_rows)
    counts['baseline_km'] = round(base_length / 1000, 2)
    counts['retained_km'] = round(kept_length / 1000, 2)
    return counts


# --------------------------------------------------------------- watercourses

WATER_BASE_COLS = [
    'geom', 'Habitat Ref', 'Baseline River Type', 'Baseline Distinctiveness',
    'Baseline Condition', 'Baseline Strategic Significance',
    'Baseline Encroachment into Watercourse',
    'Baseline Encroachment into riparian zone', 'Length', 'Comment',
    'feature_uuid']
WATER_PI_COLS = [
    'geom', 'Habitat Ref', 'Parent Ref', 'Baseline River Type',
    'Baseline Distinctiveness', 'Baseline Condition',
    'Baseline Strategic Significance', 'Baseline Encroachment into Watercourse',
    'Baseline Encroachment into riparian zone', 'Baseline Length',
    'Retention Category', 'Proposed River Type', 'Proposed Distinctiveness',
    'Proposed Condition', 'Proposed Strategic Significance',
    'Proposed Encroachment into Watercourse',
    'Proposed Encroachment into riparian zone', 'Enhancement Type',
    'Habitat created in advance/years',
    'Delay in starting habitat creation/years', 'Spatial risk category',
    'Length', 'parent_uuid', 'parent_geom']

WATER_DISTINCTIVENESS = {'Ditches': 'Medium', 'Canals': 'Medium',
                         'Culvert': 'Low'}


def write_watercourses(conn, mesh):
    baseline = lin.build_watercourses(mesh)
    base_rows, pi_rows = [], []
    counts = {'realigned': 0, 'lost': 0, 'culverted': 0}
    base_length = 0.0

    for index, (kind, edges, river_type) in enumerate(baseline):
        seed = index + 1
        ref = f'WC-{seed:04d}'
        points = lin.joined(mesh, edges)
        length = line_length(points)
        base_length += length
        crosses_works = any(lin.edge_destroyed(mesh, edge, seed) for edge in edges)
        if crosses_works and river_type == 'Ditches' and _hash01(seed, 1601) < 0.30:
            river_type = 'Culvert'
        culvert = river_type == 'Culvert'
        condition = (lin.CULVERT_CONDITION if culvert
                     else lin._pick(lin.WATERCOURSE_CONDITIONS, _hash01(seed, 1603)))
        encroachment = (lin.CULVERT_ENCROACHMENT if culvert
                        else lin._pick(lin.ENCROACHMENT, _hash01(seed, 1607)))
        riparian = (lin.CULVERT_ENCROACHMENT if culvert
                    else lin._pick(lin.RIPARIAN, _hash01(seed, 1609)))
        significance = BASELINE_SIGNIFICANCE
        feature_uuid = uid(f'water/{ref}')
        blob = gw.line_blob(points)
        wkt = gw.line_wkt(points)
        distinctiveness = WATER_DISTINCTIVENESS[river_type]
        base_rows.append((blob, ref, river_type, distinctiveness, condition,
                          significance, encroachment, riparian, length, None,
                          feature_uuid))

        outcome = _hash01(seed, 1613)
        if outcome < 0.08 and crosses_works:
            counts['lost'] += 1
            continue
        realigned = None
        if outcome < 0.22 and river_type in ('Ditches', 'Canals'):
            realigned = lin.realigned_channel(mesh, edges)
        if realigned:
            child_points = realigned
            retention, enhancement = sc.ENHANCED, 'Enhanced by Realignment'
            proposed_type = river_type
            proposed_condition = _better_water(condition)
            counts['realigned'] += 1
        elif outcome < 0.44:
            child_points = points
            retention, enhancement = sc.ENHANCED, 'Standard Enhancement'
            if culvert:
                proposed_type, proposed_condition = 'Ditches', 'Moderate'
                counts['culverted'] += 1
            else:
                proposed_type = river_type
                proposed_condition = _better_water(condition)
        else:
            child_points = points
            retention, enhancement = sc.RETAINED, 'N/A'
            proposed_type, proposed_condition = river_type, condition
        still_culvert = proposed_type == 'Culvert'
        enhanced = retention == sc.ENHANCED
        proposed_encroachment = (lin.CULVERT_ENCROACHMENT if still_culvert
                                 else 'No Encroachment' if enhanced
                                 else encroachment)
        proposed_riparian = (lin.CULVERT_ENCROACHMENT if still_culvert
                             else lin.NO_RIPARIAN_ENCROACHMENT if enhanced
                             else riparian)
        advance, delay = sc.timing_for(retention, seed)
        pi_rows.append((
            gw.line_blob(child_points), ref, ref, river_type, distinctiveness,
            condition, significance, encroachment, riparian, length, retention,
            proposed_type, WATER_DISTINCTIVENESS[proposed_type],
            proposed_condition,
            significance if retention == sc.RETAINED
            else lin.significance(seed),
            proposed_encroachment,
            proposed_riparian, enhancement, advance, delay, ON_SITE,
            line_length(child_points), feature_uuid, wkt))

    insert_many(conn, 'Watercourses Baseline', WATER_BASE_COLS, base_rows)
    insert_many(conn, 'Watercourses Post-Intervention', WATER_PI_COLS, pi_rows)
    counts['baseline'] = len(base_rows)
    counts['post_intervention'] = len(pi_rows)
    counts['baseline_km'] = round(base_length / 1000, 2)
    return counts


def _better_water(condition):
    scale = sc.CONDITION_SCALE
    if condition not in scale:
        return condition
    return scale[max(scale.index(condition) - 1, 0)]


# ---------------------------------------------------------------------- trees

TREE_BASE_COLS = [
    'geom', 'Habitat Ref', 'Baseline Tree Size', 'Baseline Tree Type',
    'Baseline Rural or Urban Tree', 'Baseline Condition',
    'Baseline Strategic Significance', 'Count', 'Comment', 'feature_uuid']
TREE_PI_COLS = [
    'geom', 'Habitat Ref', 'Parent Ref', 'Baseline Tree Size', 'Baseline Tree Type',
    'Baseline Rural or Urban Tree', 'Baseline Condition',
    'Baseline Strategic Significance', 'Retention Category',
    'Proposed Tree Size', 'Proposed Tree Type', 'Proposed Rural or Urban Tree',
    'Proposed Condition', 'Proposed Strategic Significance', 'Category',
    'Habitat Created/Enhanced in advance/years',
    'Delay in starting habitat creation/enhancement in years',
    'Spatial risk category', 'Count', 'Comment', 'parent_uuid', 'parent_geom']


def write_trees(conn, mesh):
    base_rows, pi_rows = [], []
    counts = {'lost': 0, 'created': 0}

    tree_count = round(mesh.stations * TREES_PER_STATION)
    for index, point, station, lane in lin.build_trees(mesh, tree_count):
        seed = index + 1
        ref = f'TR-{seed:05d}'
        size = lin._pick(lin.TREE_SIZES, _hash01(seed, 1901))
        tree_type = lin._pick(lin.TREE_TYPES, _hash01(seed, 1903))
        band = sc.band_for(mesh, int(station), int(lane))
        setting = 'Urban tree' if band == 3 else 'Rural tree'
        condition = lin._pick(lin.TREE_CONDITIONS, _hash01(seed, 1907))
        significance = BASELINE_SIGNIFICANCE
        count = 1 if _hash01(seed, 1913) < 0.88 else 2
        feature_uuid = uid(f'tree/{ref}')
        blob = gw.point_blob(point)
        wkt = gw.point_wkt(point)
        base_rows.append((blob, ref, size, tree_type, setting, condition,
                          significance, count,
                          lin.baseline_tree_note(_hash01(seed, 1917)),
                          feature_uuid))

        zone = sc.zone_of(mesh, min(int(station), mesh.stations - 1),
                          min(int(lane), mesh.lanes - 1))
        if zone in (sc.CORE, sc.EARTHWORKS) or _hash01(seed, 1931) < 0.12:
            counts['lost'] += 1
            continue
        retention, proposed_condition, note = lin.tree_outcome(
            condition, _hash01(seed, 1937))
        advance, delay = sc.timing_for(retention, seed)
        counts['enhanced'] = counts.get('enhanced', 0) + (
            retention == 'Enhanced')
        pi_rows.append((
            blob, ref, ref, size, tree_type, setting, condition, significance,
            retention, size, tree_type, setting, proposed_condition,
            significance, 'Existing', advance, delay, ON_SITE, count, note,
            feature_uuid, wkt))

    for extra in range(round(mesh.stations
                             * CREATED_TREE_ATTEMPTS_PER_STATION)):
        seed = 700000 + extra
        station = 1 + _hash01(seed, 2003) * (mesh.stations - 2)
        lane = 1.0 + _hash01(seed, 2011) * (mesh.lanes - 2.0)
        # The point sits at a fractional lane, so test the cells either side
        # of it as well: a tree planted half a lane from the sealed core would
        # otherwise land inside it.
        cell_i = min(int(station), mesh.stations - 1)
        neighbours = {min(max(int(lane) + step, 0), mesh.lanes - 1)
                      for step in (-1, 0, 1)}
        if any(sc.zone_of(mesh, cell_i, cell_j) == sc.CORE
               for cell_j in neighbours):
            continue
        zone = sc.zone_of(mesh, cell_i, min(int(lane), mesh.lanes - 1))
        point = lin.mesh_point(mesh, station, lane)
        size = lin._pick([('Small', 0.74), ('Medium', 0.26)], _hash01(seed, 2017))
        advance, delay = sc.timing_for('Created', seed)
        counts['created'] += 1
        proposed_condition = lin._pick(lin.PLANTED_TREE_CONDITIONS,
                                       _hash01(seed, 2029))
        pi_rows.append((
            gw.point_blob(point), f'TN-{extra + 1:05d}', None, 'N/A', 'N/A',
            'N/A', 'N/A', None, 'Created', size, 'Native',
            'Urban tree' if zone == sc.MITIGATION and
            _hash01(seed, 2027) < 0.12 else 'Rural tree', proposed_condition,
            lin.tree_significance(seed), 'Newly Planted', advance, delay, ON_SITE,
            1, None, None, None))

    insert_many(conn, TREE_BASELINE, TREE_BASE_COLS, base_rows)
    insert_many(conn, TREE_PI, TREE_PI_COLS, pi_rows)
    counts['baseline'] = len(base_rows)
    counts['post_intervention'] = len(pi_rows)
    return counts


# ------------------------------------------------------------ red line boundary

REDLINE_COLS = ['geom', 'Site Name', 'Location', 'Survey Date',
                'Survey Details', 'Mapped by', 'Company', 'Base Map']


def write_redline(conn, mesh):
    ring = mesh.redline_ring()
    if ring_area(ring) < 0:
        ring.reverse()
    insert_many(conn, 'Red Line Boundary', REDLINE_COLS, [(
        gw.polygon_blob(ring), SITE_NAME, LOCATION, SURVEY_DATE,
        SURVEY_DETAILS, MAPPED_BY, COMPANY, BASE_MAP)])
    return {'vertices': len(ring) - 1,
            'hectares': round(abs(ring_area(ring)) / SQ_M_PER_HECTARE, 4)}
