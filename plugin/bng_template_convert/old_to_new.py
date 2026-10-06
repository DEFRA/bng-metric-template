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
        plain_label,
        polygon_blob_area_sqm,
        quote_ident,
        quoted_names,
        read_feature_table,
        read_only_uri,
        read_srs_rows,
        register_spatial_functions,
        resolve_table_name,
        sq_metres_to_hectares,
        summarise_list,
        summarise_refs,
        update_layer_extent,
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
        plain_label,
        polygon_blob_area_sqm,
        quote_ident,
        quoted_names,
        read_feature_table,
        read_only_uri,
        read_srs_rows,
        register_spatial_functions,
        resolve_table_name,
        sq_metres_to_hectares,
        summarise_list,
        summarise_refs,
        update_layer_extent,
    )

try:
    from .reference_lists import (
        BASELINE_SIGNIFICANCE,
        NE_SIGNIFICANCE_LOW,
        NE_SIGNIFICANCE_MEDIUM,
        NOT_APPLICABLE,
        PROPOSED_SIGNIFICANCE,
        SIGNIFICANCE_LOW,
        fill_template_values,
        has_baseline_part,
        service_significance,
        to_service_labels,
    )
    from .to_metric import MODULES as METRIC_MODULES, check_needed_values
except ImportError:  # pragma: no cover - running as a plain script
    from reference_lists import (
        BASELINE_SIGNIFICANCE,
        NE_SIGNIFICANCE_LOW,
        NE_SIGNIFICANCE_MEDIUM,
        NOT_APPLICABLE,
        PROPOSED_SIGNIFICANCE,
        SIGNIFICANCE_LOW,
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
INCOMING_GAP_CONSEQUENCE = (
    "Fill them in before uploading or exporting to the metric: until then "
    "neither can score those rows.")

# ---------------------------------------------------------------------------
# New-template schema — the columns of Layers/BNG Service Layers.gpkg, so the
# output can replace that file inside a copy of the template project. Filling
# a template with --into writes only the columns that template has.
# ---------------------------------------------------------------------------

BASELINE_TAIL = [("Comment", "TEXT"), ("feature_uuid", "TEXT")]
PI_TAIL = [("parent_uuid", "TEXT"), ("parent_geom", "TEXT")]
AREA_BASELINE_HEAD = [
    ("Habitat Ref", "TEXT"),
    ("Baseline Broad Habitat Type", "TEXT"),
    ("Baseline Habitat Type", "TEXT"),
    ("Baseline Distinctiveness", "TEXT"),
    ("Baseline Condition", "TEXT"),
    ("Baseline Strategic Significance", "TEXT"),
    ("Irreplaceable Habitat", "TEXT"),
    ("Area", "REAL"),
]
AREA_PI_HEAD = [
    ("Habitat Ref", "TEXT"),
    ("Parent Ref", "TEXT"),
    ("Baseline Broad Habitat Type", "TEXT"),
    ("Baseline Habitat Type", "TEXT"),
    ("Baseline Distinctiveness", "TEXT"),
    ("Baseline Condition", "TEXT"),
    ("Baseline Strategic Significance", "TEXT"),
    ("Irreplaceable Habitat", "TEXT"),
    ("Retention Category", "TEXT"),
    ("Proposed Broad Habitat Type", "TEXT"),
    ("Proposed Habitat Type", "TEXT"),
    ("Proposed Distinctiveness", "TEXT"),
    ("Proposed Condition", "TEXT"),
    ("Proposed Strategic Significance", "TEXT"),
    ("Habitat created in advance/years", "TEXT"),
    ("Delay in starting habitat creation/years", "TEXT"),
    ("Spatial risk category", "TEXT"),
    ("Area", "REAL"),
]

STAGED_LAYERS = {
    "Red Line Boundary": {
        "geom_column": "geom",
        "geom_type": "POLYGON",
        "columns": [
            ("Site Name", "TEXT"),
            ("Location", "TEXT"),
            ("Survey Date", "DATE"),
            ("Survey Details", "TEXT"),
            ("Mapped by", "TEXT"),
            ("Company", "TEXT"),
            ("Base Map", "TEXT"),
        ],
    },
    "Area Habitats Baseline": {
        "geom_column": "geom",
        "geom_type": "POLYGON",
        "columns": AREA_BASELINE_HEAD + BASELINE_TAIL,
    },
    "Area Habitats Post-Intervention": {
        "geom_column": "geom",
        "geom_type": "POLYGON",
        "columns": AREA_PI_HEAD + PI_TAIL,
    },
    "Vertical Area Habitats Baseline": {
        "geom_column": "geom",
        "geom_type": "LINESTRING",
        "columns": AREA_BASELINE_HEAD + BASELINE_TAIL,
    },
    "Vertical Area Habitats Post-Intervention": {
        "geom_column": "geom",
        "geom_type": "LINESTRING",
        "columns": AREA_PI_HEAD + PI_TAIL,
    },
    "Hedgerows Baseline": {
        "geom_column": "geom",
        "geom_type": "LINESTRING",
        "columns": [
            ("Habitat Ref", "TEXT"),
            ("Baseline Hedge Type", "TEXT"),
            ("Baseline Distinctiveness", "TEXT"),
            ("Baseline Condition", "TEXT"),
            ("Baseline Strategic Significance", "TEXT"),
            ("Length", "REAL"),
        ]
        + BASELINE_TAIL,
    },
    "Hedgerows Post-Intervention": {
        "geom_column": "geom",
        "geom_type": "LINESTRING",
        "columns": [
            ("Habitat Ref", "TEXT"),
            ("Parent Ref", "TEXT"),
            ("Baseline Hedge Type", "TEXT"),
            ("Baseline Distinctiveness", "TEXT"),
            ("Baseline Condition", "TEXT"),
            ("Baseline Strategic Significance", "TEXT"),
            ("Baseline Length", "REAL"),
            ("Retention Category", "TEXT"),
            ("Proposed Hedge Type", "TEXT"),
            ("Proposed Distinctiveness", "TEXT"),
            ("Proposed Condition", "TEXT"),
            ("Proposed Strategic Significance", "TEXT"),
            ("Habitat created in advance/years", "TEXT"),
            ("Delay in starting habitat creation/years", "TEXT"),
            ("Spatial risk category", "TEXT"),
            ("Length", "REAL"),
        ]
        + PI_TAIL,
    },
    "Watercourses Baseline": {
        "geom_column": "geom",
        "geom_type": "LINESTRING",
        "columns": [
            ("Habitat Ref", "TEXT"),
            ("Baseline River Type", "TEXT"),
            ("Baseline Distinctiveness", "TEXT"),
            ("Baseline Condition", "TEXT"),
            ("Baseline Strategic Significance", "TEXT"),
            ("Baseline Encroachment into Watercourse", "TEXT"),
            ("Baseline Encroachment into riparian zone", "TEXT"),
            ("Length", "REAL"),
        ]
        + BASELINE_TAIL,
    },
    "Watercourses Post-Intervention": {
        "geom_column": "geom",
        "geom_type": "LINESTRING",
        "columns": [
            ("Habitat Ref", "TEXT"),
            ("Parent Ref", "TEXT"),
            ("Baseline River Type", "TEXT"),
            ("Baseline Distinctiveness", "TEXT"),
            ("Baseline Condition", "TEXT"),
            ("Baseline Strategic Significance", "TEXT"),
            ("Baseline Encroachment into Watercourse", "TEXT"),
            ("Baseline Encroachment into riparian zone", "TEXT"),
            ("Baseline Length", "REAL"),
            ("Retention Category", "TEXT"),
            ("Proposed River Type", "TEXT"),
            ("Proposed Distinctiveness", "TEXT"),
            ("Proposed Condition", "TEXT"),
            ("Proposed Strategic Significance", "TEXT"),
            ("Proposed Encroachment into Watercourse", "TEXT"),
            ("Proposed Encroachment into riparian zone", "TEXT"),
            ("Enhancement Type", "TEXT"),
            ("Habitat created in advance/years", "TEXT"),
            ("Delay in starting habitat creation/years", "TEXT"),
            ("Spatial risk category", "TEXT"),
            ("Length", "REAL"),
        ]
        + PI_TAIL,
    },
    "Individual Trees Baseline": {
        "geom_column": "geom",
        "geom_type": "POINT",
        "columns": [
            ("Habitat Ref", "TEXT"),
            ("Baseline Tree Size", "TEXT"),
            ("Baseline Tree Type", "TEXT"),
            ("Baseline Rural or Urban Tree", "TEXT"),
            ("Baseline Condition", "TEXT"),
            ("Baseline Strategic Significance", "TEXT"),
            ("Count", "MEDIUMINT"),
        ]
        + BASELINE_TAIL,
    },
    "Individual Trees Post-Intervention": {
        "geom_column": "geom",
        "geom_type": "POINT",
        "columns": [
            ("Habitat Ref", "TEXT"),
            ("Parent Ref", "TEXT"),
            ("Baseline Tree Size", "TEXT"),
            ("Baseline Tree Type", "TEXT"),
            ("Baseline Rural or Urban Tree", "TEXT"),
            ("Baseline Condition", "TEXT"),
            ("Baseline Strategic Significance", "TEXT"),
            ("Retention Category", "TEXT"),
            ("Proposed Tree Size", "TEXT"),
            ("Proposed Tree Type", "TEXT"),
            ("Proposed Rural or Urban Tree", "TEXT"),
            ("Proposed Condition", "TEXT"),
            ("Proposed Strategic Significance", "TEXT"),
            ("Category", "TEXT"),
            ("Habitat Created/Enhanced in advance/years", "TEXT"),
            ("Delay in starting habitat creation/enhancement in years", "TEXT"),
            ("Spatial risk category", "TEXT"),
            ("Count", "MEDIUMINT"),
        ]
        + PI_TAIL,
    },
}

# The layers holding area habitats. Named explicitly rather than matched on the
# word "Habitats", which is also a substring of "Vertical Area Habitats *".
AREA_HABITAT_LAYERS = ("Area Habitats Baseline",
                       "Area Habitats Post-Intervention")


LEGACY_REDLINE = "Red Line Boundary"
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
MEANDER_ENHANCEMENT_TYPE = "Meanders"
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
            "redline": read_feature_table(conn, LEGACY_REDLINE),
            "areas": read_feature_table(conn, "Habitats"),
            "hedgerows": read_feature_table(conn, "Hedgerows"),
            "watercourses": read_feature_table(conn, "Rivers"),
            "trees": read_feature_table(conn, "Urban Trees"),
            "meanders": read_feature_table(conn, LEGACY_MEANDERS),
            "srs": read_srs_rows(conn),
        }
    finally:
        conn.close()


