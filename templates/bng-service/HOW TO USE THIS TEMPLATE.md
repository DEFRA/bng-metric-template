# Building a BNG habitat map in QGIS

This guide is for a surveyor who has not used QGIS before. Do the parts in
order. The result is one GeoPackage that holds a baseline, a post-intervention
map copied from it, and a created habitat that crosses two baseline parcels.

The guide is written for **QGIS on Windows**, version 3.22 or later. The long
term release from qgis.org is the safe choice. Menu names are from QGIS 3.44.

---

## What you build

```
Red Line Boundary          the site boundary
      |
<type> Baseline            what is there now      PR-1, PR-2
      |   (copy)
<type> Post-Intervention   what it becomes        PR-1, PR-2, PI-POND
```

**You draw the baseline once, then copy it.** Each post-intervention feature
starts as an exact copy, and it keeps a link to the baseline parcel it came
from. The copy button copies every parcel. Copy and paste makes the same copy
of the parcels that you select (Part 4).

**There are five habitat types.** Each type has a Baseline layer and a
Post-Intervention layer, and all of them are in one GeoPackage:

| Layer group | Drawn as | Size column | Unit | Filled in by |
| --- | --- | --- | --- | --- |
| **Area Habitats** | polygon | `Area (ha)` | hectares | QGIS |
| **Vertical Area Habitats** | line | `Area (ha)` | hectares | you |
| **Hedgerows** | line | `Length (m)` | metres | QGIS |
| **Watercourses** | line | `Length (m)` | metres | QGIS |
| **Individual Trees** | point | `Count` | trees | you |

Areas are in hectares, the unit of the Statutory Metric. The measure tool also
gives hectares. One hectare is 10,000 m², so a parcel of 100 m by 100 m shows
`1`.

Two types need an explanation:

- **Vertical Area Habitats** are green walls and intertidal hard structures.
  You draw the line along the base of the structure. The area that counts is
  the vertical face, which QGIS cannot calculate from a line, so you type it.
- **Individual Trees** are points and have no size to measure. `Count` is the
  number of trees that one point represents.

This guide uses **Area Habitats** as the example. The other four types use the
same buttons and the same copy action. Part 9 gives the differences.

---

## Part 1: Open the project and set it up

### 1.1 Open the project

**Keep the folder on a local disk, not in OneDrive.** QGIS writes to the map
file while you work. A folder that synchronises to the cloud can copy or lock
the file during a save, and this can damage a day of mapping.

