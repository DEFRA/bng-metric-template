# NSIP-scale test site

**This folder holds a synthetic habitat map at the scale of a nationally
significant infrastructure project (NSIP).** The site is a 56 km subsection of
a new rail line, with 11,554 baseline habitat parcels. It tests the template
conversion at real NSIP size. The data is invented, and describes no real
scheme or survey.

## What is in the folder

| Path | What it is |
| --- | --- |
| `generator/generate.py` | Builds the site. Run this |
| `generator/corridor_mesh.py` | Centre line, width and the shared mesh |
| `generator/corridor_parcels.py` | Groups mesh cells into parcels and traces their outlines |
| `generator/corridor_scenario.py` | Habitats, conditions and the intervention |
| `generator/corridor_linear.py` | Hedgerows, watercourses and trees |
| `generator/corridor_writers.py` | Writes the features into the template |
| `generator/gpkg_write.py` | GeoPackage geometry encoding |
| `generator/dropdown_check.py` | Checks every value against the template drop-downs |
| `verify/` | Validation, the claim 2 and claim 3 checks, a summary and a preview |
| `VERIFICATION.md` | The runbook: QGIS, each plugin feature and the service |
| `preview.png` | A 1.8 km window, before and after, to check by eye |
| `hs2-phase2a-subsection/` | Generated. A copy of the BNG Service template, with the site in it |
| `hs2-phase2a-subsection-12pc/` | Generated. The first 12% of the route |
| `legacy/` | Generated. The site converted to the legacy Natural England pair |

**The generated folders are not in git.** They come to about 100 MB, and the
generator rebuilds them to the byte in about 7 seconds.

**The code needs only the Python standard library.** A GeoPackage is a SQLite
database, so QGIS, GDAL and a network connection are not necessary. The one
exception is `verify/preview.py`, which needs matplotlib. The Python that QGIS
ships includes it.

## The site

The route runs from Handsacre in Staffordshire to Crewe. The land take is
55.8 km long and 330 m to 1,040 m wide, with eight construction compounds. Its
area is 3,184.04 hectares, below the 100 km² limit for a red line boundary.

| | Baseline | Post-intervention |
| --- | --- | --- |
| Area habitats | 11,554 | 13,682 |
| Hedgerows | 1,275 | 1,469 |
| Watercourses | 256 | 243 |
| Individual trees | 3,600 | 2,767 |
| Red line boundary | 1 | |

The site has 546,629 vertices. The staged template is 28 MB, and the converted
legacy pair is 31 MB.

**266 baseline parcels, 72.3 hectares, are ancient woodland.** Each is
broadleaved or coniferous woodland with the irreplaceable habitat flag. Every
always-irreplaceable habitat is High or V.High distinctiveness, which the
service does not accept. Ancient woodland is the one irreplaceable case that a
valid file can hold.

The baseline has 33 area habitat types, 9 hedgerow types and 3 watercourse
types. The intervention is a sealed core, earthworks on each side, a
mitigation margin, and land with no change at the edges. The result is 1,663
hectares created, 331 hectares enhanced and 1,190 hectares retained.

**The site holds only Medium, Low and V.Low distinctiveness habitats**, which
is the scope that the service accepts. **It holds no vertical area habitats**,
because the legacy template cannot hold them.

## How the geometry is built

**All parcels sit on one mesh, so they tile the site exactly.** The mesh has
1,396 cross sections at 40 m spacing, with 18 cells across. Each parcel is a
union of mesh cells, and adjacent cells share identical vertex chains. The red
line boundary is the outer edge of the mesh. The summed parcel area equals the
red line area by construction, with no union, buffer or snap.

A splined centre line, a changing width and jitter on the mesh nodes make the
outlines irregular, at 19.5 vertices for each parcel on average. Hedgerows and
ditches follow mesh edges, so they stay inside the red line. Re-meandered
channels and trees use corridor coordinates, so they can move off their line
and stay inside the site.

### The post-intervention side

Three rules come from how the staged template checks a child against its
parent.

- **Area habitats balance exactly.** Each child is a union of cells from its
  parent, and the children of a parcel tile it completely.
