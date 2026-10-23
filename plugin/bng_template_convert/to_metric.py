"""Fill the Statutory Biodiversity Metric workbook from a staged GeoPackage.

This is the third route out of the BNG Service template, alongside the legacy
GeoPackage pair and the GIS import tool's CSVs. It skips the import tool: the
habitats go straight into a copy of the metric's own workbook.

HOW IT WRITES
    Natural England publishes the metric twice, with macros (.xlsm) and
    without (.xlsx). The sheets, the formulas and the cells are the same in
    both; only the macro project differs. Either is a zip of XML, so no
    library is needed and none is available anyway (openpyxl is absent from
    QGIS's Python). Every cell this fills already exists in the sheet as an
    empty, styled element, so filling one is a replacement in place and
    nothing else moves. vbaProject.bin, where there is one, and every other
    part are copied through byte for byte, and sheet protection is left
    alone: it guards the user interface, not the file. The filled copy keeps
    the form of the blank it was made from.

    Excel caches a formula dependency chain. That cache is dropped and the
    workbook is marked for a full recalculation on open, so the numbers are
    computed from the values written here rather than from anything stale.

HOW IT MAPS
    The metric splits a site by retention across three sheets per module. Its
    baseline sheet holds an area that is then divided into "retained" and
    "enhanced", with the remainder treated as lost. Its enhancement sheet is
    nearly all formulas that pull the baseline back by lookup, in the order the
    enhanced rows appear in the baseline sheet.

    So each Retained or Enhanced post-intervention part becomes one baseline
    row carrying its parent's baseline values and its own size, with that
    size placed in retained or enhanced. Units are linear in size, so
    splitting a parent across rows gives the same totals and makes the
    correspondence with the enhancement sheet one to one. Whatever of the
    parent its parts do not carry forward is one more row with nothing
    retained or enhanced, which the metric counts as lost (see ACCOUNTING).
    So the baseline sheet always holds the whole baseline layer, however much
    of post-intervention has been drawn.

    The template stores strategic significance as "Low" or "High". The
    metric's own wording is written instead (see reference_lists.py).

    Years created in advance and years of delay are written as the row
    stores them. The metric holds blank, 0 to 30 and 30+. Text from an
    older file, such as N/A, is left blank, and the report names the rows.

    A value the metric needs and the layer leaves blank is written as a
    blank. The metric then flags that row or leaves its units blank, and a
    total including it can read Check Data, so the report lists every such
    gap, layer by layer (see BASELINE_NEEDS and PROPOSED_NEEDS).

    Comments go into each sheet's "User comments" column. A baseline line
    carries its baseline feature's comment. A Retained part's line adds the
    part's own comment after it, an Enhanced part's comment goes on its
    enhancement row, and a Created part's on its creation row.

INDIVIDUAL TREES
    The metric holds trees on the area habitat sheets, as the broad habitat
    "Individual trees" with the habitat type "Urban tree" or "Rural tree". A
    tree's area is not measured: it is the area of its size class, from the
    tree helper (User Guide, Table 15). Each point is one tree. A tree can be
    retained, enhanced, created or lost like any area habitat. Enhancing a
    tree improves its condition only. Its size class, and so its area, stays
    the baseline one, because the metric does not record natural growth
    (User Guide, page 64). Tree lines follow the area habitat lines on each
    sheet.

SCOPE
    On-site only. The off-site sheets (D, E and F) carry extra allocation
    columns and a different layout, so they are deliberately not written rather
    than guessed at.
"""

import argparse
import os
import re
import shutil
import sqlite3
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import OrderedDict, defaultdict

try:
    from .gpkg_common import (
        SQ_METRES_PER_HECTARE,
        numeric,
        tree_count_warning,
        trees_counted_above_one,
        part_path,
        parts_needed,
        plain_label,
        read_only_uri,
        require_service_tables,
        split_into_parts,
        summarise_refs,
    )
except ImportError:  # pragma: no cover - running as a plain script
    from gpkg_common import (
        SQ_METRES_PER_HECTARE,
        numeric,
        tree_count_warning,
        trees_counted_above_one,
        part_path,
        parts_needed,
        plain_label,
        read_only_uri,
        require_service_tables,
        split_into_parts,
        summarise_refs,
    )

try:
    from .reference_lists import (
        BASELINE_SIGNIFICANCE,
        IRREPLACEABLE_COLUMN,
        PROPOSED_SIGNIFICANCE,
        to_legacy_significance,
    )
except ImportError:  # pragma: no cover - running as a plain script
    from reference_lists import (
        BASELINE_SIGNIFICANCE,
        IRREPLACEABLE_COLUMN,
        PROPOSED_SIGNIFICANCE,
        to_legacy_significance,
    )

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

METRES_PER_KM = 1000

RETAINED, ENHANCED, CREATED = "Retained", "Enhanced", "Created"


# Layer keys, sheet stages, and the column and line-field names used below.
AREAS, HEDGEROWS, WATERCOURSES, TREES = (
    "areas", "hedgerows", "watercourses", "trees")
BASELINE, CREATION, ENHANCEMENT = "baseline", "creation", "enhancement"
FEATURE_UUID, PARENT_UUID = "feature_uuid", "parent_uuid"
BASELINE_CONDITION = "Baseline Condition"
PROPOSED_CONDITION = "Proposed Condition"
BASELINE_BROAD_HABITAT = "Baseline Broad Habitat Type"
PROPOSED_BROAD_HABITAT = "Proposed Broad Habitat Type"
BASELINE_TREE_SIZE = "Baseline Tree Size"
PROPOSED_TREE_SIZE = "Proposed Tree Size"
LENGTH = "Length"
LINE_COMMENT, LINE_NUMBER = "comment", "number"
RETAINED_SIZE, ENHANCED_SIZE = "retained", "enhanced"
WHOLLY_LOST, PARTLY_LOST = "wholly lost", "partly lost"
IRREPLACEABLE_LOST, OVERSUBSCRIBED = "irreplaceable lost", "oversubscribed"
MERGED_COMMENTS = "_comments"
UTF8 = "utf-8"
WORKBOOK_XML = "xl/workbook.xml"
WORKBOOK_RELS = "xl/_rels/workbook.xml.rels"
CONTENT_TYPES_XML = "[Content_Types].xml"


# Excel refuses to open a macro-free workbook named .xlsm, and a macro
# workbook named .xlsx, so a filled copy has to carry the extension of the
# blank it was made from. The workbook part's declared content type says which
# form a file is, whatever it happens to be called.
MACRO_WORKBOOK_TYPE = "application/vnd.ms-excel.sheet.macroEnabled.main+xml"
MACRO_EXTENSION, PLAIN_EXTENSION = ".xlsm", ".xlsx"

# How much of a baseline feature its post-intervention parts carry forward.
# These are the rules the service reconciles an upload by, per module.
#
#   SHORTFALL  Area habitats and hedgerows. Whatever the Retained and Enhanced
#              parts do not carry forward is lost: the ground under a Created
#              parcel, a feature deleted outright, the length taken out of a
#              shortened hedge. It is also what an unfinished post-intervention
#              layer looks like, which is why the report says how much.
#   PRESENCE   Watercourses. Re-meandering moves a channel and lengthens it,
#              so the length of the parts says nothing about how much was
#              lost. A watercourse with any Retained or Enhanced part continues
#              at its surveyed length; one with none is lost.
#
# A shortfall smaller than the tolerance is drawing noise, not a loss: half a
# square metre is the service's own area tolerance, and the service rounds
# linear sizes to whole metres.
SHORTFALL, PRESENCE = "shortfall", "presence"
ACCOUNTING = {
    AREAS: (SHORTFALL, 0.5 / SQ_METRES_PER_HECTARE),
    HEDGEROWS: (SHORTFALL, 0.5),
    WATERCOURSES: (PRESENCE, 0.5),
}

