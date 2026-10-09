# BNG Template Convert: a QGIS plugin

The plugin has three tools for a site drawn in the **BNG Service habitat
mapping template**. They fill the Statutory Biodiversity Metric workbook, and
convert the site to and from the older Natural England template. The tools run
inside QGIS, with no internet connection.

---

## Before you start

**Two tools write into a file that you supply, and that file must be empty.**
Keep one clean copy of each, and give the tool a new copy for each run.

| Tool | Clean copy it needs |
| --- | --- |
| **Export to the Statutory Metric** | A blank Statutory Metric workbook, as downloaded. The tool refuses a workbook that holds habitats, and a filled workbook cannot be emptied |
| **Convert from legacy template** | An unopened copy of the whole BNG Service template folder. Filling a used GeoPackage mixes two sites |

**Save your edits first.** The tools read the GeoPackage from disk, and stop
with the names of any layers that have unsaved edits.

**The tools read and write the current BNG Service template only.** Its
tables are `Area Habitats`, `Hedgerows`, `Watercourses`, `Individual Trees`
and `Vertical Area Habitats`, each as `Baseline` and `Post-Intervention`.
Each holds its reference in `Habitat Ref`. A file or template with the older
table names (`Habitats Baseline`, `Trees Baseline`) is refused.

**Strategic significance is `Low` or `High` in the template.** Natural England
and the metric use a wording instead. The tools convert as below.

| BNG Service | Natural England and the metric |
| --- | --- |
| `Low` | *Area/compensation not in local strategy/ no local strategy* |
| `High` | *Formally identified in local strategy*; for trees *Within area formally identified in local strategy* |
| Blank | *N/A* for a hedgerow or watercourse type of *To be created* or *N/A*, and for a newly planted tree; blank elsewhere |

---

## Install the plugin

1. Open QGIS 3.22 or later.
2. Select **Plugins** → **Manage and Install Plugins...** → **Install from
   ZIP**.
3. Select **`bng_template_convert.zip`**, then **Install Plugin**. Accept the
   warning about an untrusted source.

The **Plugins** menu and the **Processing Toolbox** (`Ctrl+Alt+T`) then show
**BNG Template Convert** with three tools. To upgrade, install the new zip. If
the menu does not change, uninstall the plugin, install it again and restart
QGIS.

---

## Export to the Statutory Metric (Excel)

**This tool fills a copy of the Statutory Biodiversity Metric workbook
directly from the habitat layers.**

| Field | Value |
| --- | --- |
| BNG Service GeoPackage | Your site, usually `Layers/BNG Service Layers.gpkg` |
| Blank Statutory Metric workbook | **A clean copy** of `The_Statutory_Metric_Macro_Enabled_1.0.4.xlsm` or `The_Statutory_Metric_Macro_Disabled_1.0.4.xlsx` |
| Filled metric workbook to write | Any location. The file keeps the extension of the blank |
| Merge rows with matching values | See below |

**Both versions of the metric give the same result.** The calculation does not
use the macros. A `Macro_Disabled` blank gives an `.xlsx` with no macro prompt.

**The tool fills on-site tabs A, B and C** for area habitats, hedgerows and
watercourses. Each baseline feature gets a baseline row. Each Retained or
Enhanced part gets its own row. What does not continue into post-intervention
gets one more row, which the metric counts as lost. The creation, enhancement
and watercourse encroachment values are filled to match.

**A watercourse that continues keeps its surveyed length.** Re-meandering
makes a channel longer but does not add to the baseline.

**A part-finished site can be exported.** The baseline tabs always hold the
whole baseline. A feature not yet in post-intervention counts as lost.

**A blank value in a layer stays blank in the metric.** The log lists each one
by layer and column. The metric then leaves that row out of its totals, or
shows *Check Data*.

**The tool writes the irreplaceable Yes or No flag on each on-site baseline
habitat row,** from the `Irreplaceable Habitat` column. Without the flag the
metric shows *Confirm irreplaceable habitat status*. A flag that disagrees
with the habitat type gives *Irreplaceable habitat* or *Cannot be
Irreplaceable*. Watercourses and hedgerows have no flag in the template.

