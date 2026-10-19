# Maintaining the template

The BNG Service QGIS habitat mapping template and a QGIS plugin that converts
sites into and out of it. Also a generated example site at the scale of a
Nationally Significant Infrastructure Project (NSIP), and a generator for
small sites.

The conversion code uses only the Python standard library. Only the plugin
needs QGIS.

## What is where

| Folder | What it holds |
| --- | --- |
| `templates/bng-service/` | **The template.** An empty QGIS project, its reference lists, and `HOW TO USE THIS TEMPLATE.md`, the surveyor's guide |
| `templates/legacy-ne/` | The Natural England template as it ships |
| `plugin/` | **The plugin.** Source, `build_plugin.py`, and `plugin/README.md`, the installation and usage guide |
| `reference/` | The Statutory Metric workbooks, the Excel GIS import tool and the user guide. Every reference list in the template is checked against these |
| `scale-test-nsip/` | The example site: generator, claim checks, `README.md`, `VERIFICATION.md` and the generated output |
| `site-generator/` | **The site generator.** Builds a small synthetic site from inputs such as the number of parcels, the area and the location. See its `README.md` |
| `development/tools/` | Tools that maintain the template. Nothing here is needed to use it |

**This file is for maintainers.** Users get `HOW TO USE THIS TEMPLATE.md`
with the template and the example site, and `plugin/README.md` with the
plugin.

## The plugin

**Edit the code only in `plugin/bng_template_convert/`.** It is the only
copy. The build zips it with `plugin/README.md`, so the plugin carries its
guide. The build also copies into the zip each drop-down list that the
converter reads from `templates/bng-service/CSV References` and
`templates/legacy-ne/CSV References`, and fails if one is missing. A change to
one of those lists therefore needs a new build, and the new zip must be sent
to the users of the plugin.

```sh
cd plugin && python3 build_plugin.py   # -> plugin/dist/bng_template_convert.zip
```

To install, in QGIS select **Plugins** > **Manage and Install Plugins...** >
**Install from ZIP**, then select the zip and **Install Plugin**. Accept the
untrusted source warning. The tools show under **Plugins** > **BNG Template
Convert** and in the **Processing Toolbox**.

**An export to the Metric and a conversion into the template each need an
empty copy of the target file.** Users most often get this wrong.

### Running the conversions without QGIS

The modules also run from the command line:

```sh
cd plugin/bng_template_convert

python3 new_to_old.py INPUT.gpkg -o OUT_DIR
        [--format gpkg|csv|both] [--consolidate] [--merge-irreplaceable]
        [--carry-lineage] [--dry-run]

python3 old_to_new.py --baseline BASE.gpkg [--post-intervention PI.gpkg]
        -o OUT_DIR [--into TEMPLATE.gpkg [--force]] [--dry-run]

python3 to_metric.py INPUT.gpkg --metric METRIC.xlsm|.xlsx -o OUT
        [--consolidate] [--allow-occupied]
```

## What conversion to legacy loses

The converter gives a warning for each of these:

- **Vertical area habitats are not carried.** Legacy has no layer for them,
  so a legacy calculation leaves out their units.
- **Irreplaceable habitat flags are dropped.** Legacy has no column for them,
  so the converter lists area habitats in `Irreplaceable habitats.csv` and
  names irreplaceable trees in a warning.
- **Lineage keys are dropped**, unless lineage is recorded in comments. The
  plugin records it by default. The command line needs `--carry-lineage`.
- **Split features are flagged.** When a baseline hedgerow, watercourse or
  tree becomes several features, each converted row repeats the parent
  reference. Legacy expects one row for each reference, so its result can
  differ.
- **Enhanced trees keep `Enhanced`.** The Natural England tree list offers
  only `Retained` and `Lost`, so their template shows it in brackets.
- **Baseline comments are not in the import tool CSVs,** which hold one row
  for each post-intervention feature. Merging CSV rows replaces their
  comments with a note.
- **Loss rows copy the parent shape.** Legacy cannot record a removal by
  absence, so the conversion writes a loss row with the baseline shape. The
  length removed is exact. The stretch removed is not known. A tree is kept
  or felled whole: each legacy tree row has a `Count` of 1.

Conversion back from legacy drops the loss rows, because the template records a
removal by leaving the feature out.

**The BNG Service template stores list labels without a list number**, as
`Fairly Poor`. The Natural England template stores the numbered form, as
`4. Fairly Poor`. Conversion from legacy removes the number. Conversion to
legacy adds it back from the legacy list, for the same habitat or watercourse
type, with three exceptions:

- `Created` on an existing watercourse becomes `4. Created`. The Natural
  England list does not offer this value: its fourth option for an existing
  watercourse is `4. Lost`.
- A watercourse loss row that the conversion adds is written as `Lost`. The
  Natural England list offers it only as `4. Lost`.