# The columns the metric needs before it can score a row, on the layers they
# are read from, so a warning names the column a user has to fill in. The
# baseline values reach the sheet for every baseline feature, carried forward
# or not. Proposed values are needed on Enhanced and Created parts only: a
# Retained part scores on its parent's baseline values.
BASELINE_NEEDS = {
    AREAS: (BASELINE_BROAD_HABITAT, "Baseline Habitat Type",
            BASELINE_CONDITION, BASELINE_SIGNIFICANCE,
            IRREPLACEABLE_COLUMN, "Area"),
    HEDGEROWS: ("Baseline Hedge Type", BASELINE_CONDITION,
                BASELINE_SIGNIFICANCE, LENGTH),
    WATERCOURSES: ("Baseline River Type", BASELINE_CONDITION,
                   BASELINE_SIGNIFICANCE,
                   "Baseline Encroachment into Watercourse",
                   "Baseline Encroachment into riparian zone", LENGTH),
}
PROPOSED_NEEDS = {
    AREAS: (PROPOSED_BROAD_HABITAT, "Proposed Habitat Type",
            PROPOSED_CONDITION, PROPOSED_SIGNIFICANCE),
    HEDGEROWS: ("Proposed Hedge Type", PROPOSED_CONDITION,
                PROPOSED_SIGNIFICANCE),
    WATERCOURSES: ("Proposed River Type", PROPOSED_CONDITION,
                   PROPOSED_SIGNIFICANCE,
                   "Proposed Encroachment into Watercourse",
                   "Proposed Encroachment into riparian zone"),
}
RETENTION_FIELD = "Retention Category"
# A Retained or Enhanced area habitat row takes its irreplaceable flag from the
# part rather than the parent, so the part needs one too.
KEPT_AREA_NEEDS = (IRREPLACEABLE_COLUMN,)

# Column letters were found by taking, on each sheet's first data row, the
# cells that EXIST but hold nothing. Those are the inputs; everything else is a
# formula and must not be written to. Header text is no guide, because it sits
# across two or three rows per sheet.
#
# The "Ref" column on the baseline and creation sheets (A-1 D, A-2 B, B-1 B,
# C-1 C) is NOT the user's reference. It holds the metric's own line numbers,
# and the enhancement sheets find their baseline through it: A-3!E12 is
# ='A-1'!AL11, which yields a line number, and A-3!F12 then looks that up in
# A-1 column D. Overwrite D and every enhancement row loses its baseline with
# nothing shown on screen. The user's reference goes in "Habitat reference
# number" instead.
# The last row is the last one the workbook treats as DATA, which is not
# always the last row of the visible block. Four of the nine sheets keep a
# totals row two rows inside their apparent range. The numbers below were
# measured from the blank workbook rather than read off the screen: a
# baseline or creation data row carries the metric's own line number as a
# literal in its Ref column, and an enhancement data row carries the formula
# that reaches back to its baseline sheet. A-2, A-3, B-3 and C-3 stop at 246
# rows where the rest hold 248, so a habitat sheet can take 248 baseline
# parcels but only 246 of them can be enhancements.
#
# The watercourse sheets multiply every row's units by two encroachment
# multipliers, one for the channel and one for the riparian zone. A blank
# encroachment makes the multiplier blank and the row's units blank with it,
# so a watercourse written without them scores nothing at all.
LAYOUT = {
    AREAS: {
        BASELINE: ("A-1 On-Site Habitat Baseline", 11, 258, {
            "broad": "E", "habitat": "F", "irreplaceable": "G", "size": "H",
            "condition": "K", "significance": "M", "retained": "S",
            "enhanced": "T", "comment": "Z", "ref": "AB"}),
        CREATION: ("A-2 On-Site Habitat Creation", 11, 256, {
            "broad": "D", "habitat": "E", "size": "G", "condition": "J",
            "significance": "L", "advance": "P", "delay": "Q",
            "comment": "Z", "ref": "AB"}),
        ENHANCEMENT: ("A-3 On-Site Habitat Enhancement", 12, 257, {
            "habitat": "R", "condition": "Y", "significance": "AA",
            "advance": "AE", "delay": "AF", "comment": "AO", "ref": "AQ"}),
    },
    HEDGEROWS: {
        BASELINE: ("B-1 On-Site Hedge Baseline", 10, 257, {
            "number": "C", "habitat": "D", "size": "E", "condition": "H",
            "significance": "J", "retained": "P", "enhanced": "Q",
            "comment": "V", "ref": "X"}),
        CREATION: ("B-2 On-Site Hedge Creation", 12, 259, {
            "number": "C", "habitat": "D", "size": "E", "condition": "H",
            "significance": "J", "advance": "N", "delay": "O",
            "comment": "X", "ref": "Z"}),
        ENHANCEMENT: ("B-3 On-Site Hedge Enhancement", 12, 257, {
            "habitat": "M", "condition": "S", "significance": "U",
            "advance": "Y", "delay": "Z", "comment": "AI", "ref": "AK"}),
    },
    WATERCOURSES: {
        BASELINE: ("C-1 On-Site WaterC' Baseline", 10, 257, {
            "habitat": "D", "size": "E", "condition": "H",
            "significance": "J", "encroachment": "M", "riparian": "O",
            "retained": "U", "enhanced": "V", "comment": "AB", "ref": "AD"}),
        CREATION: ("C-2 On-Site WaterC' Creation", 12, 259, {
            "habitat": "C", "size": "D", "condition": "G",
            "significance": "I", "advance": "M", "delay": "N",
            "encroachment": "V", "riparian": "X", "comment": "AA",
            "ref": "AC"}),
        ENHANCEMENT: ("C-3 On-Site WaterC' Enhancement", 12, 257, {
            "habitat": "N", "condition": "T", "significance": "V",
            "advance": "Z", "delay": "AA", "encroachment": "AI",
            "riparian": "AK", "comment": "AN", "ref": "AP"}),
    },
}

# module -> staged tables, the size column, the habitat-type column, and the
# factor taking the template's units to the metric's. Areas are hectares on
# both sides; the metric wants linear features in KILOMETRES.
MODULES = (
    (AREAS, "Area Habitats Baseline", "Area Habitats Post-Intervention",
     "Area", "Habitat Type", 1.0),
    (HEDGEROWS, "Hedgerows Baseline", "Hedgerows Post-Intervention",
     LENGTH, "Hedge Type", 1.0 / METRES_PER_KM),
    (WATERCOURSES, "Watercourses Baseline", "Watercourses Post-Intervention",
     LENGTH, "River Type", 1.0 / METRES_PER_KM),
)

# Individual trees go onto the area habitat sheets, after the area habitats.
TREE_TABLES = ("Individual Trees Baseline",
               "Individual Trees Post-Intervention")
TREES_BROAD = "Individual trees"
# The tree helper's area for one tree of each size class, in hectares
# (User Guide, Table 15). bng-library holds the same figures in square metres.
TREE_AREA_HA = {
    "Small": 0.0041,
    "Medium": 0.0163,
    "Large": 0.0366,
    "Very large": 0.0765,
}
TREE_ADVANCE = "Habitat Created/Enhanced in advance/years"
TREE_DELAY = "Delay in starting habitat creation/enhancement in years"
# The names every module but trees uses. A tree row is copied onto these
# before it is written, so the metric sees one pair of columns.
ADVANCE_FIELD = "Habitat created in advance/years"
DELAY_FIELD = "Delay in starting habitat creation/years"
# Blank, 0 to 30 and 30+: the years the Statutory Metric's drop-down stores.
# 30+ is the only text it holds. Anything else, such as N/A from an older
# file, is not a year.
METRIC_YEARS = {str(year) for year in range(31)} | {"30+"}
TREE_BASELINE_NEEDS = (BASELINE_TREE_SIZE, "Baseline Rural or Urban Tree",
                       BASELINE_CONDITION, BASELINE_SIGNIFICANCE,
                       IRREPLACEABLE_COLUMN)
TREE_PROPOSED_NEEDS = (PROPOSED_TREE_SIZE, "Proposed Rural or Urban Tree",
                       PROPOSED_CONDITION, PROPOSED_SIGNIFICANCE)
# The metric's condition scale for trees, worst first. An enhancement has to
# move up it: the metric shows "Error - No enhancement" for the same
# condition and "Error - Can not reduce condition" for a lower one.
TREE_CONDITIONS = ("Poor", "Fairly Poor", "Moderate", "Fairly Good", "Good")

