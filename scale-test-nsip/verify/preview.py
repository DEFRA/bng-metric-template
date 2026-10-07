import os, sqlite3, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'plugin', 'bng_template_convert'))
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
from gpkg_common import blob_geometry

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
      'hs2-phase2a-subsection', 'Layers', 'BNG Service Layers.gpkg')
conn = sqlite3.connect(DB)

# A 2.5 km window part way along the route.
cx, cy, half = 386500, 337800, 900
box = (cx - half, cx + half, cy - half, cy + half)

COLOURS = {
 'Grassland': '#bcd97c', 'Cropland': '#e8d98a', 'Woodland and forest': '#4e8b4a',
 'Heathland and shrub': '#9fbf6a', 'Urban': '#b9b0a8', 'Lakes': '#8fc0e8',
 'Sparsely vegetated land': '#d9c9a3', 'Wetland': '#7fb3a8',
}

fig, axes = plt.subplots(1, 2, figsize=(17, 8.5))
for ax, (table, hcol) in zip(axes, [('Area Habitats Baseline', 'Baseline Broad Habitat Type'),
                                    ('Area Habitats Post-Intervention', 'Proposed Broad Habitat Type')]):
    rows = conn.execute(f'SELECT geom, "{hcol}" FROM "{table}"').fetchall()
    drawn = 0
    for blob, broad in rows:
        if blob is None:
            continue
        _, coords = blob_geometry(blob)
        ring = coords[0]
        xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
        if max(xs) < box[0] or min(xs) > box[1] or max(ys) < box[2] or min(ys) > box[3]:
            continue
        ax.add_patch(MplPolygon(list(zip(xs, ys)), closed=True,
                                facecolor=COLOURS.get(broad, '#cccccc'),
                                edgecolor='#4a4a4a', linewidth=0.25))
        drawn += 1
    for tbl, colour, width in [('Hedgerows Baseline' if 'Baseline' in table else 'Hedgerows Post-Intervention', '#1f6b1f', 1.3),
                               ('Watercourses Baseline' if 'Baseline' in table else 'Watercourses Post-Intervention', '#1a6fb5', 1.6)]:
        for (blob,) in conn.execute(f'SELECT geom FROM "{tbl}"'):
            if blob is None: continue
            _, coords = blob_geometry(blob)
            xs = [p[0] for p in coords]; ys = [p[1] for p in coords]
            if max(xs) < box[0] or min(xs) > box[1] or max(ys) < box[2] or min(ys) > box[3]:
                continue
            ax.plot(xs, ys, color=colour, linewidth=width, solid_capstyle='round')
    tt = 'Individual Trees Baseline' if 'Baseline' in table else 'Individual Trees Post-Intervention'
    px, py = [], []
    for (blob,) in conn.execute(f'SELECT geom FROM "{tt}"'):
        if blob is None: continue
        _, c = blob_geometry(blob)
        if box[0] <= c[0] <= box[1] and box[2] <= c[1] <= box[3]:
            px.append(c[0]); py.append(c[1])
    ax.scatter(px, py, s=7, c='#0d3d0d', zorder=5)
    ax.set_xlim(box[0], box[1]); ax.set_ylim(box[2], box[3])
    ax.set_aspect('equal'); ax.set_title(f'{table}  ({drawn} parcels in view)')
    ax.set_xticks([]); ax.set_yticks([])
plt.tight_layout()
out = sys.argv[1]
plt.savefig(out, dpi=100)
print('wrote', out)
