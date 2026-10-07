# tools

Tools that maintain the template and check what it produces. Nothing here is
needed to use the template or the plugin.

| File | What it does |
| --- | --- |
| `qgz_actions.py` | Reads and writes the button code in a `.qgz` without a change to any other byte. The other tools use it |
| `rename_actions.py` | Removes the list numbers from the button names and puts the buttons in the order a user needs. Safe to run again |
| `patch_actions.py` | Makes text edits to the button code. Each edit is an exact piece of old text and its replacement, made in every button with that name. Safe to run again |
| `drop_field.py` | Removes the configuration of a field from the layers of a project: the widget, alias, policies, default, constraints, table column and form settings. Use it after a column is dropped from the GeoPackage. Safe to run again |
| `run_actions_headless.py` | Runs a button outside QGIS against a real site, so that its logic can be tested |
| `reset_stale_dropdowns.py` | Gives each filtered drop-down a rule that clears its value when an earlier choice makes the value invalid. Without the rule, QGIS keeps the old value in brackets. On a post-intervention layer the rule also fills Retention Category and the Proposed values of a pasted feature. Safe to run again |
| `set_paste_defaults.py` | Gives the lineage columns of each post-intervention layer the default values that make a pasted feature get the lineage the Copy button writes. Safe to run again |
| `paste_lineage.py` | The rules that the two tools above share: which baseline layer each post-intervention layer is copied from, and the expressions that find the parent of a pasted feature |
| `allow_blank.py` | Gives every drop-down a blank choice: the `<NULL>` entry on a Value Map, and "Allow NULL value" on a Value Relation. Safe to run again |
| `set_field_rules.py` | Fills in and locks the columns a surveyor never chooses: Distinctiveness from the habitat type, Baseline Strategic Significance (`Low`) and Spatial risk category (`N/A`). Makes Proposed Strategic Significance a `Low`/`High` drop-down that starts at `Low`, is never blank, and is `Low` and greyed out on a Retained row. Greys out years in advance while years of delay is above 0, and the other way round. Safe to run again. Run it before `reset_stale_dropdowns.py` |
| `rename_field.py` | Renames a field wherever the project names it as a whole, quoted name: settings, expressions and button code. Rename the GeoPackage column too. Safe to run again |
| `rename_table.py` | Points the layers at a GeoPackage table under its new name. Rename the table with GDAL too, which renames its index and triggers. Safe to run again |
| `require_shape.py` | Gives the ref column of each data layer a hard constraint that the row has a shape, so a paste of rows with no shape (what Copy Layer leaves on the clipboard) opens the Fix Pasted Features dialog instead of adding blank rows. Safe to run again |
| `order_dropdowns.py` | Makes each drop-down show its items in the order of the `Order` column of its reference list. Safe to run again |
| `check_metric_lookups.py` | Checks each condition in a filled Metric workbook against the lookup rows of the same workbook |
| `check_legacy_template.py` | Checks the recorded findings about the Natural England template against `templates/legacy-ne/`. Put a fresh download there to check them again |

## Editing the buttons

**The four attribute-table buttons are Python stored as XML attributes in the
`.qgz`.** Do not save the project through QGIS to change them. QGIS drops the
button short titles and rewrites 3 MB of project.

`qgz_actions.py` changes the attribute in place. A round trip of all 20
action bodies gives the original bytes. Two rules are necessary for this:

- QGIS does not escape `>` in an attribute.
- An action body ends at the first raw double quote after `action="`. Only
  some actions have an `<actionScope>` child.

Each tool that writes a project first saves a copy beside it, named
`.backup-YYYYMMDD-HHMMSS`. A second copy made in the same second gets `-2`
added, and so on, so that no copy replaces another. Git ignores these copies.
The NSIP generator copies the whole template folder when it makes a new
working copy. Move the copies out of `templates/bng-service/` once a change is
checked.

**The same button is stored once for each layer.** The copies differ only in
the layer names and in a few lines. `patch_actions.py` therefore takes each
edit once and makes it in every copy. An old text that is not found exactly
once in a copy stops the run before anything is written. An edit whose new
text is already in place counts as made.

## Running the tools

Run these from the root of this repo:

```sh
python3 development/tools/rename_actions.py "templates/bng-service/BNG Service Habitat Mapping.qgz"
python3 development/tools/reset_stale_dropdowns.py "templates/bng-service/BNG Service Habitat Mapping.qgz"
python3 development/tools/patch_actions.py "templates/bng-service/BNG Service Habitat Mapping.qgz" edits.py
python3 development/tools/drop_field.py "templates/bng-service/BNG Service Habitat Mapping.qgz" "<field>"
python3 development/tools/set_paste_defaults.py "templates/bng-service/BNG Service Habitat Mapping.qgz"
python3 development/tools/order_dropdowns.py "templates/bng-service/BNG Service Habitat Mapping.qgz"
python3 development/tools/set_field_rules.py "templates/bng-service/BNG Service Habitat Mapping.qgz"
python3 development/tools/rename_field.py "templates/bng-service/BNG Service Habitat Mapping.qgz" "<old>" "<new>"
python3 development/tools/rename_table.py "templates/bng-service/BNG Service Habitat Mapping.qgz" "<old>" "<new>"
python3 development/tools/allow_blank.py "templates/bng-service/BNG Service Habitat Mapping.qgz"
python3 development/tools/require_shape.py "templates/bng-service/BNG Service Habitat Mapping.qgz"
python3 development/tools/check_metric_lookups.py "Filled metric.xlsm"
python3 development/tools/check_legacy_template.py
```

The edits file for `patch_actions.py` is Python that defines `EDITS`, a
list of `(button name, old text, new text)` tuples. The edits are made in list
order.

`drop_field.py` removes the field from every layer that configures it. Add
`--layer "<layer name>"` once for each layer to limit it. Drop the column from
`Layers/BNG Service Layers.gpkg` as well. The tool does not change button
code, so edit any button that reads the field first. It names any other
element that still refers to the field, and does not remove it.

`set_field_rules.py`, `reset_stale_dropdowns.py`, `set_paste_defaults.py`,
`order_dropdowns.py`, `allow_blank.py` and `require_shape.py` take `--check`
before the project. With `--check` they write nothing, list what they would
change, and exit with 1 if a change is needed. A template that is in step
gives "no change needed" from all six. Run them in that order:
`reset_stale_dropdowns.py` manages only the filtered drop-downs that
`set_field_rules.py` leaves.

## Defaults for a pasted feature

A surveyor can fill a post-intervention layer with the Copy button, or by
copying baseline features and pasting them into the layer. The button writes
the lineage itself. A paste goes through QGIS, which fills each column from
its default value expression. The defaults make a paste write the same values
as the button:

- `Habitat Ref`, `Parent Ref`, `parent_uuid` and `parent_geom` come from the
  parent. `parent_geom` is the parent's shape as WKT at 3 decimal places,
  the same text that the button writes.
- `Retention Category` is `Retained`.
- Each `Proposed` value is the value of its `Baseline` twin, when
  `Retention Category` is `Retained`.
- On trees, `Category` is `Existing`. On hedgerows and watercourses,
  `Baseline Length` is the length rounded to 3 decimal places.

The `Baseline` values, `Irreplaceable Habitat`, `Count` and the typed `Area`
of a vertical area habitat need no default. A paste matches columns by name,
so it carries every column that the two layers share.

The parent is the one baseline feature whose geometry is exactly the same as
the pasted feature: the same vertices in the same order. The expressions find
it with `overlay_equals` and refer to the baseline layer by its id, so a
renamed layer does not break them. When no baseline feature is the same, or
more than one is, the feature gets none of these values. A new feature drawn
exactly on a baseline feature, for example a tree placed by snapping, is the
same shape and gets the lineage. The surveyor guide tells the user to place a
replacement tree or hedge off the old one, or to turn snapping off.

The values are written only while a feature is created. QGIS fills the
columns of a new feature in column order, and a default sees NULL in its own
column and in every later one. `parent_uuid` is the second-last column of
each table, so it is NULL while the feature is created. The Retention and
Proposed defaults apply only while `parent_uuid` is NULL, so a value that the
surveyor clears later stays clear. The lineage columns are never recomputed on
an edit. A moved vertex makes the shape differ from the parent, and the lookup
then gives NULL.

QGIS keeps one default for each column. The filtered drop-downs already have
the reset rule of `reset_stale_dropdowns.py`, so that tool puts the pre-fill
into its rule: `if("F" IS NULL, <pre-fill>, <reset>)`. `set_paste_defaults.py`
writes the other columns. It refuses to replace a default that it did not
write, and then writes nothing. A `Proposed` pre-fill also needs
`"Retention Category" = 'Retained'`, because Copy writes the `Baseline` twins
only beside `Retained` (`paste_lineage.prefill_gate`). Run both tools after
any change to the fields of a post-intervention layer.