# Every habitat table holds its reference in this column.
REF_FIELD = "Habitat Ref"
COMMENT_FIELD = "Comment"
# Excel holds at most this many characters in a cell.
EXCEL_CELL_LIMIT = 32767
# Characters XML 1.0 cannot carry: a workbook holding one does not open.
XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
POST_INTERVENTION_PREFIX = "Post-intervention: "

# A cell that proves the workbook already holds a site.
OCCUPIED_PROBE = ("A-1 On-Site Habitat Baseline", "E11")

SIZE_FIELDS = ("size", RETAINED_SIZE, ENHANCED_SIZE)

# An enhanced baseline line carries its own enhancement under this key rather
# than living in a parallel list. The enhancement sheet is positional against
# the baseline sheet, so the two have to be split across workbooks together,
# and a line that carries its own is impossible to separate from it by
# accident. Stripped before anything is written: it is not a column.
ENHANCEMENT_KEY = "_enhancement"


class Report:
    """Counts, notes and warnings, plus every file the run wrote.

    `paths` exists so a caller that has to name its output (the QGIS plugin
    declares one file) can find out that a site was split, rather than
    pointing a user at a path nothing was written to.
    """

    def __init__(self):
        self.lines = []
        self.warnings = []
        self.counts = {}
        self.paths = []

    def note(self, message):
        self.lines.append(message)

    def warn(self, message):
        self.warnings.append(message)

    def count(self, key, value):
        self.counts[key] = value


# ---------------------------------------------------------------------------
# Reading the staged GeoPackage
# ---------------------------------------------------------------------------


def read_table(conn, table, present):
    if table not in present:
        return []
    cursor = conn.execute(f'SELECT * FROM "{table}"')
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, values)) for values in cursor.fetchall()]


def read_staged(path):
    """Every module's rows, with significance in the metric's wording."""
    conn = sqlite3.connect(read_only_uri(path), uri=True)
    try:
        present = {
            row[0] for row in conn.execute(
                "SELECT table_name FROM gpkg_contents WHERE data_type='features'")
        }
        require_service_tables(present, [
            name for _kind, base, pi, _size, _type, _scale in MODULES
            for name in (base, pi)])
        staged = {
            kind: {BASELINE: read_table(conn, base, present),
                   "pi": read_table(conn, pi, present)}
            for kind, base, pi, _size, _type, _scale in MODULES
        }
        trees = {BASELINE: read_table(conn, TREE_TABLES[0], present),
                 "pi": read_table(conn, TREE_TABLES[1], present)}
    finally:
        conn.close()
    to_legacy_significance(staged)
    staged[TREES] = trees
    return staged


def comment_of(row):
    """A row's comment, or None when it has none."""
    value = row.get(COMMENT_FIELD)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def joined_comment(baseline_comment, part_comment):
    """A baseline comment followed by a post-intervention one."""
    if not part_comment:
        return baseline_comment
    part_comment = POST_INTERVENTION_PREFIX + part_comment
    if not baseline_comment:
        return part_comment
    return f"{baseline_comment} | {part_comment}"


# ---------------------------------------------------------------------------
# Individual trees, as the area habitat lines the metric holds them as
# ---------------------------------------------------------------------------


def tree_area(size):
    """Hectares for one tree of a size class, or None if it is unknown."""
    return TREE_AREA_HA.get(plain_label(size) if size else None)


def tree_as_area_baseline(row):
    return {
        "fid": row.get("fid"),
        REF_FIELD: row.get(REF_FIELD),
        FEATURE_UUID: row.get(FEATURE_UUID),
        BASELINE_BROAD_HABITAT: TREES_BROAD,
        "Baseline Habitat Type": row.get("Baseline Rural or Urban Tree"),
        BASELINE_CONDITION: row.get(BASELINE_CONDITION),
        BASELINE_SIGNIFICANCE: row.get(BASELINE_SIGNIFICANCE),
        # Ancient and veteran trees are irreplaceable habitat. The metric
        # gives no units for their loss and refuses to enhance them.
        IRREPLACEABLE_COLUMN: row.get(IRREPLACEABLE_COLUMN),
        "Area": tree_area(row.get(BASELINE_TREE_SIZE)),
        COMMENT_FIELD: row.get(COMMENT_FIELD),
    }


def tree_as_area_part(row, parent):
    """A post-intervention tree. A kept tree keeps its parent's size class."""
    kept = parent is not None and retention_of(row) in (RETAINED, ENHANCED)
    size = (parent.get(BASELINE_TREE_SIZE) if kept
            else row.get(PROPOSED_TREE_SIZE))
    return {
        "fid": row.get("fid"),
        REF_FIELD: row.get(REF_FIELD),
        PARENT_UUID: row.get(PARENT_UUID),
        RETENTION_FIELD: row.get(RETENTION_FIELD),
        IRREPLACEABLE_COLUMN: row.get(IRREPLACEABLE_COLUMN),
        PROPOSED_BROAD_HABITAT: TREES_BROAD,
        "Proposed Habitat Type": row.get("Proposed Rural or Urban Tree"),
        PROPOSED_CONDITION: row.get(PROPOSED_CONDITION),
        PROPOSED_SIGNIFICANCE: row.get(PROPOSED_SIGNIFICANCE),
        ADVANCE_FIELD: row.get(TREE_ADVANCE),
        DELAY_FIELD: row.get(TREE_DELAY),
        "Area": tree_area(size),
        COMMENT_FIELD: row.get(COMMENT_FIELD),
    }


def trees_as_areas(trees):
    """The tree layers as area habitat rows, significance in metric wording.

    The metric words strategic significance the same way for trees as for
    every other area habitat, so the tree wording of the legacy template is
    not used here.
    """
    parents = {row.get(FEATURE_UUID): row for row in trees[BASELINE]
               if row.get(FEATURE_UUID)}
    tables = {
        BASELINE: [tree_as_area_baseline(row) for row in trees[BASELINE]],
        "pi": [tree_as_area_part(row, parents.get(row.get(PARENT_UUID)))
               for row in trees["pi"]],
    }
    to_legacy_significance({AREAS: tables})
    return tables


def is_irreplaceable(row):
    return plain_label(row.get(IRREPLACEABLE_COLUMN)) == "Yes"


def retention_of(row):
    return row.get(RETENTION_FIELD) or ""


def baseline_line(row, size, type_field):
    """A baseline feature's own values over `size`, with nothing kept."""
    return {
        "ref": row.get(REF_FIELD),
        LINE_NUMBER: row.get(REF_FIELD),
        "broad": row.get(BASELINE_BROAD_HABITAT),
        "habitat": row.get(f"Baseline {type_field}"),
        # Its own flag, not None: a wholly lost parcel is still
        # irreplaceable habitat, and consolidation groups on this.
        "irreplaceable": row.get(IRREPLACEABLE_COLUMN),
        "size": size,
        "condition": plain_label(row.get(BASELINE_CONDITION)),
        "significance": row.get(BASELINE_SIGNIFICANCE),
        "encroachment": plain_label(
            row.get("Baseline Encroachment into Watercourse")),
        "riparian": plain_label(
            row.get("Baseline Encroachment into riparian zone")),
        RETAINED_SIZE: 0,
        ENHANCED_SIZE: 0,
        LINE_COMMENT: comment_of(row),
    }


def _timing_text(value):
    """The timing value as text, or '' when it is blank."""
    if value is None:
        return ""
    return str(value).strip()


def _year_as_stored(value):
    """A year the metric offers, as the row stores it, or None.

    None covers a blank and any text that is not a year, such as N/A from
    an older file. A year is returned unchanged.
    """
    if _timing_text(value) in METRIC_YEARS:
        return value
    return None


def _is_text_timing(value):
    """True when the value is text the metric's years list does not hold."""
    text = _timing_text(value)
    return bool(text) and text not in METRIC_YEARS


