# Templates

The two QGIS templates that the converter reads and writes. They are kept here
so that the code and the formats it targets have the same version history.

| Folder | Template | Role |
| --- | --- | --- |
| `bng-service/` | BNG Service Habitat Mapping | The staged format. `old_to_new.py` writes it and `new_to_old.py` reads it |
| `legacy-ne/` | Net Gain Habitat Mapping | The Natural England template, not changed. `new_to_old.py` writes it and `old_to_new.py` reads it |

## Differences that matter to the converter

- **Stages.** A legacy row holds the baseline and the proposed values in
  `Baseline *` and `Proposed *` columns. The BNG Service template has separate
  baseline and post-intervention layers. One legacy file becomes a pair, and a
  pair becomes one file.
- **Lineage.** The BNG Service template records two hidden columns on each
  post-intervention row: `parent_uuid`, the `feature_uuid` of the baseline
  feature, and `parent_geom`, the shape of that feature as WKT at 3 decimal
  places. Legacy has no lineage. Conversion to legacy drops it, and can keep
  the references in comments. Conversion back rebuilds both columns from the
  references: `parent_geom` is the shape of the baseline feature that the
  reference names.
- **List labels.** The BNG Service reference lists hold the words only, as
  `Fairly Poor`. Legacy holds a numbered form, as `4. Fairly Poor`.
  Conversion from legacy removes the number. Conversion to legacy adds it
  back, as the legacy template's own list gives it for that row, with three
  exceptions. `Created` on an existing watercourse becomes `4. Created`,
  which the legacy list does not offer: its fourth option there is
  `4. Lost`. A watercourse loss row that the conversion adds is written as
  `Lost`, which the legacy list offers only as `4. Lost`. A tree's proposed
  condition gets no number, because legacy stores it as words. The hedgerow lists have no numbers in either template.
- **Area units.** `Area` is in hectares in the BNG Service template and in
  whole square metres in legacy. `gpkg_common.py` converts in both directions.
  `Length` is in metres in both.
- **Vertical area habitats.** Only the BNG Service template has them, so
  conversion to legacy cannot carry them.
- **Comments.** The BNG Service template has a `Comment` on every habitat
  layer, baseline and post-intervention. Legacy has one comment column on
  each layer of each file, `Comment` on habitats and trees and `Comments` on
  hedgerows and rivers. Each stage's comments go to the file of that stage,
  with the lineage references after them, and come back without them.
- **Enhanced trees.** The BNG Service tree list offers `Enhanced` for an
  existing tree, to a better condition only, as the Statutory Metric allows.
  The legacy list offers only `Retained` and `Lost`, so conversion to legacy
  writes `Enhanced` as it is, and the legacy template shows it in brackets.

## Using a template

**Copy the folder and work in the copy.** A template that is opened and saved
in place changes.

`bng-service/HOW TO USE THIS TEMPLATE.md` is the surveyor's guide, including
the four attribute-table buttons and the paste of baseline features.
