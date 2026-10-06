# Verifying the template, the plugin and the service at NSIP scale

**This runbook tests the five claims of the template decision brief against
the Handsacre to Crewe site.** Steps 1 and 2 use QGIS, steps 3 to 6 the
plugin, and step 7 the service. Step 8 runs claims 2 and 3. Step 9 maps each
step to its claims.

**Values in bold are measured.** A step with no bold value has no recorded
result.

Run all commands from the `qgis-template` folder.

## 0. Before you start

| Item | How to get it |
| --- | --- |
| The site file | Run `python3 scale-test-nsip/generator/generate.py` (7 seconds) |
| The 12% section, for step 5 | Run `python3 scale-test-nsip/generator/generate.py --fraction 0.12` |
| QGIS, with the plugin | See `plugin/README.md`. Restart QGIS after you install or replace the plugin |
| The service, running locally | Run `docker compose up -d` in the backend, then `npm run dev` in the harness |
| A blank metric workbook | `reference/The_Statutory_Metric_Macro_Enabled_1.0.4.xlsm` |
| Excel | For step 4d and step 5 only |

**Close the QGIS project before you run a script that writes to the
GeoPackage.** QGIS locks an open project, and the script fails.

## 1. Open the site in QGIS

1. Open this project:
   `scale-test-nsip/hs2-phase2a-subsection/BNG Service Habitat Mapping.qgz`.
2. Zoom to the Area Habitats Baseline layer.
3. Switch to Area Habitats Post-Intervention.

**Pass:**

- The corridor draws without a stall.
- Parcel outlines are irregular, not rectangular.
- Field boundaries carry hedgerows.
- The post-intervention layer shows the sealed core in the land take.

**Fail:**

- A layer takes more than a few seconds to draw.
- Rendering errors show at the joins between parcels.
- The attribute table of 13,682 rows is slow to open.

**Screenshot:** the two layers side by side at about 1:15,000.
`scale-test-nsip/preview.png` shows the same view without QGIS.

Then check the feature counts in Layer Properties, Information:

| Layer | Rows |
| --- | --- |
| Area Habitats Baseline | **11,554** |
| Area Habitats Post-Intervention | **13,682** |
| Hedgerows Baseline | **1,275** |
| Hedgerows Post-Intervention | **1,469** |
| Watercourses Baseline | **256** |
| Watercourses Post-Intervention | **243** |
| Individual Trees Baseline | **3,600** |
| Individual Trees Post-Intervention | **2,767** |
| Red Line Boundary | **1** |

## 2. The template buttons, at scale

**Work on a copy.** The buttons save as they go, and there is no undo.

```sh
cp -R scale-test-nsip/hs2-phase2a-subsection \
      scale-test-nsip/hs2-phase2a-subsection-button-test
```

Open the project in the copy. The buttons are under **Actions**, at the right
of the attribute table toolbar.

| Button | Layer | Measured |
| --- | --- | --- |
| Copy baseline to post-intervention | Area Habitats Post-Intervention | **About 5 s** in QGIS on macOS, **6.1 s** on Windows, for 11,554 parcels. The interface stays responsive |
| Tidy PI refs after splitting | Area Habitats Post-Intervention | **1 s**, with nothing to change |
| Refresh from baseline | Area Habitats Post-Intervention | **9 s**, with nothing to bring in |
| Rename a ref (updates post-intervention) | Area Habitats Baseline | Not timed |

**The copy is safe to cancel.** Batches already written stay written. A second
run skips what is already copied, and takes **0.4 s** when nothing is left.

**The copy asks before it restores a removed feature.** If a post-intervention
feature was removed on purpose, the copy names it and asks first. Refresh from
baseline does the same.

### How the copy stays fast

This note is for a maintainer who changes the copy action.

- It writes through the data provider in batches of 1,000, not one feature at
  a time through the edit buffer.
- It stops the canvas from redrawing during a batch, and redraws once at the
  end.
- It reads only the two columns that it needs to find copied features.
- It records `parent_geom` at three decimal places. The service rounds both
  shapes to three decimal places before it compares them, so more digits add
  nothing. This halves that column from 11.6 MB to 5.3 MB.
- It refuses to run while the layer has unsaved edits.
- It emits `featureAdded` for each new row, so an open attribute table shows
  the rows without a reopen.

