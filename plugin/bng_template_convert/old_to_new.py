#!/usr/bin/env python3
"""
Convert a pair of legacy Natural England GeoPackages into a single BNG Service
(staged) GeoPackage for the new template.

    old template   2 files, one table per habitat type, uploaded separately
                     |
                     v
    new template   1 file,  Baseline + Post-Intervention tables per habitat type

This is the harder direction: the legacy format never recorded which baseline
feature a post-intervention feature came from, so lineage has to be rebuilt.
The script stamps only what it can prove — a post-intervention row whose
reference matches a baseline row — and deliberately leaves everything else
unstamped so the service resolves it by area-weighted geometry overlap and
warns, rather than this script guessing with cruder maths and staying silent.

Zero dependencies: Python 3.8+, no GDAL, no QGIS, no network. Input files are
never modified.

Usage:
    python3 old_to_new.py --baseline BASE.gpkg --post-intervention PI.gpkg -o out/
    python3 old_to_new.py --baseline BASE.gpkg --dry-run

See README.md for the full walkthrough and what needs checking afterwards.
"""

import argparse
import os
import re
import sqlite3
import struct
import sys
import uuid
from collections import defaultdict

# Works both as a standalone script and as a module inside the QGIS
# plugin package, where the import has to be relative.
try:
    from .gpkg_common import (
        blob_wkt,
        create_feature_table,
        create_gpkg_system_tables,
        demote_multipolygon_blob_to_polygon,
        feature_table_names,
        line_blob_length_m,
        numeric,
        tree_count_warning,
        trees_counted_above_one,
        plain_label,
        polygon_blob_area_sqm,
        quote_ident,
        quoted_names,
        read_feature_table,
        read_only_uri,
        read_srs_rows,
        FORMAT_NAME,
        TEMPLATE_VERSION,
        read_template_version,
        register_spatial_functions,
        resolve_table_name,
        sq_metres_to_hectares,
        summarise_list,
        summarise_refs,
        update_layer_extent,
        write_template_version,
    )
except ImportError:  # pragma: no cover - running as a plain script
    from gpkg_common import (
        blob_wkt,
        create_feature_table,
        create_gpkg_system_tables,
        demote_multipolygon_blob_to_polygon,
        feature_table_names,
        line_blob_length_m,
        numeric,
        tree_count_warning,
        trees_counted_above_one,
        plain_label,
        polygon_blob_area_sqm,
        quote_ident,
        quoted_names,
        read_feature_table,
        read_only_uri,
        read_srs_rows,
        FORMAT_NAME,
        TEMPLATE_VERSION,
        read_template_version,
        register_spatial_functions,
        resolve_table_name,
        sq_metres_to_hectares,
        summarise_list,
        summarise_refs,
        update_layer_extent,
        write_template_version,
    )

try:
    from .reference_lists import (
        BASELINE_SIGNIFICANCE,
        IRREPLACEABLE_COLUMN,
        NE_SIGNIFICANCE_LOW,
        NE_SIGNIFICANCE_MEDIUM,
        NOT_APPLICABLE,
        PROPOSED_SIGNIFICANCE,
        SIGNIFICANCE_LOW,
        TREE_NEWLY_PLANTED,
        VERTICAL_HABITATS,
        fill_template_values,
        has_baseline_part,
        service_significance,
        to_service_labels,
    )
    from .to_metric import MODULES as METRIC_MODULES, check_needed_values
except ImportError:  # pragma: no cover - running as a plain script
    from reference_lists import (
        BASELINE_SIGNIFICANCE,
        IRREPLACEABLE_COLUMN,
        NE_SIGNIFICANCE_LOW,
        NE_SIGNIFICANCE_MEDIUM,
        NOT_APPLICABLE,
        PROPOSED_SIGNIFICANCE,
        SIGNIFICANCE_LOW,
        TREE_NEWLY_PLANTED,
        VERTICAL_HABITATS,
        fill_template_values,
        has_baseline_part,
        service_significance,
        to_service_labels,
    )
    from to_metric import MODULES as METRIC_MODULES, check_needed_values

# What a blank costs on the way in: the converted site carries the gap.
# Irreplaceable Habitat is left out of the check because the legacy format
# has no such column, and that is already said once for the whole file.
# Every staged habitat table holds its reference in this one column.
REF_FIELD = "Habitat Ref"
SPATIAL_RISK = "Spatial risk category"

AREA_HABITATS_BASELINE = "Area Habitats Baseline"
AREA_HABITATS_POST_INTERVENTION = "Area Habitats Post-Intervention"
BASELINE_BROAD_HABITAT_TYPE = "Baseline Broad Habitat Type"
BASELINE_CONDITION = "Baseline Condition"
BASELINE_DISTINCTIVENESS = "Baseline Distinctiveness"
BASELINE_ENCROACHMENT_INTO_WATERCOURSE = (
    "Baseline Encroachment into Watercourse")
BASELINE_ENCROACHMENT_INTO_RIPARIAN_ZONE = (
    "Baseline Encroachment into riparian zone")
BASELINE_HABITAT_TYPE = "Baseline Habitat Type"
BASELINE_HEDGE_TYPE = "Baseline Hedge Type"
BASELINE_LENGTH = "Baseline Length"
BASELINE_PARCEL_REF = "Baseline Parcel Ref"
BASELINE_RIVER_TYPE = "Baseline River Type"
BASELINE_RURAL_OR_URBAN_TREE = "Baseline Rural or Urban Tree"
BASELINE_TREE_SIZE = "Baseline Tree Size"
BASELINE_TREE_TYPE = "Baseline Tree Type"
CATEGORY = "Category"
COMMENT = "Comment"
DELAY_IN_STARTING_HABITAT_CREATION_ENHANCEMENT_IN_YEARS = (
    "Delay in starting habitat creation/enhancement in years")
DELAY_IN_STARTING_HABITAT_CREATION_YEARS = (
    "Delay in starting habitat creation/years")
ENHANCEMENT_TYPE = "Enhancement Type"
HABITAT_CREATED_ENHANCED_IN_ADVANCE_YEARS = (
    "Habitat Created/Enhanced in advance/years")
HABITAT_CREATED_IN_ADVANCE_YEARS = "Habitat created in advance/years"
# The legacy meanders layer spells it with a trailing space.
MEANDER_ADVANCE_YEARS = HABITAT_CREATED_IN_ADVANCE_YEARS + " "
HABITATS = "Habitats"
HEDGEROWS = "Hedgerows"
HEDGEROWS_BASELINE = "Hedgerows Baseline"
HEDGEROWS_POST_INTERVENTION = "Hedgerows Post-Intervention"
INDIVIDUAL_TREES_BASELINE = "Individual Trees Baseline"
INDIVIDUAL_TREES_POST_INTERVENTION = "Individual Trees Post-Intervention"
LINESTRING = "LINESTRING"
LENGTH = "Length"
MEANDER_ENHANCEMENT_TYPE = "Meanders"
POLYGON = "POLYGON"
PARCEL_REF = "Parcel Ref"
PARENT_REF = "Parent Ref"
PROPOSED_BROAD_HABITAT_TYPE = "Proposed Broad Habitat Type"
PROPOSED_CONDITION = "Proposed Condition"
PROPOSED_DISTINCTIVENESS = "Proposed Distinctiveness"
PROPOSED_ENCROACHMENT_INTO_WATERCOURSE = (
    "Proposed Encroachment into Watercourse")
PROPOSED_ENCROACHMENT_INTO_RIPARIAN_ZONE = (
    "Proposed Encroachment into riparian zone")
PROPOSED_HABITAT_TYPE = "Proposed Habitat Type"
PROPOSED_HEDGE_TYPE = "Proposed Hedge Type"
PROPOSED_RIVER_TYPE = "Proposed River Type"
PROPOSED_RURAL_OR_URBAN_TREE = "Proposed Rural or Urban Tree"
PROPOSED_TREE_SIZE = "Proposed Tree Size"
PROPOSED_TREE_TYPE = "Proposed Tree Type"
LEGACY_REDLINE = "Red Line Boundary"
RETENTION_CATEGORY = "Retention Category"
TREE_REF = "Tree Ref"
TREES = "Trees"
WATERCOURSES = "Watercourses"
WATERCOURSES_BASELINE = "Watercourses Baseline"
WATERCOURSES_POST_INTERVENTION = "Watercourses Post-Intervention"
GEOM = "_geom"
PARENT_REF_KEY = "_parent_ref"
PI_REF = "_pi_ref"
AREAS = "areas"
BASELINE = "baseline"
COLUMNS = "columns"
FEATURE_UUID = "feature_uuid"
GEOM_COLUMN = "geom_column"
GEOM_TYPE = "geom_type"
HEDGEROWS_KEY = "hedgerows"
MEANDERS = "meanders"
PARENT_UUID = "parent_uuid"
REDLINE = "redline"
TREES_KEY = "trees"
WATERCOURSES_KEY = "watercourses"

INCOMING_GAP_CONSEQUENCE = (
    "Fill them in before uploading or exporting to the metric: until then "
    "neither can score those rows.")

# ---------------------------------------------------------------------------
# New-template schema — the columns of Layers/BNG Service Layers.gpkg, so the
# output can replace that file inside a copy of the template project. Filling
# a template with --into writes only the columns that template has.
# ---------------------------------------------------------------------------

