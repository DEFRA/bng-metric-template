# Templates

The two QGIS templates that the converter reads and writes. They are kept here
so that the code and the formats it targets have the same version history.

| Folder | Template | Role |
| --- | --- | --- |
| `bng-service/` | BNG Service Habitat Mapping | The staged format. `old_to_new.py` writes it and `new_to_old.py` reads it |
| `legacy-ne/` | Net Gain Habitat Mapping | The Natural England template, not changed. `new_to_old.py` writes it and `old_to_new.py` reads it |
| `bng-service-labels/` | BNG Service Habitat Mapping - Labels | `bng-service/` with a label on every habitat feature. Built by `development/tools/build_labels_template.py`; never edited by hand. For testing with users whether labels help |
| `bng-service-ukhab/` | BNG Service Habitat Mapping - UKHab symbology | `bng-service/` with the map styles of `legacy-ne/`. Built by `development/tools/build_ukhab_template.py`; never edited by hand. For internal use until the styles are cleared for public use |

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
- **Area units.** An area habitat's `Area` is in hectares in the BNG Service
  template and in whole square metres in legacy. `gpkg_common.py` converts in
  both directions. A vertical area habitat's `Area` is in hectares too, an
  estimate the surveyor types in. `Length` is in metres in both.
- **Vertical area habitats.** Only the BNG Service template has them, so
  the legacy GeoPackages cannot hold them. The GIS import tool CSVs can:
  conversion to legacy writes them in `Habitats.csv`.
- **Comments.** The BNG Service template has a `Comment` on every habitat
  layer, baseline and post-intervention. Legacy has one comment column on
  each layer of each file, `Comment` on habitats and trees and `Comments` on
  hedgerows and rivers. Each stage's comments go to the file of that stage,
  with the lineage references after them, and come back without them.
- **Enhanced trees.** The BNG Service tree list offers `Enhanced` for an
  existing tree, to a better condition only, as the Statutory Metric allows.
  The legacy list offers only `Retained` and `Lost`, so conversion to legacy
  writes `Enhanced` as it is, and the legacy template shows it in brackets.
- **Irreplaceable habitat.** The BNG Service template records it on area
  habitats, vertical area habitats and individual trees. Legacy has no
  column for it, so conversion to legacy cannot carry it, and conversion back
  leaves it blank where either answer is possible.

## Using a template

**Copy the folder and work in the copy.** A template that is opened and saved
in place changes.

`bng-service/BNG Service template - User Guide.docx` is the user guide, including
the four attribute-table buttons, the paste of baseline features and the plugin.

## The UKHab symbology copy

**`bng-service-ukhab/` is the BNG Service template with the map styles of
the Natural England template:** its extended UKHab colours and patterns. It is a separate folder so that `bng-service/` can stay as
it is until the styles are cleared for public use. Its GeoPackage, reference
lists, forms, buttons and rules are those of `bng-service/`, byte for byte,
so the service reads a file from either template in the same way.

**It is built, not edited.** After any change to `bng-service/`, build it
again and commit the result:

```sh
python3 development/tools/build_ukhab_template.py          # rebuild
python3 development/tools/build_ukhab_template.py --check  # is it in step?
```

`tests/test_ukhab_template.py` fails while the committed copy is out of step.

### What it takes from the Natural England template

| BNG Service layer | Natural England style |
| --- | --- |
| Area Habitats Baseline, Post-Intervention | `Habitats Baseline EDIT ME`, `Habitats Proposed EDIT ME`: 133 habitat types, drawn at 60% opacity with a 0.26 mm outline |
| Hedgerows Baseline, Post-Intervention | `Hedgerow Baseline EDIT ME`, `Hedgerows Proposed EDIT ME` |
| Watercourses Baseline, Post-Intervention | `Watercourse Baseline EDIT ME`, `Watercourse Proposed EDIT ME` |
| Individual Trees Baseline, Post-Intervention | `Individual tree Baseline (EDIT ME) copy`, `Individual tree Proposed (EDIT ME) copy` |
| Red Line Boundary | `Red Line Boundary` |

Each layer group also gets the Natural England **Graphics (VIEW ONLY)**
group: Condition, Distinctiveness and Retention, for the baseline and the
post-intervention where Natural England has them. Each one is a read-only
layer on the same GeoPackage table as a data layer. The groups start
switched off.

### Differences from the Natural England styles

These are deliberate. Each follows from a difference between the templates:

- **List numbers.** Natural England styles `4. Fairly Poor` and
  `1. Created`. The BNG Service template stores `Fairly Poor` and `Created`,
  so each value and rule is changed to the words.
- **No `Lost` styles.** The BNG Service template records a loss by leaving
  the feature out of the post-intervention layer. The `Lost` symbols of the
  hedgerow, watercourse and tree styles are dropped.