def proposed_values(row, type_field, text_years=None):
    """What a post-intervention part will become.

    Advance and delay are written as the row stores them. Text that is
    not a year the metric offers is left blank, and the row is named in
    `text_years`.
    """
    if text_years is not None and (
            _is_text_timing(row.get(ADVANCE_FIELD))
            or _is_text_timing(row.get(DELAY_FIELD))):
        text_years.append(row_label(row, REF_FIELD))
    return {
        "habitat": row.get(f"Proposed {type_field}"),
        "condition": plain_label(row.get(PROPOSED_CONDITION)),
        "significance": row.get(PROPOSED_SIGNIFICANCE),
        "encroachment": plain_label(
            row.get("Proposed Encroachment into Watercourse")),
        "riparian": plain_label(
            row.get("Proposed Encroachment into riparian zone")),
        "advance": _year_as_stored(row.get(ADVANCE_FIELD)),
        "delay": _year_as_stored(row.get(DELAY_FIELD)),
    }


def kept_sizes(parent, parts, size_field, rule):
    """How much of the parent each Retained or Enhanced part carries forward."""
    sizes = [numeric(part.get(size_field)) or 0.0 for part in parts]
    if rule != PRESENCE or not parts:
        return sizes
    # A watercourse that continues at all continues at its surveyed length,
    # shared between its parts in proportion to how long each one is drawn.
    whole = numeric(parent.get(size_field)) or 0.0
    drawn = sum(sizes)
    if drawn <= 0:
        return [whole / len(parts)] * len(parts)
    return [whole * size / drawn for size in sizes]


def _parents_by_uuid(rows):
    return {row.get(FEATURE_UUID): row
            for row in rows if row.get(FEATURE_UUID)}


def _creation_line(row, size_field, type_field, text_years):
    line = proposed_values(row, type_field, text_years)
    line.update({
        "ref": row.get(REF_FIELD),
        LINE_NUMBER: row.get(REF_FIELD),
        "broad": row.get(PROPOSED_BROAD_HABITAT),
        "size": numeric(row.get(size_field)) or 0.0,
        LINE_COMMENT: comment_of(row),
    })
    return line


def _sort_post_intervention(pi_rows, by_uuid, size_field, type_field,
                            text_years):
    """Kept parts by parent, and the creation lines.

    A part with a parent and no retention the metric knows carries nothing
    forward, so its share falls into the parent's lost line.
    """
    kept = defaultdict(list)
    creation = []
    for row in pi_rows:
        retention = retention_of(row)
        parent = by_uuid.get(row.get(PARENT_UUID))
        if parent is not None and retention in (RETAINED, ENHANCED):
            kept[row.get(PARENT_UUID)].append(row)
        elif retention == CREATED or parent is None:
            creation.append(_creation_line(
                row, size_field, type_field, text_years))
    return kept, creation


def _kept_baseline_line(parent, part, size, type_field, text_years):
    """One baseline row for a part that carries `size` of its parent forward."""
    retention = retention_of(part)
    line = baseline_line(parent, size, type_field)
    line.update({
        "ref": part.get(REF_FIELD),
        LINE_NUMBER: part.get(REF_FIELD),
        "irreplaceable": part.get(IRREPLACEABLE_COLUMN),
        RETAINED_SIZE: size if retention == RETAINED else 0,
        ENHANCED_SIZE: size if retention == ENHANCED else 0,
    })
    if retention == ENHANCED:
        enhancement = proposed_values(part, type_field, text_years)
        enhancement.update({"ref": part.get(REF_FIELD),
                            LINE_COMMENT: comment_of(part)})
        line[ENHANCEMENT_KEY] = enhancement
    else:
        line[LINE_COMMENT] = joined_comment(line[LINE_COMMENT],
                                            comment_of(part))
    return line


def _append_kept_parts(parent, parts, sizes, baseline, type_field, text_years):
    """Write each part that keeps some of the parent. Returns how much."""
    carried = 0.0
    for part, size in zip(parts, sizes):
        # A part of no size keeps nothing, and an enhancement row with no
        # enhanced size would sit against the wrong baseline row: the metric
        # lists only the rows whose enhanced size is above zero.
        if size <= 0:
            continue
        baseline.append(_kept_baseline_line(
            parent, part, size, type_field, text_years))
        carried += size
    return carried


def _record_loss(parent, whole, carried, tolerance, baseline, accounting,
                 type_field):
    lost = whole - carried
    ref = parent.get(REF_FIELD) or parent.get("fid")
    if lost > tolerance:
        baseline.append(baseline_line(parent, lost, type_field))
        accounting[PARTLY_LOST if carried else WHOLLY_LOST].append(ref)
        if is_irreplaceable(parent):
            accounting[IRREPLACEABLE_LOST].append(ref)
    elif lost < -tolerance:
        accounting[OVERSUBSCRIBED].append(ref)


def _baseline_from_kept(baseline_rows, kept, size_field, type_field, rule,
                        tolerance, text_years):
    baseline = []
    accounting = {WHOLLY_LOST: [], PARTLY_LOST: [], OVERSUBSCRIBED: [],
                  IRREPLACEABLE_LOST: []}
    for parent in baseline_rows:
        # Only a parent with an identifier can have parts in `kept`.
        parts = kept.get(parent.get(FEATURE_UUID), [])
        whole = numeric(parent.get(size_field)) or 0.0
        sizes = kept_sizes(parent, parts, size_field, rule)
        carried = _append_kept_parts(
            parent, parts, sizes, baseline, type_field, text_years)
        _record_loss(parent, whole, carried, tolerance, baseline, accounting,
                     type_field)
    return baseline, accounting


def build_lines(tables, size_field, type_field, consolidate,
                rule=SHORTFALL, tolerance=0.0, text_years=None):
    """Baseline, creation and enhancement lines for one module.

    Returns (baseline lines, creation lines, accounting), where accounting
    names the baseline features that were wholly lost, partly lost, and
    oversubscribed, for the report.
    """
    kept, creation = _sort_post_intervention(
        tables["pi"], _parents_by_uuid(tables[BASELINE]),
        size_field, type_field, text_years)
    baseline, accounting = _baseline_from_kept(
        tables[BASELINE], kept, size_field, type_field, rule, tolerance,
        text_years)
    if consolidate:
        baseline = consolidate_lines(baseline)
        creation = consolidate_lines(creation)
    return baseline, creation, accounting


# ---------------------------------------------------------------------------
# What the report has to say about a site that is not finished
# ---------------------------------------------------------------------------


def is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def row_label(row, ref_field):
    ref = row.get(ref_field)
    return str(ref) if not is_blank(ref) else f"fid {row.get('fid')}"


def needed_columns(kind, row, parents, size_field):
    """The columns a post-intervention part needs, given what it does."""
    retention = retention_of(row)
    has_parent = row.get(PARENT_UUID) in parents
    needs = [RETENTION_FIELD, size_field]
    if retention in (ENHANCED, CREATED) or not has_parent:
        needs.extend(PROPOSED_NEEDS[kind])
    if kind == AREAS and has_parent and retention in (RETAINED, ENHANCED):
        needs.extend(KEPT_AREA_NEEDS)
    return needs


# What a gap costs, said once per layer. The legacy converters reuse the
# check with their own wording, because their output is not the workbook.
METRIC_GAP_CONSEQUENCE = (
    "The metric cannot score a row until these are filled in. Depending on "
    "the column it flags the row or leaves its units blank, and a total that "
    "includes the row can show 'Check Data' in place of a number.")


def report_gaps(table, gaps, report, consequence=METRIC_GAP_CONSEQUENCE):
    """One warning for a layer, naming each column left blank and where."""
    if not gaps:
        return
    rows = {label for labels in gaps.values() for label in labels}
    columns = "; ".join(
        f"{column} on {len(labels)} ({summarise_refs(labels)})"
        for column, labels in gaps.items())
    message = (
        f"{table}: {len(rows)} row(s) are missing values the metric needs. "
        f"{columns}. {consequence}")
    if RETENTION_FIELD in gaps:
        message += (
            f" A part with no {RETENTION_FIELD} keeps nothing of the "
            "baseline feature it came from, so that share is counted as "
            "lost.")
    report.warn(message)


def _feature_uuids(rows):
    return {row.get(FEATURE_UUID) for row in rows if row.get(FEATURE_UUID)}


def _columns_of(columns):
    """A row function that always names the same columns."""
    def columns_for(_row):
        return columns
    return columns_for


