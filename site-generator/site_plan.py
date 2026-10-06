"""What is on the site, and what the development does to it.

Every choice is made by a hash of the seed and the thing being decided, so the
same inputs always give the same site. The weights are judgement, informed by
the real sites in the BNG500 collection of Statutory Metric workbooks: modified
grassland dominates their baselines, and the habitats most often created are
other neutral grassland, broadleaved woodland, sealed surface, introduced
shrub and mixed scrub.
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scale-test-nsip', 'generator'))

import corridor_scenario as sc                                   # noqa: E402
from corridor_mesh import _hash01, _signed                       # noqa: E402
from corridor_parcels import _is_single_ring                     # noqa: E402
from site_mesh import neighbours                                 # noqa: E402

PARTITION_ATTEMPTS = 60

# ------------------------------------------------------------- landscapes
#
# FIELD habitats go on the larger parcels and FEATURE habitats on the smaller
# ones. The largest parcel always takes the first FIELD habitat, the
# landscape's matrix.

LANDSCAPES = {
    'pastoral': {
        'field': [
            ('Modified grassland', 0.62), ('Other neutral grassland', 0.14),
            ('Temporary grass and clover leys', 0.08), ('Cereal crops', 0.06),
            ('Other woodland; broadleaved', 0.05), ('Mixed scrub', 0.05),
        ],
        'feature': [
            ('Mixed scrub', 0.18), ('Other woodland; broadleaved', 0.15),
            ('Bramble scrub', 0.12), ('Ponds (non-priority habitat)', 0.10),
            ('Ruderal/Ephemeral', 0.10), ('Other neutral grassland', 0.10),
            ('Hawthorn scrub', 0.08), ('Developed land; sealed surface', 0.10),
            ('Tall forbs', 0.07),
        ],
    },
    'arable': {
        'field': [
            ('Cereal crops', 0.55), ('Non-cereal crops', 0.15),
            ('Temporary grass and clover leys', 0.12),
            ('Modified grassland', 0.12), ('Other neutral grassland', 0.06),
        ],
        'feature': [
            ('Arable field margins tussocky', 0.25), ('Mixed scrub', 0.15),
            ('Other woodland; broadleaved', 0.15), ('Hawthorn scrub', 0.10),
            ('Ruderal/Ephemeral', 0.10), ('Modified grassland', 0.10),
            ('Ponds (non-priority habitat)', 0.08),
            ('Developed land; sealed surface', 0.07),
        ],
    },
    'wooded': {
        'field': [
            ('Other woodland; broadleaved', 0.40), ('Modified grassland', 0.25),
            ('Other neutral grassland', 0.15), ('Mixed scrub', 0.12),
            ('Other coniferous woodland', 0.08),
        ],
        'feature': [
            ('Mixed scrub', 0.20), ('Bramble scrub', 0.15),
            ('Ruderal/Ephemeral', 0.15), ('Hazel scrub', 0.10),
            ('Bracken', 0.10), ('Ponds (non-priority habitat)', 0.10),
            ('Other lowland acid grassland', 0.10), ('Hawthorn scrub', 0.10),
        ],
    },
    'urban-fringe': {
        'field': [
            ('Modified grassland', 0.45), ('Vacant or derelict land', 0.12),
            ('Developed land; sealed surface', 0.12),
            ('Other neutral grassland', 0.10), ('Ruderal/Ephemeral', 0.10),
            ('Bare ground', 0.06), ('Allotments', 0.05),
        ],
        'feature': [
            ('Bramble scrub', 0.15), ('Mixed scrub', 0.15),
            ('Ruderal/Ephemeral', 0.15), ('Developed land; sealed surface', 0.15),
            ('Introduced shrub', 0.10), ('Vegetated garden', 0.10),
            ('Other woodland; broadleaved', 0.10), ('Tall forbs', 0.10),
        ],
    },
}

# --------------------------------------------------------------- schemes
#
# `core` is the share of the site the development takes, and `margin` the
# band of green space around it. The rest is left as it is, or enhanced.

CORE, MARGIN, OUTER = 'core', 'margin', 'outer'

SCHEMES = {
    'housing': {
        'core': 0.55, 'margin': 0.20, 'clears_hedges': True,
        'clears_trees': True, 'boundary_hedge': 0.7,
        'street_trees': (2, 4),
        'habitats': [
            ('Developed land; sealed surface', 0.42), ('Vegetated garden', 0.34),
            ('Modified grassland', 0.10), ('Introduced shrub', 0.08),
            ('Rain garden', 0.03),
            ('Artificial unvegetated, unsealed surface', 0.03),
        ],
    },
    'commercial': {
        'core': 0.70, 'margin': 0.12, 'clears_hedges': True,
        'clears_trees': True, 'boundary_hedge': 0.0,
        'street_trees': (1, 3),
        'habitats': [
            ('Developed land; sealed surface', 0.62),
            ('Artificial unvegetated, unsealed surface', 0.10),
            ('Introduced shrub', 0.10), ('Modified grassland', 0.08),
            ('Other green roof', 0.05), ('Biodiverse green roof', 0.05),
        ],
    },
    'solar': {
        'core': 0.75, 'margin': 0.15, 'clears_hedges': False,
        'clears_trees': False, 'boundary_hedge': 0.7,
        'street_trees': (0, 0),
        'habitats': [
            ('Other neutral grassland', 0.72), ('Modified grassland', 0.18),
            ('Artificial unvegetated, unsealed surface', 0.10),
        ],
    },
}

MARGIN_HABITATS = [
    ('Other neutral grassland', 0.32), ('Other woodland; broadleaved', 0.20),
    ('Mixed scrub', 0.16), ('Sustainable drainage system', 0.12),
    ('Ponds (non-priority habitat)', 0.08), ('Modified grassland', 0.07),
    ('Rain garden', 0.05),
]

sc.assert_in_scope(
    {name for land in LANDSCAPES.values() for table in land.values()
     for name, _ in table}
    | {name for scheme in SCHEMES.values() for name, _ in scheme['habitats']}
    | {name for name, _ in MARGIN_HABITATS})


class Chooser:
    """Seeded choices. Every decision names what it is for."""

    def __init__(self, seed):
        self.seed = seed

    def roll(self, *parts):
        return _hash01(self.seed, *parts)

    def signed(self, *parts):
        return _signed(self.seed, *parts)

    def key(self, *parts):
        """An integer seed for the corridor's own helpers."""
        return int(self.roll(*parts) * 0xFFFFFFFF)

    def pick(self, weighted, *parts):
        total = sum(weight for _, weight in weighted)
        return sc._pick([(value, weight / total) for value, weight in weighted],
                        self.roll(*parts))


