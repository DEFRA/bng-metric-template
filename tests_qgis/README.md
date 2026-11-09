# tests_qgis

Tests of the template's behaviour **as QGIS applies it**: the default
expressions, the locked and greyed-out fields, the shape constraint, the paste
lineage, the text widths and the buttons. They need PyQGIS, so they run inside the
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
| `EnhancedTrees` | An existing tree can be Enhanced to a better condition; the same condition, another size, a newly planted tree, a tree already in Good condition or an irreplaceable tree is refused, and marking an Enhanced tree irreplaceable clears Enhanced; the only better condition fills itself in |
| `IrreplaceableTrees` | A surveyed tree's Irreplaceable Habitat starts blank and takes Yes or No; a planted tree's is always No |
| `AdvanceOrDelay` | A table cell cannot leave both timing values above 0, on area habitats, hedgerows and trees; on a saved hedgerow or watercourse row, `N/A` or `Habitat already in target condition` from an older file is cleared when the row is edited, and does not blank a year in the other column |
| `TheForm` | Picking one timing value greys out the other; Retained greys out proposed significance; distinctiveness and baseline significance are locked |
| `EveryRowNeedsAShape` | A row with no shape breaks the hard constraint, so a mistaken paste is refused |
| `PasteLineage` | A feature with exactly a baseline feature's shape gets its `Parent Ref` and `parent_uuid`; a new shape gets neither |
| `TextLimits` | The fields have the declared widths; typing stops at 99 characters in `Habitat Ref` and at 999 in `Comment` on every habitat layer, and at the site detail widths; a longer value from outside the form is cut to the width when an edit of the row is saved |
| `RefButtons` | `Tidy PI refs after splitting` adds a letter up to 99 characters and names a ref that has no space for it; `Rename a ref` refuses a new ref over 99 characters, and with one of 99 keeps the lettered refs, names them and updates `Parent Ref` |
| `CopyBaselineButton` | The Copy baseline to post-intervention button, run headless, links every baseline hedge as Retained |
