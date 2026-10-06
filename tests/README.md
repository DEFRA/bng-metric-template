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
| `test_reference_lists.py` | Every drop-down list the converter reads exists in both templates; significance lists are `Low` and `High`; list numbers come off and go back on, with the `Created` exception; Low and High map to and from the Natural England wording; blanks fill from the template's lists, and only Blanket bog, Coastal sand dunes and Limestone pavement must be irreplaceable |
| `test_template_schema.py` | The template GeoPackage, read-only: the exact table names, one `Habitat Ref` per table, the lineage columns on the right stage, no `parent_checksum`, every table empty, and the converters' own schemas in step with it |
| `test_project_xml.py` | The `.qgz` project XML: a blank choice on every drop-down, the locked and filled columns, Low on Retained rows, advance or delay but not both, the shape constraint, and Irreplaceable Habitat filling itself. Then each maintenance tool's `--check` gives "no change needed" |
| `test_new_to_old.py` | Convert to legacy: the legacy layers and columns, `Parcel Ref` and `Tree Ref`, numbered labels, the significance wording, whole square metres, Lost rows, lineage in comments, the vertical area habitat warning and the import tool CSVs |
| `test_old_to_new.py` | Convert from legacy into a copy of the template: Low on baseline rows, Medium left blank with a warning, Low on Retained rows, spatial risk `N/A`, distinctiveness and Irreplaceable Habitat filled, the refusals, and a round trip that keeps references, values, areas and lengths |
| `test_to_metric.py` | Export to the Metric, `.xlsx` and `.xlsm`: a valid workbook, the habitats, references, conditions and wording on the right sheets, sizes that add up, a refusal of a filled workbook unless allowed, and of the GIS import tool |
| `test_build_plugin.py` | The plugin zip holds the package, the guide and every list the converter reads, its version matches the changelog, and the installed plugin reads its own lists |
| `test_generators.py` | A 5% section of the NSIP site builds, passes `dropdown_check.py` and repeats to the byte; the check names a bad value; the small-site generator repeats to the byte, gives what was asked for and tiles the red line |

`support.py` holds the paths and the helpers the modules share.

## Known bugs

A test marked `@unittest.expectedFailure` records a fault in the code it
tests, explained in a comment above it. The run reports it as an expected
failure. When the fault is fixed the run reports an unexpected success: then
remove the marker.