**Individual trees go on the area habitat sheets,** after the area habitats,
as the metric holds them: broad habitat *Individual trees*, habitat type
*Urban tree* or *Rural tree*. The size is the tree helper's area for the size
class, times `Count` (User Guide, Table 15: Small 0.0041 ha, Medium 0.0163,
Large 0.0366, Very large 0.0765). An Enhanced tree keeps its baseline size
class, because the metric does not record the growth of a kept tree. Its
enhancement goes on the enhancement sheet. The log names an Enhanced tree whose
proposed condition is not better than its baseline condition: the metric gives
that row *Error - No enhancement* and no units.

**Comments go into the *User comments* column of each sheet.** A baseline row
has its baseline feature's comment. A Retained part adds its own comment after
it, as `Post-intervention: ...`. An Enhanced part's comment goes on its
enhancement row, and a Created part's on its creation row. Merging rows keeps
every distinct comment. A comment longer than an Excel cell holds is cut short,
and the log says so.

**You must fill these parts of the metric by hand:**

- the off-site tabs
- the **Irreplaceable Habitats** sheet. The template does not record the
  habitat name or the bespoke compensation agreement.

**Open the result in Excel and let it recalculate.** Macros and sheet
protection are kept. A message about trusted document settings is expected.

**A large site is written as several numbered workbooks.** Each sheet holds
248 rows, and each enhancement tab 246. Each workbook is a complete metric for
its part of the site. An enhancement stays in the workbook of the parcel that
it improves. **Add the unit totals across all the workbooks**, because the net
gain percentage of one workbook covers only its part.

**Merge rows with matching values** works like the import tool's *Consolidate
Data* button. Rows that differ only in size become one row, and no total
changes. It fits a large site into fewer workbooks, but it removes the audit
trail for each parcel, so it is off by default. Irreplaceable habitat is never
merged with other habitat.

---

## Convert to legacy template (for the older service)

**This tool splits the BNG Service GeoPackage into the baseline and
post-intervention GeoPackages of the older service.** It can also write the
three CSV files that the Excel GIS import tool reads.

| Field | Value |
| --- | --- |
| BNG Service GeoPackage | Your site |
| Folder to write into | Any folder |
| What to produce | **Legacy GeoPackages**, **GIS import tool CSVs**, or both |
| Record lineage in comments | Leave ticked |

**Read the warnings.** Vertical area habitats have no legacy layer, so their
units are missing from a legacy calculation. The irreplaceable flag has no
legacy column, so it is lost.

**`Habitat Ref` becomes `Parcel Ref`,** or `Tree Ref` for trees. A hedgerow,
watercourse or tree cut from a parent takes the parent's reference, because
legacy matches it to the baseline by reference.

**Comments are carried to both legacy files.** Each baseline and
post-intervention feature's `Comment` goes to the comment column of the same
stage. Legacy calls it `Comment` on habitats and trees and `Comments` on
hedgerows and rivers.

**Record lineage in comments** writes the parent reference of each feature to
the legacy comment column, after the feature's own comment. The reverse tool
uses it to restore the links, and takes it out of the comment again.

**An Enhanced tree is written as `Enhanced`.** The Statutory Metric allows a
tree's condition to be enhanced, but the legacy template's tree list offers
only `Retained` and `Lost`, so the legacy template shows the value in
brackets. The log names the trees.

**Some drop-down values get the Natural England list number.** The BNG Service
template stores a condition as `Fairly Poor`. The legacy template stores it as
`4. Fairly Poor`. The tool adds the number to conditions, watercourse retention
categories and riparian encroachment. It takes the number from the legacy
template's own drop-down lists, for the same habitat or watercourse type.
There are three exceptions:

- `Created` on an existing watercourse becomes `4. Created`. The legacy list
  does not offer this value, so the legacy template shows it in brackets. Its
  fourth option for an existing watercourse is `4. Lost`.
- A watercourse loss row that the tool adds is written as `Lost`. The legacy
  list offers it only as `4. Lost`, so the legacy template shows it in
  brackets.
- A tree's proposed condition gets no number, because the legacy template
  stores the words alone.

A value that already has a number is not changed. In the import tool CSVs,
conditions and retention categories have no number, because the import tool
reads the words alone. Riparian encroachment keeps its number in the CSVs.

**The CSVs hold no individual trees**, because the import tool cannot read
them. Type trees into the metric by hand, or use *Export to the Statutory
Metric*, which writes them.

**The CSVs hold each post-intervention feature's own comment.** Baseline
comments are in the legacy baseline GeoPackage only, and the log says how many.
*Merge rows* replaces the comments of merged rows with a note of how many
parcels the row holds, and the log says how many comments that replaced.

