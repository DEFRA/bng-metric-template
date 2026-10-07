"""Hedgerows, watercourses and individual trees for the corridor.

Hedgerows and ditches are drawn along the same mesh edges the habitat parcels
use, which is both realistic (a hedge is a field boundary) and convenient: the
line sits exactly on a parcel edge and therefore inside the red line.

Realigned channels and tree points are placed in corridor coordinates, so a
feature can be moved off its original line without any risk of leaving the
site.
"""

import collections
import csv
import math
import os

from corridor_mesh import _hash01, line_length
from corridor_scenario import (CONDITION_SCALE, CORE, CSV_ROOT, EARTHWORKS,
                               PROPOSED_SIGNIFICANCE, _pick, zone_of)

# ------------------------------------------------------- reference values

HEDGE_TYPES = [
    ('Native hedgerow', 0.34),
    ('Native hedgerow with trees', 0.19),
    ('Native hedgerow - associated with bank or ditch', 0.13),
    ('Species-rich native hedgerow', 0.09),
    ('Line of trees', 0.11),
    ('Line of trees - associated with bank or ditch', 0.06),
    ('Ecologically valuable line of trees', 0.04),
    ('Ecologically valuable line of trees - associated with bank or ditch', 0.02),
    ('Non-native and ornamental hedgerow', 0.02),
]
HEDGE_CONDITIONS = [('Good', 0.22), ('Moderate', 0.48), ('Poor', 0.30)]
# Enhancement targets that stay within Medium, Low and V.Low distinctiveness.
HEDGE_ENHANCEMENT = {
    'Native hedgerow': 'Native hedgerow with trees',
    'Line of trees': 'Native hedgerow with trees',
    'Line of trees - associated with bank or ditch':
        'Ecologically valuable line of trees - associated with bank or ditch',
    'Ecologically valuable line of trees':
        'Ecologically valuable line of trees - associated with bank or ditch',
}
HEDGE_CREATED = [
    ('Native hedgerow with trees', 0.42), ('Native hedgerow', 0.31),
    ('Species-rich native hedgerow', 0.16),
    ('Native hedgerow - associated with bank or ditch', 0.11),
]

WATERCOURSE_CONDITIONS = list(zip(CONDITION_SCALE,
                                  (0.10, 0.22, 0.36, 0.22, 0.10)))
# A culvert has one condition, and no encroachment to assess on either list.
CULVERT_CONDITION = 'Poor'
CULVERT_ENCROACHMENT = 'N/A - Culvert'
NO_RIPARIAN_ENCROACHMENT = 'No Encroachment/ No Encroachment'
RIPARIAN = [('Moderate/ Moderate', 0.24), ('Minor/ Minor', 0.34),
            ('Minor/ No Encroachment', 0.22),
            (NO_RIPARIAN_ENCROACHMENT, 0.20)]
ENCROACHMENT = [('No Encroachment', 0.44), ('Minor', 0.40), ('Major', 0.16)]

TREE_SIZES = [('Small', 0.28), ('Medium', 0.37), ('Large', 0.27),
              ('Very large', 0.08)]
TREE_TYPES = [('Native', 0.79), ('Non-native', 0.21)]
TREE_CONDITIONS = list(zip(CONDITION_SCALE, (0.16, 0.27, 0.34, 0.16, 0.07)))
# A planted tree is priced as an area habitat, so it needs a real condition:
# the metric cannot value one recorded as not applicable.
PLANTED_TREE_CONDITIONS = list(zip(CONDITION_SCALE, (0.34, 0.42, 0.24)))


def significance(seed):
    """A proposed significance, Low or High. A baseline one is always Low."""
    return _pick(PROPOSED_SIGNIFICANCE, _hash01(seed, 3301))


def tree_significance(seed):
    """Trees take the same Low and High as every other habitat type."""
    return significance(seed)


# ------------------------------------------------------ hedgerow lookups
#
# Read from the template's own lists, so a hedge is only ever given a
# condition or a change the template's drop-downs would offer. A non-native
# hedge, for one, can only be in poor condition and cannot be enhanced.

def _load_hedge_lists():
    folder = os.path.join(CSV_ROOT, 'Hedgerows')
    conditions = collections.defaultdict(set)
    with open(os.path.join(folder, 'Hedgerow Condition.csv'),
              encoding='utf-8-sig') as fh:
        for row in csv.DictReader(fh):
            conditions[row['Habitat']].add(row['Condition'])
    becomes = collections.defaultdict(set)
    with open(os.path.join(folder, 'Hedgerow Habitat Options - post.csv'),
              encoding='utf-8-sig') as fh:
        for row in csv.DictReader(fh):
            becomes[row['Value']].add(row['Description'])
    return conditions, becomes


HEDGE_CONDITION_LIST, HEDGE_BECOMES = _load_hedge_lists()


def hedge_condition(hedge_type, roll):
    """A weighted condition, drawn only from those the hedge type allows."""
    allowed = [(c, w) for c, w in HEDGE_CONDITIONS
               if c in HEDGE_CONDITION_LIST[hedge_type]]
    if not allowed:
        return sorted(HEDGE_CONDITION_LIST[hedge_type])[0]
    total = sum(w for _, w in allowed)
    return _pick([(c, w / total) for c, w in allowed], roll)


def hedge_condition_allowed(hedge_type, condition):
    return condition in HEDGE_CONDITION_LIST[hedge_type]


def hedge_can_become(hedge_type, retention, proposed):
    return proposed in HEDGE_BECOMES[hedge_type + retention]


