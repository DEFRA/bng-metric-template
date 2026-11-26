# tests

Tests of the converters, the generators, the plugin build and the template
files. They use the Python standard library only, as the code they test does,
so they need no install and no QGIS. The tests of the template's behaviour
in QGIS itself are in `tests_qgis/`.

Every test works on copies in a temporary folder. Nothing under `templates/`
or `reference/` is written, and the plugin build goes to a temporary folder
instead of `plugin/dist/`.

## Run them

From the root of the repo, with Python 3.11 or later:

```sh
python3 -m unittest discover -s tests -t .          # everything
python3 -m unittest tests.test_old_to_new           # one module
python3 -m unittest discover -s tests -t . -v       # each test by name
```

The whole run takes about 20 seconds. Most of it is the site generator and
the Metric workbook, which several modules build in their set-up. Nothing is
slow enough to need skipping.

## What they cover

| Module | What it checks |
| --- | --- |
| `test_reference_lists.py` | The vertical area habitat lists hold only the five habitats counted by vertical area, with their distinctiveness and the five conditions, and the area habitat lists hold none of them; an existing tree can be Enhanced, to a better condition only and at its own size, type and setting, or Created, in any condition and at its own size, type and setting; every drop-down list the converter reads exists in both templates; significance lists are `Low` and `High`; list numbers come off and go back on, with the `Created` exception; Low and High map to and from the Natural England wording; blanks fill from the template's lists, and only Blanket bog, Coastal sand dunes and Limestone pavement must be irreplaceable |
| `test_template_schema.py` | The template GeoPackage, read-only: the exact table names, one `Habitat Ref` per table, a `Comment` on every habitat table, Irreplaceable Habitat on both tree tables, the lineage columns on the right stage, no `parent_checksum`, every table empty, the converters' own schemas in step with it, the template version record, and no extension GDAL does not know |
| `test_text_widths.py` | The template declares the width of each text column from `TEXT_LIMITS`: 99 for refs, 999 for comments, no limit on the lineage columns; a width keeps TEXT affinity; Convert from legacy declares the same types; every value of every drop-down list fits its column; and `set_text_widths.py` declares every width, keeps the rows, every other table and the integrity of the file, stops on a text column not in the list, and its `--check` writes nothing; an error during the rewrite, or a copy that fails its checks, leaves the file byte for byte as it was and removes the copy; a value over its limit only because of spaces at its start and end is not over it |
| `test_gpkg_spec.py` | The GeoPackage specification: every table and column of the template, geometry types and the coordinate system, widths from `TEXT_LIMITS`, the version record, the lineage columns on their stage, drop-downs that name a described list and the columns they depend on, fixed lists without the blank marker, defaults, locked columns and the shape rule from the project; a lineage column on the wrong stage refused; two runs give the same bytes; the committed `spec/` is up to date, a stale copy is reported with its differences, and `--check` writes nothing |
| `test_markdown_to_confluence.py` | The converter that publishes the specification: headings, blockquotes, inline code, links and bold, tables, escaped pipes and angle brackets, continued list items, and the published page with its banner |
| `test_drop_to_be_created.py` | `drop_to_be_created.py` removes `To be created` from the baseline type drop-down of the 4 hedgerow and watercourse layers only, leaves every other entry and field alone, and changes nothing when run again |
| `test_limit_vertical_habitats.py` | `limit_vertical_habitats.py` keeps only the vertical broad habitats on the vertical layers and drops Intertidal hard structures from the area layers, stops on a broad habitat name it does not know or a name to keep that is gone, and changes nothing when run again |
| `test_template_version.py` | The template version record: written once, replaced not repeated, other metadata kept, the metadata tables created where missing, a record that is not JSON or is there twice refused, none in Convert to legacy output; and `set_template_version.py`, whose `--check` writes nothing |
| `test_project_xml.py` | The `.qgz` project XML: an editable `Comment` on every habitat layer, a blank choice on every drop-down, the locked and filled columns, Low on Retained rows, advance and delay offering years only and not both, the shape constraint, and Irreplaceable Habitat filling itself, the vertical layers offering only Urban and Intertidal hard structures, and the area layers not offering Intertidal hard structures. Then each maintenance tool's `--check` gives "no change needed" |
| `test_new_to_old.py` | Convert to legacy: the legacy layers and columns, `Parcel Ref` and `Tree Ref`, numbered labels, the significance wording, whole square metres, Lost rows, comments on both stages, lineage after the comment, Enhanced trees, the comments the CSVs cannot hold, the vertical area habitat warning, the import tool CSVs, and the refusal of a file with the old table names or no habitat tables |
| `test_old_to_new.py` | Convert from legacy into a copy of the template: Low on baseline rows, Medium left blank with a warning, Low on Retained rows, spatial risk `N/A`, a text advance or delay left blank and named, distinctiveness and Irreplaceable Habitat filled, the refusals, the template version in a new file and a warning for a target without it, a legacy meanders row Enhanced by Realignment, a value the template offers, a warning for an intertidal hard structure on the area habitats, a warning for comments a template from before the post-intervention `Comment` cannot hold, a value over its column's limit written whole and named with its length, cut to 99 characters in the warning, no warning for a value over its limit only because of spaces at its start and end, and a round trip that keeps references, values, areas, lengths, comments and Enhanced trees |
| `test_to_metric.py` | Export to the Metric, `.xlsx` and `.xlsm`: a valid workbook, the habitats, references, conditions and wording on the right sheets, sizes that add up, individual trees on the area habitat sheets with an Enhanced tree on the enhancement sheet, every comment on the right sheet, enhancement rows in step with their baseline rows, the warnings for an Enhanced tree the metric refuses, a text advance or delay from an older file left blank and named, a re-meandered watercourse enhanced by its whole drawn length with no loss, split into a retained and an enhanced section or shared between Enhanced parts by their drawn lengths, and a shorter one losing the rest (BMD-1212), every sheet's 350 rows ending on the blank workbook's last data row, a refusal of a filled workbook unless allowed, of a blank workbook from an earlier release with fewer rows, of the GIS import tool, and of a file with the old table names or no habitat tables |
| `test_ukhab_template.py` | The UKHab symbology copy: the committed copy is the one `build_ukhab_template.py` builds, its GeoPackage and lists are those of `bng-service/`, each layer differs only in its map style, the view-only layers are read-only on the right tables and their names are unique, the vertical layers keep their style, no style keeps a list number or `Lost`, every value a drop-down offers has a symbol or a rule, the distinctiveness views included, no layer is labelled, every renderer keeps its symbols and the red line is an outline, every tree Retention Category, Enhanced included, is drawn in both templates, each Retained tree rule has an Enhanced rule of the same shape and size in purple, `style_enhanced_trees.py` adds back an Enhanced rule that is missing, its `--check` fails on that project and a run writes it with a backup, `template_copy.differences` finds a changed, a missing and an extra file, and each maintenance tool's `--check` passes on it |
| `test_labels_template.py` | The labelled copy: the committed copy is the one `build_labels_template.py` builds, its GeoPackage and lists are those of `bng-service/`, each layer differs only in its labels, every habitat layer is labelled with its ref, and its Retention Category on the post-intervention, the red line is not, and each maintenance tool's `--check` passes on it |
| `test_build_plugin.py` | The plugin zip holds the package, the guide and every list the converter reads, its version matches the changelog, and the installed plugin reads its own lists |
| `test_generators.py` | A 5% section of the NSIP site builds, passes `dropdown_check.py` and repeats to the byte; the check names a bad value, and an area habitat on a vertical layer; the small-site generator repeats to the byte, gives what was asked for, tiles the red line and carries the template version; with `--watercourses` and `--vertical` it gives those layers, with every retention category on each layer and a loss on each linear and tree layer, a split watercourse whose stretches are runs of their parent's line and name their parent, a fixed path through one CORE edge that keeps exactly the stretches either side, and legacy and Metric outputs the converters write from them; it says when there is no room for the watercourses asked for, and without them it gives neither |

`support.py` holds the paths and the helpers the modules share.

## Known bugs

A test marked `@unittest.expectedFailure` records a fault in the code it
tests, explained in a comment above it. The run reports it as an expected
failure. When the fault is fixed the run reports an unexpected success: then
remove the marker.