- A tree's proposed condition gets no number, because the Natural England
  template stores the words alone.

The Metric workbook holds only the words. In the import tool CSVs, conditions
and retention categories have no number, but riparian encroachment keeps it.
Hedgerow lists have no numbers.

**Template areas are in hectares**, as in the Metric. Legacy areas are whole
square metres. The conversion changes the unit in both directions.

## The example site

`scale-test-nsip/hs2-phase2a-subsection/` is a generated rail corridor at NSIP
scale: 34,847 features across 11 layers, of which 11,554 are baseline area
habitats. It is a full copy of the template with data in it.

**The site is generated, not committed.** It is approximately 100 MB. The
generator rebuilds it to the same bytes in approximately seven seconds. Run
these from this folder:

```sh
python3 scale-test-nsip/generator/generate.py                  # whole corridor
python3 scale-test-nsip/generator/generate.py --fraction 0.12  # one section
```

The 12% section fits in one Metric workbook and goes to
`scale-test-nsip/hs2-phase2a-subsection-12pc/`.

**The template is always the source.** Each run copies the project file, the
reference lists and the surveyor's guide from `templates/bng-service/`.

**Every value in the site is one that a drop-down offers.** The generator does
not use the drop-downs, so each run ends with a check of every value against
the filtered list that QGIS shows for that row. The run fails on a value that
is not in the list. To check any site folder:

```sh
python3 scale-test-nsip/generator/dropdown_check.py <site folder>
```

`scale-test-nsip/VERIFICATION.md` is the runbook for the template, each
plugin tool and the service, with the measured results. The checks it uses are
in `scale-test-nsip/verify/`.

**Never edit the site by hand.** Change the template or the generator, and
generate again.

## Maintenance tools

**The template buttons are Python stored in the `.qgz` project XML.** Edit
them only with the tools in `development/tools/`, which change no other byte.
A project saved from QGIS loses the button short titles.
`development/tools/README.md` describes each tool.

**The same tools keep the field settings of the template in step.** Each
tool that writes the project first saves a timestamped copy beside it. Move
the copies out of `templates/bng-service/` before a new example site is
generated: the first run of the generator copies the whole folder.

| Change | Tool |
| --- | --- |
| Edit the code of a button | `patch_actions.py` |
| Rename the buttons or change their order | `rename_actions.py` |
| Add a column to the layers | `add_field.py`, with `--gpkg`. It adds the column to the empty tables and copies its settings from a layer that has it |
| Remove a column from the layers | `drop_field.py`, after the column is dropped from `Layers/BNG Service Layers.gpkg` and no button reads it |
| Change a filtered drop-down, or a field of a post-intervention layer | `reset_stale_dropdowns.py`, then `set_paste_defaults.py` |
| Add an `Order` column to a reference list | `order_dropdowns.py` |
| Change which habitats the Vertical Area Habitats layers offer | The lists in `CSV References/Vertical Area Habitats/`, then `limit_vertical_habitats.py`, then `reset_stale_dropdowns.py`. Keep those habitats out of the area habitat lists in `CSV References/Habitats/` (Options, Distinctiveness and Condition); the tests check it |
| Change a reference list of either template | `plugin/build_plugin.py`, then send the new zip to the users of the plugin |
| Test a button against a site | `run_actions_headless.py`, with the Python that comes with QGIS |

**A paste gives a post-intervention row the same lineage as the Copy
button.** The lineage comes from default value expressions on the
post-intervention layers. `set_paste_defaults.py` and
`reset_stale_dropdowns.py` write them from the rules in `paste_lineage.py`.
The parent is the one baseline feature whose shape is exactly the shape of the
pasted feature.

**A hedge whose condition gets worse is `Created`, on purpose.** It is the
same hedge, in effect retained in a worse condition. But a retained habitat
cannot get worse, and no other Retention Category fits, so the Metric team
asks ecologists to record it as `Created`. The Metric then counts the whole
baseline hedge as lost and the new hedge as created. The Metric team also
asks for it to be created 30 or more years in advance, so
`set_field_rules.py` fills a blank **Habitat created in advance/years** with
`30+` on an area, vertical area or hedgerow row that is `Created`, has a
baseline type, and keeps that type. A change of type, such as built-on
ground, gets no default, and nor does a watercourse, which follows the
Metric's own creation rules. On any other area, vertical area or hedgerow
row it clears `30+`, so the value cannot stay behind on a row changed, for
example, to `Enhanced`, and credit it with gains it has not made. `30+`
fits only a habitat that gets worse: a creation 30 years in advance would
be baseline habitat. This rests on the Metric team confirming it. `DegradedAdvance` in
`tests_qgis/test_template_behaviour.py` checks it. The surveyor keeps the
copied row, so the hedge keeps its link to its baseline parent, and its own
hedge type. That is why `Hedgerow Habitat Options - post.csv` offers each
hedge type its own type when `Created`, and not `N/A`. With `N/A`, a
surveyor could save a Created hedge with no type, which the Metric cannot
count; a lost hedge is recorded by deleting its row. It is an edge case for
the Metric calculation. Keep those rows: `DegradedHedgeListsTest` in
`tests/test_reference_lists.py` checks them, and `DegradedHedgerowTest` in
`tests/test_to_metric.py` checks what the Metric makes of such a hedge.