BASELINE_TAIL = [(COMMENT, "TEXT"), (FEATURE_UUID, "TEXT")]
PI_TAIL = [(COMMENT, "TEXT"), (PARENT_UUID, "TEXT"), ("parent_geom", "TEXT")]
AREA_BASELINE_HEAD = [
    (REF_FIELD, "TEXT"),
    (BASELINE_BROAD_HABITAT_TYPE, "TEXT"),
    (BASELINE_HABITAT_TYPE, "TEXT"),
    (BASELINE_DISTINCTIVENESS, "TEXT"),
    (BASELINE_CONDITION, "TEXT"),
    (BASELINE_SIGNIFICANCE, "TEXT"),
    (IRREPLACEABLE_COLUMN, "TEXT"),
    ("Area", "REAL"),
]
AREA_PI_HEAD = [
    (REF_FIELD, "TEXT"),
    (PARENT_REF, "TEXT"),
    (BASELINE_BROAD_HABITAT_TYPE, "TEXT"),
    (BASELINE_HABITAT_TYPE, "TEXT"),
    (BASELINE_DISTINCTIVENESS, "TEXT"),
    (BASELINE_CONDITION, "TEXT"),
    (BASELINE_SIGNIFICANCE, "TEXT"),
    (IRREPLACEABLE_COLUMN, "TEXT"),
    (RETENTION_CATEGORY, "TEXT"),
    (PROPOSED_BROAD_HABITAT_TYPE, "TEXT"),
    (PROPOSED_HABITAT_TYPE, "TEXT"),
    (PROPOSED_DISTINCTIVENESS, "TEXT"),
    (PROPOSED_CONDITION, "TEXT"),
    (PROPOSED_SIGNIFICANCE, "TEXT"),
    (HABITAT_CREATED_IN_ADVANCE_YEARS, "TEXT"),
    (DELAY_IN_STARTING_HABITAT_CREATION_YEARS, "TEXT"),
    (SPATIAL_RISK, "TEXT"),
    ("Area", "REAL"),
]

STAGED_LAYERS = {
    LEGACY_REDLINE: {
        GEOM_COLUMN: "geom",
        GEOM_TYPE: POLYGON,
        COLUMNS: [
            ("Site Name", "TEXT"),
            ("Location", "TEXT"),
            ("Survey Date", "DATE"),
            ("Survey Details", "TEXT"),
            ("Mapped by", "TEXT"),
            ("Company", "TEXT"),
            ("Base Map", "TEXT"),
        ],
    },
    AREA_HABITATS_BASELINE: {
        GEOM_COLUMN: "geom",
        GEOM_TYPE: POLYGON,
        COLUMNS: AREA_BASELINE_HEAD + BASELINE_TAIL,
    },
    AREA_HABITATS_POST_INTERVENTION: {
        GEOM_COLUMN: "geom",
        GEOM_TYPE: POLYGON,
        COLUMNS: AREA_PI_HEAD + PI_TAIL,
    },
    "Vertical Area Habitats Baseline": {
        GEOM_COLUMN: "geom",
        GEOM_TYPE: LINESTRING,
        COLUMNS: AREA_BASELINE_HEAD + BASELINE_TAIL,
    },
    "Vertical Area Habitats Post-Intervention": {
        GEOM_COLUMN: "geom",
        GEOM_TYPE: LINESTRING,
        COLUMNS: AREA_PI_HEAD + PI_TAIL,
    },
    HEDGEROWS_BASELINE: {
        GEOM_COLUMN: "geom",
        GEOM_TYPE: LINESTRING,
        COLUMNS: [
            (REF_FIELD, "TEXT"),
            (BASELINE_HEDGE_TYPE, "TEXT"),
            (BASELINE_DISTINCTIVENESS, "TEXT"),
            (BASELINE_CONDITION, "TEXT"),
            (BASELINE_SIGNIFICANCE, "TEXT"),
            (LENGTH, "REAL"),
        ]
        + BASELINE_TAIL,
    },
    HEDGEROWS_POST_INTERVENTION: {
        GEOM_COLUMN: "geom",
        GEOM_TYPE: LINESTRING,
        COLUMNS: [
            (REF_FIELD, "TEXT"),
            (PARENT_REF, "TEXT"),
            (BASELINE_HEDGE_TYPE, "TEXT"),
            (BASELINE_DISTINCTIVENESS, "TEXT"),
            (BASELINE_CONDITION, "TEXT"),
            (BASELINE_SIGNIFICANCE, "TEXT"),
            (BASELINE_LENGTH, "REAL"),
            (RETENTION_CATEGORY, "TEXT"),
            (PROPOSED_HEDGE_TYPE, "TEXT"),
            (PROPOSED_DISTINCTIVENESS, "TEXT"),
            (PROPOSED_CONDITION, "TEXT"),
            (PROPOSED_SIGNIFICANCE, "TEXT"),
            (HABITAT_CREATED_IN_ADVANCE_YEARS, "TEXT"),
            (DELAY_IN_STARTING_HABITAT_CREATION_YEARS, "TEXT"),
            (SPATIAL_RISK, "TEXT"),
            (LENGTH, "REAL"),
        ]
        + PI_TAIL,
    },
    WATERCOURSES_BASELINE: {
        GEOM_COLUMN: "geom",
        GEOM_TYPE: LINESTRING,
        COLUMNS: [
            (REF_FIELD, "TEXT"),
            (BASELINE_RIVER_TYPE, "TEXT"),
            (BASELINE_DISTINCTIVENESS, "TEXT"),
            (BASELINE_CONDITION, "TEXT"),
            (BASELINE_SIGNIFICANCE, "TEXT"),
            (BASELINE_ENCROACHMENT_INTO_WATERCOURSE, "TEXT"),
            (BASELINE_ENCROACHMENT_INTO_RIPARIAN_ZONE, "TEXT"),
            (LENGTH, "REAL"),
        ]
        + BASELINE_TAIL,
    },
    WATERCOURSES_POST_INTERVENTION: {
        GEOM_COLUMN: "geom",
        GEOM_TYPE: LINESTRING,
        COLUMNS: [
            (REF_FIELD, "TEXT"),
            (PARENT_REF, "TEXT"),
            (BASELINE_RIVER_TYPE, "TEXT"),
            (BASELINE_DISTINCTIVENESS, "TEXT"),
            (BASELINE_CONDITION, "TEXT"),
            (BASELINE_SIGNIFICANCE, "TEXT"),
            (BASELINE_ENCROACHMENT_INTO_WATERCOURSE, "TEXT"),
            (BASELINE_ENCROACHMENT_INTO_RIPARIAN_ZONE, "TEXT"),
            (BASELINE_LENGTH, "REAL"),
            (RETENTION_CATEGORY, "TEXT"),
            (PROPOSED_RIVER_TYPE, "TEXT"),
            (PROPOSED_DISTINCTIVENESS, "TEXT"),
            (PROPOSED_CONDITION, "TEXT"),
            (PROPOSED_SIGNIFICANCE, "TEXT"),
            (PROPOSED_ENCROACHMENT_INTO_WATERCOURSE, "TEXT"),
            (PROPOSED_ENCROACHMENT_INTO_RIPARIAN_ZONE, "TEXT"),
            (ENHANCEMENT_TYPE, "TEXT"),
            (HABITAT_CREATED_IN_ADVANCE_YEARS, "TEXT"),
            (DELAY_IN_STARTING_HABITAT_CREATION_YEARS, "TEXT"),
            (SPATIAL_RISK, "TEXT"),
            (LENGTH, "REAL"),
        ]
        + PI_TAIL,
    },
    INDIVIDUAL_TREES_BASELINE: {
        GEOM_COLUMN: "geom",
        GEOM_TYPE: "POINT",
        COLUMNS: [
            (REF_FIELD, "TEXT"),
            (BASELINE_TREE_SIZE, "TEXT"),
            (BASELINE_TREE_TYPE, "TEXT"),
            (BASELINE_RURAL_OR_URBAN_TREE, "TEXT"),
            (BASELINE_CONDITION, "TEXT"),
            (BASELINE_SIGNIFICANCE, "TEXT"),
            (IRREPLACEABLE_COLUMN, "TEXT"),
        ]
        + BASELINE_TAIL,
    },
    INDIVIDUAL_TREES_POST_INTERVENTION: {
        GEOM_COLUMN: "geom",
        GEOM_TYPE: "POINT",
        COLUMNS: [
            (REF_FIELD, "TEXT"),
            (PARENT_REF, "TEXT"),
            (BASELINE_TREE_SIZE, "TEXT"),
            (BASELINE_TREE_TYPE, "TEXT"),
            (BASELINE_RURAL_OR_URBAN_TREE, "TEXT"),
            (BASELINE_CONDITION, "TEXT"),
            (BASELINE_SIGNIFICANCE, "TEXT"),
            (IRREPLACEABLE_COLUMN, "TEXT"),
            (RETENTION_CATEGORY, "TEXT"),
            (PROPOSED_TREE_SIZE, "TEXT"),
            (PROPOSED_TREE_TYPE, "TEXT"),
            (PROPOSED_RURAL_OR_URBAN_TREE, "TEXT"),
            (PROPOSED_CONDITION, "TEXT"),
            (PROPOSED_SIGNIFICANCE, "TEXT"),
            (CATEGORY, "TEXT"),
            (HABITAT_CREATED_ENHANCED_IN_ADVANCE_YEARS, "TEXT"),
            (DELAY_IN_STARTING_HABITAT_CREATION_ENHANCEMENT_IN_YEARS, "TEXT"),
            (SPATIAL_RISK, "TEXT"),
        ]
        + PI_TAIL,
    },
}

# The layers holding area habitats. Named explicitly rather than matched on the
# word "Habitats", which is also a substring of "Vertical Area Habitats *".
AREA_HABITAT_LAYERS = (AREA_HABITATS_BASELINE,
                       AREA_HABITATS_POST_INTERVENTION)
TREE_LAYERS = (INDIVIDUAL_TREES_BASELINE,
               INDIVIDUAL_TREES_POST_INTERVENTION)


LEGACY_MEANDERS = "Water course enhancement through meanders"

