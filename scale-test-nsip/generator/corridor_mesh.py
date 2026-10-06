"""Corridor mesh for the NSIP-scale synthetic site.

The site is a long, moderately wide rail corridor. Everything is built on one
structured mesh in corridor coordinates so that:

  * every habitat parcel is a union of mesh cells;
  * neighbouring cells share IDENTICAL vertex chains, so the parcels tile the
    site with no overlap and no gap;
  * the red line boundary is the outer edge of the same mesh, so its area
    equals the summed parcel area exactly (Green's theorem: every interior
    chain is walked twice, in opposite directions, over the same points).

That last property is what makes the file pass AREA_SUM_MISMATCH, which allows
0.5 sq m across a 30 sq km site.

Realism comes from three places: a splined centre line through real British
National Grid waypoints, a varying corridor width, and per-node plus per-edge
jitter that turns the mesh into wobbly field boundaries rather than a grid.
"""

import math

# ---------------------------------------------------------------- parameters

STATION_M = 40.0          # spacing of cross sections along the route
LANES = 18                # cells across the corridor
EDGE_SUBDIVISIONS = 3     # segments per mesh edge (2 interior vertices)
NODE_JITTER_FRACTION = 0.22
EDGE_JITTER_FRACTION = 0.11

# HS2 Phase 2a runs Handsacre (Staffordshire) to Crewe. These are British
# National Grid waypoints along that corridor, used here as a plausible
# alignment for a subsection of a new rail scheme.
WAYPOINTS = [
    (410900, 315600),   # Handsacre junction
    (409100, 318400),   # Kings Bromley
    (406200, 320200),   # Colton
    (402400, 321800),   # Great Haywood, Trent and Mersey Canal
    (399000, 324100),   # Ingestre
    (396600, 327300),   # Hopton
    (394200, 330000),   # Marston
    (391300, 333200),   # Yarnfield
    (388200, 336300),   # Swynnerton
    (385100, 339000),   # Whitmore Heath
    (382000, 341800),   # Baldwins Gate
    (379200, 344600),   # Madeley
    (376400, 347600),   # Wrinehill
    (373900, 350800),   # Wybunbury
    (371600, 354200),   # Basford, Crewe
]

BASE_WIDTH_M = 520.0
MIN_WIDTH_M = 330.0
MAX_WIDTH_M = 1040.0
# Construction compounds and balancing areas: (fraction along route, extra m,
# spread as a fraction of the route).
WIDE_AREAS = [
    (0.06, 240.0, 0.010),
    (0.17, 300.0, 0.012),
    (0.29, 200.0, 0.009),
    (0.41, 340.0, 0.013),
    (0.53, 220.0, 0.010),
    (0.66, 380.0, 0.014),
    (0.78, 240.0, 0.010),
    (0.91, 300.0, 0.012),
]

HEADING_SMOOTHING_STATIONS = 12


# ------------------------------------------------------------------ helpers

def _hash01(*parts):
    """Deterministic pseudo-random float in [0, 1) from integer parts."""
    h = 0x811C9DC5
    for part in parts:
        value = int(part) & 0xFFFFFFFF
        for _ in range(4):
            h ^= value & 0xFF
            h = (h * 0x01000193) & 0xFFFFFFFF
            value >>= 8
    return h / 0x100000000


def _signed(*parts):
    """Deterministic pseudo-random float in [-1, 1)."""
    return _hash01(*parts) * 2.0 - 1.0


def _catmull_rom(points, samples_per_span=240):
    """Centripetal Catmull-Rom spline through every waypoint."""
    padded = [points[0]] + list(points) + [points[-1]]
    out = []
    for index in range(len(padded) - 3):
        p0, p1, p2, p3 = padded[index:index + 4]
        for step in range(samples_per_span):
            t = step / samples_per_span
            t2, t3 = t * t, t * t * t
            x = 0.5 * (
                2 * p1[0]
                + (-p0[0] + p2[0]) * t
                + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
            )
            y = 0.5 * (
                2 * p1[1]
                + (-p0[1] + p2[1]) * t
                + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
            )
            out.append((x, y))
    out.append(points[-1])
    return out


def _resample(polyline, spacing):
    """Resample a polyline at a fixed arc-length spacing."""
    out = [polyline[0]]
    carried = 0.0
    for start, end in zip(polyline, polyline[1:]):
        segment = math.hypot(end[0] - start[0], end[1] - start[1])
        if segment <= 0:
            continue
        position = spacing - carried
        while position <= segment:
            f = position / segment
            out.append((start[0] + (end[0] - start[0]) * f,
                        start[1] + (end[1] - start[1]) * f))
            position += spacing
        carried = (carried + segment) % spacing
    return out


def _smoothed_headings(centre, window):
    """Heading per station, averaged over a window to keep curvature gentle."""
    raw = []
    for index in range(len(centre)):
        before = centre[max(index - 1, 0)]
        after = centre[min(index + 1, len(centre) - 1)]
        raw.append(math.atan2(after[1] - before[1], after[0] - before[0]))
    # Unwrap so the average does not jump across the +/-pi seam.
    unwrapped = [raw[0]]
    for angle in raw[1:]:
        previous = unwrapped[-1]
        while angle - previous > math.pi:
            angle -= 2 * math.pi
        while previous - angle > math.pi:
            angle += 2 * math.pi
        unwrapped.append(angle)
    smoothed = []
    for index in range(len(unwrapped)):
        low = max(index - window, 0)
        high = min(index + window + 1, len(unwrapped))
        smoothed.append(sum(unwrapped[low:high]) / (high - low))
    return smoothed


