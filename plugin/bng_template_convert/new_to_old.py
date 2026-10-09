#!/usr/bin/env python3
"""
Convert a BNG Service (staged) GeoPackage into the pair of legacy Natural
England GeoPackages the older Biodiversity Metric service expects.

    new template  ->  1 file,  Baseline + Post-Intervention tables per habitat type
    old template  ->  2 files, one table per habitat type (uploaded separately)

Zero dependencies: a GeoPackage is a SQLite database, and geometry blobs are
copied verbatim, so nothing here needs GDAL, QGIS or the network.

Usage:
    python3 new_to_old.py "BNG Service Layers.gpkg" -o output/
    python3 new_to_old.py "BNG Service Layers.gpkg" --dry-run

See README.md for the full walkthrough and the list of known losses.
"""

import argparse
import csv
import os
import re
import sqlite3
import struct
import sys
from collections import OrderedDict, defaultdict

# Works both as a standalone script and as a module inside the QGIS
# plugin package, where the import has to be relative.
try:
    from .gpkg_common import (
        SQ_METRES_PER_HECTARE,
        create_feature_table,
        create_gpkg_system_tables,
        feature_table_names,
        hectares_to_sq_metres,
        numeric,
        plain_label,
        polygon_blob_area_sqm,
        promote_polygon_blob_to_multipolygon,
        quote_ident,
        quoted_names,
        read_feature_table,
        read_only_uri,
        read_srs_rows,
        part_path,
        require_service_tables,
        parts_needed,
        resolve_table_name,
        split_into_parts,
        summarise_list,
        update_layer_extent,
    )
except ImportError:  # pragma: no cover - running as a plain script
    from gpkg_common import (
        SQ_METRES_PER_HECTARE,
        create_feature_table,
        create_gpkg_system_tables,
        feature_table_names,
        hectares_to_sq_metres,
        numeric,
        plain_label,
        polygon_blob_area_sqm,
        promote_polygon_blob_to_multipolygon,
        quote_ident,
        quoted_names,
        read_feature_table,
        read_only_uri,
        read_srs_rows,
        part_path,
        require_service_tables,
        parts_needed,
        resolve_table_name,
        split_into_parts,
        summarise_list,
        update_layer_extent,
    )

try:
    from .reference_lists import to_legacy_labels, to_legacy_significance
    from .to_metric import check_needed_values
except ImportError:  # pragma: no cover - running as a plain script
    from reference_lists import to_legacy_labels, to_legacy_significance
    from to_metric import check_needed_values

# Sizes below this are treated as "no shortfall" when deciding whether a
# baseline feature was partly removed. Legacy stores whole metres, and the
# service itself rounds linear sizes to whole metres before use. Area
# habitats are in hectares here; half a square metre is the service's own
# area tolerance.
LENGTH_TOLERANCE_M = 0.5
AREA_TOLERANCE_HA = 0.5 / SQ_METRES_PER_HECTARE
COUNT_TOLERANCE = 0

# What a blank costs on the way out to legacy: the gap travels with the row.
LEGACY_GAP_CONSEQUENCE = (
    "The rows are written with the gaps, to the legacy files and the CSVs "
    "alike, and the metric cannot score them until the values are filled in.")

RETENTION_LOST = "Lost"
TREE_CATEGORY_EXISTING = "Existing"

# ---------------------------------------------------------------------------
# Legacy schema — mirrors the reference the service validates uploads against
# (gpkg-template.schema.json). Column names, order and SQLite types all matter:
# a missing column or a mismatched declared type is a hard validation error.
# Geometry column NAMES are not checked, but the registered geometry TYPE is.
# ---------------------------------------------------------------------------

SITE_COLUMNS_WIDE = [
    ("Location", "TEXT(99)"),
    ("Site Name", "TEXT(999)"),
    ("Survey Date", "DATE"),
    ("Survey Details", "TEXT(999)"),
]
SITE_COLUMNS_TAIL = [
    ("Mapped by", "TEXT(999)"),
    ("Company", "TEXT(999)"),
    ("Base Map", "TEXT(999)"),
]

LEGACY_LAYERS = {
    "Habitats": {
        "geom_column": "geom",
        "geom_type": "MULTIPOLYGON",
        "columns": [
            ("Parcel Ref", "TEXT(99)"),
            ("Baseline Broad Habitat Type", "TEXT(99)"),
            ("Baseline Habitat Type", "TEXT(99)"),
            ("Area", "MEDIUMINT"),
            ("Baseline Condition", "TEXT(99)"),
            ("Baseline Strategic Significance", "TEXT(99)"),
            ("Retention Category", "TEXT(99)"),
            ("Proposed Broad Habitat Type", "TEXT(99)"),
            ("Proposed Habitat Type", "TEXT(99)"),
            ("Proposed Condition", "TEXT(99)"),
            ("Proposed Strategic Significance", "TEXT(99)"),
            ("Habitat created in advance/years", "TEXT(99)"),
            ("Delay in starting habitat creation/years", "TEXT(99)"),
            ("Spatial risk category", "TEXT(99)"),
            *SITE_COLUMNS_WIDE,
            ("Comment", "TEXT(999)"),
            *SITE_COLUMNS_TAIL,
            ("Baseline Distinctiveness", "TEXT(999)"),
            ("Proposed Distinctiveness", "TEXT(999)"),
        ],
    },
    "Hedgerows": {
        "geom_column": "geom",
        "geom_type": "LINESTRING",
        "columns": [
            ("Parcel Ref", "TEXT(99)"),
            ("Baseline Hedge Type", "TEXT(99)"),
            ("Baseline Condition", "TEXT(99)"),
            ("Baseline Strategic Significance", "TEXT(99)"),
            ("Retention Category", "TEXT(99)"),
            ("Proposed Hedge Type", "TEXT(99)"),
            ("Proposed Condition", "TEXT(99)"),
            ("Proposed Strategic Significance", "TEXT(99)"),
            ("Length", "MEDIUMINT"),
            ("Habitat created in advance/years", "TEXT(99)"),
            ("Delay in starting habitat creation/years", "TEXT(99)"),
            ("Spatial risk category", "TEXT(99)"),
            *SITE_COLUMNS_WIDE,
            ("Comments", "TEXT(999)"),
            *SITE_COLUMNS_TAIL,
            ("Baseline Distinctiveness", "TEXT(999)"),
            ("Proposed Distinctiveness", "TEXT(999)"),
        ],
    },
    "Rivers": {
        "geom_column": "geom",
        "geom_type": "LINESTRING",
        "columns": [
            ("Parcel Ref", "TEXT(99)"),
            ("Baseline River Type", "TEXT(99)"),
            ("Baseline Condition", "TEXT(99)"),
            ("Baseline Strategic Significance", "TEXT(99)"),
            ("Baseline Encroachment into Watercourse", "TEXT(99)"),
            ("Baseline Encroachment into riparian zone", "TEXT(99)"),
            ("Retention Category", "TEXT(99)"),
            ("Proposed River Type", "TEXT(99)"),
            ("Proposed Condition", "TEXT(99)"),
            ("Proposed Strategic Significance", "TEXT(99)"),
            ("Length", "MEDIUMINT"),
            ("Habitat created in advance/years", "TEXT(99)"),
            ("Delay in starting habitat creation/years", "TEXT(99)"),
            ("Spatial risk category", "TEXT(99)"),
            ("Location", "TEXT(99)"),
            ("Proposed Encroachment into Watercourse", "TEXT(99)"),
            ("Proposed Encroachment into riparian zone", "TEXT(99)"),
            ("Site Name", "TEXT(999)"),
            ("Survey Date", "DATE"),
            ("Survey Details", "TEXT(999)"),
            ("Comments", "TEXT(999)"),
            *SITE_COLUMNS_TAIL,
            ("Enhancement Type", "TEXT(999)"),
            ("Baseline Distinctiveness", "TEXT(999)"),
            ("Proposed Distinctiveness", "TEXT(999)"),
        ],
    },
    "Urban Trees": {
        "geom_column": "geometry",
        "geom_type": "POINT",
        "columns": [
            ("Tree Ref", "TEXT(99)"),
            ("Baseline Tree Size", "TEXT(99)"),
            ("Baseline Condition", "TEXT(99)"),
            ("Baseline Strategic Significance", "TEXT(99)"),
            ("Baseline Tree Type", "TEXT(99)"),
            ("Retention Category", "TEXT(99)"),
            ("Category", "TEXT(99)"),
            ("Proposed Tree Size", "TEXT(99)"),
            ("Proposed Condition", "TEXT(99)"),
            ("Proposed Strategic Significance", "TEXT(99)"),
            ("Proposed Tree Type", "TEXT(99)"),
            ("Location", "TEXT(99)"),
            ("Habitat Created/Enhanced in advance/years", "TEXT(99)"),
            ("Delay in starting habitat creation/enhancement in years", "TEXT(99)"),
            ("Spatial risk category", "TEXT(99)"),
            ("Site Name", "TEXT(999)"),
            ("Survey Date", "DATE"),
            ("Survey Details", "TEXT(999)"),
            ("Comment", "TEXT(999)"),
            *SITE_COLUMNS_TAIL,
            ("Count", "MEDIUMINT"),
            ("Baseline Rural or Urban Tree", "TEXT(999)"),
            ("Proposed Rural or Urban Tree", "TEXT(999)"),
        ],
    },
    "Red Line Boundary": {
        "geom_column": "geometry",
        "geom_type": "POLYGON",
        "columns": [
            ("Area", "REAL"),
            ("Site Name", "TEXT(99)"),
        ],
    },
    "Water course enhancement through meanders": {
        "geom_column": "geometry",
        "geom_type": "LINESTRING",
        "columns": [
            ("Baseline Parcel Ref", "TEXT(999)"),
            ("Proposed River Type", "TEXT(999)"),
            ("Proposed Condition", "TEXT(999)"),
            ("Proposed Strategic Significance", "TEXT(99)"),
            ("Proposed Encroachment into Watercourse", "TEXT(999)"),
            ("Proposed Encroachment into riparian zone", "TEXT(999)"),
            ("Length", "MEDIUMINT"),
            # NB: the shipped NE template spells this with a trailing space in
            # its own file; the service validates against the trimmed name.
            ("Habitat created in advance/years", "TEXT(999)"),
            ("Delay in starting habitat creation/years", "TEXT(999)"),
            ("Location", "TEXT(999)"),
            ("Spatial risk category", "TEXT(999)"),
            ("Baseline Distinctiveness", "TEXT(999)"),
            ("Proposed Distinctiveness", "TEXT(999)"),
        ],
    },
}