# ---------------------------------------------------------------- parcels

def partition(cells, count, choose):
    """Divide the site's cells into exactly `count` parcels.

    Parcels grow from seed cells spread across the site, each towards its own
    share, and a cell is only added if the parcel keeps one outline with no
    hole. Growth can wedge itself; a new set of seed cells is then tried.
    """
    for attempt in range(PARTITION_ATTEMPTS):
        regions = _try_partition(sorted(cells), count, choose, attempt)
        if regions is not None:
            return regions
    raise SystemExit('could not divide the site into that many parcels; '
                     'try another --seed')


def _spread_seeds(cells, count, choose, salt):
    seeds = [min(cells, key=lambda c: choose.roll(salt, c[0], c[1], 61))]
    while len(seeds) < count:
        seeds.append(max(
            (c for c in cells if c not in seeds),
            key=lambda c: (min((c[0] - s[0]) ** 2 + (c[1] - s[1]) ** 2
                               for s in seeds)
                           + choose.roll(salt, c[0], c[1], 67))))
    return seeds


def _try_partition(cells, count, choose, salt):
    seeds = _spread_seeds(cells, count, choose, salt)
    shares = [choose.pick([(0.6, 0.30), (1.0, 0.35), (1.8, 0.22), (3.0, 0.13)],
                          salt, k, 71) for k in range(count)]
    regions = [{seed} for seed in seeds]
    unassigned = set(cells) - set(seeds)
    while unassigned:
        order = sorted(range(count), key=lambda k: (
            len(regions[k]) / shares[k], choose.roll(salt, k, len(regions[k]), 73)))
        if not any(_grow(regions[k], unassigned, choose, salt, k)
                   for k in order):
            return None
    return regions


def _grow(region, unassigned, choose, salt, k):
    frontier = sorted(
        {n for c in region for n in neighbours(c) if n in unassigned},
        key=lambda c: (-sum(n in region for n in neighbours(c)),
                       choose.roll(salt, c[0], c[1], k, 79)))
    for candidate in frontier:
        region.add(candidate)
        if _is_single_ring(None, region):
            unassigned.discard(candidate)
            return True
        region.discard(candidate)
    return False


def baseline_habitat(landscape, is_matrix, is_field, choose, seed):
    table = LANDSCAPES[landscape]['field' if is_field else 'feature']
    if is_matrix:
        return table[0][0]
    return choose.pick(table, seed, 401)


# ------------------------------------------------------------------ zones