- **Hedgerows and trees can fall short of their parent but never exceed it.**
  A hedge that the works remove is recorded by its remaining stretches only.
  The loss is the residual, as in the Statutory Metric.
- **Watercourses need only be present.** A re-meandered channel leaves its old
  line and gets longer, so child lengths do not show what was lost.

**Each row cut from a baseline feature records its parent, as the Copy
baseline button does.** `parent_uuid` holds the `feature_uuid` of the baseline
feature, and `parent_geom` holds the shape of that feature as WKT at three
decimal places. A created hedgerow or tree row leaves both blank. A created
area habitat row keeps the parent of the parcel it was cut from. Every label
is written as the reference lists hold it, with no number in front, for
example `Moderate`.

**The values the template fills itself are written as it fills them.**

- Each row holds its reference in `Habitat Ref`.
- Baseline Strategic Significance is `Low` on every baseline row, and on each
  post-intervention row cut from one. A created hedgerow or tree leaves it
  blank.
- Proposed Strategic Significance is mostly `Low` and sometimes `High`,
  chosen by hash.
- Spatial risk category is `N/A`.
- Distinctiveness comes from the template's list for the habitat type. A
  habitat that allows one condition gets that condition.
- Irreplaceable Habitat is the only answer where the habitat allows one.
  Where it allows both, ancient woodland blocks are `Yes` and the rest `No`.

## Running it

Run all commands from the root of this repo.

```sh
python3 scale-test-nsip/generator/generate.py
python3 plugin/bng_template_convert/new_to_old.py \
    "scale-test-nsip/hs2-phase2a-subsection/Layers/BNG Service Layers.gpkg" \
    -o scale-test-nsip/legacy
```

Generation takes about 7 seconds, and conversion about 2 seconds. The
generator then runs the drop-down check and stops with an error if a value is
not in the template lists. The check tests the columns the template fills
itself (distinctiveness, strategic significance, spatial risk and
Irreplaceable Habitat) against the lists and rules directly, whatever widget
the project gives them. To run that check alone:

```sh
python3 scale-test-nsip/generator/dropdown_check.py \
    scale-test-nsip/hs2-phase2a-subsection
```

**Use `--fraction` for a shorter section of the same scheme.** It starts from
the southern end and keeps the same feature density. Each sheet of the
Statutory Metric holds 248 rows, and one metric holds about an eighth of this
scheme.

```sh
python3 scale-test-nsip/generator/generate.py --fraction 0.12
# writes scale-test-nsip/hs2-phase2a-subsection-12pc/
```

**Generation gives the same bytes on each run.** Each random choice is a hash
of the position of the feature. Each run starts from a fresh copy of the empty
template, and copies the project file, reference lists and surveyor's guide
from `templates/bng-service/`. Conversion gives the same content on each run,
but not the same bytes.

**`VERIFICATION.md` gives every check**: validation, the claim 2 and claim 3
checks, `verify/summarise.py` for counts and `verify/preview.py` for a PNG.

## Measured results

**All three files are valid**, in 6.5 s to 7.5 s each.

**A site of this size fails validation intermittently.** The service gives one
validation 10 seconds. The converted post-intervention file takes 7.3 to 9.3
seconds, and one run went past the limit. The same file uploaded twice can
give two different answers. File size is not the limit: the 100 MB upload
limit is three times the largest file here.

**The parcels reassemble exactly.** The service measures the 11,554 baseline
parcels and the 13,682 post-intervention parcels at the same total:
31,840,368.775235 m². The two agree to six decimal places across 3,184
hectares. The service allows 0.5 m².

**Consolidation without the irreplaceable flag hides irreplaceable habitat.**
The import tool merges rows that agree on every attribute, and its CSVs have
no irreplaceable column. That merge absorbs 215 of the 314 irreplaceable rows
into rows that show as ordinary habitat. The converter keeps the flag in its
own merge by default.

**Claims 2 and 3 both pass.** Claim 2 checks about 34,000 rows against a
transformation list written in advance. Claim 3 prices the whole site in both
templates. The unit totals differ by 0.0003% and the net change by 0.000112
percentage points, which is within the rounding that the legacy format forces.