# Staged (new template) table names, by habitat type. Resolution is by EXACT
# name (see resolve_table_name), so "Area Habitats Baseline" can never match
# "Vertical Area Habitats Baseline".
STAGED_TABLES = {
    "areas": {
        "label": "Area habitats",
        "baseline": ("Area Habitats Baseline",),
        "pi": ("Area Habitats Post-Intervention",),
    },
    "hedgerows": {
        "label": "Hedgerows",
        "baseline": ("Hedgerows Baseline",),
        "pi": ("Hedgerows Post-Intervention",),
    },
    "watercourses": {
        "label": "Watercourses",
        "baseline": ("Watercourses Baseline",),
        "pi": ("Watercourses Post-Intervention",),
    },
    "trees": {
        "label": "Trees",
        "baseline": ("Individual Trees Baseline",),
        "pi": ("Individual Trees Post-Intervention",),
    },
    "verticalAreas": {
        "label": "Vertical area habitats",
        "baseline": ("Vertical Area Habitats Baseline",),
        "pi": ("Vertical Area Habitats Post-Intervention",),
    },
}
# Key in STAGED_TABLES -> how that stage reads in a message.
STAGED_STAGES = (("baseline", "baseline"), ("pi", "post-intervention"))
STAGED_REDLINE_TABLE = "Red Line Boundary"
# Every staged habitat table holds its reference in this one column. Legacy
# calls it Parcel Ref, or Tree Ref for trees.
REF_FIELD = "Habitat Ref"

SITE_DETAIL_FIELDS = [
    "Site Name",
    "Location",
    "Survey Date",
    "Survey Details",
    "Mapped by",
    "Company",
    "Base Map",
]


# ---------------------------------------------------------------------------
# Writing an empty legacy GeoPackage
# ---------------------------------------------------------------------------


def create_legacy_gpkg(path, srs_rows):
    """Create an empty GeoPackage carrying the six legacy layers."""
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    create_gpkg_system_tables(conn, srs_rows)
    for table, spec in LEGACY_LAYERS.items():
        create_feature_table(
            conn, table, spec["geom_column"], spec["geom_type"], spec["columns"]
        )
    conn.commit()
    return conn


def rounded_size(value):
    """Legacy size columns are integer-typed; match that (and the service's own
    whole-metre rounding of linear sizes)."""
    number = numeric(value)
    return None if number is None else int(round(number))


# ---------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------


def child_ref(row):
    """The reference a post-intervention row carries in the new template."""
    return row.get(REF_FIELD)


def continuing_ref(row):
    """Ref to write into a legacy PI row for the linear/tree types.

    Legacy resolves an Enhanced hedgerow or watercourse back to its baseline by
    matching this ref against the baseline file, so a child of a split parcel
    must carry its PARENT's ref. New features (no parent) keep their own.
    """
    return row.get("Parent Ref") or child_ref(row)


def site_details(redline_rows):
    """Site-wide details, which the new template stores once on the red line."""
    if not redline_rows:
        return {field: None for field in SITE_DETAIL_FIELDS}
    first = redline_rows[0]
    return {field: first.get(field) for field in SITE_DETAIL_FIELDS}


def with_site(values, site, comment_column=None, comment=None):
    """Fan the site-wide details out onto a legacy row, as legacy expects."""
    values.update(
        {
            "Location": site.get("Location"),
            "Site Name": site.get("Site Name"),
            "Survey Date": site.get("Survey Date"),
            "Survey Details": site.get("Survey Details"),
            "Mapped by": site.get("Mapped by"),
            "Company": site.get("Company"),
            "Base Map": site.get("Base Map"),
        }
    )
    if comment_column:
        values[comment_column] = comment
    return values


def parent_note(row):
    """Breadcrumb for area rows, which keep their own ref and lose the parent's."""
    parent = row.get("Parent Ref")
    return f"[parent={parent}]" if parent else None


def child_note(row):
    """Breadcrumb for linear/tree rows, which take the PARENT's ref and so lose
    their own."""
    own = child_ref(row)
    parent = row.get("Parent Ref")
    if not own or not parent or own == parent:
        return None
    return f"[pi={own}]"


def merged_comment(base_comment, note):
    if not note:
        return base_comment
    if base_comment:
        return f"{base_comment} {note}"
    return note


# --- area habitats ---------------------------------------------------------


