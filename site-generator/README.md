# Site generator

**The generator builds a small, realistic BNG site from a few inputs.** It
writes the baseline and the post-intervention stage into the BNG Service
template, into both Natural England templates and into the Statutory Metric.
The same inputs always give the same GeoPackages, to the byte.

Use it for test data, demonstrations and training. The sites are synthetic:
no site is a survey of real land.

## Build a site

Run the generator from the root of this repo:

```sh
python3 site-generator/generate_site.py                  # 20 parcels, 5 ha, housing
python3 site-generator/generate_site.py --habitats 1     # the simplest site
python3 site-generator/generate_site.py --habitats 50 --area-ha 30 \
    --centre 451000,206000 --scheme solar --landscape arable --seed 4
```

The output goes to `site-generator/output/<name>/`, which git ignores. Each
file in it is a copy of the clean file in this repository, filled with the
site:

| In the output folder | What it is |
| --- | --- |
| `bng-service/` | The BNG Service template, with the baseline and post-intervention layers |
| `legacy-ne-baseline/` | The Natural England template, with the baseline in its GeoPackage |
| `legacy-ne-post-intervention/` | The Natural England template, with the post-intervention stage in its GeoPackage |
| `The_Statutory_Metric_Macro_Enabled_1.0.4.xlsm` | The macro-enabled Statutory Metric, with the on-site tabs filled |

Open the `.qgz` file in a template folder to see the site in QGIS. Open the
metric in Excel and let it recalculate.

**The two Natural England files are the ones the service asks a user to
upload.** Each is the template's own GeoPackage, so it keeps the template's
styles and layers. The metric holds the area habitats and hedgerows.
Individual trees are not written to it, because the metric works out their
size from a band.

| Input | Default | What it sets |
| --- | --- | --- |
| `--habitats` | 20 | Baseline habitat parcels, from 1 to 50 |
| `--area-ha` | 5 | Site area in hectares, from 0.05 to 500 |
| `--centre` | 455920.7,285323.1 | Site centre, as a British National Grid easting and northing |
| `--hedgerows` | 1 | Baseline hedgerows, from 0 to 10 |
| `--trees` | 3 | Baseline individual trees, from 0 to 50 |
| `--landscape` | pastoral | The land now: `pastoral`, `arable`, `wooded` or `urban-fringe` |
| `--scheme` | housing | The development: `housing`, `commercial` or `solar` |
| `--seed` | 1 | A different seed gives a different layout and different choices |
| `--name` | from the inputs | The site name, and the name of the output folder |
| `--out` | `output/<name>` | Another output folder |
| `--no-legacy` | off | Leaves out the two Natural England templates |
| `--no-metric` | off | Leaves out the Statutory Metric |

**The generator stops with an error if it cannot deliver what was asked.**
The usual cause is too many hedgerows for a small site. Ask for fewer
hedgerows, more habitats, or use another seed.

---

## What a site holds

**The parcels tile the red line boundary exactly.** Their areas add up to the
requested area, to within 0.01 m². The boundary is compact and
irregular, and the site is centred on the requested point.

**Each parcel has a habitat that the landscape makes likely.** The largest
parcel takes the landscape's main habitat, for example modified grassland on
pastoral land. The other large parcels take field habitats. The small parcels
take features such as scrub, ponds and woodland. The weights are judgement,
informed by the real sites in the BNG500 collection of Statutory Metric
workbooks. In those sites modified grassland is the most common baseline
habitat.

**The development comes in from one side of the site.** The scheme sets its
share of the site:

| Scheme | Development | Green margin | Hedgerows and trees in the development |
| --- | --- | --- | --- |
| Housing | 55% | 20% | Removed. Street trees planted |
| Commercial | 70% | 12% | Removed. Street trees planted |
| Solar | 75% | 15% | Kept. Grassland created under the panels |

A parcel that the development crosses is divided into parts. Each part tiles
its parent, and each part has its own retention category:

- **Development:** created as the scheme's habitats, for example sealed
  surface and vegetated garden.
- **Green margin:** created as new green space, or enhanced, or retained.
- **The rest:** mostly retained, with some enhancement.

**Hedgerows run along the boundaries between parcels.** A hedgerow is never
on the red line. Where the development crosses a hedgerow, only the parts
outside it are kept. Housing and solar schemes can also plant a new hedgerow
along the edge of the development.

**Trees stand near a hedgerow or inside a parcel.** A tree inside the
development is lost. New trees are planted in the development and in the
green margin.

**The values the template fills itself are written as it fills them.** Each
row holds its reference in `Habitat Ref`. Baseline Strategic Significance is
`Low`, and blank on a created hedgerow or planted tree. Proposed Strategic
Significance is mostly `Low` and sometimes `High`. Spatial risk category is
`N/A`. Irreplaceable Habitat is the only answer where the habitat allows one,
and `No` where it allows both. The Natural England templates and the metric
get the metric's wording for significance: see `../plugin/README.md`.

---

## How the output is checked

Every run checks these, and stops with an error if one fails:

- The site has exactly the number of parcels that was asked for.
- The parcel areas add up to the red line area.
- The site has the number of hedgerows that was asked for.
- Every value is one that the template's drop-downs offer.

These checks were run by hand across the input range:

| Check | Result |
| --- | --- |
| 150 sites, 1 to 50 parcels, every scheme and landscape, 0.05 to 500 ha | All built and passed the checks above |
| The service's own GeoPackage validation, on the Natural England files of 9 sites, from 1 to 50 parcels and 0.05 to 500 ha | All valid, baseline and post-intervention |
| The metric engine, on every area habitat row of 5 of those sites | Every row priced |
| The same inputs, run twice | Identical GeoPackages. The metric has identical contents, but the dates inside the workbook file differ |

**The generator does not aim for net gain.** A site shows the on-site loss
that a development usually shows before off-site units are bought. The 5
sites above lost between 31% and 73% of their area habitat units.

---

## How it is built

The generator uses the same construction as the NSIP example site, and its
code. The files in `../scale-test-nsip/generator/` supply the mesh helpers,
the reference lists, the condition and enhancement rules, the column lists
and the drop-down check.

| File | What it does |
| --- | --- |
| `generate_site.py` | Reads the inputs, builds the site and writes the output |
| `site_mesh.py` | The mesh, the site outline, and the scale and position of the site |
| `site_plan.py` | Parcels, habitats, the development, and hedgerow routes |
| `site_writers.py` | Writes the rows of each layer |
| `site_outputs.py` | Fills the Natural England templates and the metric, with the plugin's own conversions |

**The site is a group of cells on one jittered mesh.** Neighbouring cells
share their edges point for point, so parcels never overlap or leave a gap.
The mesh is built once to measure the site, then scaled to the requested
area. Scaling keeps every shared edge shared.

**Every choice comes from a hash of the seed.** The generator uses no random
number source and no clock, so a run can always be repeated.

Watercourses are not generated.
