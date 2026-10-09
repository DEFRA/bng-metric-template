# tests_qgis

Tests of the template's behaviour **as QGIS applies it**: the default
expressions, the locked and greyed-out fields, the shape constraint, the paste
lineage and the Copy baseline button. They need PyQGIS, so they run inside the
official `qgis/qgis` Docker image, at QGIS 3.42.1, the version the template is
built in. The standard-library tests in `tests/` cover everything that does
not need QGIS.

Each test opens a fresh copy of `templates/bng-service/` in a temporary
folder, so the template itself is never written.

## Run them

From the root of the repo, with Docker running:

```sh
docker run --rm -v "$PWD":/repo:ro -w /repo \
  -e QT_QPA_PLATFORM=offscreen -e PYTHONDONTWRITEBYTECODE=1 \
  qgis/qgis:3.42.1 \
  python3 -m unittest discover -s tests_qgis -t . -v
```

The image is about 2.6 GB on first pull. The run takes about 20 seconds.
`.github/workflows/tests.yml` runs the same tests on every pull request, with
the image pinned by digest.

## What they cover

| Class | What it checks |
| --- | --- |
| `TheProject` | The project opens, every layer is valid, and the data layers are empty |
| `FilledColumns` | New rows get Low significance and N/A spatial risk; distinctiveness follows the habitat type; a single allowed condition or Irreplaceable Habitat answer fills itself in |
| `RetainedSignificance` | A Retained row stays Low, whether set to High or cleared; a Created row can be High |
| `Comments` | Every habitat layer, on both stages, saves a comment and lets the form edit it |
| `EnhancedTrees` | An existing tree can be Enhanced to a better condition; the same condition, another size or a newly planted tree is refused; the only better condition fills itself in |
| `AdvanceOrDelay` | A table cell cannot leave both timing values above 0, on area habitats, hedgerows and trees |
| `TheForm` | Picking one timing value greys out the other; Retained greys out proposed significance; distinctiveness and baseline significance are locked |
| `EveryRowNeedsAShape` | A row with no shape breaks the hard constraint, so a mistaken paste is refused |
| `PasteLineage` | A feature with exactly a baseline feature's shape gets its `Parent Ref` and `parent_uuid`; a new shape gets neither |
| `CopyBaselineButton` | The Copy baseline to post-intervention button, run headless, links every baseline hedge as Retained |