def _pi_columns(kind, parents, size_field):
    def columns_for(row):
        return needed_columns(kind, row, parents, size_field)
    return columns_for


def _column_gaps(rows, columns_for, skip):
    """Blanks in the columns `columns_for` names for each row."""
    gaps = OrderedDict()
    for row in rows:
        for column in columns_for(row):
            if column not in skip and is_blank(row.get(column)):
                gaps.setdefault(column, []).append(row_label(row, REF_FIELD))
    return gaps


def check_needed_values(staged, report, consequence=METRIC_GAP_CONSEQUENCE,
                        skip=()):
    """Warn, one summary per layer, about blanks the metric cannot score.

    Nothing is refused for a gap. A site part-way through is normal, and the
    rows that are complete are worth having in the workbook. But a blank the
    metric needs is written as a blank, and the metric then shows that row
    as needing data and leaves it out of the totals, with nothing on the
    headline results to say so. The report is where that gets said.

    `staged` maps each module to its "baseline" and "pi" rows under the
    BNG Service template's column names. `skip` leaves out columns a caller
    has already warned about in its own terms.
    """
    for kind, base_table, pi_table, size_field, _type, _scale in MODULES:
        tables = staged[kind]
        parents = _feature_uuids(tables[BASELINE])
        report_gaps(base_table, _column_gaps(
            tables[BASELINE], _columns_of(BASELINE_NEEDS[kind]), skip),
            report, consequence)
        report_gaps(pi_table, _column_gaps(
            tables["pi"], _pi_columns(kind, parents, size_field), skip),
            report, consequence)


def check_post_intervention(staged, report):
    """Say so when post-intervention has not been drawn, in part or at all.

    An empty post-intervention layer is written exactly as the template
    means it: every baseline feature lost. That is right for a site being
    cleared and wrong for one not designed yet, and only the user knows
    which, so the report says what the numbers mean either way.
    """
    started = [(base, pi) for kind, base, pi, *_rest in MODULES
               if staged[kind][BASELINE]]
    empty = [(base, pi) for kind, base, pi, *_rest in MODULES
             if staged[kind][BASELINE] and not staged[kind]["pi"]]
    if not empty:
        return
    if len(empty) == len(started):
        irreplaceable = any(is_irreplaceable(row)
                            for row in staged[AREAS][BASELINE])
        report.warn(
            "Nothing has been drawn in post-intervention, so every baseline "
            "feature is written as lost. The baseline units are right"
            + (", apart from irreplaceable habitat (see below)"
               if irreplaceable else "")
            + ". The post-intervention units and the net change describe a "
            "site cleared of all its habitat, so ignore them until "
            "post-intervention is drawn.")
        return
    for base, pi in empty:
        report.warn(
            f"{pi} is empty, so every feature in {base} is written as lost. "
            "If that layer has not been drawn yet, ignore its "
            "post-intervention units and net change for now.")


def condition_rank(value):
    words = plain_label(value) if value else None
    return TREE_CONDITIONS.index(words) if words in TREE_CONDITIONS else None


def _report_tree_baseline(rows, table, report):
    report_gaps(table, _column_gaps(rows, _columns_of(TREE_BASELINE_NEEDS), ()),
                report)


def _report_tree_counts(trees, report):
    for table, rows in zip(TREE_TABLES, (trees[BASELINE], trees["pi"])):
        many = trees_counted_above_one(rows, REF_FIELD)
        if many:
            report.warn(tree_count_warning(table, many))


def _tree_part_needs(row, parent):
    retention = retention_of(row)
    needs = [RETENTION_FIELD]
    if retention in (ENHANCED, CREATED) or parent is None:
        needs.extend(TREE_PROPOSED_NEEDS)
    if parent is not None and retention in (RETAINED, ENHANCED):
        needs.extend(KEPT_AREA_NEEDS)
    return needs


def _note_enhanced_tree(row, parent, not_better, resized, irreplaceable):
    """Name an Enhanced tree the metric will refuse or mis-score."""
    label = row_label(row, REF_FIELD)
    if is_irreplaceable(row) or is_irreplaceable(parent):
        irreplaceable.append(label)
    before = condition_rank(parent.get(BASELINE_CONDITION))
    after = condition_rank(row.get(PROPOSED_CONDITION))
    if before is not None and after is not None and after <= before:
        not_better.append(label)
    proposed_size = row.get(PROPOSED_TREE_SIZE)
    if (not is_blank(proposed_size)
            and proposed_size != parent.get(BASELINE_TREE_SIZE)):
        resized.append(label)


def _inspect_tree_parts(rows, parents):
    gaps = OrderedDict()
    not_better, resized, irreplaceable = [], [], []
    for row in rows:
        parent = parents.get(row.get(PARENT_UUID))
        for column in _tree_part_needs(row, parent):
            if is_blank(row.get(column)):
                gaps.setdefault(column, []).append(row_label(row, REF_FIELD))
        if retention_of(row) != ENHANCED or parent is None:
            continue
        _note_enhanced_tree(row, parent, not_better, resized, irreplaceable)
    return gaps, not_better, resized, irreplaceable


def _report_enhanced_tree_problems(table, not_better, resized, irreplaceable,
                                   report):
    if not_better:
        report.warn(
            f"{table}: {len(not_better)} Enhanced tree(s) do not move to a "
            f"better condition ({summarise_refs(not_better)}). Enhancing a "
            "tree means improving its condition, and the metric shows "
            "'Error - No enhancement' or 'Error - Can not reduce condition' "
            "on these rows and gives them no units. Record the tree as "
            "Retained, or choose a better condition.")
    if irreplaceable:
        report.warn(
            f"{table}: {len(irreplaceable)} Enhanced tree(s) are "
            f"irreplaceable ({summarise_refs(irreplaceable)}). The metric "
            "does not allow an irreplaceable tree to be enhanced: it shows "
            "'Error - you cannot enhance irreplaceable individual trees' and "
            "gives the row no units. Record the tree as Retained.")
    if resized:
        report.warn(
            f"{table}: {len(resized)} Enhanced tree(s) have a proposed "
            f"size class that is not their baseline one "
            f"({summarise_refs(resized)}). The metric does not record the "
            "growth of a kept tree (User Guide, page 64), so they are written "
            "at their baseline size.")


def check_trees(trees, report):
    """What the metric needs from the tree layers, and what it refuses.

    The gaps are reported as for the other layers. An Enhanced tree has to
    move to a better condition, keeps its baseline size class and cannot be
    irreplaceable, so the report names a tree that breaks any of those.
    """
    if not trees:
        return
    baseline_table, pi_table = TREE_TABLES
    _report_tree_baseline(trees[BASELINE], baseline_table, report)
    _report_tree_counts(trees, report)
    gaps, not_better, resized, irreplaceable = _inspect_tree_parts(
        trees["pi"], _parents_by_uuid(trees[BASELINE]))
    report_gaps(pi_table, gaps, report)
    _report_enhanced_tree_problems(
        pi_table, not_better, resized, irreplaceable, report)
    if trees[BASELINE] and not trees["pi"]:
        report.warn(
            f"{pi_table} is empty, so every tree in {baseline_table} is "
            "written as lost. If that layer has not been drawn yet, ignore "
            "its post-intervention units and net change for now.")


def report_text_timing(table, refs, report):
    """Name the rows whose advance or delay was text the metric cannot hold."""
    if not refs:
        return
    report.warn(
        f"{table}: {len(refs)} row(s) had a text value for years created "
        f"in advance or years of delay ({summarise_refs(refs)}). The "
        "Statutory Metric offers blank, 0 to 30 and 30+ only, so they "
        "were left blank."
    )