def site_details(legacy):
    """Collapse the site details legacy repeats on every row into one record.

    Takes the first non-empty value seen for each field, so a partly-filled
    layer does not blank out a field another layer has.
    """
    details = {field: None for field in SITE_DETAIL_FIELDS}
    sources = ["redline", "areas", "hedgerows", "watercourses", "trees"]
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


def read_breadcrumbs(rows):
    """Recover lineage from the breadcrumbs new_to_old.py --carry-lineage left.

    Converting to the legacy format has to discard the parent link; that flag
    parks it in the Comment column, which the legacy service ignores. Reading it
    back turns a round trip into an exact restoration rather than a re-guess.
    """
    found = 0
    for row in rows:
        comment = row.get("Comment") or row.get("Comments") or ""
        parent = BREADCRUMB_PARENT.search(str(comment))
        own = BREADCRUMB_PI.search(str(comment))
        if parent:
            row["_parent_ref"] = parent.group(1).strip()
            found += 1
        if own:
            row["_pi_ref"] = own.group(1).strip()
            found += 1
    return found


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
        if row.get("Retention Category") != RETENTION_LOST:
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
        if row.get("_pi_ref"):
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
            row["_pi_ref"] = candidate
            names.append(candidate)
        renamed_groups.append((ref, names))

    for row in rows:
        row.setdefault("_pi_ref", row.get(ref_key))

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
    values["Parent Ref"] = candidate
    values["parent_uuid"] = parent["uuid"]
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
    duplicate_refs = _duplicate_refs(rows, "Parcel Ref")
    for row in rows:
        blob = row.get("_geom")
        if blob is not None:
            blob, was_multipart = demote_multipolygon_blob_to_polygon(blob)
            multipart += 1 if was_multipart else 0
        feature_uuid = new_uuid()
        # legacy stores square metres; the new template's column is hectares
        area = sq_metres_to_hectares(row.get("Area"))
        if area is None and blob is not None:
            area = sq_metres_to_hectares(polygon_blob_area_sqm(blob))
        index.add(row.get("Parcel Ref"), feature_uuid, blob_wkt(blob), area)
        out.append(
            (
                blob,
                {
                    REF_FIELD: row.get("Parcel Ref"),
                    "Baseline Broad Habitat Type": row.get(
                        "Baseline Broad Habitat Type"
                    ),
                    "Baseline Habitat Type": row.get("Baseline Habitat Type"),
                    "Baseline Distinctiveness": row.get("Baseline Distinctiveness"),
                    "Baseline Condition": row.get("Baseline Condition"),
                    "Baseline Strategic Significance": row.get(
                        "Baseline Strategic Significance"
                    ),
                    # No legacy column: filled below where the habitat
                    # allows only one answer.
                    "Irreplaceable Habitat": None,
                    "Area": area,
                    "Comment": row.get("Comment"),
                    "feature_uuid": feature_uuid,
                },
            )
        )
    if multipart:
        report.warn(
            f"{multipart} baseline area habitat(s) are multi-part polygons. The new "
            "template expects one polygon per feature — split them in QGIS "
            "(Edit > Multipart to singleparts) before uploading."
        )
    _report_duplicate_baseline_refs(duplicate_refs, "Habitats", report)
    return out, index


