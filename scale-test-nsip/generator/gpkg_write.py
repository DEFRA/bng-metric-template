"""Minimal GeoPackage geometry encoding.

A GeoPackage is a SQLite database and its geometry column holds a short binary
header followed by ordinary WKB, so writing one needs nothing but the standard
library. The converters beside this folder read the same format.
"""

import struct

SRS_ID = 27700
_HEADER_FLAGS_WITH_ENVELOPE = 0x01 | (1 << 1)   # little endian, XY envelope


def wkb_polygon(rings):
    parts = [struct.pack('<BII', 1, 3, len(rings))]
    for ring in rings:
        parts.append(struct.pack('<I', len(ring)))
        parts.append(struct.pack(f'<{2 * len(ring)}d',
                                 *[value for point in ring for value in point]))
    return b''.join(parts)


def wkb_linestring(points):
    return (struct.pack('<BII', 1, 2, len(points))
            + struct.pack(f'<{2 * len(points)}d',
                          *[value for point in points for value in point]))


def wkb_point(point):
    return struct.pack('<BI2d', 1, 1, point[0], point[1])


def envelope_of(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), max(xs), min(ys), max(ys))


def blob(wkb, envelope, srs_id=SRS_ID):
    header = (b'GP' + bytes([0, _HEADER_FLAGS_WITH_ENVELOPE])
              + struct.pack('<i', srs_id) + struct.pack('<4d', *envelope))
    return header + wkb


def polygon_blob(ring):
    return blob(wkb_polygon([ring]), envelope_of(ring))


def line_blob(points):
    return blob(wkb_linestring(points), envelope_of(points))


def point_blob(point):
    return blob(wkb_point(point), (point[0], point[0], point[1], point[1]))


def polygon_wkt(ring, decimals=3):
    inner = ', '.join(f'{x:.{decimals}f} {y:.{decimals}f}' for x, y in ring)
    return f'POLYGON (({inner}))'


def line_wkt(points, decimals=3):
    inner = ', '.join(f'{x:.{decimals}f} {y:.{decimals}f}' for x, y in points)
    return f'LINESTRING ({inner})'


def point_wkt(point, decimals=3):
    return f'POINT ({point[0]:.{decimals}f} {point[1]:.{decimals}f})'