**The pasted feature gets no lineage when its shape changes on the way in.**
Avoid Overlap trims a polygon pasted over an existing post-intervention
feature. A paste from a layer in another coordinate reference system is
transformed. In both cases the shape no longer equals the baseline feature.

Three limits follow from the design:

- A hedgerow, tree, watercourse or vertical area habitat pasted twice gets
  two rows with the same `parent_uuid`. The service refuses a hedgerow, tree
  or vertical area habitat whose rows add up to more than the parent. It
  cannot tell a second watercourse row from a split. An area habitat pasted
  twice is different: Avoid Overlap trims the second paste to an empty
  geometry, which matches no baseline feature, so QGIS adds an empty row with
  no lineage.
- A paste from the baseline is not the only way that QGIS creates a feature
  column by column. Split Features, Duplicate Feature and a paste of a
  post-intervention row do the same: a paste into the same layer goes through
  Duplicate Feature, and a paste from another layer or file goes through the
  paste path. `parent_uuid` is NULL while each of them runs. So when the new
  shape equals one baseline feature, the gate is true, and a pre-fill that
  applies on update replaces the value that the row brought with it. The
  result depends on the type:
  - On hedgerows, trees and watercourses, `Retention Category` is itself such
    a pre-fill. The row becomes `Retained` and its filtered `Proposed` values
    take their `Baseline` twins. No column before `Retention Category` tells
    these cases apart from a paste from the baseline.
  - On area and vertical area habitats, the default of `Retention Category`
    applies only to a blank value, so the row keeps its own. An `Enhanced` or
    `Created` row then keeps its `Proposed` values. A `Retained` row takes the
    `Baseline` twins, which is what Copy writes.

  Typical cases are an unmoved enhanced hedgerow that is duplicated, or a
  copied hedge split at the same vertex as its baseline hedge. The surveyor
  guide tells the user to paste only from the Baseline layer of the same
  project, and to check `Retention Category` and the `Proposed` values after
  a split or paste whose result matches a baseline feature.
- A row with a NULL `parent_uuid` whose shape equals one baseline feature,
  such as a row linked only by `Parent Ref`, gets a blank filtered value
  filled on its next edit.

The behaviour was measured on QGIS 3.42.1 on macOS, with the desktop Paste
Features command. The split and duplicate cases were measured with the PyQGIS
calls that those commands use (`splitFeatures`, `duplicateFeature`). The test
for "being created" depends on the order in which QGIS fills the columns. It has not been measured on the long term releases or
on Windows.

## The order of a drop-down

QGIS shows the items of a drop-down sorted by their key, unless the drop-down
is set to sort by a column of its reference list. The Natural England
template numbers its condition, retention and riparian encroachment labels, as
`1. Good`, and the numbers set the order. The BNG Service template holds the
words only, so without help the items sort alphabetically, with `Fairly Good`
before `Good`. Each such list has an `Order` column. It holds the position of
each item in a sort by the numbered label, and the rows of the list are in
that order.
`order_dropdowns.py` sets each drop-down that reads such a list to sort by the
column. The column is read from the reference list, so the tool needs
the `CSV References` folder beside the project.

How QGIS uses the setting depends on the version:

| QGIS | Order shown |
| --- | --- |
| 3.44 and later | The `Order` column |
| 3.42 | The order of the rows in the file, measured on macOS. QGIS 3.42 accepts the setting but does not read the column |
| 3.40 and earlier | Alphabetical, because these versions do not have the setting |

## Testing a button

`run_actions_headless.py` needs the Python that comes with QGIS, because it
loads the project through PyQGIS. Its arguments are the project, the start of
the button name, and the layer:

```sh
/Applications/QGIS.app/Contents/MacOS/bin/python3 \
    development/tools/run_actions_headless.py \
    "<site>/BNG Service Habitat Mapping.qgz" "Copy baseline" \
    "Hedgerows Post-Intervention" --answer no
```

`--answer` sets the reply to any question that the button asks. The runner
replaces the message bar, the progress dialog and the question box. A change
to a button can then be tested against a site of 11,000 parcels in seconds,
not by hand.

**A button saves as it runs and has no undo. Run it only against a copy of a
site.**