def _width_at(fraction):
    width = (
        BASE_WIDTH_M
        + 190.0 * math.sin(fraction * 2.1 * math.pi + 0.30)
        + 110.0 * math.sin(fraction * 5.7 * math.pi + 1.90)
        + 70.0 * math.sin(fraction * 13.3 * math.pi + 0.70)
    )
    for centre, extra, spread in WIDE_AREAS:
        width += extra * math.exp(-((fraction - centre) / spread) ** 2)
    return max(MIN_WIDTH_M, min(MAX_WIDTH_M, width))


# --------------------------------------------------------------------- mesh

class CorridorMesh:
    """Nodes, edge chains and cell rings for the corridor.

    `fraction` builds a shorter section of the same scheme, measured from the
    southern end. A whole nationally significant project does not fit in the
    Statutory Metric workbook, which holds 248 rows a sheet, and the published
    guidance says to split it into geographic sections; this is that split.
    """

    def __init__(self, fraction=1.0):
        dense = _catmull_rom(WAYPOINTS)
        self.centre = _resample(dense, STATION_M)
        if fraction < 1.0:
            keep = max(2, int(len(self.centre) * fraction))
            self.centre = self.centre[:keep]
        self.stations = len(self.centre) - 1
        self.lanes = LANES
        headings = _smoothed_headings(self.centre, HEADING_SMOOTHING_STATIONS)
        self.route_length_m = self.stations * STATION_M

        self._nodes = []
        for i, ((cx, cy), heading) in enumerate(zip(self.centre, headings)):
            fraction = i / self.stations
            width = _width_at(fraction)
            lane_width = width / LANES
            nx, ny = -math.sin(heading), math.cos(heading)
            tx, ty = math.cos(heading), math.sin(heading)
            amplitude = NODE_JITTER_FRACTION * min(STATION_M, lane_width)
            row = []
            for j in range(LANES + 1):
                offset = (j / LANES - 0.5) * width
                jn = amplitude * _signed(i, j, 11)
                jt = amplitude * _signed(i, j, 29)
                row.append((cx + nx * (offset + jn) + tx * jt,
                            cy + ny * (offset + jn) + ty * jt))
            self._nodes.append(row)

        self._chain_cache = {}

    # -- nodes and edges

    def node(self, i, j):
        return self._nodes[i][j]

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
            f = step / EDGE_SUBDIVISIONS
            wobble = amplitude * _signed(key[1], key[2], step, ord(key[0]))
            points.append((start[0] + dx * f + px * wobble,
                           start[1] + dy * f + py * wobble))
        self._chain_cache[key] = points
        return points

    def chain_a(self, i, j):
        """Along-route edge at lane boundary j, from station i to station i+1."""
        return self._chain(('A', i, j), self.node(i, j), self.node(i + 1, j))

    def chain_b(self, i, j):
        """Across-route edge at station i, from lane boundary j to j+1."""
        return self._chain(('B', i, j), self.node(i, j), self.node(i, j + 1))

    # -- cells

    def cell_ring(self, i, j):
        """Closed ring of cell (i, j), anticlockwise."""
        ring = [self.node(i, j)]
        ring += self.chain_a(i, j)
        ring.append(self.node(i + 1, j))
        ring += self.chain_b(i + 1, j)
        ring.append(self.node(i + 1, j + 1))
        ring += reversed(self.chain_a(i, j + 1))
        ring.append(self.node(i, j + 1))
        ring += reversed(self.chain_b(i, j))
        ring.append(ring[0])
        # Anticlockwise, the OGC convention for an exterior ring. Reversing a
        # ring keeps the shared chains identical, so the tiling stays exact.
        ring.reverse()
        return ring

    def redline_ring(self):
        """Outer edge of the whole mesh, built from the same shared chains."""
        ring = [self.node(0, 0)]
        for i in range(self.stations):
            ring += self.chain_a(i, 0)
            ring.append(self.node(i + 1, 0))
        for j in range(self.lanes):
            ring += self.chain_b(self.stations, j)
            ring.append(self.node(self.stations, j + 1))
        for i in range(self.stations - 1, -1, -1):
            ring += reversed(self.chain_a(i, self.lanes))
            ring.append(self.node(i, self.lanes))
        for j in range(self.lanes - 1, -1, -1):
            ring += reversed(self.chain_b(0, j))
            ring.append(self.node(0, j))
        ring.reverse()
        return ring

    def edge_line(self, kind, i, j):
        """One mesh edge as an open polyline, for hedgerows and watercourses."""
        if kind == 'A':
            return [self.node(i, j)] + self.chain_a(i, j) + [self.node(i + 1, j)]
        return [self.node(i, j)] + self.chain_b(i, j) + [self.node(i, j + 1)]

    def cell_centroid(self, i, j):
        ring = self.cell_ring(i, j)[:-1]
        return (sum(p[0] for p in ring) / len(ring),
                sum(p[1] for p in ring) / len(ring))


def ring_area(ring):
    """Signed area, shifted to the first vertex the way GEOS does it."""
    x0 = ring[0][0]
    total = 0.0
    for index in range(1, len(ring) - 1):
        total += (ring[index][0] - x0) * (ring[index - 1][1] - ring[index + 1][1])
    return total / 2.0


def line_length(points):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1])
               for a, b in zip(points, points[1:]))
