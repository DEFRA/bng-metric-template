"""Mesh and red line boundary for a small synthetic site.

The site is a compact, irregular group of cells on one jittered mesh, the same
construction the NSIP corridor uses:

  * every habitat parcel is a union of mesh cells;
  * neighbouring cells share identical vertex chains, so the parcels tile the
    site with no overlap and no gap;
  * the red line boundary is the outer edge of the same cells, so its area
    equals the summed parcel area exactly.

The mesh is built once at unit size to measure the chosen cells, then again
scaled and moved so the site has the requested area and is centred on the
requested point. Scaling a similarity transform keeps every shared chain
shared, so the tiling stays exact.
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scale-test-nsip', 'generator'))

from corridor_mesh import _hash01, _signed, ring_area          # noqa: E402
from corridor_parcels import _is_single_ring, trace_ring        # noqa: E402

NODE_JITTER_FRACTION = 0.22
EDGE_JITTER_FRACTION = 0.11
EDGE_SUBDIVISIONS = 3
# Mesh cells per habitat parcel, on average. Enough for parcels of different
# sizes and for a parcel to be split by the development, few enough that a
# 50-parcel site stays small.
CELLS_PER_PARCEL = 3.5
MIN_CELLS = 9
GRID_MARGIN = 3
BLOB_SPREAD = 1.3


def neighbours(cell):
    i, j = cell
    return ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1))


class SiteMesh:
    """Nodes and shared edge chains, with the same interface as CorridorMesh.

    `stations` and `lanes` are the grid's columns and rows, named as the
    corridor names them so the corridor's ring tracing works unchanged.
    """

    def __init__(self, cols, rows, seed, stretch, angle, scale=1.0,
                 offset=(0.0, 0.0)):
        self.stations = cols
        self.lanes = rows
        self.seed = seed
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        self._nodes = {}
        for i in range(cols + 1):
            for j in range(rows + 1):
                x = i + NODE_JITTER_FRACTION * _signed(seed, i, j, 11)
                y = (j + NODE_JITTER_FRACTION * _signed(seed, i, j, 29)) * stretch
                self._nodes[(i, j)] = (
                    offset[0] + scale * (x * cos_a - y * sin_a),
                    offset[1] + scale * (x * sin_a + y * cos_a))
        self._chain_cache = {}

    def node(self, i, j):
        return self._nodes[(i, j)]

    def _chain(self, key, start, end):
        """Interior vertices of one mesh edge, generated once and shared."""
        cached = self._chain_cache.get(key)
        if cached is not None:
            return cached
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        px, py = (-dy / length, dx / length) if length else (0.0, 0.0)
        amplitude = EDGE_JITTER_FRACTION * length
        points = []
        for step in range(1, EDGE_SUBDIVISIONS):
            fraction = step / EDGE_SUBDIVISIONS
            wobble = amplitude * _signed(self.seed, key[1], key[2], step,
                                         ord(key[0]))
            points.append((start[0] + dx * fraction + px * wobble,
                           start[1] + dy * fraction + py * wobble))
        self._chain_cache[key] = points
        return points

    def edge_line(self, kind, i, j):
        """One mesh edge as an open polyline, from its lower node."""
        if kind == 'A':
            start, end = self.node(i, j), self.node(i + 1, j)
        else:
            start, end = self.node(i, j), self.node(i, j + 1)
        return [start] + self._chain((kind, i, j), start, end) + [end]

    def cell_point(self, i, j, u, v):
        """A point inside cell (i, j), from its corners.

        Keep u and v between 0.3 and 0.7: the edge chains wobble inwards by up
        to a tenth of a side, and a point nearer the edge could fall outside.
        """
        a, b = self.node(i, j), self.node(i + 1, j)
        c, d = self.node(i + 1, j + 1), self.node(i, j + 1)
        return ((1 - u) * (1 - v) * a[0] + u * (1 - v) * b[0]
                + u * v * c[0] + (1 - u) * v * d[0],
                (1 - u) * (1 - v) * a[1] + u * (1 - v) * b[1]
                + u * v * c[1] + (1 - u) * v * d[1])


def cell_count_for(parcels):
    return max(MIN_CELLS, round(parcels * CELLS_PER_PARCEL))


def choose_cells(cell_count, seed):
    """A compact, irregular set of cells with one outline and no holes."""
    half = math.ceil(BLOB_SPREAD * math.sqrt(cell_count)) + GRID_MARGIN
    size = 2 * half
    elongation = 1.0 + 0.6 * _hash01(seed, 41)
    phase_2 = 2 * math.pi * _hash01(seed, 43)
    phase_3 = 2 * math.pi * _hash01(seed, 47)

    def score(cell):
        di = cell[0] + 0.5 - half
        dj = cell[1] + 0.5 - half
        theta = math.atan2(dj, di)
        lobes = (1.0 + 0.22 * math.sin(2 * theta + phase_2)
                 + 0.12 * math.sin(3 * theta + phase_3))
        return (math.hypot(di / elongation, dj) / lobes
                + 0.35 * _hash01(seed, cell[0], cell[1], 53))

    cells = {(half, half)}
    while len(cells) < cell_count:
        frontier = sorted(
            {n for c in cells for n in neighbours(c)
             if n not in cells and 0 <= n[0] < size and 0 <= n[1] < size},
            key=score)
        for candidate in frontier:
            cells.add(candidate)
            if _is_single_ring(None, cells):
                break
            cells.discard(candidate)
        else:
            raise RuntimeError('could not grow the site outline')
    return size, size, cells


def polygon_centroid(ring):
    area = 0.0
    cx = cy = 0.0
    x0, y0 = ring[0]
    for (xa, ya), (xb, yb) in zip(ring, ring[1:]):
        xa, ya, xb, yb = xa - x0, ya - y0, xb - x0, yb - y0
        cross = xa * yb - xb * ya
        area += cross
        cx += (xa + xb) * cross
        cy += (ya + yb) * cross
    area /= 2.0
    return (x0 + cx / (6.0 * area), y0 + cy / (6.0 * area))


def build_site(parcels, area_sq_m, centre, seed):
    """Return (mesh, cells, outline ring) for a site of the given area."""
    cols, rows, cells = choose_cells(cell_count_for(parcels), seed)
    stretch = 0.75 + 0.5 * _hash01(seed, 59)
    angle = math.pi * _hash01(seed, 61)
    unit = SiteMesh(cols, rows, seed, stretch, angle)
    unit_ring = trace_ring(unit, cells)
    scale = math.sqrt(area_sq_m / abs(ring_area(unit_ring)))
    cx, cy = polygon_centroid(unit_ring)
    offset = (centre[0] - scale * cx, centre[1] - scale * cy)
    mesh = SiteMesh(cols, rows, seed, stretch, angle, scale, offset)
    ring = trace_ring(mesh, cells)
    if ring_area(ring) < 0:
        ring.reverse()
    mesh.cell_side_m = scale * math.sqrt(stretch)
    return mesh, cells, ring