def zones(cells, scheme, choose):
    """Core, margin or outer for every cell.

    The development comes in from one side of the site, chosen by the seed,
    with a wavering edge. Shares are counted in cells, so they hold exactly.
    """
    angle = 2 * math.pi * choose.roll(83)
    dx, dy = math.cos(angle), math.sin(angle)
    ranked = sorted(cells, key=lambda c: (
        (c[0] + 0.5) * dx + (c[1] + 0.5) * dy
        + 0.6 * choose.signed(c[0] // 2, c[1] // 2, 89), c))
    total = len(ranked)
    core = round(total * SCHEMES[scheme]['core'])
    margin = round(total * SCHEMES[scheme]['margin'])
    out = {}
    for index, cell in enumerate(ranked):
        if index >= total - core:
            out[cell] = CORE
        elif index >= total - core - margin:
            out[cell] = MARGIN
        else:
            out[cell] = OUTER
    return out


def intervention(zone, scheme, habitat, condition, choose, seed):
    """Return (retention, proposed habitat, proposed condition)."""
    roll = choose.roll(seed, 5501)
    key = choose.key(seed, 5502)
    if zone == CORE:
        proposed = choose.pick(SCHEMES[scheme]['habitats'], seed, 5503)
    elif zone == MARGIN and roll < 0.45:
        proposed = choose.pick(MARGIN_HABITATS, seed, 5507)
    elif zone == OUTER and roll < 0.05:
        proposed = choose.pick(MARGIN_HABITATS, seed, 5509)
    elif (zone == MARGIN and roll < 0.85) or (zone == OUTER and roll < 0.30):
        return sc._enhance(habitat, condition, key)
    else:
        return sc.RETAINED, habitat, condition
    if proposed == habitat:
        return sc.RETAINED, habitat, condition
    return sc.CREATED, proposed, sc.condition_for(proposed,
                                                  choose.roll(seed, 5511))


# -------------------------------------------------------------- hedgerows
#
# A hedge runs along the edges between cells: between parcels where it can,
# since a hedge is a field boundary, and never on the red line itself. It is
# held as a list of mesh nodes; consecutive nodes name one mesh edge.

def edge_between(a, b):
    """(kind, i, j, forward) for the mesh edge from node a to node b."""
    if a[1] == b[1]:
        return 'A', min(a[0], b[0]), a[1], b[0] > a[0]
    return 'B', a[0], min(a[1], b[1]), b[1] > a[1]


def edge_cells(a, b):
    kind, i, j, _ = edge_between(a, b)
    if kind == 'A':
        return (i, j - 1), (i, j)
    return (i - 1, j), (i, j)


def _node_neighbours(node):
    i, j = node
    return ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1))


def _walk(allowed, preferred, busy, length, choose, salt):
    """A path of up to `length` unused edges through `allowed`, as nodes.

    Hedges can meet at a node, as field boundaries do, but never share an
    edge. A path never crosses itself.
    """
    pool = sorted(e for e in allowed if e not in busy)
    if not pool:
        return None
    start = min(pool, key=lambda e: (e not in preferred,
                                     choose.roll(salt, *e[0], *e[1], 97)))
    path = list(start)
    for grow_end in (True, False):
        while len(path) - 1 < length:
            tip = path[-1] if grow_end else path[0]
            behind = path[-2] if grow_end else path[1]
            options = []
            for nxt in _node_neighbours(tip):
                edge = tuple(sorted((tip, nxt)))
                if edge not in allowed or edge in busy or nxt in path:
                    continue
                straight = (nxt[0] - tip[0], nxt[1] - tip[1]) == \
                    (tip[0] - behind[0], tip[1] - behind[1])
                options.append(((edge not in preferred, not straight,
                                 choose.roll(salt, *nxt, 101)), nxt))
            if not options:
                break
            nxt = min(options)[1]
            if grow_end:
                path.append(nxt)
            else:
                path.insert(0, nxt)
    return path


def internal_edges(cells, owner):
    """Every mesh edge with a site cell on both sides, as sorted node pairs."""
    edges, between_parcels = set(), set()
    for (i, j) in cells:
        for other, edge in (((i, j - 1), ((i, j), (i + 1, j))),
                            ((i - 1, j), ((i, j), (i, j + 1)))):
            if other in cells:
                edges.add(edge)
                if owner[other] != owner[(i, j)]:
                    between_parcels.add(edge)
    return edges, between_parcels


def build_hedges(count, cells, owner, choose):
    edges, between_parcels = internal_edges(cells, owner)
    busy, hedges = set(), []
    for k in range(count):
        length = 3 + int(choose.roll(k, 103) * 5)
        path = _walk(edges, between_parcels, busy, length, choose, k)
        if path is None:
            break
        hedges.append(path)
        busy |= path_edges(path)
    return hedges


def path_edges(path):
    return {tuple(sorted(pair)) for pair in zip(path, path[1:])}


def boundary_hedge(cells, zone_of, busy, choose):
    """A new hedge planted along the edge of the development, or None."""
    edges = set()
    for (i, j) in cells:
        for other, edge in (((i, j - 1), ((i, j), (i + 1, j))),
                            ((i - 1, j), ((i, j), (i, j + 1)))):
            if other in cells and ((zone_of[other] == CORE)
                                   != (zone_of[(i, j)] == CORE)):
                edges.add(edge)
    length = 3 + int(choose.roll(107) * 5)
    return _walk(edges, edges, busy, length, choose, 109)
