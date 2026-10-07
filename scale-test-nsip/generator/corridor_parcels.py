"""Group mesh cells into habitat parcels and trace their outlines.

A parcel is a connected set of cells. Its outline is traced from the cells'
own shared edge chains, so two neighbouring parcels are separated by one
sequence of points walked twice in opposite directions. Nothing is unioned,
buffered or snapped, which is what keeps the tiling exact.

Sets that would pinch at a single node, or that would enclose a hole, are
rejected during growth: either produces more than one ring, and a habitat
parcel drawn by a surveyor does neither.
"""

from corridor_mesh import _hash01, ring_area

# Cell counts and their relative frequency. Field remnants beside a rail
# corridor are mostly small, with a long tail of whole fields.
SIZE_WEIGHTS = [
    (1, 0.42), (2, 0.24), (3, 0.13), (4, 0.08), (5, 0.045),
    (6, 0.03), (8, 0.025), (10, 0.015), (13, 0.008), (18, 0.007),
]


def _draw_size(seed):
    roll = _hash01(seed, 7717)
    running = 0.0
    for size, weight in SIZE_WEIGHTS:
        running += weight
        if roll < running:
            return size
    return SIZE_WEIGHTS[-1][0]


def _sides(cells):
    """The four anticlockwise sides of each cell whose neighbour is outside."""
    out = []
    for (i, j) in cells:
        if (i - 1, j) not in cells:
            out.append(('B', i, j, 1))
        if (i, j + 1) not in cells:
            out.append(('A', i, j + 1, 1))
        if (i + 1, j) not in cells:
            out.append(('B', i + 1, j, -1))
        if (i, j - 1) not in cells:
            out.append(('A', i, j, -1))
    return out


def _endpoints(side):
    kind, i, j, direction = side
    if kind == 'A':
        start, end = (i, j), (i + 1, j)
    else:
        start, end = (i, j), (i, j + 1)
    return (start, end) if direction == 1 else (end, start)


def trace_ring(mesh, cells):
    """Closed anticlockwise ring for a cell set, or None if it is not simple."""
    sides = _sides(cells)
    by_start = {}
    for side in sides:
        start, _ = _endpoints(side)
        if start in by_start:
            return None            # pinch: two outgoing sides at one node
        by_start[start] = side

    start_node, _ = _endpoints(sides[0])
    ring = []
    node = start_node
    for step in range(len(sides)):
        side = by_start.get(node)
        if side is None:
            return None
        ring.extend(_side_points(mesh, side)[:-1])
        _, node = _endpoints(side)
        if node == start_node:
            if step + 1 != len(sides):
                return None        # a second ring: the set encloses a hole
            ring.append(ring[0])
            return ring
    return None


def _side_points(mesh, side):
    kind, i, j, direction = side
    points = mesh.edge_line(kind, i, j)
    return points if direction == 1 else list(reversed(points))


def _is_single_ring(mesh, cells):
    sides = _sides(cells)
    by_start = {}
    for side in sides:
        start, _ = _endpoints(side)
        if start in by_start:
            return False
        by_start[start] = side
    start_node, _ = _endpoints(sides[0])
    node = start_node
    for step in range(len(sides)):
        side = by_start.get(node)
        if side is None:
            return False
        _, node = _endpoints(side)
        if node == start_node:
            return step + 1 == len(sides)
    return False


def build_parcels(mesh):
    """Assign every cell to exactly one parcel. Returns a list of cell sets."""
    stations, lanes = mesh.stations, mesh.lanes
    order = sorted(
        ((i, j) for i in range(stations) for j in range(lanes)),
        key=lambda c: _hash01(c[0], c[1], 3313),
    )
    assigned = {}
    parcels = []

    for seed in order:
        if seed in assigned:
            continue
        cells = {seed}
        target = _draw_size(seed[0] * 1000 + seed[1])
        attempts = 0
        while len(cells) < target and attempts < target * 6:
            attempts += 1
            frontier = []
            for (i, j) in cells:
                for candidate in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)):
                    ci, cj = candidate
                    if 0 <= ci < stations and 0 <= cj < lanes \
                            and candidate not in assigned and candidate not in cells:
                        frontier.append(candidate)
            if not frontier:
                break
            frontier.sort(key=lambda c: _hash01(c[0], c[1], len(cells), 991))
            picked = frontier[0]
            cells.add(picked)
            if not _is_single_ring(mesh, cells):
                cells.discard(picked)
                if len(frontier) == 1:
                    break
        index = len(parcels)
        for cell in cells:
            assigned[cell] = index
        parcels.append(cells)

    return parcels


def parcel_ring(mesh, cells):
    ring = trace_ring(mesh, cells)
    if ring is None:
        raise ValueError('parcel outline is not a single ring')
    if ring_area(ring) < 0:
        ring.reverse()
    return ring