def map_area_baseline(row, site):
    return with_site(
        {
            "Parcel Ref": row.get(REF_FIELD),
            "Baseline Broad Habitat Type": row.get("Baseline Broad Habitat Type"),
            "Baseline Habitat Type": row.get("Baseline Habitat Type"),
            "Baseline Distinctiveness": row.get("Baseline Distinctiveness"),
            "Baseline Condition": row.get("Baseline Condition"),
            "Baseline Strategic Significance": row.get(
                "Baseline Strategic Significance"
            ),
            "Area": rounded_size(hectares_to_sq_metres(row.get("Area"))),
        },
        site,
        "Comment",
        row.get("Comment"),
    )


def map_area_pi(row, site, carry_lineage):
    # Area habitats keep the CHILD ref: legacy rejects duplicate Parcel Refs in
    # the habitats layer, and a split parcel would otherwise repeat its parent's.
    return with_site(
        {
            "Parcel Ref": child_ref(row),
            "Baseline Broad Habitat Type": row.get("Baseline Broad Habitat Type"),
            "Baseline Habitat Type": row.get("Baseline Habitat Type"),
            "Baseline Distinctiveness": row.get("Baseline Distinctiveness"),
            "Baseline Condition": row.get("Baseline Condition"),
            "Baseline Strategic Significance": row.get(
                "Baseline Strategic Significance"
            ),
            "Retention Category": row.get("Retention Category"),
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
            "Area": rounded_size(hectares_to_sq_metres(row.get("Area"))),
            # Private, and dropped by every writer: both of them iterate the
            # legacy column list. Kept so CSV consolidation can group on it.
            IRREPLACEABLE_KEY: normalise_irreplaceable(
                row.get("Irreplaceable Habitat")
            ),
        },
        site,
        "Comment",
        merged_comment(row.get("Comment"),
                       parent_note(row) if carry_lineage else None),
    )


def area_lost_row(parent, lost_hectares, site):
    """A CSV row for area habitat baseline that nothing carries forward.

    The import tool builds the metric's baseline from these rows alone, so a
    parcel with nothing in post-intervention would otherwise vanish from the
    baseline instead of counting as lost.
    """
    return with_site(
        {
            "Parcel Ref": parent.get(REF_FIELD),
            "Baseline Broad Habitat Type": parent.get("Baseline Broad Habitat Type"),
            "Baseline Habitat Type": parent.get("Baseline Habitat Type"),
            "Baseline Distinctiveness": parent.get("Baseline Distinctiveness"),
            "Baseline Condition": parent.get("Baseline Condition"),
            "Baseline Strategic Significance": parent.get(
                "Baseline Strategic Significance"
            ),
            "Retention Category": RETENTION_LOST,
            "Area": rounded_size(hectares_to_sq_metres(lost_hectares)),
            IRREPLACEABLE_KEY: normalise_irreplaceable(
                parent.get("Irreplaceable Habitat")
            ),
        },
        site,
        "Comment",
        "Not carried forward to post-intervention — written by the conversion",
    )


# --- hedgerows -------------------------------------------------------------


def map_hedgerow_baseline(row, site):
    return with_site(
        {
            "Parcel Ref": row.get(REF_FIELD),
            "Baseline Hedge Type": row.get("Baseline Hedge Type"),
            "Baseline Distinctiveness": row.get("Baseline Distinctiveness"),
            "Baseline Condition": row.get("Baseline Condition"),
            "Baseline Strategic Significance": row.get(
                "Baseline Strategic Significance"
            ),
            "Length": rounded_size(row.get("Length")),
        },
        site,
        "Comments",
        row.get("Comment"),
    )


def map_hedgerow_pi(row, site, carry_lineage):
    return with_site(
        {
            "Parcel Ref": continuing_ref(row),
            "Baseline Hedge Type": row.get("Baseline Hedge Type"),
            "Baseline Distinctiveness": row.get("Baseline Distinctiveness"),
            "Baseline Condition": row.get("Baseline Condition"),
            "Baseline Strategic Significance": row.get(
                "Baseline Strategic Significance"
            ),
            "Retention Category": row.get("Retention Category"),
            "Proposed Hedge Type": row.get("Proposed Hedge Type"),
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
            "Length": rounded_size(row.get("Length")),
        },
        site,
        "Comments",
        merged_comment(row.get("Comment"),
                       child_note(row) if carry_lineage else None),
    )


def hedgerow_lost_row(parent, lost_length, site):
    return with_site(
        {
            "Parcel Ref": parent.get(REF_FIELD),
            "Baseline Hedge Type": parent.get("Baseline Hedge Type"),
            "Baseline Distinctiveness": parent.get("Baseline Distinctiveness"),
            "Baseline Condition": parent.get("Baseline Condition"),
            "Baseline Strategic Significance": parent.get(
                "Baseline Strategic Significance"
            ),
            "Retention Category": RETENTION_LOST,
            "Length": int(round(lost_length)),
        },
        site,
        "Comments",
        "Removed — written by the conversion from the baseline feature",
    )


# --- watercourses ----------------------------------------------------------


def map_watercourse_baseline(row, site):
    return with_site(
        {
            "Parcel Ref": row.get(REF_FIELD),
            "Baseline River Type": row.get("Baseline River Type"),
            "Baseline Distinctiveness": row.get("Baseline Distinctiveness"),
            "Baseline Condition": row.get("Baseline Condition"),
            "Baseline Strategic Significance": row.get(
                "Baseline Strategic Significance"
            ),
            "Baseline Encroachment into Watercourse": row.get(
                "Baseline Encroachment into Watercourse"
            ),
            "Baseline Encroachment into riparian zone": row.get(
                "Baseline Encroachment into riparian zone"
            ),
            "Length": rounded_size(row.get("Length")),
        },
        site,
        "Comments",
        row.get("Comment"),
    )


def map_watercourse_pi(row, site, carry_lineage):
    return with_site(
        {
            "Parcel Ref": continuing_ref(row),
            "Baseline River Type": row.get("Baseline River Type"),
            "Baseline Distinctiveness": row.get("Baseline Distinctiveness"),
            "Baseline Condition": row.get("Baseline Condition"),
            "Baseline Strategic Significance": row.get(
                "Baseline Strategic Significance"
            ),
            "Baseline Encroachment into Watercourse": row.get(
                "Baseline Encroachment into Watercourse"
            ),
            "Baseline Encroachment into riparian zone": row.get(
                "Baseline Encroachment into riparian zone"
            ),
            "Retention Category": row.get("Retention Category"),
            "Proposed River Type": row.get("Proposed River Type"),
            "Proposed Distinctiveness": row.get("Proposed Distinctiveness"),
            "Proposed Condition": row.get("Proposed Condition"),
            "Proposed Strategic Significance": row.get(
                "Proposed Strategic Significance"
            ),
            "Proposed Encroachment into Watercourse": row.get(
                "Proposed Encroachment into Watercourse"
            ),
            "Proposed Encroachment into riparian zone": row.get(
                "Proposed Encroachment into riparian zone"
            ),
            "Enhancement Type": row.get("Enhancement Type"),
            "Habitat created in advance/years": row.get(
                "Habitat created in advance/years"
            ),
            "Delay in starting habitat creation/years": row.get(
                "Delay in starting habitat creation/years"
            ),
            "Spatial risk category": row.get("Spatial risk category"),
            "Length": rounded_size(row.get("Length")),
        },
        site,
        "Comments",
        merged_comment(row.get("Comment"),
                       child_note(row) if carry_lineage else None),
    )