def build_linear_baseline(rows, spec, report, label):
    """Baseline hedgerows or watercourses."""
    index = BaselineIndex()
    out = []
    _report_duplicate_baseline_refs(
        _duplicate_refs(rows, "Parcel Ref"), label, report
    )
    for row in rows:
        blob = row.get("_geom")
        feature_uuid = new_uuid()
        length = numeric(row.get("Length"))
        if length is None and blob is not None:
            length = line_blob_length_m(blob)
        index.add(row.get("Parcel Ref"), feature_uuid, blob_wkt(blob), length)
        values = {
            REF_FIELD: row.get("Parcel Ref"),
            "Baseline Condition": row.get("Baseline Condition"),
            "Baseline Distinctiveness": row.get("Baseline Distinctiveness"),
            "Baseline Strategic Significance": row.get(
                "Baseline Strategic Significance"
            ),
            "Length": length,
            "Comment": row.get("Comments") or row.get("Comment"),
            "feature_uuid": feature_uuid,
        }
        for target, source in spec.items():
            values[target] = row.get(source)
        out.append((blob, values))
    return out, index


def build_tree_baseline(rows, report):
    index = BaselineIndex()
    out = []
    _report_duplicate_baseline_refs(
        _duplicate_refs(rows, "Tree Ref"), "Urban Trees", report
    )
    for row in rows:
        blob = row.get("_geom")
        feature_uuid = new_uuid()
        count = numeric(row.get("Count"))
        index.add(row.get("Tree Ref"), feature_uuid, blob_wkt(blob), count)
        out.append(
            (
                blob,
                {
                    REF_FIELD: row.get("Tree Ref"),
                    "Baseline Tree Size": row.get("Baseline Tree Size"),
                    "Baseline Tree Type": row.get("Baseline Tree Type"),
                    "Baseline Rural or Urban Tree": row.get(
                        "Baseline Rural or Urban Tree"
                    ),
                    "Baseline Condition": row.get("Baseline Condition"),
                    "Baseline Strategic Significance": row.get(
                        "Baseline Strategic Significance"
                    ),
                    "Count": int(count) if count is not None else None,
                    "Comment": row.get("Comment"),
                    "feature_uuid": feature_uuid,
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
        blob = row.get("_geom")
        if blob is not None:
            blob, was_multipart = demote_multipolygon_blob_to_polygon(blob)
            multipart += 1 if was_multipart else 0
        retention = row.get("Retention Category")
        if retention == RETENTION_LOST:
            retention = RETENTION_CREATED
            lost_converted += 1
        # legacy stores square metres; the new template's column is hectares
        area = sq_metres_to_hectares(row.get("Area"))
        if area is None and blob is not None:
            area = sq_metres_to_hectares(polygon_blob_area_sqm(blob))
        values = {
            REF_FIELD: row.get("_pi_ref"),
            "Baseline Broad Habitat Type": row.get("Baseline Broad Habitat Type"),
            "Baseline Habitat Type": row.get("Baseline Habitat Type"),
            "Baseline Distinctiveness": row.get("Baseline Distinctiveness"),
            "Baseline Condition": row.get("Baseline Condition"),
            "Baseline Strategic Significance": row.get(
                "Baseline Strategic Significance"
            ),
            "Irreplaceable Habitat": None,
            "Retention Category": retention,
            "Proposed Broad Habitat Type": row.get("Proposed Broad Habitat Type"),
            "Proposed Habitat Type": row.get("Proposed Habitat Type"),
            "Proposed Distinctiveness": row.get("Proposed Distinctiveness"),
            "Proposed Condition": row.get("Proposed Condition"),
            "Proposed Strategic Significance": row.get(
                "Proposed Strategic Significance"
            ),
            "Habitat created in advance/years": row.get(
                "Habitat created in advance/years"
            ),
            "Delay in starting habitat creation/years": row.get(
                "Delay in starting habitat creation/years"
            ),
            "Spatial risk category": row.get("Spatial risk category"),
            "Area": area,
        }
        stamp_parent(values, row.get("_parent_ref"), index, unmatched,
                     own_ref=row.get("Parcel Ref"))
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
    _report_unmatched(unmatched, "Habitats", report)
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
        blob = row.get("_geom")
        length = numeric(row.get("Length"))
        if length is None and blob is not None:
            length = line_blob_length_m(blob)
        values = {
            REF_FIELD: row.get("_pi_ref"),
            "Baseline Condition": row.get("Baseline Condition"),
            "Baseline Distinctiveness": row.get("Baseline Distinctiveness"),
            "Baseline Strategic Significance": row.get(
                "Baseline Strategic Significance"
            ),
            "Retention Category": row.get("Retention Category"),
            "Proposed Distinctiveness": row.get("Proposed Distinctiveness"),
            "Proposed Condition": row.get("Proposed Condition"),
            "Proposed Strategic Significance": row.get(
                "Proposed Strategic Significance"
            ),
            "Habitat created in advance/years": row.get(
                "Habitat created in advance/years"
            ),
            "Delay in starting habitat creation/years": row.get(
                "Delay in starting habitat creation/years"
            ),
            "Spatial risk category": row.get("Spatial risk category"),
            "Length": length,
        }
        for target, source in spec.items():
            values[target] = row.get(source)
        if is_watercourse:
            values["Enhancement Type"] = row.get("Enhancement Type")

        parent_ref = row.get("_parent_ref") or row.get("Parcel Ref")
        if stamp_parent(values, row.get("_parent_ref"), index, unmatched,
                        own_ref=row.get("Parcel Ref")):
            values["Baseline Length"] = index.get(parent_ref)["size"]
        out.append((blob, values))

    _report_unmatched(unmatched, label, report)
    return out


def build_tree_pi(rows, index, report):
    """Post-intervention trees; legacy 'Lost' rows are dropped as above."""
    out = []
    unmatched = []
    for row in rows:
        count = numeric(row.get("Count"))
        values = {
            REF_FIELD: row.get("_pi_ref"),
            "Baseline Tree Size": row.get("Baseline Tree Size"),
            "Baseline Tree Type": row.get("Baseline Tree Type"),
            "Baseline Rural or Urban Tree": row.get("Baseline Rural or Urban Tree"),
            "Baseline Condition": row.get("Baseline Condition"),
            "Baseline Strategic Significance": row.get(
                "Baseline Strategic Significance"
            ),
            "Retention Category": row.get("Retention Category"),
            "Proposed Tree Size": row.get("Proposed Tree Size"),
            "Proposed Tree Type": row.get("Proposed Tree Type"),
            "Proposed Rural or Urban Tree": row.get("Proposed Rural or Urban Tree"),
            "Proposed Condition": row.get("Proposed Condition"),
            "Proposed Strategic Significance": row.get(
                "Proposed Strategic Significance"
            ),
            "Category": row.get("Category") or TREE_CATEGORY_EXISTING,
            "Habitat Created/Enhanced in advance/years": row.get(
                "Habitat Created/Enhanced in advance/years"
            ),
            "Delay in starting habitat creation/enhancement in years": row.get(
                "Delay in starting habitat creation/enhancement in years"
            ),
            "Spatial risk category": row.get("Spatial risk category"),
            "Count": int(count) if count is not None else None,
        }
        stamp_parent(values, row.get("_parent_ref"), index, unmatched,
                     own_ref=row.get("Tree Ref"))
        out.append((row.get("_geom"), values))

    _report_unmatched(unmatched, "Trees", report)
    return out


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
        blob = row.get("_geom")
        length = numeric(row.get("Length"))
        if length is None and blob is not None:
            length = line_blob_length_m(blob)
        values = {
            REF_FIELD: row.get("Baseline Parcel Ref"),
            "Retention Category": "Enhanced",
            "Enhancement Type": MEANDER_ENHANCEMENT_TYPE,
            "Proposed River Type": row.get("Proposed River Type"),
            "Proposed Condition": row.get("Proposed Condition"),
            "Proposed Distinctiveness": row.get("Proposed Distinctiveness"),
            "Proposed Strategic Significance": row.get(
                "Proposed Strategic Significance"
            ),
            "Proposed Encroachment into Watercourse": row.get(
                "Proposed Encroachment into Watercourse"
            ),
            "Proposed Encroachment into riparian zone": row.get(
                "Proposed Encroachment into riparian zone"
            ),
            "Baseline Distinctiveness": row.get("Baseline Distinctiveness"),
            "Habitat created in advance/years": row.get(
                "Habitat created in advance/years "
            )
            or row.get("Habitat created in advance/years"),
            "Delay in starting habitat creation/years": row.get(
                "Delay in starting habitat creation/years"
            ),
            "Spatial risk category": row.get("Spatial risk category"),
            "Length": length,
        }
        parent_ref = row.get("Baseline Parcel Ref")
        if stamp_parent(values, parent_ref, index, unmatched):
            values["Baseline Length"] = index.get(parent_ref)["size"]
        out.append((blob, values))

    report.warn(
        f"{len(out)} row(s) from the legacy 'Water course enhancement through "
        "meanders' layer were carried into Watercourses Post-Intervention as "
        f"Enhanced, with Enhancement Type '{MEANDER_ENHANCEMENT_TYPE}'. The new "
        "template has no separate meanders layer, so this is an interpretation — "
        "check these rows."
    )
    _report_unmatched(unmatched, "Meanders", report)
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
        known = {name for name, _ in spec["columns"]} | {spec["geom_column"]}
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
        absent = [name for name, _ in STAGED_LAYERS[layer]["columns"]
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
    column_names = [name for name, _ in spec["columns"] if name in present]
    placeholders = ", ".join(["?"] * (len(column_names) + 1))
    quoted = ", ".join(
        [quote_ident(spec["geom_column"])]
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
            conn, table, spec["geom_column"], spec["geom_type"], spec["columns"]
        )
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

HEDGEROW_BASELINE_SPEC = {"Baseline Hedge Type": "Baseline Hedge Type"}
HEDGEROW_PI_SPEC = {
    "Baseline Hedge Type": "Baseline Hedge Type",
    "Proposed Hedge Type": "Proposed Hedge Type",
}
WATERCOURSE_BASELINE_SPEC = {
    "Baseline River Type": "Baseline River Type",
    "Baseline Encroachment into Watercourse": "Baseline Encroachment into Watercourse",
    "Baseline Encroachment into riparian zone": (
        "Baseline Encroachment into riparian zone"
    ),
}
WATERCOURSE_PI_SPEC = {
    "Baseline River Type": "Baseline River Type",
    "Baseline Encroachment into Watercourse": "Baseline Encroachment into Watercourse",
    "Baseline Encroachment into riparian zone": (
        "Baseline Encroachment into riparian zone"
    ),
    "Proposed River Type": "Proposed River Type",
    "Proposed Encroachment into Watercourse": "Proposed Encroachment into Watercourse",
    "Proposed Encroachment into riparian zone": (
        "Proposed Encroachment into riparian zone"
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

    if not baseline["redline"]:
        report.warn(
            "The baseline file has no Red Line Boundary feature — the new "
            "template needs one, and it carries the site details."
        )

    site = site_details(post or baseline) if (post or baseline) else {}
    for field in SITE_DETAIL_FIELDS:
        if site.get(field) in (None, ""):
            site[field] = site_details(baseline).get(field)

    # Build the baseline side first: every stamp a child needs comes from here.
    area_baseline, area_index = build_area_baseline(baseline["areas"], report)
    hedge_baseline, hedge_index = build_linear_baseline(
        baseline["hedgerows"], HEDGEROW_BASELINE_SPEC, report, "Hedgerows"
    )
    water_baseline, water_index = build_linear_baseline(
        baseline["watercourses"], WATERCOURSE_BASELINE_SPEC, report, "Watercourses"
    )
    tree_baseline, tree_index = build_tree_baseline(baseline["trees"], report)

    area_pi, hedge_pi, water_pi, tree_pi = [], [], [], []
    if post:
        recovered = 0
        for key in ("areas", "hedgerows", "watercourses", "trees"):
            recovered += read_breadcrumbs(post[key])
        if recovered:
            report.note(
                f"Recovered {recovered} lineage breadcrumb(s) from the "
                "comment column, left there by the conversion out to legacy"
            )

        post["hedgerows"] = drop_lost_rows(
            post["hedgerows"], "Parcel Ref", "Hedgerows", report, hedge_index
        )
        post["watercourses"] = drop_lost_rows(
            post["watercourses"], "Parcel Ref", "Watercourses", report,
            water_index,
        )
        post["trees"] = drop_lost_rows(
            post["trees"], "Tree Ref", "Trees", report, tree_index
        )
        _post_significance(post, report)
        _post_spatial_risk(post, report)
        _post_timing(post, report)

        unique_pi_refs(post["areas"], "Parcel Ref", report, "Habitats")
        unique_pi_refs(post["hedgerows"], "Parcel Ref", report, "Hedgerows")
        unique_pi_refs(post["watercourses"], "Parcel Ref", report, "Watercourses")
        unique_pi_refs(post["trees"], "Tree Ref", report, "Trees")

        area_pi = build_area_pi(post["areas"], area_index, report)
        hedge_pi = build_linear_pi(
            post["hedgerows"], hedge_index, HEDGEROW_PI_SPEC, report, "Hedgerows"
        )
        water_pi = build_linear_pi(
            post["watercourses"], water_index, WATERCOURSE_PI_SPEC, report,
            "Watercourses", is_watercourse=True,
        )
        water_pi.extend(build_meander_rows(post["meanders"], water_index, report))
        tree_pi = build_tree_pi(post["trees"], tree_index, report)
    else:
        report.note(
            "No post-intervention file given — only the baseline was converted."
        )

    redline_rows = [
        (row.get("_geom"), {field: site.get(field) for field in SITE_DETAIL_FIELDS})
        for row in baseline["redline"]
    ]

    tables = {
        "Red Line Boundary": redline_rows,
        "Area Habitats Baseline": area_baseline,
        "Area Habitats Post-Intervention": area_pi,
        "Hedgerows Baseline": hedge_baseline,
        "Hedgerows Post-Intervention": hedge_pi,
        "Watercourses Baseline": water_baseline,
        "Watercourses Post-Intervention": water_pi,
        "Individual Trees Baseline": tree_baseline,
        "Individual Trees Post-Intervention": tree_pi,
    }
    for table, rows in tables.items():
        report.count(table, len(rows))

    _fill_template_values(tables, report)
    _report_lineage_quality(tables, report)
    _report_manual_steps(tables, report)
    check_needed_values(_as_staged(tables), report, INCOMING_GAP_CONSEQUENCE,
                        skip=("Irreplaceable Habitat",))

    if dry_run:
        return report

    if into_path:
        conn, table_names = open_template_gpkg(into_path, force)
        target = into_path
        _report_missing_columns(missing_columns(conn, table_names), report)
        _report_extra_columns(extra_columns(conn, table_names), report)
    else:
        if out_file:
            target = out_file
            parent = os.path.dirname(os.path.abspath(target))
            os.makedirs(parent, exist_ok=True)
        else:
            os.makedirs(out_dir, exist_ok=True)
            stem = os.path.splitext(os.path.basename(baseline_path))[0]
            target = os.path.join(out_dir, f"{stem} - Staged.gpkg")
        conn = create_staged_gpkg(target, baseline["srs"])
        # A file we create ourselves carries the template's own table names.
        table_names = {layer: layer for layer in STAGED_LAYERS}

    try:
        for table, rows in tables.items():
            insert_rows(conn, table, rows, table_names[table])
        for table, spec in STAGED_LAYERS.items():
            update_layer_extent(conn, table_names[table], spec["geom_column"])
        conn.commit()
    finally:
        conn.close()

    report.note(f"Staged file: {target}")
    return report


# Legacy layer key -> (its reference column, how it reads in a message).
LEGACY_REFS = {
    "areas": ("Parcel Ref", "Habitats"),
    "hedgerows": ("Parcel Ref", "Hedgerows"),
    "watercourses": ("Parcel Ref", "Watercourses"),
    "trees": ("Tree Ref", "Trees"),
    "meanders": ("Baseline Parcel Ref", "Meanders"),
}
HABITAT_KEYS = ("areas", "hedgerows", "watercourses", "trees")


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


RETENTION_CATEGORY = "Retention Category"
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
            if BASELINE_SIGNIFICANCE in row:
                value = plain_label(row.get(BASELINE_SIGNIFICANCE))
                if has_baseline_part(key, row):
                    stored = SIGNIFICANCE_LOW
                    if value != NE_SIGNIFICANCE_LOW:
                        changed.append(ref)
                else:
                    stored = None
                    if value not in (None, "", NOT_APPLICABLE):
                        changed.append(ref)
                row[BASELINE_SIGNIFICANCE] = stored
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
        _report_significance(label, changed, medium, unknown, report)
        if retained:
            report.warn(
                f"{label}: {len(retained)} Retained post-intervention row(s) "
                f"had a Proposed Strategic Significance other than Low "
                f"({summarise_refs(retained)}). A retained habitat keeps its "
                "baseline value, which the template holds as Low, so they "
                "were written as Low."
            )


def _report_significance(label, changed, medium, unknown, report):
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


def _post_timing(post, report):
    """Name the rows with years in advance and years of delay both above 0.

    The metric allows one or the other. The template blanks one when the
    other is above 0, but cannot tell which value to keep for a row that
    arrives with both, so the converter keeps both and names the rows.
    """
    for key, (_ref_column, label) in LEGACY_REFS.items():
        both = []
        for row in post[key]:
            advance, delay = timing_columns(row)
            if _above_zero(row.get(advance)) and _above_zero(row.get(delay)):
                both.append(_legacy_ref(row, key))
        if both:
            report.warn(
                f"{label}: {len(both)} post-intervention row(s) have both "
                f"years created in advance and years of delay above 0 "
                f"({summarise_refs(both)}). The metric allows only one. "
                "Clear one of them for these rows."
            )


def timing_columns(row):
    """(years created in advance, years of delay) as this row names them."""
    if "Habitat Created/Enhanced in advance/years" in row:
        return ("Habitat Created/Enhanced in advance/years",
                "Delay in starting habitat creation/enhancement in years")
    return ("Habitat created in advance/years",
            "Delay in starting habitat creation/years")


def _above_zero(value):
    text = "" if value is None else str(value).strip()
    return text not in ("", "0")


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
    "areas": AREA_HABITAT_LAYERS,
    "hedgerows": ("Hedgerows Baseline", "Hedgerows Post-Intervention"),
    "watercourses": ("Watercourses Baseline", "Watercourses Post-Intervention"),
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
        kind: {"baseline": [values for _, values in tables[base]],
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
            if values.get("parent_uuid"):
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
    blank = [
        values.get(REF_FIELD)
        for table, rows in tables.items()
        if table in AREA_HABITAT_LAYERS
        for _, values in rows
        if values.get("Irreplaceable Habitat") is None
    ]
    if blank:
        report.warn(
            f"Irreplaceable Habitat is blank on {len(blank)} area habitat row(s) "
            f"({summarise_refs(blank)}). The legacy template has "
            "no such column, and their habitat can be either. Choose Yes or "
            "No before uploading."
        )
    report.warn(
        "Vertical area habitats (green walls, intertidal hard structures) are "
        "empty: the legacy template cannot record them. Add any that exist."
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
        ("baseline", args.baseline),
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