**Use a short path, such as `C:\BNG\`.** Windows refuses a file path longer
than 260 characters. The longest path inside this folder is already 85
characters.

1. Double-click **`BNG Service Habitat Mapping.qgz`**.
2. In the **Select Transformation** window, click **OK**.
3. Ignore the yellow bar *Cannot use preferred transform*. It is not a fault.
4. Right-click a layer that has data, then click **Zoom to Layer**.

The map opens on the whole United Kingdom until you do step 4.

The **Layers** panel on the left holds these groups:

- **Red Line Boundary**, at the top.
- One group for each habitat type. The **Post-Intervention** layer is above
  the **Baseline** layer. Turn off the top layer to see the baseline. The line
  and point groups are above **Area Habitats**, so polygons do not hide them.
- **Reference data**, at the bottom. These tables supply the dropdown lists.
  Keep the group collapsed and do not edit it.

**Every list in Reference data agrees with version 1.0.4 of the Statutory
Biodiversity Metric workbook.** This includes habitat names, distinctiveness
bands, the conditions each habitat allows, hedgerow and watercourse types,
encroachment values, tree sizes, spatial risk and strategic significance.
Natural England's own template keeps the Metric 4.0 bands for five habitats.

### 1.2 Turn on the toolbars

1. Click **View → Toolbars**.
2. Tick **Digitizing**, for drawing and editing.
3. Tick **Advanced Digitizing**, for splitting and carving.
4. Tick **Snapping**, for making shapes meet exactly.

### 1.3 Find the template buttons

The template adds four buttons. They are in the **attribute table**, not in
the right-click menu of the Layers panel.

1. In the Layers panel, right-click the layer, then click **Open Attribute
   Table**. Or select the layer and press `F6`.
2. On the toolbar of the attribute table window, find the right-hand end.
3. Click **Actions**, the second button from the end. The last button docks
   the window, so do not click it by mistake.

| Layer | Buttons, in the order you use them |
| --- | --- |
| Each **Post-Intervention** layer | `Copy baseline to post-intervention`, `Tidy PI refs after splitting`, `Refresh from baseline` |
| Each **Baseline** layer | `Rename a ref (updates post-intervention)` |

A layer with no buttons, such as a reference table, shows no **Actions**
button.

**After a button runs, the attribute table goes behind the main QGIS window.**
Click the table on the task bar to show it again. A click that hits the main
window by mistake can open QGIS Help.

**Every button saves as it goes, and there is no undo.** Use a copy of the
GeoPackage the first time you use a button on real data.

**`Rename a ref (updates post-intervention)`** is the safe way to rename a
parcel after the copy. It changes the baseline ref and every post-intervention
row that points at it, including split suffixes such as `PR-1a`.

**`Refresh from baseline`** applies later baseline edits to the
Post-Intervention layer. For each row copied or pasted from a baseline
feature:

- It refreshes the locked `Baseline …` values, even when the shape did not
  move.
- It moves your shape with the baseline when no guess is needed. A baseline
  feature moved as a whole moves your row by the same amount. Rows cut from a
  reshaped area parcel are trimmed to fit inside it.
- When the shape needs a guess, it refreshes only the values and names the row
  for you to check.
- When the baseline feature is **deleted**, it clears the `Baseline …` values
  and the link. Decide if the remaining shape is `Created` or must be deleted.
- When a baseline feature has **no row**, it makes one, as the copy button
  does.
- It reports each area parcel that its rows no longer cover exactly.
- It gives each half of a **split baseline feature** its own hidden id, and
  names the new parcels. This is the only time a button edits a Baseline
  layer.

On an existing row, it changes only the `Baseline …` columns, `Parent Ref`,
the hidden record of the parent's shape and, in the cases above, the shape.
Your `Proposed …` values, `Retention Category` and `Irreplaceable Habitat` do
not change.

**A row that it moves or trims gets a new record of the parent's shape** (Part
4). A row that it names for you to check keeps the old record. The service then
gives its warning for that row on upload.

### 1.4 Turn on tracing

**Tracing makes a line follow an existing edge exactly.** Use it when a new
habitat runs along the boundary of a parcel.

1. Press `T`, or click **Enable Tracing** on the **Snapping** toolbar.
2. While you draw, click where your line joins the existing edge.
3. Click again further along that edge. QGIS adds every corner between the two
   clicks.

Without tracing, QGIS draws a straight line between your two clicks. That line
cuts corners, and where the edge bends outwards the line goes outside the
parcel. This causes the error `could not add ring: the inserted Ring is not
contained in a feature`.

> Tracing needs snapping on for the traced layer (section 1.5). Tracing turns
> itself off when too many features are on screen. Zoom in to use it.

### 1.5 Turn on snapping

**Do not skip this section.** Snapping moves a new corner onto a near corner
or edge. Without it, parcels have thin gaps and overlaps, and the areas do not
add up.

1. Click **Project → Snapping Options…**.
2. Click the **magnet** icon at the left of the bar, so that it is highlighted.
3. Set the mode to **All Layers**.
4. Set the type to **Vertex and Segment**. Some versions call it **Vertex and
   Edge**.
5. Set the tolerance to about **10 pixels**.
6. Tick **Topological Editing**, the icon of two joined polygons. A moved
   corner that two parcels share then moves in both.
7. If the option shows, tick **Avoid Overlap** for the two area habitat
   layers. QGIS then trims a new shape so it cannot overlap an existing one.

Keep this bar visible while you work.

**Snapping can link a new tree or hedge to the baseline.** A new feature that
lands exactly on a baseline feature is treated as that feature. Part 9 tells
you how to prevent this.

---

## Part 2: Draw the red line boundary

The red line is the site boundary. All habitats must be inside it.

1. In the Layers panel, click **Red Line Boundary**.
2. Click the **yellow pencil** (**Toggle Editing**) on the Digitizing toolbar.
3. Click **Add Polygon Feature**, the polygon icon with a yellow star.
4. Left-click each corner of the site. For a first test, a rough rectangle is
   enough.
5. Right-click to finish the shape.
6. Fill in the form, then click **OK**. For a first test, **Site Name** is
   enough.
7. Click the **pencil** to stop editing, then click **Save**.

| Field | What to enter |
| --- | --- |
| Site Name | The name of the site |
| Location | Where the site is |
| Survey Date | The date of the survey |
| Survey Details | Other facts about the survey |
| Mapped by | Your name |
| Company | Your organisation |
| Base Map | The map you drew over, for example aerial photography |

**These site details are on the red line boundary only.** The habitat forms
have only a **Comment** field for each parcel.

The boundary shows as a red outline with no fill, so the habitats inside it
stay visible.

> **If nothing draws:** the wrong layer is selected in the Layers panel. QGIS
> always draws into the highlighted layer.

---

## Part 3: Draw the baseline habitats

The baseline records what is on the site now. **Cover the whole site with no
gaps and no overlaps.**

1. Click **Area Habitats Baseline** in the Layers panel.
2. Click the **pencil** to start editing.
3. Click **Add Polygon Feature**.
4. Start the corners on the red line. Snapping puts them exactly on it.
5. Right-click to finish, then fill in the form.
6. Click **OK**.
7. Draw the next parcel against the first. Snapping locks onto the shared
   edge, so there is no gap.
8. Continue until the parcels cover the whole red line area.
9. Click the **pencil** to stop editing, then click **Save**.

| Field | What to enter |
| --- | --- |
| Habitat Ref | A label, for example `PR-1`. Each label must be different. |
| Baseline Broad Habitat Type | Select from the list, for example `Grassland` |
| Baseline Habitat Type | Select from the habitats in that broad type, for example `Modified grassland` |
| Baseline Distinctiveness | Do not enter. QGIS fills it in from the habitat type and locks it. |
| Baseline Condition | Select from the conditions that the habitat allows. When the habitat allows one condition only, QGIS fills it in. |
| Baseline Strategic Significance | Do not enter. It is always `Low`, and locked. |
| Irreplaceable Habitat | QGIS fills it in when the habitat allows one answer only: `No` for most habitats, `Yes` for Blanket bog, Coastal sand dunes and Limestone pavement. Otherwise select `Yes` or `No`. |
| Area (ha) | Do not enter. QGIS fills it in and locks it. |
| Comment | Optional notes about this parcel |

**Each list shows only the values that your earlier choices allow.** If you
change the habitat type, a condition that the new type does not allow is
cleared. Select it again. A condition that still fits stays.

**Some fields fill themselves in.** On every layer:

| Field | What QGIS does |
| --- | --- |
| Baseline and Proposed Distinctiveness | Fills in the band of the habitat type, and locks the field. Blank until you choose a habitat type. |
| Baseline Strategic Significance | Always `Low`, and locked. |
| Proposed Strategic Significance | `Low` on a new or copied row, and never blank. Change it to `High` where the site is in an area formally identified in a local strategy. On a `Retained` row it is `Low`, as the baseline is, and you cannot change it. |
| Habitat created in advance and Delay in starting habitat creation | The Metric allows one or the other. While one is above 0, the other is greyed out. To switch, set the first to `0` or blank, then pick the other. `0` and blank are both allowed. |
| Baseline and Proposed Condition | Fills in the condition when the habitat allows one only, for example `N/A - Other` for Developed land; sealed surface. You can still change it. |
| Spatial risk category | Always `N/A` on the post-intervention layers, and locked. |

The Metric has a third strategic significance, "Location ecologically
desirable but not in local strategy". The template does not offer it.

Set these in a form: the feature form, or the attribute table's form view. A
form applies the rules as soon as you pick a value. A cell of the attribute
table applies them only when you leave it, and does not grey anything out. If
both timing values end up above 0 there, QGIS blanks one of them, which may be
the one you just typed.

**Each parcel takes the Natural England UKHab colour for its habitat type.** A
parcel with an unexpected colour probably has the wrong habitat type.

### Check for gaps

1. Right-click **Area Habitats Baseline**, then click **Open Attribute Table**.
2. Add up the `Area (ha)` column.
3. Compare the total with the red line area. A smaller total means a gap.

---

## Part 4: Copy the baseline

**There are two ways to copy the baseline.** The copy button copies every
parcel. Copy and paste copies the parcels that you select. Both give a row the
same values and the same link to its baseline parcel.

### 4.1 Use the copy button

1. Right-click **Area Habitats Post-Intervention**, then click **Open
   Attribute Table**. The table is empty.
2. Click **Actions** (section 1.3).
3. Click **`Copy baseline to post-intervention`**.

A green bar at the top of the **main QGIS window** gives the number of parcels
copied. The attribute table now has one row for each baseline parcel.

**The copy button does not run while the layer is in edit mode.** Click the
pencil to stop editing, save, then click the button again.

**Each copied row gets these values:**

- **Habitat Ref**: the same as the baseline ref.
- **Parent Ref**: the baseline parcel it came from. The field is locked.
- **Retention Category**: `Retained`. It is next to the Proposed columns,
  because it describes what happens to the parcel.
- All the baseline values, which include **Irreplaceable Habitat**. The
  Proposed values start the same as the baseline values.
- On a tree, **Category** is `Existing`. On a hedgerow or a watercourse,
  **Baseline Length (m)** is the length of the baseline line.
- Two hidden columns that link the row to its baseline parcel.
  `parent_uuid` holds the hidden id of the parcel. `parent_geom` holds the
  shape of the parcel at the copy. The service uses them to find later
  baseline changes. They make a rename safe.

**The Baseline columns on a Post-Intervention layer are locked.** Only the
copy button, a paste and `Refresh from baseline` write them. You cannot change
the baseline values here by accident.

**You can run the copy button again.** It copies only baseline parcels that
have no row yet, copied or pasted, and it keeps all existing rows. The message
gives the number it skipped.

**On a layer that already has rows, the button asks first.** A missing
post-intervention row records a removal. So a baseline parcel with no row is
either a removal or a parcel drawn after the copy. The button names these
parcels:

- Click **No** if you have recorded removals.
- Click **Yes** to copy parcels that you added to the baseline after the copy.

> To start again, delete the copied rows. In the attribute table, click the
> pencil, select all rows, click the **delete** button, then save.

### 4.2 Paste baseline parcels

Use this to copy one parcel or a few, for example a parcel that you added to
the baseline after the copy.

1. In the Layers panel, click **Area Habitats Baseline**.
2. Click the **Select** tool, then click the parcel. Hold `Shift` to select
   more than one.
3. Click **Edit → Copy Features** (`Ctrl+C`).
4. In the Layers panel, click **Area Habitats Post-Intervention**, then click
   the **pencil**.
5. Click **Edit → Paste Features** (`Ctrl+V`).
6. Open the attribute table. Check that each pasted row has a `Parent Ref`.
7. Click the **pencil** to stop editing, then click **Save**.

To paste every parcel, click **Edit → Select → Select All Features**
(`Ctrl+A`) at step 2.

**Do not use Copy Layer.** Copy Layer, on the right-click menu of the Layers
panel, copies the layer's settings, not its parcels. Paste Features turns that
text into thousands of rows with no shape and every field blank. The template
refuses a row with no shape: QGIS opens the **Fix Pasted Features** dialog. Click
**Discard All**, then copy the parcels with **Copy Features**.

**A pasted parcel gets its link only when its shape is exactly the shape of
one baseline parcel.** It then gets the same values as a copied row, and
`parent_geom` records the shape at the paste. In the cases below, the pasted
row gets no link, and its `Parent Ref` stays blank:

| Case | Why there is no link | What to do |
| --- | --- | --- |
| The pasted parcel overlaps a post-intervention parcel | **Avoid Overlap** trims the pasted shape, so it is no longer the baseline shape | The ground already has a row. To bring a baseline change across, use `Refresh from baseline` (section 1.3) |
| The pasted shape is not exactly the baseline shape, for example because the other file holds a different version of the shape, or the layer is in a different coordinate reference system | The link needs the same corners, in the same order | Copy the parcel from the **Baseline** layer of this project |
| You changed the baseline parcel after you copied it | The clipboard holds the old shape | Copy the parcel again |
| Two baseline parcels have exactly the same shape | The paste cannot tell which parcel is the parent | Correct the baseline, or use the copy button (section 4.1). The button links by the hidden id, not by the shape |

**First delete the pasted row that has a blank `Parent Ref`.** The field is
locked, so the link cannot be added by hand. Then do what the table says.

**Paste only from the Baseline layer of this project.** QGIS cannot tell
where a pasted feature came from. Any pasted feature with exactly the shape of
one baseline feature is treated as a paste from the baseline, and QGIS fills
in the values of the copy button. Do not paste post-intervention rows from a
backup, from another copy of the site, or from the same layer. If such a row
is still exactly the shape of its baseline feature, for example an enhanced
parcel that was not moved, QGIS changes its values:

| Type | What QGIS changes on the pasted row |
| --- | --- |
| Hedgerows, individual trees and watercourses | **Retention Category** becomes `Retained`, and the Proposed drop-downs take the Baseline values |
| Area habitats and vertical area habitats | A `Retained` row: the Proposed drop-downs take the Baseline values. An `Enhanced` or `Created` row keeps its values |

The same change happens when **Split Features** or **Duplicate Feature** makes
a feature with exactly the shape of one baseline feature. For example, a
copied hedge is split at the same corner as its baseline hedge. If a paste of
this kind cannot be avoided, check **Retention Category** and every Proposed
value on each new row, and set them again.

**Unlike the copy button, a paste does not check for an existing row.** A
parcel that already has a row gets a second row. Delete the second row. Do not
use `Tidy PI refs after splitting` on it: that gives the two rows the
suffixes of a split, and both stay. For each type, the result of a second row
is:

| Type | Result of a second row |
| --- | --- |
| Area habitats | **Avoid Overlap** trims the second parcel to nothing. QGIS still adds a row, with no shape. |
| Hedgerows, individual trees and vertical area habitats | The service refuses the file. The rows of one baseline feature add up to more than the feature. |
| Watercourses | The service does not find it, because a watercourse can continue as two rows. Look for it yourself (Part 7). |

---

## Part 5: Make changes

**Edit only the Post-Intervention layer.** The baseline does not change after
Part 3.

Select **Area Habitats Post-Intervention**, then click the **pencil**.

### 5a. Enhance a whole parcel

1. Click the **Identify** tool, then click the parcel. Or find its row in the
   attribute table.
2. Set **Retention Category** to `Enhanced`. It is next to the Proposed
   fields.
3. Set **Proposed Habitat Type** and **Proposed Condition**.
4. Do not change the shape.

### 5b. Split a parcel

Use this when a change applies to part of a parcel.

1. Click **Split Features** on the Advanced Digitizing toolbar.
2. Start the line outside the parcel. Left-click each point.
3. End the line outside the parcel, then right-click to finish.
4. Edit each part. For example, one part stays `Retained` and the other
   becomes `Enhanced`.

The two parts keep the same `Parent Ref`, because both came from one baseline
parcel.

> The split line must cross the full parcel. A line that stops inside the
> parcel does nothing.

### 5c. Create a new habitat inside the site

A created habitat, such as a pond, takes ground from the parcels that were
there. Select the method from where the new habitat is.

**Wholly inside one parcel, with no shared edge: use Fill Ring.**

1. Click **Fill Ring** on the Advanced Digitizing toolbar.
2. Draw the pond inside the parcel, then right-click to finish.
3. QGIS cuts a hole in the parcel and fills it with a new feature.
4. Set **Habitat Ref** to a new label, for example `PI-POND`.
5. Set **Retention Category** to `Created`.
6. Set the Proposed habitat fields for the pond.

`Parent Ref` and the Baseline fields are locked and blank. This is correct: a
new shape has no baseline.

**Touching an edge of one parcel: use Split Features, not Fill Ring.** A ring
along a parcel edge makes an invalid, self-intersecting polygon. Do not use
Fill Ring here, even when QGIS accepts it.

1. Click **Split Features**.
2. Start the line outside the parcel and cross the edge.
3. Draw the inner outline of the pond, then cross the edge again.
4. Right-click to finish. The parcel becomes two features.
5. On the pond part, set **Retention Category** to `Created` and the Proposed
   fields to the pond.
6. Do not change the other part. It is the remaining baseline habitat.

The pond keeps the `Parent Ref` of the parcel. This is correct, because the
ground came from that parcel.

> If nothing happens, one end of the line was inside the parcel. Both ends must
> be outside the parcel, or exactly on its edge.

**Across two parcels: split both in one pass, then merge.** Each half of the
pond touches the shared edge, so Fill Ring cannot work.

1. Press `Ctrl+Shift+A` (**Deselect Features from All Layers**). A split cuts
   only the selected features, and it reports nothing when it cuts none.
2. Click **Split Features**.
3. Draw the full pond outline across both parcels, and finish where you
   started. Right-click to finish.
4. Check that there are four features: two pond halves and two remainders.
5. Click the **Select** tool. Hold `Shift` and click both pond halves.
6. Click **Merge Selected Features** on the Advanced Digitizing toolbar.
7. Click **Take attributes from selected feature** on one row, then **OK**.
8. Set **Retention Category** to `Created` and the Proposed fields to the pond.

Do not change the `Parent Ref` of the merged pond.

> **Do not draw the pond as a new feature on top of the parcels.** It then
> overlaps them, and the total area is more than the site. A split removes and
> replaces ground in one step. The parts add up exactly to the original
> parcels.

### 5d. Ground that is built on

1. Keep the row. Do not delete it.
2. Set **Retention Category** to `Created`.
3. Set the Proposed habitat to the new surface, for example `Developed land;
   sealed surface`.

**There is no `Lost` category.** The options are `Created`, `Retained` and
`Enhanced`. The Statutory Metric records built-on ground as creation of the
new surface. Ground inside the red line cannot disappear, so the row must stay.

**This rule is for area habitats only.** A removed hedgerow, watercourse, tree
or vertical area habitat has no replacement surface. For these, delete the
copied row. The missing row records the removal (Part 9). The service lists
all removals when it checks the file, so a row deleted by mistake shows there.

When you finish, click the **pencil**, then click **Save**.

---

## Part 6: Tidy the references

A split leaves two rows with one `Habitat Ref`.

1. Open the attribute table of **Area Habitats Post-Intervention**.
2. Click **Actions**, then **`Tidy PI refs after splitting`**.

The duplicates become `PR-1a`, `PR-1b` and so on. The order is left to right
on the map, so each run gives the same labels.

---

## Part 7: Check the numbers

Open the attribute table of each layer and compare the totals.

| Check | Expected result |
| --- | --- |
| **Area Habitats** baseline total and post-intervention total | The same. Ground cannot disappear. |
| Hedgerow, watercourse, vertical area habitat and tree totals | The post-intervention total can be smaller. The difference is what you removed, and the service lists it as removed. |
| Each post-intervention row | Has a Retention Category |
| `Created` rows | Have Proposed values. For area habitats, only a Fill Ring shape has a blank `Parent Ref`. A split, copied or pasted row keeps the parcel's `Parent Ref`. For the other types, a `Created` row always has a blank `Parent Ref`. |
| `Enhanced` rows | Have Baseline and Proposed values |
| `Retained` rows | Proposed values agree with Baseline values. A shortened hedge stays `Retained` at its new length. |
| `Retained` and `Enhanced` rows | Have a `Parent Ref`. A blank one is a paste that found no baseline feature (section 4.2). |
| Rows that share a `Parent Ref` | Are the parts of a split. Two such rows with the same size are one feature pasted twice (section 4.2). |

**Different area totals mean a gap or an overlap.** The usual cause is that
snapping was off for part of the work.

---

## Part 8: Send the file

**All layers are in one GeoPackage, `Layers/BNG Service Layers.gpkg`.** QGIS
saves your edits into it, so there is no export step. Send this one `.gpkg`
file to the service.

---

## Part 9: The other four habitat types

The procedure is the same:

1. Draw the baseline.
2. Run the copy button on the Post-Intervention layer, or paste the baseline
   features (Part 4).
3. Edit only the Post-Intervention layer.
4. Tidy the refs.

The differences follow.

### New habitats: draw them on the Post-Intervention layer

**For these four types, a habitat can be fully new.** Examples are a planted
hedge, a new channel, a planted tree and a new green wall. A new habitat has
no baseline, so you draw it directly on the Post-Intervention layer.

1. Select the **Post-Intervention** layer of the type, then click the
   **pencil**.
2. Click **Add Line Feature**, or **Add Point Feature** for trees, and draw it.
3. Give it a new **Habitat Ref**.
4. Set **Retention Category** to `Created`.
5. Fill in the Proposed fields. The Baseline fields stay blank and locked.
6. Check that **Parent Ref** is blank. It is locked. If it is filled, see
   *A new feature exactly on a baseline feature*, below.

For a vertical area habitat, type the `Area (ha)`. For a tree, type the
`Count`.

**The service accepts a `Created` row as it is.** It accepts one when the
Baseline layer is empty, because a site with no hedges can gain new ones. A
`Created` row gives no warning and is not on the list of removals. The service
does not match it to a baseline feature by overlap, so a new hedge along an
old one stays separate. The exception is a new feature that lies exactly on a
baseline feature.

**A `Retained` or `Enhanced` row over an empty Baseline layer is refused.** A
copy must have a baseline feature to copy.

**Fill in every Proposed field that the type needs:**

| Type | Proposed fields |
| --- | --- |
| Hedgerows | Proposed Hedge Type, Proposed Condition |
| Individual Trees | Proposed Tree Size, Proposed Rural or Urban Tree, Proposed Condition |
| Watercourses | Proposed River Type, Proposed Condition, Proposed Encroachment into Watercourse, Proposed Encroachment into riparian zone |

**Never draw an area habitat from nothing.** All ground inside the red line
must agree with the baseline. Cut new area habitat from the copied parcels with
Split Features or Fill Ring (Part 5c).

> If the Retention Category and Proposed lists are empty on a new feature, get
> a new copy of this template.

### A new feature exactly on a baseline feature

**QGIS links a new feature to a baseline feature that has exactly the same
shape.** It treats the new feature as a paste of the baseline feature. This
happens when snapping puts a new tree on the point of a baseline tree. It
also happens when tracing gives a new hedge every corner of a baseline hedge,
in the same order.

The new feature then gets the `Parent Ref` of the baseline feature, and
**Retention Category** `Retained`. A tree also gets **Category** `Existing`.
The service counts the baseline feature as kept, not removed. For a tree that
was felled and replaced, the loss is then never counted.

To prevent this:

- Place a replacement tree or hedge a short distance from the old one.
- Or turn snapping off, with the **magnet** icon, while you draw it.

If a new feature shows a `Parent Ref`, delete it and draw it again. The link
is locked, and it stays when you move the feature.

### Vertical Area Habitats

A vertical area habitat is a green wall or an intertidal hard structure. Draw
it as a **line** along the base of the structure.

1. Click **Add Line Feature**.
2. Left-click along the route, then right-click to finish.
3. Type the face area in **`Area (ha)`**.

**The face area is length × height ÷ 10,000.** A wall 200 m long and 2 m high
is 400 m², so type `0.04`. QGIS cannot get the height from a line, so this
field is not locked.

The other fields work as for area habitats, except removal. **For a demolished
structure, delete its copied row.** A new structure is drawn on the
Post-Intervention layer (see *New habitats*).

### Hedgerows

Draw a hedgerow as a **line**. QGIS fills in `Length (m)` and locks it.

- **Part of a hedge changes:** split it with **Split Features**. Both parts
  keep the same `Parent Ref`.
- **Part of a hedge is removed:** split off that part and delete its row.
- **A hedge is shorter but its condition is the same:** keep it `Retained`.
  Shorten the copied line with the **Vertex Tool**, or split it to the
  shorter length. A new line drawn in its place has no link to the baseline.
- **A new hedge:** draw a new line on the Post-Intervention layer (see *New
  habitats*).

**After a split, check the values of each part.** A part with exactly the
shape of a baseline hedge becomes `Retained`, with the Baseline values in its
Proposed fields (section 4.2). Set them again.

**The service calculates lost length as the baseline length minus the
remaining post-intervention length.** The Statutory Metric sheets use the same
method. The service lists the missing length as removed. Check that the list
agrees with your plan.

### Watercourses

Draw a watercourse as a **line**. QGIS fills in `Length (m)` and locks it.

**A post-intervention watercourse can leave the baseline line completely.** A
re-meandered channel moves and gets longer. This is correct.

- **A re-meandered channel:** move the copied line onto the new route with
  **Reshape Features** or the **Vertex Tool**, so that it keeps its link to
  the baseline. Set **Retention Category** to `Enhanced` and fill in
  **Enhancement Type**.
- **Do not edit `Baseline Length (m)`.** The copy button and a paste write the
  original length there. The calculation needs it after the channel moves.
- **A stretch is fully lost**, for example culverted or filled: delete its
  copied row.
- **A new channel:** draw it on the Post-Intervention layer (see *New
  habitats*).

**The service cannot measure part loss of a watercourse from the map.** A
channel can move legally, so a baseline stretch either continues or is
removed. If only part of a stretch will be lost, draw it as two baseline
features at the survey. Then you can keep or delete each part.

### Individual Trees

Draw each tree as a **point**. A point cannot be split.

1. Click **Add Point Feature**.
2. Click once at the tree.
3. Type the number of trees in **`Count`**, usually `1`.

- **A tree that stays:** `Retained`.
- **A planted tree:** add a point, set **Retention Category** to `Created`, and
  fill in only the Proposed fields. **Parent Ref** stays blank. The
  **Category** field fills in as `Newly Planted` by itself. A point exactly on
  a baseline tree is the exception (see *A new feature exactly on a baseline
  feature*).
- **A felled tree:** delete its copied row. The service lists it as removed.
- **Some trees of a point are felled:** keep the row as `Retained` and reduce
  its `Count`.
- **A tree planted where a tree was felled:** add a separate `Created` point,
  a short distance from the felled tree or with snapping off. Its `Parent Ref`
  must stay blank. The Statutory Metric also treats the two as separate.

### Layers that you do not need

Fill in only the types that are on the site. Empty layers are correct. For
example, a site with no watercourses has two empty watercourse layers.

---

## Quick reference

| Task | Tool | Toolbar |
| --- | --- | --- |
| Start or stop editing | Toggle Editing (pencil) | Digitizing |
| Draw a new shape | Add Polygon, Line or Point Feature | Digitizing |
| Move a corner | Vertex Tool | Digitizing |
| Cut a parcel in two | Split Features | Advanced Digitizing |
| Cut a hole and fill it | Fill Ring | Advanced Digitizing |
| Join two shapes | Merge Selected Features | Advanced Digitizing |
| Give a line a new route | Reshape Features | Advanced Digitizing |
| Copy selected features | Copy Features (`Ctrl+C`) | **Edit** menu |
| Paste features into the selected layer | Paste Features (`Ctrl+V`) | **Edit** menu |
| Make shapes meet exactly | Enable Snapping (magnet) | Snapping |
| Follow an existing edge | Enable Tracing (`T`) | Snapping |
| See the values of a feature | Identify | Attributes |
| Run a template button | Actions | Right-hand end of the **attribute table** toolbar |
| Undo | `Ctrl+Z` | Works while you edit |

---

## Problems and solutions

**The fields are plain text, with no dropdowns.** The layer is not in edit
mode. Click the yellow pencil or press `Ctrl+E`.

**The dropdowns are empty.** The **Reference data** tables did not load. Make
sure that the `CSV References` folder is next to the `.qgz` file. Unzip the
full folder. Do not open the project from inside the zip file.

**A list is in alphabetical order, with `Fairly Good` before `Good`.** Older
versions of QGIS sort each list by name. The values are correct. QGIS 3.44 and
later show each list in order, from `Good` to `Poor` for a condition.

**A value shows in brackets, such as `(1. Good)`.** The value is not on the
list. The lists hold the words only, with no list number, so a numbered value
from an older copy of this template is not on them. Select the value again
from the list.

**QGIS cannot save.** The folder is probably in OneDrive, SharePoint or
another synchronised folder. Move the full folder to a local disk, such as
`C:\BNG\`, and open the project again.

**A file name is too long, or a file cannot be written.** The folder path is
too long. Move the folder to `C:\BNG\`.

**QGIS says that a different version saved the project.** This is not a
problem. Open the project.

**You cannot draw.** Select the layer in the Layers panel, then click the
pencil.

**You cannot find `Copy baseline to post-intervention`.** Open the attribute
table of a **Post-Intervention** layer and click **Actions** (section 1.3).
`Rename a ref` is on the **Baseline** layers.

**The copy button says that the layer has unsaved edits.** The layer is in
edit mode, for example after a paste. Click the pencil to stop editing, save,
then click the button again.

**A pasted row has a blank `Parent Ref`.** The paste found no baseline feature
with exactly the same shape. Section 4.2 gives the causes and what to do.

**A paste opens the Fix Pasted Features dialog, and every field is blank.** The
clipboard held a layer, not features: Copy Layer was used instead of Copy
Features. Click **Discard All**. Then select the features and click **Edit →
Copy Features** (section 4.2).

**A drop-down shows `()`.** The field holds an empty text value, which is not
in the list. Pick `<NULL>` to leave the field blank, or pick a value. Every
drop-down offers `<NULL>`.

**A hedgerow, tree or watercourse row changed back to `Retained`, with the
Baseline values in its Proposed fields.** The row was pasted, duplicated or
split, and the result has exactly the shape of one baseline feature. QGIS
treats it as a paste from the baseline. Set the values again, and paste only
from the Baseline layer of this project (section 4.2).

**A new tree or hedge has a `Parent Ref`.** It lies exactly on a baseline
feature, usually because of snapping. Delete it, and draw it again a short
distance from the old one or with snapping off (Part 9).

**You typed a new baseline ref, and the post-intervention rows did not
change.** Typing changes one cell only. Press `Ctrl+Z`, then use **`Rename a
ref (updates post-intervention)`** on the Baseline layer (section 1.3).

**There are thin gaps between shapes.** Snapping was off. Undo, turn on
snapping (section 1.5) and draw again.

**Split Features did nothing.** There are two possible causes:

- The line did not cross the full parcel. Both ends must be outside the parcel
  or exactly on its edge.
- Features were selected. QGIS then splits only the selected features. Press
  `Ctrl+Shift+A` and try again.

**Fill Ring works sometimes and fails at other times.** Your ring touches a
parcel edge. QGIS needs the ring fully inside the parcel, to a very small
tolerance. A snapped point can land on the edge or just outside it, so the
result changes. A ring that succeeds there makes an invalid polygon. Use Split
Features (Part 5c).

**`could not add ring: the inserted Ring is not contained in a feature`.** Part
of the ring is outside the parcel. Usually a straight line between two
boundary points cut a corner. Turn on tracing (section 1.4). If the habitat
touches the parcel edge, use Split Features (Part 5c).

**You edited the baseline by mistake.** Press `Ctrl+Z` before you save.

**The service says that the baseline changed after the copy, but you did not
change it.** The service compares each baseline shape with its hidden record in
`parent_geom`. That record is made at the copy, at the paste or at the last
`Refresh from baseline`. The comparison is to the nearest millimetre. It
ignores corners that do not change the shape, such as those that **Topological
Editing** adds during a split.

Run **`Refresh from baseline`** on the layer (section 1.3). It records the
current shape on each row that it can update, and names the other rows for you
to check. To clear the warning for a named row, delete every row that came
from its baseline feature, then paste that feature again (section 4.2). This
removes your Part 5 edits on those rows, so first compare them with the
warning.