def report_accounting(base_table, accounting, report):
    """What the baseline sheet counts as lost, and anything that cannot be."""
    wholly, partly = accounting[WHOLLY_LOST], accounting[PARTLY_LOST]
    if wholly or partly:
        report.note(
            f"{base_table}: {len(wholly)} feature(s) carry nothing forward "
            f"to post-intervention and {len(partly)} carry forward only part "
            "of their size. The metric counts the rest as lost.")
    if accounting[IRREPLACEABLE_LOST]:
        refs = accounting[IRREPLACEABLE_LOST]
        report.warn(
            f"{base_table}: {len(refs)} irreplaceable parcel(s) are written "
            f"as wholly or partly lost ({summarise_refs(refs)}). The metric "
            "gives no units for a loss of irreplaceable habitat: it shows "
            "'Any Loss Unacceptable' and leaves the parcel out of the "
            "baseline total. If post-intervention is not finished, that is "
            "why. If the loss is real, it needs bespoke compensation.")
    if accounting[OVERSUBSCRIBED]:
        refs = accounting[OVERSUBSCRIBED]
        report.warn(
            f"{base_table}: {len(refs)} feature(s) have Retained and Enhanced "
            f"parts adding up to more than the feature itself "
            f"({summarise_refs(refs)}). The service refuses a file like "
            "this. Here each part is written at its own size, which "
            "overstates the baseline.")


def enhancements_for(baseline_lines):
    """The enhancement rows belonging to a run of baseline rows, in order.

    The metric collects the enhanced baseline rows into a dense list of its
    own and the enhancement sheet reads that list one row at a time, so the
    nth enhancement row belongs to the nth ENHANCED baseline row rather than
    to the nth baseline row. Filtering in baseline order reproduces exactly
    that, for a whole site or for one workbook's share of it.
    """
    return [line[ENHANCEMENT_KEY] for line in baseline_lines
            if ENHANCEMENT_KEY in line]


def _merge_key(line):
    """Everything but size, reference and comment: what makes two lines one."""
    ignored = ("ref", LINE_NUMBER, LINE_COMMENT, ENHANCEMENT_KEY)
    return tuple(sorted(
        (k, v) for k, v in line.items()
        if k not in SIZE_FIELDS and k not in ignored))


def _merge_into(target, line):
    """Add `line`'s sizes and comment onto a line it matches."""
    for field in SIZE_FIELDS:
        if field in line:
            target[field] = target.get(field, 0) + line[field]
    target["ref"] = f"{target['ref']} +"
    target[LINE_NUMBER] = target["ref"]
    # A comment does not stop two lines merging, and is not lost when they
    # do: each distinct comment is kept, in order.
    target[MERGED_COMMENTS].extend(
        c for c in [line.get(LINE_COMMENT)]
        if c and c not in target[MERGED_COMMENTS])


def _new_merged(line):
    copied = dict(line)
    copied[MERGED_COMMENTS] = (
        [line[LINE_COMMENT]] if line.get(LINE_COMMENT) else [])
    return copied


def consolidate_lines(lines):
    """Merge lines agreeing on everything but size, summing the sizes.

    The import tool offers the same thing. It is arithmetically free: units are
    linear in size and merged lines share every multiplier, so the totals do
    not move. What it costs is the per-parcel audit trail.

    IRREPLACEABLE LINES ARE NEVER MERGED WITH REPLACEABLE ONES. The key below
    is built from every field except size and reference, and `irreplaceable`
    is one of those fields, so a flagged parcel can only ever join a group of
    flagged parcels. That is the difference between doing this here and
    pressing Consolidate Data in the import tool, which cannot see the flag
    at all because the legacy CSVs have no column for it.

    COMMENTS DO NOT KEEP LINES APART. Lines that differ only in their
    comments merge, and the merged line holds each distinct comment.

    ENHANCED LINES ARE NEVER MERGED. The enhancement sheet is positional
    against the baseline sheet: its Nth row belongs to the Nth baseline row
    with an enhanced size. Merging two enhanced parcels that share their
    baseline values but head for different habitats would leave one baseline
    row against two enhancement rows, and every target after it would be
    applied to the wrong parcel, with nothing shown on screen.
    """
    merged = OrderedDict()
    kept = []
    for line in lines:
        if line.get(ENHANCED_SIZE):
            kept.append(line)
            continue
        key = _merge_key(line)
        if key in merged:
            _merge_into(merged[key], line)
        else:
            merged[key] = _new_merged(line)
    for line in merged.values():
        comments = line.pop(MERGED_COMMENTS)
        if comments:
            line[LINE_COMMENT] = " | ".join(comments)
    # enhanced lines keep their original position relative to each other
    return list(merged.values()) + kept


# ---------------------------------------------------------------------------
# Writing the workbook
# ---------------------------------------------------------------------------


def escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _without_type(attributes):
    """The attributes with each ``t="..."`` attribute removed.

    The replacement cell sets its own type, so the original type goes,
    along with the whitespace in front of it. A search for that whitespace
    retries across a run of spaces when the attribute is absent, which is
    super-linear. Each character is read once instead.
    """
    kept = []
    start = 0
    while True:
        found = attributes.find('t="', start)
        if found < 0:
            kept.append(attributes[start:])
            return "".join(kept)
        space = found
        while space > start and attributes[space - 1].isspace():
            space -= 1
        if space == found:
            kept.append(attributes[start:found + 1])
            start = found + 1
            continue
        closing = attributes.find('"', found + 3)
        if closing < 0:
            kept.append(attributes[start:])
            return "".join(kept)
        kept.append(attributes[start:space])
        start = closing + 1


def cell_xml(ref, attributes, value):
    """A replacement <c> keeping the original style, now holding a value."""
    keep = _without_type(attributes)
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{keep}><v>{value}</v></c>'
    return (f'<c r="{ref}"{keep} t="inlineStr"><is><t xml:space="preserve">'
            f"{escape(value)}</t></is></c>")


# Every cell on a sheet, with its reference and its attributes. Cells do not
# nest, so the lazy body stops at the first closing tag.
CELL_PATTERN = re.compile(
    r'<c r="([A-Z]+\d+)"((?:\s+[a-zA-Z:]+="[^"]*")*)\s*(?:/>|>.*?</c>)', re.S)


def set_cells(sheet_xml, values):
    """Put a value in each named cell, in one pass over the sheet.

    Searching the sheet once per cell is quadratic, and the sheets here are
    megabytes: each search reads from the start of the sheet and each
    replacement copies the whole of it again. Filling a habitat sheet that way
    costs several seconds per workbook and freezes whatever is driving it.
    One pass costs the same whether one cell is being set or five thousand.
    """
    found = set()

    def replace(match):
        ref = match.group(1)
        if ref not in values:
            return match.group(0)
        found.add(ref)
        return cell_xml(ref, match.group(2), values[ref])

    return CELL_PATTERN.sub(replace, sheet_xml), [
        ref for ref in values if ref not in found
    ]


def sheet_paths(archive):
    rels = {rel.get("Id"): rel.get("Target") for rel in
            ET.fromstring(archive.read(WORKBOOK_RELS))}
    paths = {}
    for sheet in ET.fromstring(archive.read(WORKBOOK_XML)).iter(f"{NS}sheet"):
        target = rels[sheet.get(f"{REL}id")].lstrip("/")
        paths[sheet.get("name")] = (
            target if target.startswith("xl/") else "xl/" + target)
    return paths


def cell_is_empty(archive, paths, sheet, ref):
    xml = archive.read(paths[sheet]).decode(UTF8)
    match = re.search(
        r'<c r="%s"(?:\s+[a-zA-Z:]+="[^"]*")*\s*(?:/>|>(.*?)</c>)' % ref, xml, re.S)
    return match is None or not (match.group(1) or "").strip()


def drop_incomplete_rows(xml, values):
    """Discard every edit on a row the sheet cannot hold in full.

    Some columns run out of styled cells a row or two before others do. Writing
    the cells that exist and silently skipping the rest would leave a row
    carrying a size with no habitat against it, which the metric would then
    total. A row that cannot be written whole is not written at all.

    Returns (values to write, refs that were dropped).
    """
    present = set(re.findall(r'<c r="([A-Z]+\d+)"', xml))
    by_row = defaultdict(list)
    for ref in values:
        by_row[re.sub(r"^[A-Z]+", "", ref)].append(ref)

    keep, dropped = {}, []
    for refs in by_row.values():
        if all(ref in present for ref in refs):
            keep.update({ref: values[ref] for ref in refs})
        else:
            dropped.extend(sorted(refs))
    return keep, dropped