# ------------------------------------------------------- corridor geometry

def mesh_point(mesh, station, lane):
    """A point inside the corridor, in (station, lane) coordinates."""
    i0 = max(0, min(mesh.stations, int(math.floor(station))))
    i1 = min(mesh.stations, i0 + 1)
    fi = station - i0
    j0 = max(0, min(mesh.lanes, int(math.floor(lane))))
    j1 = min(mesh.lanes, j0 + 1)
    fj = lane - j0
    a, b = mesh.node(i0, j0), mesh.node(i0, j1)
    c, d = mesh.node(i1, j0), mesh.node(i1, j1)
    top = (a[0] + (b[0] - a[0]) * fj, a[1] + (b[1] - a[1]) * fj)
    bottom = (c[0] + (d[0] - c[0]) * fj, c[1] + (d[1] - c[1]) * fj)
    return (top[0] + (bottom[0] - top[0]) * fi,
            top[1] + (bottom[1] - top[1]) * fi)


def joined(mesh, edges):
    """Concatenate mesh edges into one polyline, dropping repeated joints."""
    points = []
    for kind, i, j in edges:
        piece = mesh.edge_line(kind, i, j)
        points.extend(piece if not points else piece[1:])
    return points


def runs(flags):
    """Maximal runs of True, as (start, end) index pairs."""
    out, start = [], None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            out.append((start, index))
            start = None
    if start is not None:
        out.append((start, len(flags)))
    return out


# ------------------------------------------------------------- hedgerows

def build_hedgerows(mesh):
    """Baseline hedgerows as lists of mesh edges."""
    features = []
    for j in range(1, mesh.lanes):
        i = 0
        while i < mesh.stations:
            if _hash01(j, i, 71) < 0.062:
                span = 2 + int(_hash01(j, i, 73) * 9)
                span = min(span, mesh.stations - i)
                features.append([('A', k, j) for k in range(i, i + span)])
                i += span + 1 + int(_hash01(j, i, 79) * 6)
            else:
                i += 1
    for i in range(1, mesh.stations):
        if _hash01(i, 0, 131) < 0.20:
            j0 = int(_hash01(i, 0, 137) * (mesh.lanes - 3))
            j1 = min(j0 + 2 + int(_hash01(i, 0, 139) * 7), mesh.lanes)
            features.append([('B', i, j) for j in range(j0, j1)])
    return features


def edge_destroyed(mesh, edge, seed):
    """Whether the works remove this stretch of boundary."""
    kind, i, j = edge
    if kind == 'A':
        left = zone_of(mesh, i, max(j - 1, 0))
        right = zone_of(mesh, i, min(j, mesh.lanes - 1))
    else:
        left = zone_of(mesh, max(i - 1, 0), j)
        right = zone_of(mesh, min(i, mesh.stations - 1), j)
    if CORE in (left, right):
        return True
    if EARTHWORKS in (left, right):
        return _hash01(i, j, seed, 217) < 0.72
    return False


# ---------------------------------------------------------- watercourses

def build_watercourses(mesh):
    """Baseline watercourses as (kind, edges, river type) tuples."""
    features = []
    for j in range(2, mesh.lanes - 1, 2):
        i = 0
        while i < mesh.stations:
            if _hash01(j, i, 311) < 0.020:
                span = 4 + int(_hash01(j, i, 313) * 12)
                span = min(span, mesh.stations - i)
                features.append(('along', [('A', k, j) for k in range(i, i + span)],
                                 'Ditches'))
                i += span + 6
            else:
                i += 1
    for i in range(2, mesh.stations, 2):
        if _hash01(i, 0, 331) < 0.065:
            j0 = int(_hash01(i, 0, 337) * 3)
            j1 = mesh.lanes - int(_hash01(i, 0, 341) * 3)
            crossing = [('B', i, j) for j in range(j0, j1)]
            features.append(('cross', crossing, 'Ditches'))
    # The Trent and Mersey Canal, running beside the corridor near Great
    # Haywood, drawn as four surveyed stretches.
    canal_start = int(mesh.stations * 0.155)
    for block in range(4):
        first = canal_start + block * 11
        features.append(('along',
                         [('A', k, 3) for k in range(first, first + 10)],
                         'Canals'))
    return features


def realigned_channel(mesh, edges):
    """A new, more sinuous channel drawn off the old line."""
    kind = edges[0][0]
    if kind != 'A':
        return None
    lane = edges[0][2]
    if lane < 3 or lane > mesh.lanes - 3:
        return None
    stations = [i for _, i, _ in edges] + [edges[-1][1] + 1]
    points = []
    for step, station in enumerate(stations):
        for sub in range(3):
            position = station + sub / 3.0
            if position > stations[-1]:
                break
            phase = (step * 3 + sub) * 0.42
            offset = 1.25 * math.sin(phase) + 0.45 * math.sin(phase * 2.7 + 1.1)
            points.append(mesh_point(mesh, position, lane + offset))
    points.append(mesh_point(mesh, stations[-1], lane))
    return points


# ----------------------------------------------------------------- trees

def build_trees(mesh, count):
    """Baseline tree points, spread along the corridor."""
    trees = []
    for index in range(count):
        station = _hash01(index, 811) * (mesh.stations - 2) + 1
        lane = 1.0 + _hash01(index, 823) * (mesh.lanes - 2.0)
        trees.append((index, mesh_point(mesh, station, lane), station, lane))
    return trees