def watercourse_lost_row(parent, lost_length, site):
    return with_site(
        {
            "Parcel Ref": parent.get(REF_FIELD),
            "Baseline River Type": parent.get("Baseline River Type"),
            "Baseline Distinctiveness": parent.get("Baseline Distinctiveness"),
            "Baseline Condition": parent.get("Baseline Condition"),
            "Baseline Strategic Significance": parent.get(
                "Baseline Strategic Significance"
            ),
            "Baseline Encroachment into Watercourse": parent.get(
                "Baseline Encroachment into Watercourse"
            ),
            "Baseline Encroachment into riparian zone": parent.get(
                "Baseline Encroachment into riparian zone"
            ),
            "Retention Category": RETENTION_LOST,
            "Length": int(round(lost_length)),
        },
        site,
        "Comments",
        "Removed — written by the conversion from the baseline feature",
    )


# --- trees -----------------------------------------------------------------


def map_tree_baseline(row, site):
    return with_site(
        {
            "Tree Ref": row.get(REF_FIELD),
            "Baseline Tree Size": row.get("Baseline Tree Size"),
            "Baseline Tree Type": row.get("Baseline Tree Type"),
            "Baseline Rural or Urban Tree": row.get("Baseline Rural or Urban Tree"),
            "Baseline Condition": row.get("Baseline Condition"),
            "Baseline Strategic Significance": row.get(
                "Baseline Strategic Significance"
            ),
            "Category": TREE_CATEGORY_EXISTING,
            "Count": rounded_size(row.get("Count")),
        },
        site,
        "Comment",
        row.get("Comment"),
    )


def map_tree_pi(row, site, carry_lineage):
    return with_site(
        {
            "Tree Ref": continuing_ref(row),
            "Baseline Tree Size": row.get("Baseline Tree Size"),
            "Baseline Tree Type": row.get("Baseline Tree Type"),
            "Baseline Rural or Urban Tree": row.get("Baseline Rural or Urban Tree"),
            "Baseline Condition": row.get("Baseline Condition"),
            "Baseline Strategic Significance": row.get(
                "Baseline Strategic Significance"
            ),
            "Retention Category": row.get("Retention Category"),
            "Category": row.get("Category"),
            "Proposed Tree Size": row.get("Proposed Tree Size"),
            "Proposed Tree Type": row.get("Proposed Tree Type"),
            "Proposed Rural or Urban Tree": row.get("Proposed Rural or Urban Tree"),
            "Proposed Condition": row.get("Proposed Condition"),
            "Proposed Strategic Significance": row.get(
                "Proposed Strategic Significance"
            ),
            "Habitat Created/Enhanced in advance/years": row.get(
                "Habitat Created/Enhanced in advance/years"
            ),
            "Delay in starting habitat creation/enhancement in years": row.get(
                "Delay in starting habitat creation/enhancement in years"
            ),
            "Spatial risk category": row.get("Spatial risk category"),
            "Count": rounded_size(row.get("Count")),
        },
        site,
        "Comment",
        merged_comment(row.get("Comment"),
                       child_note(row) if carry_lineage else None),
    )


def tree_lost_row(parent, lost_count, site):
    return with_site(
        {
            "Tree Ref": parent.get(REF_FIELD),
            "Baseline Tree Size": parent.get("Baseline Tree Size"),
            "Baseline Tree Type": parent.get("Baseline Tree Type"),
            "Baseline Rural or Urban Tree": parent.get("Baseline Rural or Urban Tree"),
            "Baseline Condition": parent.get("Baseline Condition"),
            "Baseline Strategic Significance": parent.get(
                "Baseline Strategic Significance"
            ),
            "Retention Category": RETENTION_LOST,
            "Category": TREE_CATEGORY_EXISTING,
            "Count": int(round(lost_count)),
        },
        site,
        "Comment",
        "Removed — written by the conversion from the baseline feature",
    )


# ---------------------------------------------------------------------------
# Removal ("Lost") synthesis
# ---------------------------------------------------------------------------

# Mirrors the service's own reconciliation policy:
#   shortfall — hedgerows and trees: any baseline size not carried forward is lost
#   presence  — watercourses: a stretch either continues or is wholly removed
REMOVAL_RULE_SHORTFALL = "shortfall"
REMOVAL_RULE_PRESENCE = "presence"


def synthesise_lost_rows(baseline_rows, pi_rows, size_field, rule, tolerance):
    """Work out what the post-intervention file never accounts for.

    Returns [(baseline_row, lost_size)] — the new template records removal by
    simply leaving the feature out, but legacy needs an explicit "Lost" row.
    """
    carried = defaultdict(float)
    has_child = set()
    for row in pi_rows:
        parent = row.get("Parent Ref")
        if not parent:
            continue  # a brand-new feature accounts for no baseline
        has_child.add(parent)
        size = numeric(row.get(size_field))
        if size is not None:
            carried[parent] += size

    losses = []
    for row in baseline_rows:
        ref = row.get(REF_FIELD)
        baseline_size = numeric(row.get(size_field))
        if ref is None or baseline_size is None:
            continue
        if rule == REMOVAL_RULE_PRESENCE:
            if ref not in has_child:
                losses.append((row, baseline_size))
            continue
        shortfall = baseline_size - carried.get(ref, 0.0)
        if shortfall > tolerance:
            losses.append((row, shortfall))
    return losses


# ---------------------------------------------------------------------------
# Writing rows
# ---------------------------------------------------------------------------


# The GIS import tool takes ONE CSV per module and works out which module a
# file holds from its NAME: it looks for 'hab', 'hed' or 'riv' (User Guide
# 2.5.40). These names carry no site prefix on purpose. A site called
# "Riverside" would otherwise put 'riv' into the habitats file name, and which
# module the tool picked would depend on the order it happens to test in.
#
# Individual trees have no entry here because the import tool cannot take them
# at all: the User Guide (2.4.1) says tree points are illustrative and "will
# need to be manually filled into these tools".
CSV_MODULES = [
    ("Habitats", "Habitats.csv"),
    ("Hedgerows", "Hedgerows.csv"),
    ("Rivers", "Rivers.csv"),
]

# The legacy template's project file looks for its data at
# ./Layers/Net Gain Habitat Mapping Layers.gpkg, by that exact name. Naming
# the output to match means a user only has to move it and drop the stage
# suffix, rather than work out what to call it.
LEGACY_LAYERS_STEM = "Net Gain Habitat Mapping Layers"

CSV_SUBFOLDER = "GIS import tool CSVs"
IRREPLACEABLE_CSV = "Irreplaceable habitats.csv"


IRREPLACEABLE_KEY = "_irreplaceable"

# Columns that do not take part in grouping: the reference and comment are
# rebuilt for the merged row, and the size is what gets summed.
CSV_MERGE_EXCLUDED = frozenset(
    {"Parcel Ref", "Comment", "Comments", "Area", "Length"}
)
CSV_SIZE_COLUMNS = ("Area", "Length")

# The GIS import tool holds this many rows per module (User Guide 3.1.5).
IMPORT_TOOL_ROW_LIMIT = 248


def normalise_irreplaceable(value):
    """'Yes' or 'No'. Anything blank or unrecognised is treated as 'No'."""
    text = "" if value is None else str(value).strip().lower()
    return "Yes" if text in ("yes", "y", "true", "1") else "No"