def _without_calc_chain(rels):
    """The relationships with the calcChain entry removed.

    That entry is the self-closing ``<Relationship>`` whose target is
    ``calcChain.xml``. Finding it with two ``[^>]*`` retries every way of
    splitting the tag between them, which is super-linear. Each character
    is read once instead.
    """
    marker = 'Target="calcChain.xml"'
    open_tag = "<Relationship"
    kept = []
    start = 0
    while True:
        found = rels.find(marker, start)
        if found < 0:
            kept.append(rels[start:])
            return "".join(kept)
        tag = rels.rfind(open_tag, start, found)
        end = rels.find("/>", found + len(marker))
        name_ends = tag + len(open_tag)
        if (tag < 0 or end < 0 or rels[name_ends].isalnum()
                or ">" in rels[name_ends:end]):
            kept.append(rels[start:found + len(marker)])
            start = found + len(marker)
            continue
        kept.append(rels[start:tag])
        start = end + 2


def write_workbook(template, out_path, edits):
    """Apply edits to a copy of the metric workbook. Everything else is kept."""
    with zipfile.ZipFile(template) as archive:
        names = archive.namelist()
        paths = sheet_paths(archive)
        payload = {name: archive.read(name) for name in names}

    missing = {}
    for sheet, values in edits.items():
        path = paths[sheet]
        xml = payload[path].decode(UTF8)
        values, dropped = drop_incomplete_rows(xml, values)
        if dropped:
            missing[sheet] = dropped
        xml, gone = set_cells(xml, values)
        if gone:
            missing.setdefault(sheet, []).extend(gone)
        payload[path] = xml.encode(UTF8)

    workbook = payload[WORKBOOK_XML].decode(UTF8)
    if "fullCalcOnLoad" in workbook:
        workbook = re.sub(r'fullCalcOnLoad="[^"]*"', 'fullCalcOnLoad="1"', workbook)
    else:
        workbook = workbook.replace("<calcPr ", '<calcPr fullCalcOnLoad="1" ', 1)
    payload[WORKBOOK_XML] = workbook.encode(UTF8)

    # Drop the cached formula dependency chain so it cannot disagree with the
    # values just written; Excel rebuilds it on open.
    content_types = payload[CONTENT_TYPES_XML].decode(UTF8)
    payload[CONTENT_TYPES_XML] = re.sub(
        r'<Override PartName="/xl/calcChain\.xml"[^>]*/>', "",
        content_types).encode(UTF8)
    rels = payload[WORKBOOK_RELS].decode(UTF8)
    payload[WORKBOOK_RELS] = _without_calc_chain(rels).encode(UTF8)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as out:
        for name in names:
            if name == "xl/calcChain.xml":
                continue
            out.writestr(name, payload[name])
    return missing


# ---------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------


def cell_text(value):
    """Text a cell can hold: no character XML refuses, within Excel's limit."""
    text = XML_ILLEGAL.sub("", str(value))
    return text[:EXCEL_CELL_LIMIT], len(text) > EXCEL_CELL_LIMIT


def cells_for(row_number, columns, line, scale, cut=None):
    """The cells of one line. `cut` collects the refs of shortened comments."""
    out = {}
    for field, column in columns.items():
        if field not in line:
            continue
        value = line[field]
        if value in (None, ""):
            continue
        if field in SIZE_FIELDS:
            value = round(float(value) * scale, 6)
        elif field == LINE_COMMENT:
            value, shortened = cell_text(value)
            if shortened and cut is not None:
                cut.append(str(line.get("ref")))
        out[f"{column}{row_number}"] = value
    return out


def stage_capacity(kind, stage):
    _sheet, first, last, _columns = LAYOUT[kind][stage]
    return last - first + 1


def plan_parts(staged, consolidate, report):
    """Split the site into as many workbooks as its longest sheet requires.

    Every sheet in the metric takes 248 rows, and a site that needs more than
    that cannot be priced in one workbook at all. The parts are cut from the
    baseline and creation lines of each module and dealt out evenly, so a site
    needing two workbooks produces two half-full ones.

    Baseline and enhancement are cut together, never independently: the
    enhancement sheet reads the enhanced baseline rows of ITS OWN workbook, so
    an enhancement separated from its baseline would be applied to whichever
    parcel happened to take that position.
    """
    lines = {}
    for kind, base_table, pi_table, size_field, type_field, _scale in MODULES:
        rule, tolerance = ACCOUNTING[kind]
        text_years = []
        baseline, creation, accounting = build_lines(
            staged[kind], size_field, type_field, consolidate, rule,
            tolerance, text_years)
        lines[kind] = (baseline, creation)
        report_accounting(base_table, accounting, report)
        report_text_timing(pi_table, text_years, report)
        report.count(f"{kind} baseline", len(baseline))
        report.count(f"{kind} creation", len(creation))
        report.count(f"{kind} enhancement", len(enhancements_for(baseline)))

    # Trees share the area habitat sheets, after the area habitats. The
    # enhancement sheet takes the enhanced lines in the order the baseline
    # sheet holds them, so appending keeps the two in step.
    trees = staged.get(TREES)
    if trees and (trees[BASELINE] or trees["pi"]):
        rule, tolerance = ACCOUNTING[AREAS]
        text_years = []
        baseline, creation, accounting = build_lines(
            trees_as_areas(trees), "Area", "Habitat Type", consolidate, rule,
            tolerance, text_years)
        area_baseline, area_creation = lines[AREAS]
        lines[AREAS] = (area_baseline + baseline, area_creation + creation)
        report_accounting(TREE_TABLES[0], accounting, report)
        report_text_timing(TREE_TABLES[1], text_years, report)
        report.count("trees baseline", len(baseline))
        report.count("trees creation", len(creation))
        report.count("trees enhancement", len(enhancements_for(baseline)))

    parts = 1
    for kind, (baseline, creation) in lines.items():
        parts = max(
            parts,
            parts_needed(len(baseline), stage_capacity(kind, BASELINE)),
            parts_needed(len(creation), stage_capacity(kind, CREATION)),
            parts_needed(len(enhancements_for(baseline)),
                         stage_capacity(kind, ENHANCEMENT)),
        )
    parts = widen_for_enhancements(lines, parts)

    runs = {
        kind: (split_into_parts(baseline, parts),
               split_into_parts(creation, parts))
        for kind, (baseline, creation) in lines.items()
    }
    return [build_edits(runs, index, report) for index in range(parts)]


def widen_for_enhancements(lines, parts):
    """Add parts until no run of baseline rows overflows its enhancement sheet.

    The enhancement sheet holds two fewer rows than the baseline sheet it
    serves, so a run of 248 baseline parcels that happen to be all
    enhancements needs a finer split even though the baseline sheet has room.
    Counting the whole site cannot see that, because it is the run that
    overflows, not the total. Splitting further can only shorten the longest
    run, so this terminates.
    """
    while True:
        longest = 0
        for kind, (baseline, _creation) in lines.items():
            capacity = stage_capacity(kind, ENHANCEMENT)
            for run in split_into_parts(baseline, parts):
                longest = max(longest, len(enhancements_for(run)) - capacity)
        if longest <= 0 or parts >= max(
                (len(baseline) for baseline, _ in lines.values()), default=1):
            return parts
        parts += 1


def build_edits(runs, index, report):
    """The cell edits for one workbook: each module's share of each stage."""
    edits = {}
    for kind, _base, _pi, _size_field, _type_field, scale in MODULES:
        baseline_runs, creation_runs = runs[kind]
        baseline = baseline_runs[index]
        staged_lines = (
            (BASELINE, baseline),
            (CREATION, creation_runs[index]),
            (ENHANCEMENT, enhancements_for(baseline)),
        )
        for stage, module_lines in staged_lines:
            sheet, first, last, columns = LAYOUT[kind][stage]
            capacity = last - first + 1
            if len(module_lines) > capacity:
                # Unreachable by construction: the part count is taken from
                # the longest stage, and an enhancement run can never be
                # longer than the baseline run it was filtered from. Kept so
                # a future layout change fails loudly rather than silently
                # dropping rows.
                report.warn(
                    f"{sheet} holds {capacity} rows and part {index + 1} "
                    f"needs {len(module_lines)}. The extra rows were NOT "
                    "written.")
                module_lines = module_lines[:capacity]
            target = edits.setdefault(sheet, {})
            cut = []
            for offset, line in enumerate(module_lines):
                target.update(cells_for(first + offset, columns, line, scale,
                                        cut))
            if cut:
                report.warn(
                    f"{sheet}: {len(cut)} comment(s) are longer than the "
                    f"{EXCEL_CELL_LIMIT} characters an Excel cell holds, so "
                    f"they were cut short ({summarise_refs(cut)}). The whole "
                    "comment is still in the GeoPackage.")
    return edits