**Only `featureAdded` updates an open attribute table.** A layer reload,
`dataChanged`, a repaint, a field update, an empty edit session, a cache reset
and a subset string reset each leave the table empty. The signal costs 4.7 s
for 11,554 rows with a table open, and 0.02 s with no table open. On Windows,
5.07 s of the 6.1 s total is the table update, which also drives the progress
dialog.

### Checks still to run

1. Run **Rename a ref** on a parcel with several children, for example an
   `AH-` ref with `-1` and `-2` rows. Every child must follow.
2. Run **Tidy PI refs after splitting** on the 1,847 split parcels. Check the
   suffixes.
3. Edit some baseline parcels. Then run **Refresh from baseline** and time it.
   The 9 s figure is the minimum, because it had no work to do.
4. Run each button on hedgerows, watercourses and trees.

**Screenshot:** the message bar report and the elapsed time for each button.

## 3. Plugin: convert to the legacy pair

1. Open the Processing Toolbox, **BNG Template Convert**, **BNG template
   conversion**.
2. Open **Convert to legacy template (for the older service)**.
3. Set the input to the site GeoPackage.
4. Set **What to produce** to **Legacy GeoPackages only**.
5. Tick **Record lineage in comments**.

Or from a terminal:

```sh
python3 plugin/bng_template_convert/new_to_old.py \
    "scale-test-nsip/hs2-phase2a-subsection/Layers/BNG Service Layers.gpkg" \
    -o scale-test-nsip/legacy --carry-lineage
```

**Pass:** about **2 seconds**, two files of **31 MB** in total, and these
rows:

| | Baseline | Post-intervention |
| --- | --- | --- |
| Habitats | **11,554** | **13,682** |
| Hedgerows | **1,275** | **2,157** |
| Rivers | **256** | **256** |
| Urban Trees | **3,600** | **4,752** |

**The legacy post-intervention counts are larger on purpose.** The legacy
format cannot record a removal by absence. The converter adds a `Lost` row for
each removed feature: **688** hedgerows, **13** watercourses and **1,985**
trees. The report lists them.

The report also warns that the irreplaceable flag is dropped, on **580**
features. The legacy template has no column for it.

**Strategic significance gets the Natural England wording.** `Low` becomes
*Area/compensation not in local strategy/ no local strategy*. `High` becomes
*Formally identified in local strategy*, or *Within area formally identified
in local strategy* for trees. A blank becomes *N/A* on the **394** created
hedgerows and the **1,152** planted trees, as before, and stays blank on the
added `Lost` rows. `Habitat Ref` becomes `Parcel Ref`, or `Tree Ref`.

**Screenshot:** the plugin log with the row counts and the warnings.

### Open the result in the legacy QGIS template

The legacy project reads `./Layers/Net Gain Habitat Mapping Layers.gpkg` by
that exact name. Each stage needs its own template folder.

1. Copy `templates/legacy-ne/` twice, one folder for each stage.
2. Put the matching file in the `Layers/` folder of each copy.
3. Rename it to `Net Gain Habitat Mapping Layers.gpkg`, and replace the empty
   file.
4. Open `Net Gain Habitat Mapping.qgz` in that folder.

**Pass: the site opens in the legacy template and draws correctly.**

**Screenshot:** the legacy template open on the converted site. It proves that
a site of this size converts into the format that Natural England tooling
reads.

## 4. Plugin: import tool CSVs and consolidation

Use the same algorithm as step 3, with **What to produce** set to **GIS import
tool CSVs only**. The converter writes a `GIS import tool CSVs` folder. It
splits each file into parts of 248 rows, the limit of the import tool.

### 4a. Without consolidation (the default)

```sh
python3 plugin/bng_template_convert/new_to_old.py \
    "scale-test-nsip/hs2-phase2a-subsection/Layers/BNG Service Layers.gpkg" \
    -o scale-test-nsip/csv-out --format csv
```

**Pass:**

| File | Rows | Parts |
| --- | --- | --- |
| Habitats | **13,682** | **56** |
| Hedgerows | **2,157** | **9** |
| Rivers | **256** | **2** |
| Irreplaceable habitats.csv | **314** | 1 |

### 4b. With consolidation

Tick **CSVs: merge rows with matching values**. Keep **CSVs: keep
irreplaceable habitat in its own rows** ticked.

```sh
python3 plugin/bng_template_convert/new_to_old.py \
    "scale-test-nsip/hs2-phase2a-subsection/Layers/BNG Service Layers.gpkg" \
    -o scale-test-nsip/csv-consolidated --format csv --consolidate
```