- **Area habitat `Created` uses the Natural England `Lost` symbol.** The
  Natural England area list pairs `Lost` with `To be created`: the habitat
  is lost and a new one created. That is a BNG Service `Created` row. The
  Natural England area retention style has no `Created` symbol of its own.
- **Baseline trees.** Natural England draws a baseline tree only when its
  `Category` is `Existing`. The BNG Service baseline layer has no `Category`:
  every baseline tree exists. The rule for an existing tree with incomplete
  details becomes the catch-all rule.
- **No labels.** Natural England labels its hedgerows with their UKHab code
  from a joined field, but its project has no join, so the labels never
  show. The copy takes no labels. `bng-service-labels/` tries labels of its
  own.
- **`Individual tree Retention (VIEW ONLY)`.** The BNG Service project
  already has a reference list layer named `Individual tree Retention`, as
  has the Natural England one, which holds that name twice.
- **Enhanced trees.** The Natural England tree style has rules for
  `Created`, `Retained` and `Lost` only, as its list offers no `Enhanced`, so
  an Enhanced tree was not drawn. `style_enhanced_trees.py` gives both BNG
  Service templates an `Enhanced` rule for each `Retained` one: the same
  shape and size, in the purple Natural England's tree retention view gives
  `Enhanced`.
- **The view-only groups start switched off.** Natural England has them
  on, under the data layers.

### Gaps

Each of these is open. None of them changes what the GeoPackage holds.

| Gap | Where | Why | What would close it |
| --- | --- | --- | --- |
| **Vertical area habitats keep the BNG Service style** | Vertical Area Habitats layers | Natural England has no such layers. Its area style has fills for the five vertical habitats, but they are polygon fills and these layers are lines | A line style for the five habitats, if one is wanted. No Condition, Distinctiveness or Retention views either |
| **No Master layers** | All groups | Natural England keeps baseline and proposed values on one row, and its `Master` layers draw the proposed habitat over the whole site. The post-intervention layers do that job here | None needed |
| **No realigned watercourse layers** | Watercourses | Natural England keeps watercourses enhanced by realignment in a table of their own, `Water course enhancement through meanders`. The BNG Service template records them on Watercourses Post-Intervention as `Enhanced by Realignment`, which its style already draws in one symbol. Their condition and distinctiveness are not drawn on their own | Rules for `Enhanced by Realignment` by condition and distinctiveness, if wanted |
| **A watercourse with a blank Enhancement Type is not drawn on its Proposed Condition and Distinctiveness views** | Watercourse Graphics | The Natural England rules ask for an Enhancement Type that is not `Enhanced by Realignment`. A blank value is neither, so the rule fails. The data layer has a catch-all rule and still draws it | A catch-all rule on each view |
| **No `Styles/` folder of `.qml` files** | Folder | Natural England ships a `Styles/` folder for a surveyor to load by hand. Its styles name joined fields, such as `Habitat Fixed Criteria - pre_Baseline Distinctivness`, that no BNG Service layer has | Not needed: every style is in the project |
| **The user guide does not show the view-only groups** | `BNG Service template - User Guide.docx` | The copy carries the BNG Service guide unchanged | A section on the copy, once the styles are cleared |
| **Public use of the styles is not cleared** | The whole copy | The extended UKHab styles are fine for internal use. Their use in a published template is to be confirmed | Clearance, then a decision on whether `bng-service/` takes them |

## The labelled copy

**`bng-service-labels/` is the BNG Service template with a label on every
habitat feature.** It is for testing with users whether labels help, so
`bng-service/` stays without them. Like the UKHab copy, it is built, and its
GeoPackage, lists, forms, buttons and styles are those of `bng-service/`:

```sh
python3 development/tools/build_labels_template.py          # rebuild
python3 development/tools/build_labels_template.py --check  # is it in step?
```

| Layers | Label | Example |
| --- | --- | --- |
| The five baseline layers | `Habitat Ref`, grey and italic | `AH-004` |
| The five post-intervention layers | `Habitat Ref` and the Retention Category, black and bold | `AH-004-2 (Enhanced)` |
| Red Line Boundary | None | |

**QGIS leaves out a label that would hide another, so each label may move:**
anywhere inside its area, around its tree, or to either side of its line.
Where the two stages compete for room, the post-intervention label wins: it
names the feature and says what happens to it. So on a kept tree, where the
two labels would sit on the same point, the baseline label is often left
out. Some labels show only when zoomed in.

**A surveyor turns the labels of a layer off and on** in the Layers panel:
right-click the layer and select **Show Labels**. **Layer Labeling Options**
on the Label toolbar, and the Labels tab of the layer's properties, change
them. The setting is saved with the project. It is the `labelsEnabled` of
the layer: QGIS 3.42.1 was checked to load each label and read its setting.

It takes its styles from `bng-service/`. To try labels with the UKHab styles
too, build it from `bng-service-ukhab/` instead.