# Retention categories, legacy -> new.
#
# The new template dropped "Lost": removal is recorded by simply leaving the
# feature out. Area habitats are the exception — every square metre inside the
# red line has to be accounted for, and the Statutory Metric treats built-over
# ground as *creating* the new surface, so a lost parcel becomes "Created".
RETENTION_CREATED = "Created"
RETENTION_LOST = "Lost"
CONTINUING_CATEGORIES = ("Retained", "Enhanced")
TREE_CATEGORY_EXISTING = "Existing"

SITE_DETAIL_FIELDS = [
    "Site Name",
    "Location",
    "Survey Date",
    "Survey Details",
    "Mapped by",
    "Company",
    "Base Map",
]

ALPHABET_SIZE = 26


class Report:
    def __init__(self):
        self.lines = []
        self.warnings = []
        self.counts = {}

    def note(self, message):
        self.lines.append(message)

    def warn(self, message):
        self.warnings.append(message)

    def count(self, key, value):
        self.counts[key] = value


# ---------------------------------------------------------------------------
# Baseline index — the lineage the legacy format never recorded
# ---------------------------------------------------------------------------


class BaselineIndex:
    """Baseline features keyed by reference, with the stamps a child needs."""

    def __init__(self):
        self._by_ref = {}

    def add(self, ref, feature_uuid, geom, size):
        if ref is None or ref == "":
            return
        # A duplicated baseline ref is ambiguous; the first wins and the
        # caller reports it, because guessing between them would be worse.
        self._by_ref.setdefault(
            ref, {"uuid": feature_uuid, "geom": geom, "size": size}
        )

    def get(self, ref):
        return self._by_ref.get(ref)

    def refs(self):
        return set(self._by_ref)