**Pass:**

| File | Rows before | Rows after | Parts after |
| --- | --- | --- | --- |
| Habitats | 13,682 | **3,105** | **13** |
| Hedgerows | 2,157 | **122** | 1 |
| Rivers | 256 | **81** | 1 |

Measured 30 September 2026. Every baseline row is now `Low`, so more rows
match than before.

**The totals must not change.** Both runs give **31,840,375** m² of habitat,
**411,018** m of hedgerow and **111,031** m of watercourse. Check it:

```sh
python3 - <<'PY'
import csv, glob
for name, col in [("Habitats", "Area"), ("Hedgerows", "Length"),
                  ("Rivers", "Length")]:
    for folder in ("csv-out", "csv-consolidated"):
        rows = []
        for path in glob.glob(f"scale-test-nsip/{folder}/"
                              f"GIS import tool CSVs/{name}*.csv"):
            rows += list(csv.DictReader(open(path, encoding="utf-8-sig")))
        print(f"{folder:16s} {name:10s} {len(rows):6d} rows  "
              f"{sum(float(r[col] or 0) for r in rows):.0f}")
PY
```

### 4c. Irreplaceable habitat

**Pass:** of the 3,105 consolidated habitat rows, **147** have a `Parcel Ref`
that ends `-IRR`. Their comment reads
`IRREPLACEABLE HABITAT, do not merge with other rows`.

Then run the comparison without that protection. Untick **keep irreplaceable
habitat in its own rows**, or add `--merge-irreplaceable`:

```sh
python3 plugin/bng_template_convert/new_to_old.py \
    "scale-test-nsip/hs2-phase2a-subsection/Layers/BNG Service Layers.gpkg" \
    -o scale-test-nsip/csv-merged --format csv --consolidate \
    --merge-irreplaceable
```

**Result:** **3,020** rows, 85 fewer. The 85 groups mix flagged and unflagged
parcels. They absorb **248 of the 314** irreplaceable rows into rows that show
as ordinary habitat. The largest of them has **110** parcels.

**Screenshot:** 3,105 rows against 3,020, on one screen.

Git ignores the `csv-merged/` folder, so it can stay after the check.

### 4d. Through the import tool

Not yet run. Needs Excel.

1. Open `reference/GIS Import Tool.xlsb`.
2. On the Habitats, Hedges and Rivers tabs, use **Import GIS CSV Data**.
3. Load each file from `scale-test-nsip/csv-consolidated`.

**Pass:** Hedgerows and Rivers load whole, at 122 and 81 rows. Habitats needs
13 separate imports, one for each part, and each part is a separate metric.

**Do not press Consolidate Data.** The tool cannot see the irreplaceable flag,
so the button undoes step 4b. Take a screenshot before and after, to show that
the protection depends on a user not pressing this button.

## 5. Plugin: export to the Statutory Metric workbook

**This route does not use the CSVs or the import tool.** The plugin opens a
copy of the blank metric workbook and writes cell values into its on-site
sheets. An `.xlsm` file is a zip of XML, so this needs no Excel and no
library. Macros, sheet protection and all other parts stay the same. Excel
recalculates the workbook when it next opens it.

**Each sheet holds 248 rows, and 246 on the enhancement sheets.** A site that
does not fit goes into several workbooks. Each workbook is a valid metric for
its share of the site. The answer for the site is the sum of their unit
columns. Do not read a net gain percentage from one workbook.

### Fill the metric from the 12% section

In QGIS, open **Plugins**, **BNG Template Convert**, **Export to the
Statutory Metric**. If the item is not there, reinstall the plugin and restart
QGIS.

| Field | Value |
| --- | --- |
| BNG Service GeoPackage | `scale-test-nsip/hs2-phase2a-subsection-12pc/Layers/BNG Service Layers.gpkg` |
| Blank Statutory Metric workbook | `reference/The_Statutory_Metric_Macro_Enabled_1.0.4.xlsm` |
| Filled metric workbook to write | Any path that ends `.xlsm` |
| Merge rows with matching values | Ticked |

Or from a terminal:

```sh
python3 plugin/bng_template_convert/to_metric.py \
    "scale-test-nsip/hs2-phase2a-subsection-12pc/Layers/BNG Service Layers.gpkg" \
    --metric reference/The_Statutory_Metric_Macro_Enabled_1.0.4.xlsm \
    -o "scale-test-nsip/metric-out/Section 1 - consolidated.xlsm" \
    --consolidate
```