def consolidate_csv_rows(table, rows, split_irreplaceable=True):
    """Group rows agreeing on every metric attribute, summing their size.

    This is the same merge the import tool's Consolidate Data button performs,
    done here instead so the grouping key is ours to choose. It is
    arithmetically free: units are linear in size and merged rows share every
    multiplier, so no total moves. What it costs is the per-parcel audit trail,
    which is why guidance 3.2.3 tells a user who needs that trail not to
    consolidate at all.

    Doing it here buys the one thing the tool cannot do. Irreplaceable habitat
    has no column in the legacy CSVs, so two parcels differing only in whether
    they are irreplaceable look identical to the tool and are merged into a row
    that reads as ordinary habitat. Keeping the flag in the grouping key stops
    that.

    Returns (rows, groups_that_were_split_by_the_flag).
    """
    column_names = [name for name, _ in LEGACY_LAYERS[table]["columns"]]
    size_columns = [name for name in CSV_SIZE_COLUMNS if name in column_names]
    key_columns = [name for name in column_names if name not in CSV_MERGE_EXCLUDED]
    comment_column = "Comments" if "Comments" in column_names else "Comment"

    groups = OrderedDict()
    for geometry, values in rows:
        key = tuple(values.get(name) for name in key_columns)
        if split_irreplaceable:
            key += (values.get(IRREPLACEABLE_KEY, "No"),)
        entry = groups.get(key)
        if entry is None:
            groups[key] = entry = {
                "geometry": geometry,
                "values": dict(values),
                "members": [],
            }
            for name in size_columns:
                entry["values"][name] = 0
        entry["members"].append(values.get("Parcel Ref"))
        for name in size_columns:
            entry["values"][name] = (
                numeric(entry["values"].get(name)) or 0
            ) + (numeric(values.get(name)) or 0)

    merged = []
    flagged_groups = 0
    for index, entry in enumerate(groups.values(), start=1):
        values = entry["values"]
        irreplaceable = values.get(IRREPLACEABLE_KEY, "No") == "Yes"
        if irreplaceable:
            flagged_groups += 1
        # A distinct reference and comment, so a reader can tell the rows
        # apart and so the import tool has something to tell them apart by if
        # its own grouping happens to include either column.
        suffix = "-IRR" if irreplaceable and split_irreplaceable else ""
        values["Parcel Ref"] = f"G{index:04d}{suffix}"
        note = f"{len(entry['members'])} parcel(s) consolidated"
        if irreplaceable:
            note += "; IRREPLACEABLE HABITAT, do not merge with other rows"
        values[comment_column] = note
        for name in size_columns:
            values[name] = rounded_size(values[name])
        merged.append((entry["geometry"], values))
    return merged, flagged_groups


# Columns whose legacy reference list carries the metric's own numbering in
# front of the value, such as "4. Fairly Poor" or "2. Retained". The legacy
# GeoPackages keep that numbering, because the legacy template stores it and
# Natural England's own tooling reads those files. The import tool does not:
# its lookups hold the words alone, so a numbered value matches nothing there
# and the row it belongs to scores zero with no error to say why.
CSV_PLAIN_LABEL_COLUMNS = frozenset(
    {"Baseline Condition", "Proposed Condition", "Retention Category"}
)


def csv_value(value, column=None):
    """A cell as QGIS writes it: missing becomes empty, never the word None.

    Values in the numbered columns lose their list number on the way out.
    """
    if value is None:
        return ""
    if column in CSV_PLAIN_LABEL_COLUMNS:
        return plain_label(value)
    return value


def write_module_csv(path, table, rows):
    """One module's rows, shaped like a 'Save As CSV' of the legacy Master layer.

    Same columns in the same order as the legacy table, with `fid` in front,
    because that is what the import tool is used to reading. Geometry is left
    out: the tool reads attributes only.

    Written with a BOM so Excel opens it as UTF-8 rather than guessing a
    code page and mangling any habitat name that is not plain ASCII.
    """
    column_names = [name for name, _ in LEGACY_LAYERS[table]["columns"]]
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["fid"] + column_names)
        for index, (_geometry, values) in enumerate(rows, start=1):
            writer.writerow(
                [index]
                + [csv_value(values.get(name), name) for name in column_names]
            )
    return len(rows)


def _write_irreplaceable_listing(csv_dir, flagged_rows, report, consolidate,
                                 split_irreplaceable):
    """List irreplaceable parcels on their own, because the CSVs cannot say so.

    The legacy CSVs have no irreplaceable habitat column, so whatever is done
    about grouping, the flag itself does not reach the import tool. The metric
    treats irreplaceable habitat separately anyway, so the useful thing is a
    list the user can work from by hand.
    """
    if not flagged_rows:
        return
    path = os.path.join(csv_dir, IRREPLACEABLE_CSV)
    column_names = [name for name, _ in LEGACY_LAYERS["Habitats"]["columns"]]
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["fid"] + column_names + ["Irreplaceable Habitat"])
        for index, (_geometry, values) in enumerate(flagged_rows, start=1):
            writer.writerow(
                [index]
                + [csv_value(values.get(name), name) for name in column_names]
                + ["Yes"]
            )
    report.count(IRREPLACEABLE_CSV, len(flagged_rows))
    report.warn(
        f"{len(flagged_rows)} parcel(s) are irreplaceable habitat. The legacy "
        f"CSVs have no column for that, so they are also listed on their own "
        f"in {IRREPLACEABLE_CSV}. "
        + (
            "They were kept in separate rows here, but do NOT press "
            "Consolidate Data in the import tool: it cannot see the flag and "
            "would merge them back into ordinary habitat."
            if consolidate and split_irreplaceable
            else "Do NOT press Consolidate Data in the import tool: it cannot "
            "see the flag and would merge them into ordinary habitat."
        )
    )


def insert_rows(conn, table, rows):
    """Insert mapped rows, filling every legacy column (absent keys become NULL).

    `conn` is None when the run was asked for CSVs only, so no GeoPackage was
    opened. The rows are still built and still returned to the caller.
    """
    if conn is None or not rows:
        return 0
    spec = LEGACY_LAYERS[table]
    column_names = [name for name, _ in spec["columns"]]
    placeholders = ", ".join(["?"] * (len(column_names) + 1))
    quoted = ", ".join(
        [quote_ident(spec["geom_column"])]
        + [quote_ident(name) for name in column_names]
    )
    statement = f"INSERT INTO {quote_ident(table)} ({quoted}) VALUES ({placeholders})"

    payload = []
    for geometry, values in rows:
        payload.append([geometry] + [values.get(name) for name in column_names])
    conn.executemany(statement, payload)
    return len(payload)


def geometry_for(table, blob):
    if blob is None:
        return None
    if LEGACY_LAYERS[table]["geom_type"] == "MULTIPOLYGON":
        return promote_polygon_blob_to_multipolygon(blob)
    return blob


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


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


def resolve_staged_tables(source, report):
    """Match every habitat type to the table names this input actually has.

    A type whose table is missing altogether is called out by name. Without
    that, a renamed input would read as zero rows for every type and produce a
    silently empty conversion — indistinguishable from a genuinely empty layer.
    """
    present = feature_table_names(source)
    require_service_tables(present, [
        name for spec in STAGED_TABLES.values()
        for stage, _ in STAGED_STAGES for name in spec[stage]])
    resolved = {}
    for habitat_type, spec in STAGED_TABLES.items():
        names = {}
        for stage, stage_label in STAGED_STAGES:
            candidates = spec[stage]
            table = resolve_table_name(candidates, present)
            names[stage] = table
            if table is None:
                report.warn(
                    f"{spec['label']}: no {stage_label} table in the input — "
                    f"looked for {quoted_names(candidates)}. That layer is "
                    "treated as EMPTY, so nothing from it reaches the legacy "
                    "files. Check the input is a BNG Service template file."
                )
        resolved[habitat_type] = names
    return resolved