def new_uuid():
    """Match the template's uuid('WithoutBraces') default."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Reading the legacy pair
# ---------------------------------------------------------------------------


def read_legacy(path):
    """Read every layer of a legacy GeoPackage we know how to carry over."""
    conn = sqlite3.connect(read_only_uri(path), uri=True)
    try:
        return {
            REDLINE: read_feature_table(conn, LEGACY_REDLINE),
            AREAS: read_feature_table(conn, HABITATS),
            HEDGEROWS_KEY: read_feature_table(conn, HEDGEROWS),
            WATERCOURSES_KEY: read_feature_table(conn, "Rivers"),
            TREES_KEY: read_feature_table(conn, "Urban Trees"),
            MEANDERS: read_feature_table(conn, LEGACY_MEANDERS),
            "srs": read_srs_rows(conn),
        }
    finally:
        conn.close()


def site_details(legacy):
    """Collapse the site details legacy repeats on every row into one record.

    Takes the first non-empty value seen for each field, so a partly-filled
    layer does not blank out a field another layer has.
    """
    details = dict.fromkeys(SITE_DETAIL_FIELDS)
    sources = [REDLINE, AREAS, HEDGEROWS_KEY, WATERCOURSES_KEY, TREES_KEY]
    for key in sources:
        for row in legacy.get(key, []):
            for field in SITE_DETAIL_FIELDS:
                if details[field] in (None, "") and row.get(field) not in (None, ""):
                    details[field] = row.get(field)
    return details


# ---------------------------------------------------------------------------
# Reference handling
# ---------------------------------------------------------------------------


BREADCRUMB_PARENT = re.compile(r"\[parent=([^\];]+)\]")
BREADCRUMB_PI = re.compile(r"\[pi=([^\];]+)\]")
BREADCRUMBS = re.compile(r" ?\[(?:parent|pi)=[^\];]+\]")


def read_breadcrumbs(rows):
    """Recover lineage from the breadcrumbs new_to_old.py --carry-lineage left.

    Converting to the legacy format has to discard the parent link; that flag
    parks it in the Comment column, which the legacy service ignores. Reading it
    back turns a round trip into an exact restoration rather than a re-guess.
    """
    found = 0
    for row in rows:
        comment = row.get(COMMENT) or row.get("Comments") or ""
        parent = BREADCRUMB_PARENT.search(str(comment))
        own = BREADCRUMB_PI.search(str(comment))
        if parent:
            row[PARENT_REF_KEY] = parent.group(1).strip()
            found += 1
        if own:
            row[PI_REF] = own.group(1).strip()
            found += 1
    return found


def user_comment(row):
    """The surveyor's own comment on a legacy row, without the breadcrumbs.

    Legacy spells the column "Comment" on habitats and trees and "Comments"
    on hedgerows and rivers. The breadcrumbs are lineage, which the template
    keeps in its own columns, so they are taken out of the text.
    """
    comment = row.get(COMMENT) or row.get("Comments")
    if not isinstance(comment, str):
        return comment
    # The conversion out joins a breadcrumb to the comment with one space.
    text = BREADCRUMBS.sub("", comment).strip()
    return text or None


def drop_lost_rows(rows, ref_key, label, report, index=None):
    """Remove legacy 'Lost' rows: the new template records removal by absence.

    Done before references are made unique so a feature that merely outlived a
    sibling is not renamed for nothing.

    Dropping a 'Lost' row is only safe while the baseline still holds the
    feature, because the baseline is then the sole surviving record that it
    ever existed and the service recovers the loss by subtraction. A legacy
    pair is two files a user maintains by hand, so the two can disagree, and a
    'Lost' row naming a reference the baseline does not have is that
    disagreement: the feature is dropped here, was never in the baseline, and
    leaves the conversion having never existed. The loss goes unrecorded and
    the reported gain is too large. Passing the baseline index turns that
    silent case into a warning; omitting it keeps the old behaviour for callers
    that have no index to offer.
    """
    kept = []
    dropped = []
    orphaned = []
    for row in rows:
        if row.get(RETENTION_CATEGORY) != RETENTION_LOST:
            kept.append(row)
            continue
        ref = row.get(ref_key)
        dropped.append(ref)
        if index is not None and index.get(ref) is None:
            orphaned.append(ref)
    if dropped:
        report.note(
            f"{label}: dropped {len(dropped)} 'Lost' row(s) "
            f"({summarise_refs(dropped)}) — the new template records removal "
            "by leaving the feature out"
        )
    if orphaned:
        report.warn(
            f"{label}: {len(orphaned)} 'Lost' row(s) name a baseline feature "
            f"that is not in the baseline file ({summarise_refs(orphaned)}). "
            "Those features are removed by the scheme but were never recorded "
            "as existing, so nothing is left to subtract and the reported gain "
            "will be too large. Check the baseline file covers everything the "
            "post-intervention file says was lost."
        )
    return kept


def unique_pi_refs(rows, ref_key, report, label):
    """Give post-intervention rows distinct references, as the template does.

    Legacy allows several post-intervention rows to share one reference (its
    only way of saying "part of this feature became X and part became Y"). The
    new template gives each its own Habitat Ref and records the shared origin
    in Parent Ref instead.
    """
    occurrences = defaultdict(list)
    for row in rows:
        if row.get(PI_REF):
            continue  # already recovered from a breadcrumb
        occurrences[row.get(ref_key)].append(row)

    taken = {ref for ref, items in occurrences.items() if len(items) == 1}
    renamed_groups = []
    for ref, items in occurrences.items():
        if ref in (None, "") or len(items) == 1:
            continue
        names = []
        for index, row in enumerate(items):
            candidate = _next_free_ref(ref, index, taken)
            taken.add(candidate)
            row[PI_REF] = candidate
            names.append(candidate)
        renamed_groups.append((ref, names))

    for row in rows:
        row.setdefault(PI_REF, row.get(ref_key))

    # One line for the layer, not one per reference: a site that splits a
    # thousand features would otherwise bury every other line in the report.
    if renamed_groups:
        # Four, not the usual eight: each entry is itself a list of names.
        examples = summarise_list(
            (f"'{ref}' -> {', '.join(names)}" for ref, names in renamed_groups),
            limit=4,
        )
        report.note(
            f"{label}: {len(renamed_groups)} reference(s) appeared on more "
            f"than one post-intervention row and were given distinct Habitat Refs, "
            f"each keeping its original as Parent Ref ({examples})"
        )


def _next_free_ref(ref, index, taken):
    attempt = index
    while True:
        suffix = chr(ord("a") + attempt % ALPHABET_SIZE)
        cycle = attempt // ALPHABET_SIZE
        candidate = f"{ref}{suffix}" if cycle == 0 else f"{ref}{suffix}{cycle}"
        if candidate not in taken:
            return candidate
        attempt += 1


def stamp_parent(values, parent_ref, index, report_unmatched, own_ref=None):
    """Attach the lineage stamps for a resolved parent, if there is one.

    Two quite different things arrive here looking the same, and telling them
    apart is the difference between a warning worth acting on and noise. A row
    carrying a breadcrumb this tool left on the way out names a parent
    outright, so a parent that is not in the baseline file is a broken link. A
    row carrying no breadcrumb names nothing: the legacy format never recorded
    lineage, so the only candidate is the row's own reference, and a miss
    there almost always means the feature is simply new.

    Returns True when the row was stamped. An unmatched continuing row is left
    entirely unstamped on purpose: the service then resolves it by area-weighted
    overlap and raises a "parent inferred" warning the user can see and check.
    """
    declared = bool(parent_ref)
    candidate = parent_ref or own_ref
    parent = index.get(candidate) if candidate else None
    if parent is None:
        if candidate:
            report_unmatched.append((candidate, declared))
        return False
    values[PARENT_REF] = candidate
    values[PARENT_UUID] = parent["uuid"]
    values["parent_geom"] = parent["geom"]
    return True


# ---------------------------------------------------------------------------
# Row mapping — baseline
# ---------------------------------------------------------------------------


def build_area_baseline(rows, report):
    """Baseline area habitats, each with a fresh uuid and its shape as text.

    The shape is taken after a single-part multipolygon is demoted, so a
    child's parent_geom is the shape the baseline row stores.
    """
    index = BaselineIndex()
    out = []
    multipart = 0
    duplicate_refs = _duplicate_refs(rows, PARCEL_REF)
    for row in rows:
        blob = row.get(GEOM)
        if blob is not None:
            blob, was_multipart = demote_multipolygon_blob_to_polygon(blob)
            multipart += 1 if was_multipart else 0
        feature_uuid = new_uuid()
        # legacy stores square metres; the new template's column is hectares
        area = sq_metres_to_hectares(row.get("Area"))
        if area is None and blob is not None:
            area = sq_metres_to_hectares(polygon_blob_area_sqm(blob))
        index.add(row.get(PARCEL_REF), feature_uuid, blob_wkt(blob), area)
        out.append(
            (
                blob,
                {
                    REF_FIELD: row.get(PARCEL_REF),
                    BASELINE_BROAD_HABITAT_TYPE: row.get(
                        BASELINE_BROAD_HABITAT_TYPE
                    ),
                    BASELINE_HABITAT_TYPE: row.get(BASELINE_HABITAT_TYPE),
                    BASELINE_DISTINCTIVENESS: row.get(BASELINE_DISTINCTIVENESS),
                    BASELINE_CONDITION: row.get(BASELINE_CONDITION),
                    BASELINE_SIGNIFICANCE: row.get(
                        BASELINE_SIGNIFICANCE
                    ),
                    # No legacy column: filled below where the habitat
                    # allows only one answer.
                    IRREPLACEABLE_COLUMN: None,
                    "Area": area,
                    COMMENT: user_comment(row),
                    FEATURE_UUID: feature_uuid,
                },
            )
        )
    if multipart:
        report.warn(
            f"{multipart} baseline area habitat(s) are multi-part polygons. The new "
            "template expects one polygon per feature — split them in QGIS "
            "(Edit > Multipart to singleparts) before uploading."
        )
    _report_duplicate_baseline_refs(duplicate_refs, HABITATS, report)
    return out, index


def build_linear_baseline(rows, spec, report, label):
    """Baseline hedgerows or watercourses."""
    index = BaselineIndex()
    out = []
    _report_duplicate_baseline_refs(
        _duplicate_refs(rows, PARCEL_REF), label, report
    )
    for row in rows:
        blob = row.get(GEOM)
        feature_uuid = new_uuid()
        length = numeric(row.get(LENGTH))
        if length is None and blob is not None:
            length = line_blob_length_m(blob)
        index.add(row.get(PARCEL_REF), feature_uuid, blob_wkt(blob), length)
        values = {
            REF_FIELD: row.get(PARCEL_REF),
            BASELINE_CONDITION: row.get(BASELINE_CONDITION),
            BASELINE_DISTINCTIVENESS: row.get(BASELINE_DISTINCTIVENESS),
            BASELINE_SIGNIFICANCE: row.get(
                BASELINE_SIGNIFICANCE
            ),
            LENGTH: length,
            COMMENT: user_comment(row),
            FEATURE_UUID: feature_uuid,
        }
        for target, source in spec.items():
            values[target] = row.get(source)
        out.append((blob, values))
    return out, index


def build_tree_baseline(rows, report):
    index = BaselineIndex()
    out = []
    _report_duplicate_baseline_refs(
        _duplicate_refs(rows, TREE_REF), "Urban Trees", report
    )
    _report_tree_counts(rows, BASELINE, report)
    for row in rows:
        blob = row.get(GEOM)
        feature_uuid = new_uuid()
        index.add(row.get(TREE_REF), feature_uuid, blob_wkt(blob), None)
        out.append(
            (
                blob,
                {
                    REF_FIELD: row.get(TREE_REF),
                    BASELINE_TREE_SIZE: row.get(BASELINE_TREE_SIZE),
                    BASELINE_TREE_TYPE: row.get(BASELINE_TREE_TYPE),
                    BASELINE_RURAL_OR_URBAN_TREE: row.get(
                        BASELINE_RURAL_OR_URBAN_TREE
                    ),
                    BASELINE_CONDITION: row.get(BASELINE_CONDITION),
                    BASELINE_SIGNIFICANCE: row.get(
                        BASELINE_SIGNIFICANCE
                    ),
                    # No legacy column. A surveyed tree can be either, so
                    # it is left for the surveyor (see _report_manual_steps).
                    IRREPLACEABLE_COLUMN: None,
                    COMMENT: user_comment(row),
                    FEATURE_UUID: feature_uuid,
                },
            )
        )
    return out, index


def _duplicate_refs(rows, ref_key):
    seen = defaultdict(int)
    for row in rows:
        ref = row.get(ref_key)
        if ref not in (None, ""):
            seen[ref] += 1
    return {ref for ref, count in seen.items() if count > 1}


def _report_duplicate_baseline_refs(duplicates, label, report):
    if duplicates:
        report.warn(
            f"{label} baseline has duplicate references ({', '.join(sorted(duplicates))}). "
            "Post-intervention features matching them are linked to the first "
            "occurrence — check those links in QGIS."
        )


# ---------------------------------------------------------------------------
# Row mapping — post-intervention
# ---------------------------------------------------------------------------


def build_area_pi(rows, index, report):
    """Post-intervention area habitats.

    Legacy "Lost" becomes "Created": the parcel's baseline habitat goes and
    something else takes its place, which is how the Statutory Metric records
    development. The row stays, because area habitats must account for every
    square metre inside the red line.
    """
    out = []
    unmatched = []
    lost_converted = 0
    multipart = 0
    for row in rows:
        blob = row.get(GEOM)
        if blob is not None:
            blob, was_multipart = demote_multipolygon_blob_to_polygon(blob)
            multipart += 1 if was_multipart else 0
        retention = row.get(RETENTION_CATEGORY)
        if retention == RETENTION_LOST:
            retention = RETENTION_CREATED
            lost_converted += 1
        # legacy stores square metres; the new template's column is hectares
        area = sq_metres_to_hectares(row.get("Area"))
        if area is None and blob is not None:
            area = sq_metres_to_hectares(polygon_blob_area_sqm(blob))
        values = {
            REF_FIELD: row.get(PI_REF),
            BASELINE_BROAD_HABITAT_TYPE: row.get(BASELINE_BROAD_HABITAT_TYPE),
            BASELINE_HABITAT_TYPE: row.get(BASELINE_HABITAT_TYPE),
            BASELINE_DISTINCTIVENESS: row.get(BASELINE_DISTINCTIVENESS),
            BASELINE_CONDITION: row.get(BASELINE_CONDITION),
            BASELINE_SIGNIFICANCE: row.get(
                BASELINE_SIGNIFICANCE
            ),
            IRREPLACEABLE_COLUMN: None,
            RETENTION_CATEGORY: retention,
            PROPOSED_BROAD_HABITAT_TYPE: row.get(PROPOSED_BROAD_HABITAT_TYPE),
            PROPOSED_HABITAT_TYPE: row.get(PROPOSED_HABITAT_TYPE),
            PROPOSED_DISTINCTIVENESS: row.get(PROPOSED_DISTINCTIVENESS),
            PROPOSED_CONDITION: row.get(PROPOSED_CONDITION),
            PROPOSED_SIGNIFICANCE: row.get(
                PROPOSED_SIGNIFICANCE
            ),
            HABITAT_CREATED_IN_ADVANCE_YEARS: row.get(
                HABITAT_CREATED_IN_ADVANCE_YEARS
            ),
            DELAY_IN_STARTING_HABITAT_CREATION_YEARS: row.get(
                DELAY_IN_STARTING_HABITAT_CREATION_YEARS
            ),
            SPATIAL_RISK: row.get(SPATIAL_RISK),
            "Area": area,
            COMMENT: user_comment(row),
        }
        stamp_parent(values, row.get(PARENT_REF_KEY), index, unmatched,
                     own_ref=row.get(PARCEL_REF))
        out.append((blob, values))

    if lost_converted:
        report.note(
            f"Habitats: {lost_converted} 'Lost' row(s) recorded as 'Created' — the "
            "new template records built-over ground as creating the new surface"
        )
    if multipart:
        report.warn(
            f"{multipart} post-intervention area habitat(s) are multi-part polygons; "
            "split them in QGIS (Edit > Multipart to singleparts)."
        )
    _report_unmatched(unmatched, HABITATS, report)
    return out


def build_linear_pi(rows, index, spec, report, label, is_watercourse=False):
    """Post-intervention hedgerows or watercourses.

    Legacy "Lost" rows are dropped: the new template records removal by leaving
    the feature out, and the service works out what went missing by comparing
    the baseline against what carried forward.
    """
    out = []
    unmatched = []
    for row in rows:
        blob = row.get(GEOM)
        length = numeric(row.get(LENGTH))
        if length is None and blob is not None:
            length = line_blob_length_m(blob)
        values = {
            REF_FIELD: row.get(PI_REF),
            BASELINE_CONDITION: row.get(BASELINE_CONDITION),
            BASELINE_DISTINCTIVENESS: row.get(BASELINE_DISTINCTIVENESS),
            BASELINE_SIGNIFICANCE: row.get(
                BASELINE_SIGNIFICANCE
            ),
            RETENTION_CATEGORY: row.get(RETENTION_CATEGORY),
            PROPOSED_DISTINCTIVENESS: row.get(PROPOSED_DISTINCTIVENESS),
            PROPOSED_CONDITION: row.get(PROPOSED_CONDITION),
            PROPOSED_SIGNIFICANCE: row.get(
                PROPOSED_SIGNIFICANCE
            ),
            HABITAT_CREATED_IN_ADVANCE_YEARS: row.get(
                HABITAT_CREATED_IN_ADVANCE_YEARS
            ),
            DELAY_IN_STARTING_HABITAT_CREATION_YEARS: row.get(
                DELAY_IN_STARTING_HABITAT_CREATION_YEARS
            ),
            SPATIAL_RISK: row.get(SPATIAL_RISK),
            LENGTH: length,
            COMMENT: user_comment(row),
        }
        for target, source in spec.items():
            values[target] = row.get(source)
        if is_watercourse:
            values[ENHANCEMENT_TYPE] = row.get(ENHANCEMENT_TYPE)

        parent_ref = row.get(PARENT_REF_KEY) or row.get(PARCEL_REF)
        if stamp_parent(values, row.get(PARENT_REF_KEY), index, unmatched,
                        own_ref=row.get(PARCEL_REF)):
            values[BASELINE_LENGTH] = index.get(parent_ref)["size"]
        out.append((blob, values))

    _report_unmatched(unmatched, label, report)
    return out


def build_tree_pi(rows, index, report):
    """Post-intervention trees; legacy 'Lost' rows are dropped as above."""
    out = []
    unmatched = []
    _report_tree_counts(rows, "post-intervention", report)
    for row in rows:
        values = {
            REF_FIELD: row.get(PI_REF),
            BASELINE_TREE_SIZE: row.get(BASELINE_TREE_SIZE),
            BASELINE_TREE_TYPE: row.get(BASELINE_TREE_TYPE),
            BASELINE_RURAL_OR_URBAN_TREE: row.get(BASELINE_RURAL_OR_URBAN_TREE),
            BASELINE_CONDITION: row.get(BASELINE_CONDITION),
            BASELINE_SIGNIFICANCE: row.get(
                BASELINE_SIGNIFICANCE
            ),
            RETENTION_CATEGORY: row.get(RETENTION_CATEGORY),
            PROPOSED_TREE_SIZE: row.get(PROPOSED_TREE_SIZE),
            PROPOSED_TREE_TYPE: row.get(PROPOSED_TREE_TYPE),
            PROPOSED_RURAL_OR_URBAN_TREE: row.get(PROPOSED_RURAL_OR_URBAN_TREE),
            PROPOSED_CONDITION: row.get(PROPOSED_CONDITION),
            PROPOSED_SIGNIFICANCE: row.get(
                PROPOSED_SIGNIFICANCE
            ),
            CATEGORY: row.get(CATEGORY) or TREE_CATEGORY_EXISTING,
            # A newly planted tree is never irreplaceable, as the template
            # fills it. An existing one is left for the surveyor.
            IRREPLACEABLE_COLUMN: (
                "No" if row.get(CATEGORY) == TREE_NEWLY_PLANTED else None),
            HABITAT_CREATED_ENHANCED_IN_ADVANCE_YEARS: row.get(
                HABITAT_CREATED_ENHANCED_IN_ADVANCE_YEARS
            ),
            DELAY_IN_STARTING_HABITAT_CREATION_ENHANCEMENT_IN_YEARS: row.get(
                DELAY_IN_STARTING_HABITAT_CREATION_ENHANCEMENT_IN_YEARS
            ),
            SPATIAL_RISK: row.get(SPATIAL_RISK),
            COMMENT: user_comment(row),
        }
        stamp_parent(values, row.get(PARENT_REF_KEY), index, unmatched,
                     own_ref=row.get(TREE_REF))
        out.append((row.get(GEOM), values))

    _report_unmatched(unmatched, TREES, report)
    return out


def _report_tree_counts(rows, stage, report):
    """Name the legacy points that stand for more than one tree.

    The legacy template has a Count column, which its own form locks at 1.
    The BNG Service template records one tree per point, so a higher count
    cannot be carried over, and the extra trees would otherwise be lost
    without a word.
    """
    many = trees_counted_above_one(rows, TREE_REF)
    if many:
        report.warn(tree_count_warning(f"Urban Trees ({stage})", many))


def build_meander_rows(rows, index, report):
    """Carry the legacy meanders layer into Watercourses Post-Intervention.

    The new template folds re-meandering into the watercourse itself via the
    Enhancement Type column, so these become enhanced watercourse rows. That is
    an interpretation, not a stated equivalence — hence the warning.
    """
    if not rows:
        return []
    out = []
    unmatched = []
    for row in rows:
        blob = row.get(GEOM)
        length = numeric(row.get(LENGTH))
        if length is None and blob is not None:
            length = line_blob_length_m(blob)
        values = {
            REF_FIELD: row.get(BASELINE_PARCEL_REF),
            RETENTION_CATEGORY: "Enhanced",
            ENHANCEMENT_TYPE: MEANDER_ENHANCEMENT_TYPE,
            PROPOSED_RIVER_TYPE: row.get(PROPOSED_RIVER_TYPE),
            PROPOSED_CONDITION: row.get(PROPOSED_CONDITION),
            PROPOSED_DISTINCTIVENESS: row.get(PROPOSED_DISTINCTIVENESS),
            PROPOSED_SIGNIFICANCE: row.get(
                PROPOSED_SIGNIFICANCE
            ),
            PROPOSED_ENCROACHMENT_INTO_WATERCOURSE: row.get(
                PROPOSED_ENCROACHMENT_INTO_WATERCOURSE
            ),
            PROPOSED_ENCROACHMENT_INTO_RIPARIAN_ZONE: row.get(
                PROPOSED_ENCROACHMENT_INTO_RIPARIAN_ZONE
            ),
            BASELINE_DISTINCTIVENESS: row.get(BASELINE_DISTINCTIVENESS),
            HABITAT_CREATED_IN_ADVANCE_YEARS: row.get(MEANDER_ADVANCE_YEARS)
            or row.get(HABITAT_CREATED_IN_ADVANCE_YEARS),
            DELAY_IN_STARTING_HABITAT_CREATION_YEARS: row.get(
                DELAY_IN_STARTING_HABITAT_CREATION_YEARS
            ),
            SPATIAL_RISK: row.get(SPATIAL_RISK),
            LENGTH: length,
        }
        parent_ref = row.get(BASELINE_PARCEL_REF)
        if stamp_parent(values, parent_ref, index, unmatched):
            values[BASELINE_LENGTH] = index.get(parent_ref)["size"]
        out.append((blob, values))

    report.warn(
        f"{len(out)} row(s) from the legacy 'Water course enhancement through "
        "meanders' layer were carried into Watercourses Post-Intervention as "
        f"Enhanced, with Enhancement Type '{MEANDER_ENHANCEMENT_TYPE}'. The new "
        "template has no separate meanders layer, so this is an interpretation — "
        "check these rows."
    )
    _report_unmatched(unmatched, MEANDER_ENHANCEMENT_TYPE, report)
    return out


def _report_unmatched(unmatched, label, report):
    """Say which rows have a broken link and which are simply new.

    Reporting both as broken links, which an earlier version did, buries the
    handful worth looking at under every feature the scheme creates.
    """
    if not unmatched:
        return
    broken = sorted({str(ref) for ref, declared in unmatched if declared})
    fresh = sorted({str(ref) for ref, declared in unmatched if not declared})

    if broken:
        report.warn(
            f"{label}: {len(broken)} post-intervention feature(s) name a "
            f"baseline feature that is not in the baseline file "
            f"({summarise_refs(broken)}). The link is recorded but cannot be "
            "followed, which usually means the two files are from different "
            "surveys. They are left without a recorded parent, so the service "
            "will infer one from the geometry and warn you. Review those "
            "before relying on the result."
        )
    if fresh:
        report.note(
            f"{label}: {len(fresh)} post-intervention feature(s) have no "
            f"baseline feature of their own ({summarise_refs(fresh)}). The "
            "legacy format records no lineage, so these are read as newly "
            "created and left without a parent, which is what the new "
            "template records for a creation."
        )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def table_columns(conn, table):
    """The column names a table in the target actually has."""
    return {
        row[1] for row in conn.execute(f"PRAGMA table_info({quote_ident(table)})")
    }


def extra_columns(conn, table_names):
    """Logical layer -> the columns its target table has and STAGED_LAYERS
    does not, leaving out the primary key and the geometry column."""
    extra = {}
    for layer, table in table_names.items():
        spec = STAGED_LAYERS[layer]
        known = {name for name, _ in spec[COLUMNS]} | {spec[GEOM_COLUMN]}
        rows = conn.execute(f"PRAGMA table_info({quote_ident(table)})")
        # PRAGMA table_info rows: (cid, name, type, notnull, default, pk)
        unknown = [row[1] for row in rows if not row[5] and row[1] not in known]
        if unknown:
            extra[layer] = unknown
    return extra


def missing_columns(conn, table_names):
    """Logical layer -> the columns of STAGED_LAYERS its target table lacks."""
    missing = {}
    for layer, table in table_names.items():
        present = table_columns(conn, table)
        absent = [name for name, _ in STAGED_LAYERS[layer][COLUMNS]
                  if name not in present]
        if absent:
            missing[layer] = absent
    return missing


def _blank_to_null(value):
    """NULL for an empty or all-space text value.

    A drop-down lists NULL as its blank choice. An empty string is not in the
    list, and QGIS shows it as `()`.
    """
    if isinstance(value, str) and not value.strip():
        return None
    return value


def insert_rows(conn, table, rows, target_table=None):
    """Insert rows for the logical layer `table`.

    `target_table` is the name to actually write into, which differs from the
    logical name when filling a template that carries the renamed tables.
    Only the columns the target table has are written, so a template from
    before a column was added or removed still takes the rows.
    """
    if not rows:
        return 0
    spec = STAGED_LAYERS[table]
    table = target_table or table
    present = table_columns(conn, table)
    column_names = [name for name, _ in spec[COLUMNS] if name in present]
    placeholders = ", ".join(["?"] * (len(column_names) + 1))
    quoted = ", ".join(
        [quote_ident(spec[GEOM_COLUMN])]
        + [quote_ident(name) for name in column_names]
    )
    payload = [
        [geometry] + [_blank_to_null(values.get(name)) for name in column_names]
        for geometry, values in rows
    ]
    conn.executemany(
        f"INSERT INTO {quote_ident(table)} ({quoted}) VALUES ({placeholders})",
        payload,
    )
    return len(payload)


def create_staged_gpkg(path, srs_rows):
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    create_gpkg_system_tables(conn, srs_rows)
    for table, spec in STAGED_LAYERS.items():
        create_feature_table(
            conn, table, spec[GEOM_COLUMN], spec[GEOM_TYPE], spec[COLUMNS]
        )
    write_template_version(conn)
    conn.commit()
    return conn


def resolve_template_tables(conn):
    """Map each staged layer to its table in the target template.

    A layer the target lacks is a hard error naming every missing table,
    rather than the bare SQLite "no such table". A template from before the
    "Area Habitats" / "Individual Trees" rename is refused this way.
    """
    present = feature_table_names(conn)
    resolved = {}
    missing = []
    for layer in STAGED_LAYERS:
        table = resolve_table_name((layer,), present)
        if table is None:
            missing.append(layer)
        else:
            resolved[layer] = table
    if missing:
        detail = quoted_names(missing)
        raise ValueError(
            "The target GeoPackage is missing feature table(s): "
            f"{detail}. Point --into at a copy of the BNG Service template."
        )
    return resolved


def _report_template_version(conn, report):
    """Warn when the target template does not record the current version.

    The conversion writes into the template as it is, so it does not add or
    change the record: a copy of an earlier template is not the current
    version, whatever its rows hold. The BNG service reads the record, and
    refuses a file without it.
    """
    try:
        record = read_template_version(conn)
    except ValueError as error:
        report.warn(f"The target's template version cannot be read: {error}")
        return
    if record is None:
        report.warn(
            "The target template does not record its version, so the BNG "
            "service will not accept it. Convert into a fresh copy of the "
            f"current template (version {TEMPLATE_VERSION}) instead."
        )
    elif record["format"] != FORMAT_NAME:
        report.warn(
            f"The target records the format {record['format']!r}, not "
            f"{FORMAT_NAME!r}, so the BNG service will not accept it. Convert "
            "into a fresh copy of the current template (version "
            f"{TEMPLATE_VERSION}) instead."
        )
    elif record["version"] != TEMPLATE_VERSION:
        report.warn(
            f"The target is version {record['version']} of the template. The "
            f"current version is {TEMPLATE_VERSION}."
        )


def open_template_gpkg(path, force):
    """Open an existing template GeoPackage to write into.

    Returns the connection and the logical-layer -> actual-table-name map the
    caller must write through.

    Keeps the template's own spatial indexes working by supplying the ST_*
    functions its triggers call.
    """
    conn = sqlite3.connect(path)
    register_spatial_functions(conn)
    try:
        tables = resolve_template_tables(conn)
    except ValueError:
        conn.close()
        raise
    if not force:
        for table in tables.values():
            row = conn.execute(
                f"SELECT COUNT(*) FROM {quote_ident(table)}"
            ).fetchone()
            if row and row[0]:
                conn.close()
                raise ValueError(
                    f'"{table}" in the target already has {row[0]} feature(s). '
                    "Point --into at a fresh copy of the template, or pass "
                    "--force to add to what is there."
                )
    return conn, tables


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

HEDGEROW_BASELINE_SPEC = {BASELINE_HEDGE_TYPE: BASELINE_HEDGE_TYPE}
HEDGEROW_PI_SPEC = {
    BASELINE_HEDGE_TYPE: BASELINE_HEDGE_TYPE,
    PROPOSED_HEDGE_TYPE: PROPOSED_HEDGE_TYPE,
}
WATERCOURSE_BASELINE_SPEC = {
    BASELINE_RIVER_TYPE: BASELINE_RIVER_TYPE,
    BASELINE_ENCROACHMENT_INTO_WATERCOURSE: BASELINE_ENCROACHMENT_INTO_WATERCOURSE,
    BASELINE_ENCROACHMENT_INTO_RIPARIAN_ZONE: (
        BASELINE_ENCROACHMENT_INTO_RIPARIAN_ZONE
    ),
}
WATERCOURSE_PI_SPEC = {
    BASELINE_RIVER_TYPE: BASELINE_RIVER_TYPE,
    BASELINE_ENCROACHMENT_INTO_WATERCOURSE: BASELINE_ENCROACHMENT_INTO_WATERCOURSE,
    BASELINE_ENCROACHMENT_INTO_RIPARIAN_ZONE: (
        BASELINE_ENCROACHMENT_INTO_RIPARIAN_ZONE
    ),
    PROPOSED_RIVER_TYPE: PROPOSED_RIVER_TYPE,
    PROPOSED_ENCROACHMENT_INTO_WATERCOURSE: PROPOSED_ENCROACHMENT_INTO_WATERCOURSE,
    PROPOSED_ENCROACHMENT_INTO_RIPARIAN_ZONE: (
        PROPOSED_ENCROACHMENT_INTO_RIPARIAN_ZONE
    ),
}


def convert(baseline_path, pi_path, out_dir, into_path, force, dry_run,
            out_file=None):
    report = Report()
    baseline = read_legacy(baseline_path)
    post = read_legacy(pi_path) if pi_path else None
    # Before anything compares a value: a legacy watercourse removal reads
    # "4. Lost", and the rows marked Lost are dropped below.
    _strip_list_numbers(baseline, report, "Baseline file")
    if post:
        _strip_list_numbers(post, report, "Post-intervention file")

    _baseline_significance(baseline, report)

    if not baseline[REDLINE]:
        report.warn(
            "The baseline file has no Red Line Boundary feature — the new "
            "template needs one, and it carries the site details."
        )

    site = _site_record(baseline, post)

    # Build the baseline side first: every stamp a child needs comes from here.
    area_baseline, area_index = build_area_baseline(baseline[AREAS], report)
    hedge_baseline, hedge_index = build_linear_baseline(
        baseline[HEDGEROWS_KEY], HEDGEROW_BASELINE_SPEC, report, HEDGEROWS
    )
    water_baseline, water_index = build_linear_baseline(
        baseline[WATERCOURSES_KEY], WATERCOURSE_BASELINE_SPEC, report,
        WATERCOURSES,
    )
    tree_baseline, tree_index = build_tree_baseline(baseline[TREES_KEY], report)
    area_pi, hedge_pi, water_pi, tree_pi = _post_intervention_rows(
        post, report, area_index, hedge_index, water_index, tree_index
    )

    redline_rows = [
        (row.get(GEOM), {field: site.get(field) for field in SITE_DETAIL_FIELDS})
        for row in baseline[REDLINE]
    ]
    tables = {
        LEGACY_REDLINE: redline_rows,
        AREA_HABITATS_BASELINE: area_baseline,
        AREA_HABITATS_POST_INTERVENTION: area_pi,
        HEDGEROWS_BASELINE: hedge_baseline,
        HEDGEROWS_POST_INTERVENTION: hedge_pi,
        WATERCOURSES_BASELINE: water_baseline,
        WATERCOURSES_POST_INTERVENTION: water_pi,
        INDIVIDUAL_TREES_BASELINE: tree_baseline,
        INDIVIDUAL_TREES_POST_INTERVENTION: tree_pi,
    }
    for table, rows in tables.items():
        report.count(table, len(rows))

    _fill_template_values(tables, report)
    _report_lineage_quality(tables, report)
    _report_manual_steps(tables, report)
    check_needed_values(_as_staged(tables), report, INCOMING_GAP_CONSEQUENCE,
                        skip=(IRREPLACEABLE_COLUMN,))

    if dry_run:
        return report

    conn, table_names, target = _open_output(
        baseline_path, baseline["srs"], out_dir, into_path, force, out_file,
        tables, report,
    )
    try:
        for table, rows in tables.items():
            insert_rows(conn, table, rows, table_names[table])
        for table, spec in STAGED_LAYERS.items():
            update_layer_extent(conn, table_names[table], spec[GEOM_COLUMN])
        conn.commit()
    finally:
        conn.close()

    report.note(f"Staged file: {target}")
    return report


def _site_record(baseline, post):
    """Site details from the post-intervention file, filled from the baseline.

    A field left blank there keeps the baseline value. The red line carries
    these details into the new template.
    """
    source = post or baseline
    site = site_details(source) if source else {}
    for field in SITE_DETAIL_FIELDS:
        if site.get(field) in (None, ""):
            site[field] = site_details(baseline).get(field)
    return site


def _post_intervention_rows(post, report, area_index, hedge_index,
                            water_index, tree_index):
    """Post-intervention rows, or empty lists when that file was not given."""
    if not post:
        report.note(
            "No post-intervention file given — only the baseline was converted."
        )
        return [], [], [], []

    recovered = 0
    for key in (AREAS, HEDGEROWS_KEY, WATERCOURSES_KEY, TREES_KEY):
        recovered += read_breadcrumbs(post[key])
    if recovered:
        report.note(
            f"Recovered {recovered} lineage breadcrumb(s) from the "
            "comment column, left there by the conversion out to legacy"
        )

    post[HEDGEROWS_KEY] = drop_lost_rows(
        post[HEDGEROWS_KEY], PARCEL_REF, HEDGEROWS, report, hedge_index
    )
    post[WATERCOURSES_KEY] = drop_lost_rows(
        post[WATERCOURSES_KEY], PARCEL_REF, WATERCOURSES, report,
        water_index,
    )
    post[TREES_KEY] = drop_lost_rows(
        post[TREES_KEY], TREE_REF, TREES, report, tree_index
    )
    _post_significance(post, report)
    _post_spatial_risk(post, report)
    _post_timing(post, report)

    unique_pi_refs(post[AREAS], PARCEL_REF, report, HABITATS)
    unique_pi_refs(post[HEDGEROWS_KEY], PARCEL_REF, report, HEDGEROWS)
    unique_pi_refs(post[WATERCOURSES_KEY], PARCEL_REF, report, WATERCOURSES)
    unique_pi_refs(post[TREES_KEY], TREE_REF, report, TREES)

    area_pi = build_area_pi(post[AREAS], area_index, report)
    hedge_pi = build_linear_pi(
        post[HEDGEROWS_KEY], hedge_index, HEDGEROW_PI_SPEC, report, HEDGEROWS
    )
    water_pi = build_linear_pi(
        post[WATERCOURSES_KEY], water_index, WATERCOURSE_PI_SPEC, report,
        WATERCOURSES, is_watercourse=True,
    )
    water_pi.extend(build_meander_rows(post[MEANDERS], water_index, report))
    tree_pi = build_tree_pi(post[TREES_KEY], tree_index, report)
    return area_pi, hedge_pi, water_pi, tree_pi


def _open_output(baseline_path, srs, out_dir, into_path, force, out_file,
                 tables, report):
    """The connection, logical-layer to table-name map, and the file path.

    An existing template keeps its own table names. A new file uses the
    template's names, and is named from the baseline unless out_file is set.
    """
    if into_path:
        conn, table_names = open_template_gpkg(into_path, force)
        missing = missing_columns(conn, table_names)
        _report_missing_columns(missing, report)
        _report_dropped_comments(tables, missing, report)
        _report_extra_columns(extra_columns(conn, table_names), report)
        _report_template_version(conn, report)
        return conn, table_names, into_path

    if out_file:
        target = out_file
        parent = os.path.dirname(os.path.abspath(target))
        os.makedirs(parent, exist_ok=True)
    else:
        os.makedirs(out_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(baseline_path))[0]
        target = os.path.join(out_dir, f"{stem} - Staged.gpkg")
    conn = create_staged_gpkg(target, srs)
    # A file we create ourselves carries the template's own table names.
    table_names = {layer: layer for layer in STAGED_LAYERS}
    return conn, table_names, target


# Legacy layer key -> (its reference column, how it reads in a message).
LEGACY_REFS = {
    AREAS: (PARCEL_REF, HABITATS),
    HEDGEROWS_KEY: (PARCEL_REF, HEDGEROWS),
    WATERCOURSES_KEY: (PARCEL_REF, WATERCOURSES),
    TREES_KEY: (TREE_REF, TREES),
    MEANDERS: (BASELINE_PARCEL_REF, MEANDER_ENHANCEMENT_TYPE),
}
HABITAT_KEYS = (AREAS, HEDGEROWS_KEY, WATERCOURSES_KEY, TREES_KEY)


def _legacy_ref(row, key):
    ref = row.get(LEGACY_REFS[key][0])
    return ref if ref not in (None, "") else f"fid {row.get('fid')}"


def _baseline_significance(legacy, report):
    """Write Low on every baseline row, as the BNG Service template stores it.

    The template holds no other value for a baseline feature. A row whose
    legacy value said anything else is named, so the user can check it.
    """
    for key in HABITAT_KEYS:
        other = []
        for row in legacy[key]:
            if plain_label(row.get(BASELINE_SIGNIFICANCE)) != NE_SIGNIFICANCE_LOW:
                other.append(_legacy_ref(row, key))
            row[BASELINE_SIGNIFICANCE] = SIGNIFICANCE_LOW
        if other:
            report.warn(
                f"{LEGACY_REFS[key][1]} baseline: {len(other)} row(s) had a "
                f"Baseline Strategic Significance other than "
                f"'{NE_SIGNIFICANCE_LOW}' ({summarise_refs(other)}). The BNG "
                "Service template stores Low for every baseline feature, so "
                "they were written as Low."
            )


RETAINED = "Retained"


def _post_significance(post, report):
    """Read strategic significance into the template's Low and High.

    Baseline Strategic Significance on a post-intervention row is Low where
    the row has a baseline habitat, and blank where it has none, as the
    template fills it. Proposed Strategic Significance maps by wording.
    Natural England's middle value has no place in the template, so it is
    left blank, and the rows are named. A Retained row keeps its baseline
    value, which the template holds as Low.
    """
    for key, (_ref_column, label) in LEGACY_REFS.items():
        changed, medium, unknown, retained = [], [], [], []
        for row in post[key]:
            ref = _legacy_ref(row, key)
            _set_post_baseline_significance(key, row, ref, changed)
            _set_post_proposed_significance(
                row, ref, medium, unknown, retained)
        _report_significance(
            label, changed, medium, unknown, retained, report)


def _set_post_baseline_significance(key, row, ref, changed):
    """Write baseline significance as the template stores it on this row.

    Low where the row has a baseline habitat, blank where it has none.
    A value the template would not have held is named in `changed`.
    """
    if BASELINE_SIGNIFICANCE not in row:
        return
    value = plain_label(row.get(BASELINE_SIGNIFICANCE))
    if has_baseline_part(key, row):
        row[BASELINE_SIGNIFICANCE] = SIGNIFICANCE_LOW
        if value != NE_SIGNIFICANCE_LOW:
            changed.append(ref)
        return
    row[BASELINE_SIGNIFICANCE] = None
    if value not in (None, "", NOT_APPLICABLE):
        changed.append(ref)


def _set_post_proposed_significance(row, ref, medium, unknown, retained):
    """Write proposed significance as Low, High, or blank.

    A Retained row keeps its baseline value, which the template holds as
    Low. Medium, and any wording the template does not know, are left
    blank and named.
    """
    value = row.get(PROPOSED_SIGNIFICANCE)
    stored, known = service_significance(value)
    if plain_label(row.get(RETENTION_CATEGORY)) == RETAINED:
        if stored != SIGNIFICANCE_LOW:
            retained.append(ref)
        stored = SIGNIFICANCE_LOW
    elif plain_label(value) == NE_SIGNIFICANCE_MEDIUM:
        medium.append(ref)
    elif not known:
        unknown.append(ref)
    row[PROPOSED_SIGNIFICANCE] = stored


def _report_significance(label, changed, medium, unknown, retained, report):
    if changed:
        report.warn(
            f"{label} post-intervention: {len(changed)} row(s) had a Baseline "
            f"Strategic Significance the template does not hold "
            f"({summarise_refs(changed)}). The template stores Low where a "
            "row has a baseline habitat and leaves it blank where it has "
            "none, so they were written that way."
        )
    if medium:
        report.warn(
            f"{label}: {len(medium)} post-intervention row(s) have Proposed "
            f"Strategic Significance '{NE_SIGNIFICANCE_MEDIUM}' "
            f"({summarise_refs(medium)}). The BNG Service template holds "
            "only Low or High, so it was left blank. Choose Low or High for "
            "these rows."
        )
    if unknown:
        report.warn(
            f"{label}: {len(unknown)} post-intervention row(s) have a Proposed "
            f"Strategic Significance that is not a Natural England value "
            f"({summarise_refs(unknown)}). It was left blank. Choose Low or "
            "High for these rows."
        )
    if retained:
        report.warn(
            f"{label}: {len(retained)} Retained post-intervention row(s) "
            f"had a Proposed Strategic Significance other than Low "
            f"({summarise_refs(retained)}). A retained habitat keeps its "
            "baseline value, which the template holds as Low, so they "
            "were written as Low."
        )


# Blank, 0 to 30 and 30+: the years an advance or delay drop-down stores.
TIMING_YEARS = {str(year) for year in range(31)} | {"30+"}


def _post_timing(post, report):
    """Blank a text advance or delay, then name rows with both above 0.

    The legacy lists offered text such as N/A. The template offers blank,
    0 to 30 and 30+ only, so any other text is left blank and the rows
    are named. That happens first: a text value is not a year above 0,
    and must not be reported as one beside a real year.

    The metric allows one of advance and delay. The template blanks one
    when the other is above 0, but cannot tell which value to keep for a
    row that arrives with both, so the converter keeps both and names the
    rows.
    """
    for key, (_ref_column, label) in LEGACY_REFS.items():
        cleared, both = [], []
        for row in post[key]:
            advance, delay = timing_columns(row)
            if _clear_text_timing(row, advance, delay):
                cleared.append(_legacy_ref(row, key))
            if (_above_zero(row.get(advance))
                    and _above_zero(row.get(delay))):
                both.append(_legacy_ref(row, key))
        if cleared:
            report.warn(
                f"{label}: {len(cleared)} post-intervention row(s) had a "
                f"text value for years created in advance or years of "
                f"delay ({summarise_refs(cleared)}). The template offers "
                "blank, 0 to 30 and 30+ only, so they were left blank."
            )
        if both:
            report.warn(
                f"{label}: {len(both)} post-intervention row(s) have both "
                f"years created in advance and years of delay above 0 "
                f"({summarise_refs(both)}). The metric allows only one. "
                "Clear one of them for these rows."
            )


def _clear_text_timing(row, advance, delay):
    """Set a timing value the drop-down does not offer to blank.

    A year is written as the drop-down stores it, without spaces around
    it: the template's rule compares exactly, and would clear " 5" on the
    next edit.

    Returns whether this row held a value that is not a year.
    """
    cleared = False
    for field in (advance, delay):
        if field not in row:
            continue
        text = _timing_text(row[field])
        if text and text not in TIMING_YEARS:
            row[field] = None
            cleared = True
        else:
            row[field] = text or None
    return cleared


def _timing_text(value):
    """The timing value as text, or '' when it is blank."""
    if value is None:
        return ""
    return str(value).strip()


def timing_columns(row):
    """(years created in advance, years of delay) as this row names them."""
    if HABITAT_CREATED_ENHANCED_IN_ADVANCE_YEARS in row:
        return (HABITAT_CREATED_ENHANCED_IN_ADVANCE_YEARS,
                DELAY_IN_STARTING_HABITAT_CREATION_ENHANCEMENT_IN_YEARS)
    if MEANDER_ADVANCE_YEARS in row:
        return (MEANDER_ADVANCE_YEARS,
                DELAY_IN_STARTING_HABITAT_CREATION_YEARS)
    return (HABITAT_CREATED_IN_ADVANCE_YEARS,
            DELAY_IN_STARTING_HABITAT_CREATION_YEARS)


def _above_zero(value):
    return _timing_text(value) not in ("", "0")


def _post_spatial_risk(post, report):
    """Write N/A on every post-intervention row, as the template does.

    The template maps on-site habitat only, where spatial risk does not
    apply. A row whose legacy value said something else is named.
    """
    for key, (_ref_column, label) in LEGACY_REFS.items():
        other = []
        for row in post[key]:
            value = plain_label(row.get(SPATIAL_RISK))
            if value not in (None, "", NOT_APPLICABLE):
                other.append(_legacy_ref(row, key))
            row[SPATIAL_RISK] = NOT_APPLICABLE
        if other:
            report.warn(
                f"{label}: {len(other)} post-intervention row(s) had a "
                f"Spatial risk category other than N/A "
                f"({summarise_refs(other)}). The BNG Service template is for "
                "on-site habitat and stores N/A, so they were written as N/A."
            )


# Layer key -> the staged tables whose blanks the template would fill.
FILLED_LAYERS = {
    AREAS: AREA_HABITAT_LAYERS,
    HEDGEROWS_KEY: (HEDGEROWS_BASELINE, HEDGEROWS_POST_INTERVENTION),
    WATERCOURSES_KEY: (WATERCOURSES_BASELINE, WATERCOURSES_POST_INTERVENTION),
}


def _fill_template_values(tables, report):
    """Fill the blanks the template would fill itself, from its own lists."""
    totals = {}
    for key, names in FILLED_LAYERS.items():
        for name in names:
            filled = fill_template_values(
                key, [values for _, values in tables[name]])
            for column, count in filled.items():
                totals[column] = totals.get(column, 0) + count
    if totals:
        detail = ", ".join(f"{column} on {count}"
                           for column, count in totals.items())
        report.note(
            "Filled blanks the BNG Service template fills itself from the "
            f"habitat type: {detail} row(s). Distinctiveness comes from the "
            "template's list; a condition or Irreplaceable Habitat only where "
            "the habitat allows one answer"
        )


def _as_staged(tables):
    """The converted rows, in the shape the needed-values check reads."""
    return {
        kind: {BASELINE: [values for _, values in tables[base]],
               "pi": [values for _, values in tables[pi]]}
        for kind, base, pi, *_rest in METRIC_MODULES
    }


def _report_lineage_quality(tables, report):
    """How much of the lineage could actually be proved, rather than guessed."""
    stamped = 0
    total = 0
    for table, rows in tables.items():
        if not table.endswith("Post-Intervention"):
            continue
        for _, values in rows:
            total += 1
            if values.get(PARENT_UUID):
                stamped += 1
    if not total:
        return
    inferred = total - stamped
    report.note(
        f"Lineage: {stamped} of {total} post-intervention feature(s) linked to a "
        f"baseline feature by reference"
        + (
            f"; {inferred} left for the service to infer from geometry"
            if inferred
            else ""
        )
    )


def _report_missing_columns(missing, report):
    """Name the columns the target template lacks, whose values are not written."""
    if not missing:
        return
    detail = "; ".join(
        f"{layer}: {', '.join(columns)}" for layer, columns in missing.items()
    )
    report.warn(
        "The target template has no column for some converted values, so "
        f"those values were not written ({detail}). Fill a copy of the current "
        "BNG Service template to keep them."
    )


def _report_dropped_comments(tables, missing, report):
    """Say how many comments a template with no Comment column loses.

    A template from before post-intervention layers had a Comment column
    takes the rows but not their comments, which are the one thing in the
    conversion a surveyor wrote in their own words.
    """
    lost = {layer: sum(1 for _geometry, values in tables.get(layer, [])
                       if values.get(COMMENT))
            for layer, columns in missing.items() if COMMENT in columns}
    lost = {layer: count for layer, count in lost.items() if count}
    if not lost:
        return
    detail = "; ".join(f"{layer}: {count}" for layer, count in lost.items())
    report.warn(
        f"{sum(lost.values())} comment(s) were not written, because the "
        f"target template has no Comment column on that layer ({detail}). "
        "Fill a copy of the current BNG Service template to keep them.")


def _report_extra_columns(extra, report):
    """Name the columns of the target template that nothing here fills."""
    if not extra:
        return
    detail = "; ".join(
        f"{layer}: {', '.join(columns)}" for layer, columns in extra.items()
    )
    report.warn(
        "The target template has columns that this converter does not fill, "
        f"so they stay blank ({detail})."
    )


def _strip_list_numbers(legacy, report, label):
    """Take the legacy list number off the values of the numbered drop-downs."""
    changed = to_service_labels(legacy)
    if changed:
        report.note(
            f"{label}: took the list number off {changed} drop-down value(s), "
            "such as '4. Fairly Poor' to 'Fairly Poor'. The BNG Service "
            "template stores the words alone"
        )


def _report_manual_steps(tables, report):
    for label, layers in (("area habitat", AREA_HABITAT_LAYERS),
                          ("individual tree", TREE_LAYERS)):
        blank = [
            values.get(REF_FIELD)
            for table, rows in tables.items()
            if table in layers
            for _, values in rows
            if values.get(IRREPLACEABLE_COLUMN) is None
        ]
        if blank:
            report.warn(
                f"Irreplaceable Habitat is blank on {len(blank)} {label} "
                f"row(s) ({summarise_refs(blank)}). The legacy template has "
                "no such column, and they can be either. Choose Yes or No "
                "before uploading."
            )
    report.warn(
        "Vertical Area Habitats are empty. The legacy template cannot record "
        "a green wall, so add any that exist. It records an intertidal hard "
        "structure as an area habitat: any such row is named in a separate "
        "warning, to move to Vertical Area Habitats."
    )
    _report_vertical_on_area(tables, report)


def _report_vertical_on_area(tables, report):
    """Name the area habitat rows that hold a vertical area habitat.

    The legacy template records an intertidal hard structure as an area
    habitat. The template records it on the Vertical Area Habitats layers,
    by its vertical area, and the area habitat drop-downs do not offer it.
    The row is written as it is, for the user to move.
    """
    # A ref is in both tables when its row is carried forward. Name it once.
    found = list(dict.fromkeys(
        values.get(REF_FIELD)
        for table, rows in tables.items()
        if table in AREA_HABITAT_LAYERS
        for _, values in rows
        if any(VERTICAL_HABITATS.values(values.get(column))
               for column in (BASELINE_HABITAT_TYPE, PROPOSED_HABITAT_TYPE))
    ))
    if found:
        report.warn(
            f"{len(found)} area habitat row(s) hold a habitat that the "
            f"template records on the Vertical Area Habitats layers "
            f"({summarise_refs(found)}). The area habitat drop-downs do not "
            "offer it. Draw it on Vertical Area Habitats, as a line with its "
            "area in hectares, and give the area habitat row the habitat of "
            "the ground it stands on."
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def print_report(report, dry_run):
    print()
    print("=" * 70)
    print("  legacy Natural England GeoPackages  ->  BNG Service GeoPackage")
    print("=" * 70)
    if dry_run:
        print("  DRY RUN — nothing was written")
        print("-" * 70)

    print("\nRows:")
    for key, value in report.counts.items():
        print(f"  {key:.<50} {value}")

    if report.lines:
        print("\nNotes:")
        for line in report.lines:
            print(f"  - {line}")

    if report.warnings:
        print("\nWARNINGS — check these before uploading:")
        for line in report.warnings:
            print(f"  ! {line}")

    print(
        "\nLineage is rebuilt from references, which the legacy format never "
        "guaranteed.\nOpen the result in the new template and check the parent "
        "links before relying\non it.\n"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Convert a legacy Natural England baseline + post-intervention pair "
            "into a single BNG Service staged GeoPackage."
        )
    )
    parser.add_argument("--baseline", required=True, help="legacy baseline .gpkg")
    parser.add_argument(
        "--post-intervention", help="legacy post-intervention .gpkg (optional)"
    )
    parser.add_argument(
        "-o", "--out-dir", default=".", help="directory for the staged file"
    )
    parser.add_argument(
        "--into",
        help=(
            "write into this existing template GeoPackage (a fresh copy of "
            "Layers/BNG Service Layers.gpkg) instead of creating a new file"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow --into when the target already holds features",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be produced without writing anything",
    )
    args = parser.parse_args(argv)

    for label, path in (
        (BASELINE, args.baseline),
        ("post-intervention", args.post_intervention),
        ("target", args.into),
    ):
        if path and not os.path.exists(path):
            print(f"error: {label} file not found: {path}", file=sys.stderr)
            return 1

    try:
        report = convert(
            args.baseline,
            args.post_intervention,
            args.out_dir,
            args.into,
            args.force,
            args.dry_run,
        )
    except (sqlite3.Error, ValueError, struct.error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print_report(report, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