**Pass**, measured 30 September 2026: about **1.5 seconds**, **1** workbook
and **4,292** cells.

| Rows mapped | Baseline | Creation | Enhancement |
| --- | --- | --- | --- |
| Area habitats | **222** | **151** | **135** |
| Hedgerows | **45** | **14** | **29** |
| Watercourses | **28** | **0** | **11** |

The export gives one warning, and it is correct: **19** irreplaceable parcels
are wholly or partly lost. The metric shows 'Any Loss Unacceptable' for them
and leaves them out of the baseline total.

**Strategic significance is written in the metric's wording**, as in step 3.

**Open each workbook in Excel and let it recalculate.** Check that the on-site
habitat tabs hold names, sizes and conditions, and the headline units show no
errors.

**Screenshot:** tab A-1 filled.

### Contrasts

- **Without merging**, the same section needs **7** workbooks: **1,533**
  baseline and **923** creation rows.
- **The full site, merged**, needs **5** workbooks and **21,832** cells.
- **A wrong input stops the export.** The `.xlsb` import tool is refused with
  a message. A workbook that already holds a site is refused, unless you add
  `--allow-occupied`.

### What the export does not fill

- Individual trees, **428** in the 12% section. The metric gets their size
  from a band lookup, not from the map.
- The off-site tabs, which have allocation columns and a different layout.
- The Irreplaceable Habitats sheet. The irreplaceable flag itself is written
  on the on-site baseline habitat sheet.

The export lists these on each run. Enter them by hand.

## 6. Plugin: convert back, and round trip

Open **Convert from legacy template** and select the two files from step 3.
Or from a terminal:

```sh
python3 plugin/bng_template_convert/old_to_new.py \
    --baseline "scale-test-nsip/legacy/Net Gain Habitat Mapping Layers - Baseline.gpkg" \
    --post-intervention "scale-test-nsip/legacy/Net Gain Habitat Mapping Layers - Post-intervention.gpkg" \
    -o scale-test-nsip/roundtrip
```

**Pass:** about **3 seconds**, and each count as it started: **11,554**,
**13,682**, **1,275**, **1,469**, **256**, **243**, **3,600**, **2,767**.

**Strategic significance comes back as `Low` and `High`.** The wordings from
step 3 map back one to one, and *N/A* comes back blank. Spatial risk category
is `N/A` on every post-intervention row. Irreplaceable Habitat is filled on
**23,049** rows whose habitat allows only one answer.

**The converter drops the `Lost` rows from step 3.** The staged template
records a removal by absence, so the 688 hedgerow, 13 watercourse and 1,985
tree rows go. The report names each dropped reference.

The report also warns that Irreplaceable Habitat is blank on **2,187** rows,
whose habitat allows either answer, and that vertical area habitats are empty.
The legacy template holds neither.

This step satisfies claim 1 for the round trip, at the level of counts. Step 8
compares the values.

## 7. The running service

1. Start the stack, sign in and create a project.
2. On the task list, select **On-site baseline habitats**.
3. Upload the baseline file from `scale-test-nsip/legacy/`.
4. Upload the post-intervention file from `scale-test-nsip/legacy/`.
5. Repeat step 4 a few times, and time each upload.
6. Open the habitat list and some habitat detail pages.

**Pass:** the service accepts both files, and the pages stay usable.

**Screenshot:** the project summary with both tasks complete.

**The post-intervention upload is near the time limit.** The service gives one
validation 10 seconds on a worker thread, then fails the upload.

| Condition | Measured |
| --- | --- |
| Idle laptop | **7.3 to 8.0 s** |
| Other load on the machine | **7.8 to 9.3 s** |
| One run | **Over 10 s, upload failed** |

**A screenshot of the failure is more useful than one of the success.** The
same file uploaded twice can give two different answers.

To run the same validation without the interface:

```sh
node scale-test-nsip/verify/validate-legacy.mjs \
    "scale-test-nsip/legacy/Net Gain Habitat Mapping Layers - Baseline.gpkg" \
    baseline
node scale-test-nsip/verify/validate-legacy.mjs \
    "scale-test-nsip/legacy/Net Gain Habitat Mapping Layers - Post-intervention.gpkg" \
    postIntervention
```

The script uses the harness `backend` folder. Set `BACKEND_DIR` to use a
different checkout.