def convert(input_path, out_dir, carry_lineage, dry_run, formats=("gpkg",),
            consolidate=False, split_irreplaceable=True):
    """Write the legacy pair, the GIS import tool's CSVs, or both.

    `formats` may hold "gpkg", "csv" or both. It defaults to the GeoPackage
    pair alone so a plain call keeps doing what it always did.

    `consolidate` merges CSV rows that agree on every metric attribute. It
    affects the CSVs only: the GeoPackages carry geometry, and merging that
    away would destroy the map. `split_irreplaceable` keeps irreplaceable
    habitat out of those merges, and is on unless deliberately turned off.
    """
    report = Report()
    source = sqlite3.connect(read_only_uri(input_path), uri=True)

    try:
        staged_tables = resolve_staged_tables(source, report)
    except ValueError:
        source.close()
        raise
    staged = {}
    for habitat_type, names in staged_tables.items():
        staged[habitat_type] = {
            stage: read_feature_table(source, names[stage]) if names[stage] else []
            for stage, _ in STAGED_STAGES
        }
    redline = read_feature_table(source, STAGED_REDLINE_TABLE)
    site = site_details(redline)
    srs_rows = read_srs_rows(source)
    source.close()
    _number_list_values(staged, report)

    if not redline:
        report.warn(
            "No Red Line Boundary feature found — the legacy service requires one."
        )

    _report_losses(staged, report)
    _report_splits(staged, report)
    _report_enhanced_trees(staged, report)
    check_needed_values(staged, report, LEGACY_GAP_CONSEQUENCE)
    # Area habitats account for every square metre of the red line, so on a
    # finished site nothing falls short and this is empty. On a site part-way
    # through it names the parcels not yet carried forward.
    area_losses = synthesise_lost_rows(
        staged["areas"]["baseline"], staged["areas"]["pi"], "Area",
        REMOVAL_RULE_SHORTFALL, AREA_TOLERANCE_HA)

    if dry_run:
        _plan_counts(staged, redline, report)
        return report

    want_gpkg = "gpkg" in formats
    want_csv = "csv" in formats
    if not (want_gpkg or want_csv):
        raise ValueError("nothing to write: ask for gpkg, csv or both")

    os.makedirs(out_dir, exist_ok=True)
    baseline_path = os.path.join(out_dir, f"{LEGACY_LAYERS_STEM} - Baseline.gpkg")
    pi_path = os.path.join(out_dir, f"{LEGACY_LAYERS_STEM} - Post-intervention.gpkg")

    baseline_conn = pi_conn = None
    if want_gpkg:
        baseline_conn = create_legacy_gpkg(baseline_path, srs_rows)
        pi_conn = create_legacy_gpkg(pi_path, srs_rows)

    try:
        _write_redline(baseline_conn, pi_conn, redline, site, report)
        # The post-intervention rows are the ones the import tool wants: one
        # row per feature carrying its baseline values, its retention and its
        # proposed values side by side, which is the shape of the legacy
        # Master layer a user would otherwise export by hand.
        pi_rows = {
            "Habitats": _write_areas(
                baseline_conn, pi_conn, staged["areas"], site,
                carry_lineage, report),
            "Hedgerows": _write_hedgerows(
                baseline_conn, pi_conn, staged["hedgerows"], site,
                carry_lineage, report),
            "Rivers": _write_watercourses(
                baseline_conn, pi_conn, staged["watercourses"], site,
                carry_lineage, report),
            "Urban Trees": _write_trees(
                baseline_conn, pi_conn, staged["trees"], site,
                carry_lineage, report),
        }

        if want_gpkg:
            for conn in (baseline_conn, pi_conn):
                for table, spec in LEGACY_LAYERS.items():
                    update_layer_extent(conn, table, spec["geom_column"])
                conn.commit()
    finally:
        for conn in (baseline_conn, pi_conn):
            if conn is not None:
                conn.close()

    if want_gpkg:
        report.note(f"Baseline file:          {baseline_path}")
        report.note(f"Post-intervention file: {pi_path}")
        report.note(
            "To open either in the legacy QGIS template, take a copy of the "
            f"whole template folder for that stage, put the file in its "
            f"Layers folder and rename it to "
            f"'{LEGACY_LAYERS_STEM}.gpkg'. The project looks for that exact "
            "name, so baseline and post-intervention need a folder each."
        )
    if area_losses:
        _report_area_losses(area_losses, want_gpkg, want_csv, report)
    if want_csv:
        # The CSVs, not the GeoPackages, get the lost rows. Converting back
        # from legacy reads an area habitat marked Lost as built over, so a
        # lost row in the post-intervention file would come back as a
        # created parcel with nothing proposed on it.
        csv_rows = dict(pi_rows)
        csv_rows["Habitats"] = pi_rows["Habitats"] + [
            (None, area_lost_row(parent, size, site))
            for parent, size in area_losses
        ]
        _write_csvs(out_dir, csv_rows, report, consolidate, split_irreplaceable)
        _report_baseline_comments(staged, report)
    return report


def _report_area_losses(losses, want_gpkg, want_csv, report):
    """Area habitat baseline that post-intervention does not yet cover."""
    detail = summarise_list(
        f"{parent.get(REF_FIELD)} "
        f"({int(round(hectares_to_sq_metres(size)))} m²)"
        for parent, size in losses
    )
    if want_csv:
        report.note(
            f"Habitats.csv: synthesised {len(losses)} 'Lost' row(s) for area "
            f"habitat not carried forward to post-intervention — {detail}"
        )
    if want_gpkg:
        report.warn(
            f"{len(losses)} baseline area habitat parcel(s) are not, or not "
            "wholly, carried forward to post-intervention, so the legacy "
            "post-intervention file does not cover the red line and the "
            "older service will refuse it until post-intervention is "
            f"finished. The baseline file is complete. Parcels: {detail}"
        )


def has_user_comment(values):
    """True when a legacy row's comment holds more than the conversion's notes.

    The conversion writes a note on each loss row and, with lineage carried,
    a breadcrumb. Neither is the surveyor's words, so neither counts as a
    comment that can be lost.
    """
    comment = values.get("Comment") or values.get("Comments")
    if not isinstance(comment, str) or not comment.strip():
        return False
    if "written by the conversion" in comment:
        return False
    text = re.sub(r"\[(?:parent|pi)=[^\]]*\]", "", comment)
    return bool(text.strip())


def _report_baseline_comments(staged, report):
    """Baseline comments have no place in the import tool CSVs.

    The CSVs hold one row per post-intervention feature, carrying its own
    comment. A baseline feature's comment is in the legacy baseline
    GeoPackage only.
    """
    counts = {
        STAGED_TABLES[key]["label"]: sum(
            1 for row in staged.get(key, {}).get("baseline", [])
            if isinstance(row.get("Comment"), str) and row["Comment"].strip())
        for key in ("areas", "hedgerows", "watercourses")
    }
    counts = {label: count for label, count in counts.items() if count}
    if not counts:
        return
    detail = "; ".join(f"{label}: {count}" for label, count in counts.items())
    report.note(
        f"{sum(counts.values())} baseline comment(s) are not in the import "
        "tool CSVs, which hold one row for each post-intervention feature "
        f"with that feature's own comment ({detail}). They are in the "
        "baseline GeoPackage if you asked for one.")


def _report_enhanced_trees(staged, report):
    """The Natural England tree list has no Enhanced."""
    refs = [str(row.get(REF_FIELD) or f"fid {row.get('fid')}")
            for row in staged.get("trees", {}).get("pi", [])
            if row.get("Retention Category") == "Enhanced"]
    if not refs:
        return
    report.warn(
        f"{len(refs)} individual tree(s) are Enhanced ({summarise_list(refs)}). "
        "The Statutory Metric allows a tree's condition to be enhanced, but "
        "the Natural England template's tree list offers only Retained and "
        "Lost, so the legacy QGIS template shows these values in brackets. "
        "They are written as Enhanced, with the proposed condition.")