**An existing watercourse set to `Created` keeps its own type, too.** The
Metric team asks for an existing watercourse to be recordable as `Created`,
as a hedge is. `Watercourse Habitat Options - post.csv` therefore offers each
watercourse type its own type when `Created`, and not `N/A`, which has no
condition or encroachment and which the Metric cannot count. Its own type
offers every condition and encroachment of the type, so the encroachment can
be worse than the baseline's. Unlike a hedge, the template has no recipe for
a watercourse that gets worse: the surveyor applies the Metric's own
watercourse rules, including its years created in advance. A culvert offers
only `Poor` and no encroachment, so a `Created` culvert is never worse.
`DegradedWatercourseListsTest` in `tests/test_reference_lists.py` checks the
lists, and `CreatedExistingWatercourseTest` in `tests/test_to_metric.py`
checks what the Metric makes of such a watercourse.

After any change to the template, check that the seven generated settings and
the template version record are in step. Each command gives "no change
needed" on a template that is in step, and exits with 1 otherwise:

```sh
P="templates/bng-service/BNG Service Habitat Mapping.qgz"
python3 development/tools/set_field_rules.py --check "$P"
python3 development/tools/reset_stale_dropdowns.py --check "$P"
python3 development/tools/set_paste_defaults.py --check "$P"
python3 development/tools/order_dropdowns.py --check "$P"
python3 development/tools/allow_blank.py --check "$P"
python3 development/tools/require_shape.py --check "$P"
python3 development/tools/limit_vertical_habitats.py --check "$P"
python3 development/tools/set_template_version.py --check "templates/bng-service/Layers/BNG Service Layers.gpkg"
```

Then generate the example site again. Its run ends with `dropdown_check.py`.

## Template version

**The template's GeoPackage records which format it follows, and which
version.** The BNG service reads the record to know how to read a file, and
refuses a file that has none, or a version it does not support. A surveyor's
file keeps the version of the template copy it started from.

The record is one row of the GeoPackage metadata extension, referenced to the
whole GeoPackage:

| Column of `gpkg_metadata` | Value |
| --- | --- |
| `md_scope` | `dataset` |
| `md_standard_uri` | `tag:defra.gov.uk,2026:bng-metric/gpkg-format` |
| `mime_type` | `application/json` |
| `metadata` | `{"format": "bng-service", "version": "1.0"}` |

To read it, select the `metadata` of the row with that `md_standard_uri`.
GDAL shows it as the dataset metadata item `GPKG_METADATA_ITEM_1`.
`read_template_version()` in `plugin/bng_template_convert/gpkg_common.py`
reads it, and refuses a file that records it more than once.

**Another tool can write a file in this format.** It must write this record,
as well as the template's tables, columns and values. The service checks the
whole file, not only the record: the record says which version the file
claims to be, and the service checks the file against that version.

**It is not a row of its own in `gpkg_extensions`.** GDAL, and so QGIS,
warns about an extension that it does not know: on every open of the file
when its scope is `read-write`, and on every edit when it is `write-only`.
GDAL knows the metadata extension, gives no warning, and keeps the record
when the layers are edited or when it writes its own metadata.

**The version is `TEMPLATE_VERSION` in `gpkg_common.py`.** The plugin writes
it into each GeoPackage that Convert from legacy creates, and
`set_template_version.py` writes it into the template. The generators copy
the template, so their sites carry it too.

**Raise the version for every change to what the GeoPackage holds:** a
table, a column, a geometry type, a value that a drop-down offers, or the
meaning of a value. A change only to the project, such as a button, a style
or a form, does not change it.

- Raise the second number (1.0 to 1.1) for an addition that a reader of the
  earlier version can ignore, such as a new column that can be blank.
- Raise the first number (1.4 to 2.0) for any other change.

To raise it:

1. Change `TEMPLATE_VERSION` in `plugin/bng_template_convert/gpkg_common.py`.
2. Write it into the template:

   ```sh
   python3 development/tools/set_template_version.py "templates/bng-service/Layers/BNG Service Layers.gpkg"
   ```

3. Raise the plugin version, with a changelog line, and rebuild the plugin.
4. Tell the BNG service team. The service refuses the new version until it
   supports it.