**Pass:** `valid true`, and a summed parcel area of **31,840,368.775235** m²
for both files. This is what "the parcels reassemble exactly" means.

### The staged file

The staged validation needs PostGIS, which the backend compose stack
provides. It also needs a backend checkout that holds
`src/validation/geopackage/lineage/`. Make one as a worktree:

```sh
git -C ../backend worktree add /tmp/staged spike/baseline-pi-lineage
ln -s "$PWD/../backend/node_modules" /tmp/staged/node_modules
STAGED_BACKEND_DIR=/tmp/staged node scale-test-nsip/verify/validate-staged.mjs \
    "scale-test-nsip/hs2-phase2a-subsection/Layers/BNG Service Layers.gpkg"
```

**Pass:** valid, in about **6.5 s**, with one removal warning. The warning is
the intended loss of hedgerows and trees under the works.

## 8. Claims 2 and 3

Run both after each conversion to `scale-test-nsip/legacy`:

```sh
python3 scale-test-nsip/verify/claim2_nothing_altered.py
node scale-test-nsip/verify/claim3-answer-does-not-move.mjs
```

### Claim 2: nothing is altered

`verify/claim2_manifest.py` is the transformation list. It comes from the
documented behaviour, not from the converter code, so a fault in the code
cannot hide in it. It marks each column on each side as one of these:

- carried unchanged;
- changed by a stated rule;
- composed from more than one staged column;
- dropped, for a stated reason;
- invented, from a stated source.

`verify/claim2_nothing_altered.py` compares the staged site with the legacy
pair against that list. It pairs rows by position, then proves each pair by
geometry. A column that is on one side and not in the list fails the check.

**Some legacy labels have a number in front.** The Natural England lists
number the conditions, the watercourse retention categories and the riparian
encroachment values, for example `3. Moderate`. The BNG Service lists hold
the same label with no number, `Moderate`. The list marks each of these
columns. The legacy value must hold the same words, and must be a label that
the Natural England list in `templates/legacy-ne/` offers for the habitat or
watercourse type of that row, with its number. A wrong or missing number
fails. There are three exceptions. `Created` on an existing watercourse must
be `4. Created`, which the Natural England list does not offer. A watercourse
loss row that the conversion adds is checked without its number, because it
is written as `Lost`. A tree's proposed condition must have no number.

**Strategic significance is checked against the wording.** `Low` must arrive
as *Area/compensation not in local strategy/ no local strategy*. `High` must
arrive as *Formally identified in local strategy*, or *Within area formally
identified in local strategy* for trees. A blank must arrive as *N/A* for a
hedgerow or watercourse type of *To be created* or *N/A* and for a newly
planted tree, and as a blank elsewhere.

**Pass: all eight layer pairs and the red line boundary, about 34,000 rows.**

### Claim 3: the answer does not move

`verify/claim3-answer-does-not-move.mjs` prices the site twice: once as the
staged file, once as the legacy pair. Both use `bng-metric-engine`, the
calculator of the service, from the backend dependencies. The script does not
use the converter, so a conversion fault cannot cancel itself out.

**The pass mark is a difference no larger than rounding explains.** The staged
file holds hectares and metres as measured. The legacy files hold whole square
metres and whole metres. An exact match would be suspicious.

| | Staged | Legacy | Difference |
| --- | --- | --- | --- |
| Baseline units | 16,045.7269 | 16,045.6896 | **0.000232%** |
| Post-intervention units | 15,281.4052 | 15,281.3517 | **0.000350%** |
| Net change | -4.763397% | -4.763509% | **0.000112 percentage points** |

**Pass: 34,846 rows, each priced on both sides.**

**The generator must give each planted tree a condition, and each enhancement
a better condition than the baseline.** Otherwise the metric prices that row
at zero with no error.

## 9. Which step covers which claim

| Step | Claim | Screenshot |
| --- | --- | --- |
| 1. Open in QGIS | None, a sanity check | Baseline and post-intervention side by side |
| 2. Template buttons | 5, in the template | The message bar report and time for each button |
| 3. Convert to legacy, and open in the legacy template | 1, 5 | The legacy template open on the site |
| 4. CSVs and consolidation | 1, 5 | 3,105 rows against 3,020 |
| 5. Metric workbook | 5 | Tab A-1 filled |
| 6. Round trip | 1, 4 | The counts, unchanged |
| 7. The service | 5 | The upload that timed out |
| 8. Claims 2 and 3 | 2, 3 | The two check summaries |