def _write_csvs(out_dir, pi_rows, report, consolidate=False,
                split_irreplaceable=True):
    """The three CSVs the Excel GIS import tool reads, one per module."""
    csv_dir = os.path.join(out_dir, CSV_SUBFOLDER)
    os.makedirs(csv_dir, exist_ok=True)

    flagged_rows = [
        (geometry, values)
        for geometry, values in pi_rows.get("Habitats", [])
        if values.get(IRREPLACEABLE_KEY) == "Yes"
    ]

    for table, filename in CSV_MODULES:
        rows = pi_rows.get(table, [])
        before = len(rows)
        flagged_groups = 0
        if consolidate:
            commented = sum(1 for _geometry, values in rows
                            if has_user_comment(values))
            rows, flagged_groups = consolidate_csv_rows(
                table, rows, split_irreplaceable)
            if commented:
                report.warn(
                    f"{filename}: {commented} comment(s) were replaced by "
                    "the consolidation note, because a merged row holds "
                    "several features. They are in the post-intervention "
                    "GeoPackage if you asked for one, or convert without "
                    "consolidating to keep them in the CSV.")
            report.count(f"{filename}", len(rows))
            report.note(
                f"{filename}: {before} row(s) consolidated to {len(rows)}"
                + (f", of which {flagged_groups} hold irreplaceable habitat "
                   "and were kept apart" if flagged_groups else "")
            )
        else:
            report.count(f"{filename}", len(rows))
        # The import tool takes 248 rows per module, so a site with more is
        # written as several files rather than one the tool cannot read.
        # Rows carry no reference to each other, so any run of them is a
        # valid import on its own.
        count = parts_needed(len(rows), IMPORT_TOOL_ROW_LIMIT)
        for index, run in enumerate(split_into_parts(rows, count)):
            path = part_path(os.path.join(csv_dir, filename), index, count)
            write_module_csv(path, table, run)
        if count > 1:
            report.warn(
                f"{filename}: {len(rows)} rows against the import tool's "
                f"{IMPORT_TOOL_ROW_LIMIT} per module (User Guide 3.1.5), so "
                f"it was written as {count} files. Import each into its own "
                "copy of the tool and add the resulting metric figures "
                "together"
                + ("" if consolidate else ", or consolidate the rows to fit "
                   "fewer files")
                + "."
            )

    _write_irreplaceable_listing(csv_dir, flagged_rows, report,
                                 consolidate, split_irreplaceable)

    report.note(f"Import tool CSVs:       {csv_dir}")
    report.note(
        "Import each CSV into its own tab of the GIS import tool, then choose "
        "On Site or Off Site there before exporting to the metric."
    )

    trees = len(pi_rows.get("Urban Trees", []))
    if trees:
        report.warn(
            f"{trees} individual tree(s) are NOT in the CSVs. The import tool "
            "cannot read tree points at all (User Guide 2.4.1), so they have to "
            "be typed into the metric by hand. They are in the "
            "post-intervention GeoPackage if you asked for one."
        )


def _write_redline(baseline_conn, pi_conn, redline, site, report):
    rows = []
    for row in redline:
        blob = row.get("_geom")
        area = polygon_blob_area_sqm(blob) if blob else None
        rows.append(
            (
                blob,
                {"Area": area, "Site Name": site.get("Site Name")},
            )
        )
    for conn in (baseline_conn, pi_conn):
        insert_rows(conn, "Red Line Boundary", rows)
    report.count("Red Line Boundary", len(rows))


def deduplicate_area_refs(pi_rows, report):
    """Give every area habitat row a unique Parcel Ref.

    Legacy rejects a repeated Parcel Ref in the habitats layer, but the new
    template only makes child refs unique when the user runs its "Tidy PI refs"
    action — so split parcels commonly arrive sharing a parent's ref. Suffix
    them the way that action would (GR-1a, GR-1b, ...). Safe for area habitats:
    legacy reads each row's baseline from the row's own columns, so nothing
    resolves an area ref back to the baseline file.
    """
    occurrences = defaultdict(list)
    for _, values in pi_rows:
        occurrences[values.get("Parcel Ref")].append(values)

    taken = {ref for ref, rows in occurrences.items() if len(rows) == 1}
    renames = []
    for ref, rows in occurrences.items():
        if ref is None or ref == "" or len(rows) == 1:
            continue
        renamed = []
        for index, values in enumerate(rows):
            candidate = _next_free_ref(ref, index, taken)
            taken.add(candidate)
            values["Parcel Ref"] = candidate
            renamed.append(candidate)
        renames.append((ref, renamed))

    for ref, renamed in renames:
        report.note(
            f"Habitats: '{ref}' appeared {len(renamed)} times — renamed to "
            f"{summarise_list(renamed)} (legacy requires unique Parcel Refs)"
        )
    return renames


ALPHABET_SIZE = 26


def _next_free_ref(ref, index, taken):
    """`ref` + a, b, c... skipping anything already used."""
    attempt = index
    while True:
        suffix = chr(ord("a") + attempt % ALPHABET_SIZE)
        cycle = attempt // ALPHABET_SIZE
        candidate = f"{ref}{suffix}" if cycle == 0 else f"{ref}{suffix}{cycle}"
        if candidate not in taken:
            return candidate
        attempt += 1


def _write_areas(baseline_conn, pi_conn, tables, site, carry_lineage, report):
    baseline_rows = [
        (geometry_for("Habitats", row.get("_geom")), map_area_baseline(row, site))
        for row in tables["baseline"]
    ]
    pi_rows = [
        (
            geometry_for("Habitats", row.get("_geom")),
            map_area_pi(row, site, carry_lineage),
        )
        for row in tables["pi"]
    ]
    deduplicate_area_refs(pi_rows, report)
    insert_rows(baseline_conn, "Habitats", baseline_rows)
    insert_rows(pi_conn, "Habitats", pi_rows)
    report.count("Habitats (baseline)", len(baseline_rows))
    report.count("Habitats (post-intervention)", len(pi_rows))
    return pi_rows


def _write_linear(
    baseline_conn,
    pi_conn,
    tables,
    site,
    carry_lineage,
    report,
    table_name,
    baseline_mapper,
    pi_mapper,
    lost_mapper,
    rule,
):
    baseline_rows = [
        (row.get("_geom"), baseline_mapper(row, site)) for row in tables["baseline"]
    ]
    pi_rows = [
        (row.get("_geom"), pi_mapper(row, site, carry_lineage)) for row in tables["pi"]
    ]

    losses = synthesise_lost_rows(
        tables["baseline"], tables["pi"], "Length", rule, LENGTH_TOLERANCE_M
    )
    for parent, lost_length in losses:
        pi_rows.append((parent.get("_geom"), lost_mapper(parent, lost_length, site)))

    insert_rows(baseline_conn, table_name, baseline_rows)
    insert_rows(pi_conn, table_name, pi_rows)
    report.count(f"{table_name} (baseline)", len(baseline_rows))
    report.count(f"{table_name} (post-intervention)", len(pi_rows))
    if losses:
        detail = summarise_list(
            f"{parent.get(REF_FIELD)} ({int(round(size))} m)"
            for parent, size in losses
        )
        report.note(
            f"{table_name}: synthesised {len(losses)} 'Lost' row(s) — {detail}"
        )
    return pi_rows