def workbook_extension(archive):
    """.xlsm for the metric with macros, .xlsx for the one without."""
    types = archive.read(CONTENT_TYPES_XML).decode(UTF8)
    return MACRO_EXTENSION if MACRO_WORKBOOK_TYPE in types else PLAIN_EXTENSION


def with_extension(path, extension):
    """`path`, ending in the extension the workbook's content needs."""
    stem, current = os.path.splitext(path)
    if current.lower() == extension:
        return path
    if current.lower() in (MACRO_EXTENSION, PLAIN_EXTENSION):
        return stem + extension
    return path + extension


def _progress(progress, fraction, message):
    """Report progress. False from the caller stops the run."""
    if progress is None:
        return True
    return progress(fraction, message) is not False


def _metric_sheet_names():
    return {LAYOUT[k][s][0] for k in LAYOUT for s in LAYOUT[k]}


def _check_metric(template_path):
    """(extension, whether the workbook already holds habitats).

    Raises ValueError when the file is not a Statutory Metric workbook.
    """
    with zipfile.ZipFile(template_path) as archive:
        try:
            paths = sheet_paths(archive)
        except KeyError:
            # .xlsb keeps its sheets as binary parts, and anything else is not
            # a workbook at all.
            raise ValueError(
                f"{os.path.basename(template_path)} is not a readable "
                "Statutory Metric workbook. Either version of the metric "
                "will do, with macros (.xlsm) or without (.xlsx), but not the "
                ".xlsb GIS import tool.")
        extension = workbook_extension(archive)
        for sheet in _metric_sheet_names():
            if sheet not in paths:
                raise ValueError(
                    f"{os.path.basename(template_path)} has no '{sheet}' sheet, "
                    "so it does not look like the Statutory Metric workbook.")
        occupied = not cell_is_empty(archive, paths, *OCCUPIED_PROBE)
    return extension, occupied


def _note_extension(out_path, extension, report):
    """`out_path` corrected to the blank metric's extension, with a note."""
    matched = with_extension(out_path, extension)
    if matched == out_path:
        return out_path
    form = "with" if extension == MACRO_EXTENSION else "without"
    report.note(
        f"The blank metric is the version {form} macros, so the filled "
        f"copy is written as {os.path.basename(matched)}. Excel will not "
        "open a workbook whose extension does not match its content.")
    return matched


def _has_habitat_edits(parts):
    return any(any(edits.values()) for edits in parts)


def _warn_missing_rows(target, missing, report):
    for sheet, refs in missing.items():
        rows = sorted({re.sub(r"^[A-Z]+", "", ref) for ref in refs}, key=int)
        report.warn(
            f"{os.path.basename(target)}, {sheet}: {len(rows)} row(s) "
            "skipped because the sheet runs out of cells before the last "
            f"row of its stated range (row(s) {', '.join(rows)}). Nothing "
            "partial was written.")


def _write_metric_parts(template_path, out_path, parts, report, progress):
    """Write each workbook. Returns (cells written, whether the run stopped)."""
    written = 0
    for index, edits in enumerate(parts):
        label = (f"Writing workbook {index + 1} of {len(parts)}..."
                 if len(parts) > 1 else "Writing the workbook...")
        if not _progress(progress, 0.05 + 0.95 * index / len(parts), label):
            report.warn(
                f"Stopped after {index} of {len(parts)} workbook(s). Those "
                "already written are complete, but they hold only part of "
                "the site.")
            return written, True
        target = part_path(out_path, index, len(parts))
        _warn_missing_rows(
            target, write_workbook(template_path, target, edits), report)
        written += sum(len(values) for values in edits.values())
        report.paths.append(target)
        report.note(f"Metric workbook: {target}")
    return written, False


def _warn_split_site(parts, report):
    report.warn(
        "This site does not fit one workbook, so it was written as "
        f"{len(parts)} of them. The metric holds "
        f"{stage_capacity(AREAS, BASELINE)} rows per sheet, and "
        f"{stage_capacity(AREAS, ENHANCEMENT)} on the enhancement "
        "sheets. Each workbook is a "
        "complete, valid metric for its own share of the site, and the "
        "site's answer is the SUM of their unit columns. Do not read a "
        "net gain percentage off one workbook: a percentage of part of a "
        "site means nothing. Add the baseline units and the "
        f"post-intervention units across all {len(parts)}, then take the "
        "percentage of those two totals."
    )


def convert(input_path, template_path, out_path, consolidate=False,
            allow_occupied=False, progress=None):
    """Fill a copy of the metric workbook from a staged GeoPackage.

    `template_path` is either form of the metric, with macros or without.
    The copy keeps that form, so `out_path` has its extension corrected to
    match if it names the other one.

    `progress`, when given, is called with a fraction from 0 to 1 and a line
    of text as each workbook is written, so a caller can show how far along
    it is. Returning False from it stops the run between workbooks.
    """
    report = Report()
    _progress(progress, 0.0, "Reading the habitats...")
    staged = read_staged(input_path)
    extension, occupied = _check_metric(template_path)
    if occupied and not allow_occupied:
        raise ValueError(
            f"{os.path.basename(template_path)} already holds habitat data. "
            "Point this at a blank copy of the metric so nothing is "
            "overwritten.")
    out_path = _note_extension(out_path, extension, report)

    _progress(progress, 0.05, "Working out what goes where...")
    check_post_intervention(staged, report)
    check_needed_values(staged, report)
    check_trees(staged.get(TREES), report)
    parts = plan_parts(staged, consolidate, report)
    if not _has_habitat_edits(parts):
        report.warn("Nothing was written: the GeoPackage holds no habitats.")

    written, stopped = _write_metric_parts(
        template_path, out_path, parts, report, progress)
    _progress(progress, 1.0, "Done.")
    report.count("cells written", written)
    report.count("workbooks written", len(report.paths))
    if len(parts) > 1 and not stopped:
        _warn_split_site(parts, report)
    report.note("Open it in Excel and let it recalculate. On-site tabs only.")
    return report


def print_report(report):
    print("\nRows mapped")
    for key, value in report.counts.items():
        print(f"  {key}".ljust(50, ".") + f" {value}")
    if report.lines:
        print("\nNotes:")
        for line in report.lines:
            print(f"  - {line}")
    if report.warnings:
        print("\nWARNINGS — read before relying on the numbers:")
        for line in report.warnings:
            print(f"  ! {line}")
    print(
        "\nNot written: the off-site tabs and the Irreplaceable Habitats "
        "\nsheet. The irreplaceable flag itself IS written, on the on-site "
        "\nbaseline habitat sheet. Individual trees are written on the area "
        "\nhabitat sheets, at the tree helper's area for their size class."
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=("Fill a copy of the Statutory Biodiversity Metric "
                     "workbook from a BNG Service staged GeoPackage."))
    parser.add_argument("input", help="the staged .gpkg from the new template")
    parser.add_argument("--metric", required=True,
                        help="a blank copy of the metric, .xlsm or .xlsx")
    parser.add_argument("-o", "--out", required=True,
                        help="where to write the filled workbook")
    parser.add_argument("--consolidate", action="store_true",
                        help="merge rows agreeing on everything but size")
    parser.add_argument("--allow-occupied", action="store_true",
                        help="write even if the metric already holds habitats")
    args = parser.parse_args(argv)

    for path in (args.input, args.metric):
        if not os.path.exists(path):
            print(f"error: file not found: {path}", file=sys.stderr)
            return 1
    try:
        report = convert(args.input, args.metric, args.out, args.consolidate,
                         args.allow_occupied)
    except (sqlite3.Error, ValueError, zipfile.BadZipFile, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