**A part-finished site can be converted.** The older service refuses a
post-intervention file that does not cover the red line boundary, and the log
names the missing parcels. The CSVs always give a complete baseline: each
parcel not yet in post-intervention gets a *Lost* row.

**To open a converted file in the legacy QGIS template,** copy the whole
legacy template folder, one copy for each stage. Put the file in the `Layers`
folder of the copy, and rename it `Net Gain Habitat Mapping Layers.gpkg` to
replace the empty file.

---

## Convert from legacy template (into the BNG Service template)

**This tool joins a legacy baseline file and post-intervention file into one
BNG Service GeoPackage.**

| Field | Value |
| --- | --- |
| Legacy baseline GeoPackage | The baseline file |
| Legacy post-intervention GeoPackage | The post-intervention file, or blank |
| Existing template GeoPackage to fill | **A clean copy** of `Layers/BNG Service Layers.gpkg` in the template |
| ...or write a new GeoPackage here | Blank when you fill a template |

**Fill a clean copy of the whole template folder,** then open its project to
see the habitats with the template styles and drop-down lists.

**The tool links only the parents it can prove,** from matching references and
lineage comments. It leaves the other links blank for the service to work out
from the shapes. The log gives the number of links.

**Each linked feature records the shape of its parent** in `parent_geom`, at
three decimal places, as the template's buttons do. The service compares that
shape with the baseline, and warns when a baseline feature has changed since.

**The tool takes the list number off drop-down values,** such as
`4. Fairly Poor`, because the BNG Service template stores the words alone.

**`Parcel Ref` and `Tree Ref` become `Habitat Ref`.**

**Strategic significance becomes `Low` or `High`:**

- Every baseline row is `Low`. The log names each row whose legacy value was
  something else.
- On a post-intervention row, *Baseline Strategic Significance* is `Low` where
  the row has a baseline habitat, and blank where it has none.
- *Proposed Strategic Significance* follows the table above. *Location
  ecologically desirable but not in local strategy* has no place in the
  template, so it is left blank, and the log names the rows. *N/A* is left
  blank.

**Spatial risk category is `N/A` on every post-intervention row.** The log
names each row whose legacy value was something else.

**The tool fills the blanks that the template fills itself:** distinctiveness
from the habitat type, a condition where the habitat allows only one, and
Irreplaceable Habitat where the habitat allows only one answer. It reads these
from the template's own lists.

**The target template must have the current table names.** The tool writes
only the columns that the template has. The log names each column that the
template lacks, whose values are not written, and each column of the template
that the tool leaves blank.

**After the conversion, you must** fill in Irreplaceable Habitat where the
habitat allows either answer, choose `Low` or `High` where significance was
left blank, and add any vertical area habitats, such as green walls.

---

## Read the log

Each tool writes to the **Log** tab of its dialog:

- **Rows**: the number of features in each layer or sheet.
- **Notes**: intended changes, such as loss rows added for legacy.
- **Warnings**: items to examine before you use the result. A warning is not
  a failure, and a warning that needs action says so.

---

## Problems

| What you see | What to do |
| --- | --- |
| *These layers have unsaved edits* | Save and stop editing, then run again |
| *already holds habitat data* | Use a new copy of the workbook |
| *is not a readable Statutory Metric workbook* | Select the metric, not the `.xlsb` GIS import tool |
| *Cannot find the ...* | The file has moved |
| Fewer than three tools in the menu | Uninstall the old plugin, install this one and restart QGIS |
| `Check Data` in the metric | The *CHECK THIS* lines in the log name each blank value. If none do, report it |

---

## Command line

The plugin uses only the Python standard library. The conversion scripts also
run without QGIS:

```
python3 new_to_old.py INPUT.gpkg -o OUT_DIR [--format gpkg|csv|both] [--consolidate] [--carry-lineage]
python3 old_to_new.py --baseline BASE.gpkg [--post-intervention PI.gpkg] -o OUT_DIR [--into TEMPLATE.gpkg]
python3 to_metric.py  INPUT.gpkg --metric METRIC.xlsm|.xlsx -o OUT [--consolidate]
```

Add `--dry-run` to `new_to_old.py` or `old_to_new.py` to see the report and
write nothing.

The two conversion scripts read the drop-down lists of both templates, and
`old_to_new.py` also reads the BNG Service distinctiveness, condition and
irreplaceable lists. Run from the repository, they read them from
`templates/`. The plugin zip carries a copy of each list, which
`build_plugin.py` adds.