def _write_hedgerows(baseline_conn, pi_conn, tables, site, carry_lineage, report):
    return _write_linear(
        baseline_conn, pi_conn, tables, site, carry_lineage, report,
        "Hedgerows", map_hedgerow_baseline, map_hedgerow_pi, hedgerow_lost_row,
        REMOVAL_RULE_SHORTFALL,
    )


def _write_watercourses(baseline_conn, pi_conn, tables, site, carry_lineage, report):
    return _write_linear(
        baseline_conn, pi_conn, tables, site, carry_lineage, report,
        "Rivers", map_watercourse_baseline, map_watercourse_pi,
        watercourse_lost_row, REMOVAL_RULE_PRESENCE,
    )


def _write_trees(baseline_conn, pi_conn, tables, site, carry_lineage, report):
    baseline_rows = [
        (row.get("_geom"), map_tree_baseline(row, site)) for row in tables["baseline"]
    ]
    pi_rows = [
        (row.get("_geom"), map_tree_pi(row, site, carry_lineage))
        for row in tables["pi"]
    ]

    losses = synthesise_lost_rows(
        tables["baseline"], tables["pi"], "Count",
        REMOVAL_RULE_SHORTFALL, COUNT_TOLERANCE,
    )
    for parent, lost_count in losses:
        pi_rows.append((parent.get("_geom"), tree_lost_row(parent, lost_count, site)))

    insert_rows(baseline_conn, "Urban Trees", baseline_rows)
    insert_rows(pi_conn, "Urban Trees", pi_rows)
    report.count("Urban Trees (baseline)", len(baseline_rows))
    report.count("Urban Trees (post-intervention)", len(pi_rows))
    if losses:
        detail = summarise_list(
            f"{parent.get(REF_FIELD)} ({int(round(size))})" for parent, size in losses
        )
        report.note(f"Urban Trees: synthesised {len(losses)} 'Lost' row(s) — {detail}")
    return pi_rows


def _number_list_values(staged, report):
    """Put the Natural England list number back on the numbered drop-downs.

    Done once, on the rows as read, so every legacy row and CSV row built from
    them, including the Lost rows made from a baseline feature, carries the
    form the legacy template stores.
    """
    changed = to_legacy_labels(staged)
    if changed:
        report.note(
            f"Put the Natural England list number on {changed} drop-down "
            "value(s), such as 'Fairly Poor' to '4. Fairly Poor', because the "
            "legacy template stores them that way"
        )
    changed = to_legacy_significance(staged)
    if changed:
        report.note(
            f"Wrote {changed} strategic significance value(s) in the Natural "
            "England wording: Low as 'Area/compensation not in local "
            "strategy/ no local strategy', High as 'Formally identified in "
            "local strategy' (for trees, 'Within area formally identified in "
            "local strategy')"
        )


def _report_losses(staged, report):
    vertical = staged["verticalAreas"]
    vertical_total = len(vertical["baseline"]) + len(vertical["pi"])
    if vertical_total:
        report.warn(
            f"{vertical_total} vertical area habitat feature(s) CANNOT be carried "
            "over — the legacy template has no layer for them. Their biodiversity "
            "units will be missing from the legacy calculation."
        )

    irreplaceable = 0
    for key in ("areas", "verticalAreas"):
        for stage in ("baseline", "pi"):
            for row in staged[key][stage]:
                value = row.get("Irreplaceable Habitat")
                if value not in (None, "", "No"):
                    irreplaceable += 1
    if irreplaceable:
        report.warn(
            f"{irreplaceable} feature(s) are flagged as irreplaceable habitat — the "
            "legacy template has no column for this, so the flag is dropped."
        )


def _report_splits(staged, report):
    for habitat_type in ("hedgerows", "watercourses", "trees"):
        children = defaultdict(int)
        for row in staged[habitat_type]["pi"]:
            parent = row.get("Parent Ref")
            if parent:
                children[parent] += 1
        split = {ref: n for ref, n in children.items() if n > 1}
        if split:
            detail = summarise_list(
                f"{ref} -> {n}" for ref, n in sorted(split.items())
            )
            report.warn(
                f"{habitat_type}: {len(split)} baseline feature(s) were split into "
                f"several post-intervention features ({detail}). Legacy expects one "
                "row per reference, so the converted rows repeat their parent's ref "
                "and the legacy calculation may differ. Review these."
            )


def _plan_counts(staged, redline, report):
    report.count("Red Line Boundary", len(redline))
    labels = {
        "areas": "Habitats",
        "hedgerows": "Hedgerows",
        "watercourses": "Rivers",
        "trees": "Urban Trees",
    }
    for habitat_type, label in labels.items():
        report.count(f"{label} (baseline)", len(staged[habitat_type]["baseline"]))
        report.count(
            f"{label} (post-intervention)", len(staged[habitat_type]["pi"])
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def print_report(report, dry_run):
    print()
    print("=" * 70)
    print("  BNG Service GeoPackage  ->  legacy Natural England GeoPackages")
    print("=" * 70)
    if dry_run:
        print("  DRY RUN — nothing was written")
        print("-" * 70)

    print("\nRows:")
    for key, value in report.counts.items():
        print(f"  {key:.<48} {value}")

    if report.lines:
        print("\nNotes:")
        for line in report.lines:
            print(f"  - {line}")

    if report.warnings:
        print("\nWARNINGS — read before uploading:")
        for line in report.warnings:
            print(f"  ! {line}")

    print(
        "\nAlways dropped: the lineage columns (feature_uuid, parent_uuid and "
        "parent_geom),\nirreplaceable-habitat flags, and vertical area "
        "habitats. Sizes are rounded to\nwhole units to match the legacy integer "
        "columns.\n"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Convert a BNG Service staged GeoPackage into the legacy Natural "
            "England baseline + post-intervention pair."
        )
    )
    parser.add_argument("input", help="the staged .gpkg from the new template")
    parser.add_argument(
        "-o", "--out-dir", default=".", help="directory for the two output files"
    )
    parser.add_argument(
        "--carry-lineage",
        action="store_true",
        help=(
            "record each feature's parent reference in the legacy Comment column, "
            "so lineage can be recovered if the files are converted back"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be produced without writing any files",
    )
    parser.add_argument(
        "--consolidate",
        action="store_true",
        help=(
            "CSV output only: merge rows that agree on every metric attribute "
            "and sum their size, the way the import tool's Consolidate Data "
            "button does. Off by default, because it loses the per-parcel "
            "audit trail (User Guide 3.2.3)"
        ),
    )
    parser.add_argument(
        "--merge-irreplaceable",
        action="store_true",
        help=(
            "allow irreplaceable habitat to be consolidated together with "
            "otherwise identical habitat that is not irreplaceable. Off by "
            "default, and turning it on hides the distinction"
        ),
    )
    parser.add_argument(
        "--format",
        choices=("gpkg", "csv", "both"),
        default="gpkg",
        help=(
            "gpkg: the legacy baseline + post-intervention pair (default); "
            "csv: the three CSVs the Excel GIS import tool reads; both"
        ),
    )
    args = parser.parse_args(argv)

    formats = ("gpkg", "csv") if args.format == "both" else (args.format,)

    if not os.path.exists(args.input):
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1

    try:
        report = convert(
            args.input, args.out_dir, args.carry_lineage, args.dry_run, formats,
            consolidate=args.consolidate,
            split_irreplaceable=not args.merge_irreplaceable,
        )
    except (sqlite3.Error, ValueError, struct.error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print_report(report, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
