"""What conversion to the legacy pair is allowed to change.

This is the list claim 2 is judged against: every value is carried across, or
transformed by a rule written down here. It is written from the documented
behaviour of the conversion, not read out of the converter, because a list
derived from the code it checks would agree with any bug the code contains.

Three kinds of entry, and the checker insists on complete coverage:

  CARRY    the value must arrive unchanged, possibly under another name
  CHANGE   the value must arrive transformed by the named rule
  COMPOSE  a legacy column built from more than one staged column, or a
           label whose legacy number depends on another column of the row
  DROP     the column has no destination, and why
  INVENT   a legacy column with no source, and where it comes from instead

A numbered label is checked against the Natural England template's own list
in templates/legacy-ne, not against the converter's reading of it.

A staged column absent from all of these, or a legacy column that nothing
accounts for, fails the check on its own. That is deliberate: the failure
mode this guards against is a column quietly appearing or disappearing.
"""

import csv
import os
import re

SQ_METRES_PER_HECTARE = 10000

# The Natural England lists put a number in front of some labels,
# "3. Moderate", to set the order of the drop-down. The BNG Service lists hold
# the label with no number, "Moderate".
NE_NUMBER = re.compile(r"^\d+\. ")
NE_LISTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                        "templates", "legacy-ne", "CSV References")
NE_LABEL = "Label"

# The filter values the Natural England drop-downs fall back to.
TO_BE_CREATED = "To be created"
EXISTING_TREE = "Existing"
# The documented exception: the Natural England list has no Created for an
# existing watercourse (its fourth option there is "4. Lost"), and the
# conversion writes the value with the number of its place.
CREATED = "Created"
EXISTING_WATERCOURSE_CREATED = "4. Created"

# Strategic significance. The BNG Service template stores Low or High, and
# NULL where the value does not apply. Natural England stores the metric's
# wording, and trees word High differently from every other habitat type.
LOW, HIGH = "Low", "High"
NE_LOW = "Area/compensation not in local strategy/ no local strategy"
NE_HIGH = "Formally identified in local strategy"
NE_HIGH_TREES = "Within area formally identified in local strategy"
NOT_APPLICABLE = "N/A"
NO_HABITAT_TYPES = (TO_BE_CREATED, NOT_APPLICABLE)
NEWLY_PLANTED = "Newly Planted"

# --- rules -----------------------------------------------------------------


def same(staged, legacy):
    return normalise(staged) == normalise(legacy)


def normalise(value):
    """Blank, missing and whitespace are the same absence of a value."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return value


def unnumbered(value):
    """The value, with any Natural England list number removed."""
    value = normalise(value)
    return NE_NUMBER.sub("", value) if isinstance(value, str) else value


class NeList:
    """The labels one Natural England drop-down offers, by filter value."""

    def __init__(self, path, filter_column):
        self.path = path
        self.filter_column = filter_column
        self._offered = None

    def offers(self, context, label):
        if self._offered is None:
            self._offered = {}
            path = os.path.join(NE_LISTS, self.path)
            with open(path, newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    self._offered.setdefault(
                        row[self.filter_column], set()).add(row[NE_LABEL])
        return label in self._offered.get(context, ())


AREA_CONDITION = NeList("Habitats/Habitat Condition.csv", "UKHAB")
WATERCOURSE_CONDITION = NeList("Watercourses/Watercourse Condition.csv",
                               "Habitat")
RIPARIAN_ENCROACHMENT = NeList("Watercourses/Riparian Encroachment.csv",
                               "Value")
WATERCOURSE_RETENTION = NeList(
    "Watercourses/Watercourse Retention Options.csv", "Value")
TREE_CONDITION = NeList("Individual trees/Individual tree Condition - pre.csv",
                        "Category")


def created_on_existing_watercourse(words, context):
    """The one legacy value outside the list: see EXISTING_WATERCOURSE_CREATED."""
    if words == CREATED and context != TO_BE_CREATED:
        return EXISTING_WATERCOURSE_CREATED
    return None


def numbered(column, ne_list, context_column=None, fallback=None,
             exception=None):
    """A COMPOSE entry for a label that a Natural England list numbers.

    The legacy value must hold the same words, and must be a label that the
    Natural England list offers for the row's filter value, number included,
    so a wrong or missing number fails. The filter value is the row's
    `context_column`, or `fallback` when that is blank or not in the table.
    `exception` gives the one documented value the list does not offer.
    """
    def rule(row, legacy):
        staged, legacy = normalise(row.get(column)), normalise(legacy)
        if staged == "" or legacy == "":
            return staged == legacy
        if unnumbered(staged) != unnumbered(legacy):
            return False
        context = normalise(row.get(context_column)) or fallback
        extra = exception(unnumbered(staged), context) if exception else None
        return ne_list.offers(context, legacy) or legacy == extra

    sources = (column, context_column) if context_column else (column,)
    filtered_by = context_column or f"the value {fallback!r}"
    return (sources, rule,
            f"numbered as the Natural England list numbers it for "
            f"{filtered_by}")


def words_without_number(staged, legacy):
    """The words arrive unchanged, and no list number is put in front."""
    legacy = normalise(legacy)
    return (normalise(staged) == legacy
            and not (isinstance(legacy, str) and NE_NUMBER.match(legacy)))


def hectares_to_whole_sq_metres(staged, legacy):
    """Legacy stores a whole number of square metres; the staged file stores
    hectares. The rounding is the transformation, and it is one way."""
    if staged in (None, ""):
        return legacy in (None, "", 0)
    return int(legacy) == round(float(staged) * SQ_METRES_PER_HECTARE)


def rounded_to_whole(staged, legacy):
    """Lengths and counts, rounded to the whole units legacy stores."""
    if staged in (None, ""):
        return legacy in (None, "", 0)
    return int(legacy) == round(float(staged))


def significance_blank(column, type_column, row):
    """What legacy holds where the staged value is NULL.

    The earlier template's drop-downs held "N/A" for a hedgerow or
    watercourse type of "To be created" or "N/A", and for a newly planted
    tree's baseline. Everywhere else they held a blank, and so does legacy.
    """
    if type_column == "Category":
        is_na = (column.startswith("Baseline")
                 and normalise(row.get("Category")) == NEWLY_PLANTED)
    else:
        is_na = bool(type_column) and normalise(
            row.get(type_column)) in NO_HABITAT_TYPES
    return NOT_APPLICABLE if is_na else ""


def significance(column, trees=False, type_column=None):
    """A COMPOSE entry for strategic significance: Low and High to wording."""
    def rule(row, legacy):
        staged, legacy = normalise(row.get(column)), normalise(legacy)
        if staged == LOW:
            return legacy == NE_LOW
        if staged == HIGH:
            return legacy == (NE_HIGH_TREES if trees else NE_HIGH)
        if staged == "":
            return legacy == significance_blank(column, type_column, row)
        return False

    sources = (column, type_column) if type_column else (column,)
    return (sources, rule,
            "Low and High as the metric words them; a blank as N/A where "
            "the earlier template offered only N/A, else blank")


def linear_reference(row, legacy):
    """The reference a derived feature is matched back to its baseline by.

    Legacy resolves an enhanced or retained hedgerow, watercourse or tree to
    its baseline row by matching the reference, so a feature cut from a parent
    has to carry the parent's. A feature created from nothing has no parent,
    and carries its own reference instead.
    """
    parent = normalise(row.get("Parent Ref"))
    own = normalise(row.get("Habitat Ref"))
    return normalise(legacy) == (parent or own)


def comment_carries(staged, legacy):
    """The comment survives. A lineage note may be appended to it."""
    left, right = normalise(staged), normalise(legacy)
    return right == left or (left in right if left else True)


# --- per layer -------------------------------------------------------------
#
# Each entry is (staged table, legacy table, stage, mapping), where mapping
# holds CARRY/CHANGE/DROP/INVENT as described above.

AREA_BASELINE = {
    "CARRY": {
        "Habitat Ref": "Parcel Ref",
        "Baseline Broad Habitat Type": "Baseline Broad Habitat Type",
        "Baseline Habitat Type": "Baseline Habitat Type",
        "Baseline Distinctiveness": "Baseline Distinctiveness",
    },
    "COMPOSE": {
        "Baseline Strategic Significance": significance("Baseline Strategic Significance"),
        "Baseline Condition": numbered(
            "Baseline Condition", AREA_CONDITION, "Baseline Habitat Type"),
    },
    "CHANGE": {
        "Area": ("Area", hectares_to_whole_sq_metres,
                 "hectares to whole square metres"),
        "Comment": ("Comment", comment_carries,
                    "kept, with a lineage note appended when asked for"),
    },
    "DROP": {
        "Irreplaceable Habitat": "the legacy template has no column for it",
        "feature_uuid": "lineage key, and legacy carries no lineage",
    },
    "INVENT": {
        "Location": "site detail, held once on the red line and repeated here",
        "Site Name": "site detail",
        "Survey Date": "site detail",
        "Survey Details": "site detail",
        "Mapped by": "site detail",
        "Company": "site detail",
        "Base Map": "site detail",
        "Retention Category": "empty: a baseline file records no intervention",
        "Proposed Broad Habitat Type": "empty in a baseline file",
        "Proposed Habitat Type": "empty in a baseline file",
        "Proposed Condition": "empty in a baseline file",
        "Proposed Strategic Significance": "empty in a baseline file",
        "Proposed Distinctiveness": "empty in a baseline file",
        "Habitat created in advance/years": "empty in a baseline file",
        "Delay in starting habitat creation/years": "empty in a baseline file",
        "Spatial risk category": "empty in a baseline file",
    },
}

AREA_PI = {
    "CARRY": {
        "Habitat Ref": "Parcel Ref",
        "Baseline Broad Habitat Type": "Baseline Broad Habitat Type",
        "Baseline Habitat Type": "Baseline Habitat Type",
        "Baseline Distinctiveness": "Baseline Distinctiveness",
        "Retention Category": "Retention Category",
        "Proposed Broad Habitat Type": "Proposed Broad Habitat Type",
        "Proposed Habitat Type": "Proposed Habitat Type",
        "Proposed Distinctiveness": "Proposed Distinctiveness",
        "Habitat created in advance/years": "Habitat created in advance/years",
        "Delay in starting habitat creation/years":
            "Delay in starting habitat creation/years",
        "Spatial risk category": "Spatial risk category",
    },
    "COMPOSE": {
        "Baseline Strategic Significance": significance(
            "Baseline Strategic Significance", type_column="Baseline Habitat Type"),
        "Proposed Strategic Significance": significance("Proposed Strategic Significance"),
        "Baseline Condition": numbered(
            "Baseline Condition", AREA_CONDITION, "Baseline Habitat Type"),
        "Proposed Condition": numbered(
            "Proposed Condition", AREA_CONDITION, "Proposed Habitat Type"),
    },
    "CHANGE": {
        "Area": ("Area", hectares_to_whole_sq_metres,
                 "hectares to whole square metres"),
    },
    "DROP": {
        "Parent Ref": "lineage; recorded in the comment when asked for",
        "Irreplaceable Habitat": "the legacy template has no column for it",
        "parent_uuid": "lineage key",
        "parent_geom": "lineage: the parent shape, which legacy cannot hold",
    },
    "INVENT": {
        "Location": "site detail", "Site Name": "site detail",
        "Survey Date": "site detail", "Survey Details": "site detail",
        "Mapped by": "site detail", "Company": "site detail",
        "Base Map": "site detail",
        "Comment": "carries the lineage note when asked for",
    },
}

HEDGEROW_BASELINE = {
    "CARRY": {
        "Habitat Ref": "Parcel Ref",
        "Baseline Hedge Type": "Baseline Hedge Type",
        "Baseline Distinctiveness": "Baseline Distinctiveness",
        "Baseline Condition": "Baseline Condition",
    },
    "COMPOSE": {
        "Baseline Strategic Significance": significance("Baseline Strategic Significance"),
    },
    "CHANGE": {
        "Length": ("Length", rounded_to_whole, "rounded to whole metres"),
        "Comment": ("Comments", comment_carries,
                    "kept, and the column is named Comments here"),
    },
    "DROP": {"feature_uuid": "lineage key"},
    "INVENT": {
        "Location": "site detail", "Site Name": "site detail",
        "Survey Date": "site detail", "Survey Details": "site detail",
        "Mapped by": "site detail", "Company": "site detail",
        "Base Map": "site detail",
        "Retention Category": "empty in a baseline file",
        "Proposed Hedge Type": "empty in a baseline file",
        "Proposed Condition": "empty in a baseline file",
        "Proposed Strategic Significance": "empty in a baseline file",
        "Proposed Distinctiveness": "empty in a baseline file",
        "Habitat created in advance/years": "empty in a baseline file",
        "Delay in starting habitat creation/years": "empty in a baseline file",
        "Spatial risk category": "empty in a baseline file",
    },
}

HEDGEROW_PI = {
    "CARRY": {
        "Baseline Hedge Type": "Baseline Hedge Type",
        "Baseline Distinctiveness": "Baseline Distinctiveness",
        "Baseline Condition": "Baseline Condition",
        "Retention Category": "Retention Category",
        "Proposed Hedge Type": "Proposed Hedge Type",
        "Proposed Distinctiveness": "Proposed Distinctiveness",
        "Proposed Condition": "Proposed Condition",
        "Habitat created in advance/years": "Habitat created in advance/years",
        "Delay in starting habitat creation/years":
            "Delay in starting habitat creation/years",
        "Spatial risk category": "Spatial risk category",
    },
    "COMPOSE": {
        "Baseline Strategic Significance": significance(
            "Baseline Strategic Significance", type_column="Baseline Hedge Type"),
        "Proposed Strategic Significance": significance(
            "Proposed Strategic Significance", type_column="Proposed Hedge Type"),
        "Parcel Ref": (("Parent Ref", "Habitat Ref"), linear_reference,
                        "the parent's reference, or the feature's own when it\n                         was created from nothing"),
    },
    "CHANGE": {
        "Length": ("Length", rounded_to_whole, "rounded to whole metres"),
    },
    "DROP": {
        "Baseline Length": "held in the baseline file instead",
        "parent_uuid": "lineage key",
        "parent_geom": "lineage",
    },
    "INVENT": {
        "Location": "site detail", "Site Name": "site detail",
        "Survey Date": "site detail", "Survey Details": "site detail",
        "Mapped by": "site detail", "Company": "site detail",
        "Base Map": "site detail",
        "Comments": "carries the lineage note when asked for",
    },
}

WATERCOURSE_BASELINE = {
    "CARRY": {
        "Habitat Ref": "Parcel Ref",
        "Baseline River Type": "Baseline River Type",
        "Baseline Distinctiveness": "Baseline Distinctiveness",
        "Baseline Encroachment into Watercourse":
            "Baseline Encroachment into Watercourse",
    },
    "COMPOSE": {
        "Baseline Strategic Significance": significance("Baseline Strategic Significance"),
        "Baseline Condition": numbered(
            "Baseline Condition", WATERCOURSE_CONDITION, "Baseline River Type"),
        "Baseline Encroachment into riparian zone": numbered(
            "Baseline Encroachment into riparian zone", RIPARIAN_ENCROACHMENT,
            "Baseline River Type"),
    },
    "CHANGE": {
        "Length": ("Length", rounded_to_whole, "rounded to whole metres"),
        "Comment": ("Comments", comment_carries,
                    "kept, and the column is named Comments here"),
    },
    "DROP": {"feature_uuid": "lineage key"},
    "INVENT": {
        "Location": "site detail", "Site Name": "site detail",
        "Survey Date": "site detail", "Survey Details": "site detail",
        "Mapped by": "site detail", "Company": "site detail",
        "Base Map": "site detail",
        "Retention Category": "empty in a baseline file",
        "Proposed River Type": "empty in a baseline file",
        "Proposed Condition": "empty in a baseline file",
        "Proposed Strategic Significance": "empty in a baseline file",
        "Proposed Distinctiveness": "empty in a baseline file",
        "Proposed Encroachment into Watercourse": "empty in a baseline file",
        "Proposed Encroachment into riparian zone": "empty in a baseline file",
        "Enhancement Type": "empty in a baseline file",
        "Habitat created in advance/years": "empty in a baseline file",
        "Delay in starting habitat creation/years": "empty in a baseline file",
        "Spatial risk category": "empty in a baseline file",
    },
}

WATERCOURSE_PI = {
    "CARRY": {
        "Baseline River Type": "Baseline River Type",
        "Baseline Distinctiveness": "Baseline Distinctiveness",
        "Baseline Encroachment into Watercourse":
            "Baseline Encroachment into Watercourse",
        "Proposed River Type": "Proposed River Type",
        "Proposed Distinctiveness": "Proposed Distinctiveness",
        "Proposed Encroachment into Watercourse":
            "Proposed Encroachment into Watercourse",
        "Enhancement Type": "Enhancement Type",
        "Habitat created in advance/years": "Habitat created in advance/years",
        "Delay in starting habitat creation/years":
            "Delay in starting habitat creation/years",
        "Spatial risk category": "Spatial risk category",
    },
    "COMPOSE": {
        "Baseline Strategic Significance": significance(
            "Baseline Strategic Significance", type_column="Baseline River Type"),
        "Proposed Strategic Significance": significance(
            "Proposed Strategic Significance", type_column="Proposed River Type"),
        "Parcel Ref": (("Parent Ref", "Habitat Ref"), linear_reference,
                        "the parent's reference, or the feature's own when it\n                         was created from nothing"),
        "Baseline Condition": numbered(
            "Baseline Condition", WATERCOURSE_CONDITION, "Baseline River Type"),
        "Baseline Encroachment into riparian zone": numbered(
            "Baseline Encroachment into riparian zone", RIPARIAN_ENCROACHMENT,
            "Baseline River Type"),
        "Retention Category": numbered(
            "Retention Category", WATERCOURSE_RETENTION, "Baseline River Type",
            fallback=TO_BE_CREATED, exception=created_on_existing_watercourse),
        "Proposed Condition": numbered(
            "Proposed Condition", WATERCOURSE_CONDITION, "Proposed River Type"),
        "Proposed Encroachment into riparian zone": numbered(
            "Proposed Encroachment into riparian zone", RIPARIAN_ENCROACHMENT,
            "Proposed River Type"),
    },
    "CHANGE": {
        "Length": ("Length", rounded_to_whole, "rounded to whole metres"),
    },
    "DROP": {
        "Baseline Length": "held in the baseline file instead",
        "parent_uuid": "lineage key",
        "parent_geom": "lineage",
    },
    "INVENT": {
        "Location": "site detail", "Site Name": "site detail",
        "Survey Date": "site detail", "Survey Details": "site detail",
        "Mapped by": "site detail", "Company": "site detail",
        "Base Map": "site detail",
        "Comments": "carries the lineage note when asked for",
    },
}

TREE_BASELINE = {
    "CARRY": {
        "Habitat Ref": "Tree Ref",
        "Baseline Tree Size": "Baseline Tree Size",
        "Baseline Tree Type": "Baseline Tree Type",
        "Baseline Rural or Urban Tree": "Baseline Rural or Urban Tree",
    },
    "COMPOSE": {
        "Baseline Strategic Significance": significance("Baseline Strategic Significance", trees=True),
        "Baseline Condition": numbered(
            "Baseline Condition", TREE_CONDITION, fallback=EXISTING_TREE),
    },
    "CHANGE": {
        "Count": ("Count", rounded_to_whole, "whole trees either way"),
        "Comment": ("Comment", comment_carries, "kept"),
    },
    "DROP": {"feature_uuid": "lineage key"},
    "INVENT": {
        "Location": "site detail", "Site Name": "site detail",
        "Survey Date": "site detail", "Survey Details": "site detail",
        "Mapped by": "site detail", "Company": "site detail",
        "Base Map": "site detail",
        "Retention Category": "empty in a baseline file",
        "Category": "empty in a baseline file",
        "Proposed Tree Size": "empty in a baseline file",
        "Proposed Tree Type": "empty in a baseline file",
        "Proposed Rural or Urban Tree": "empty in a baseline file",
        "Proposed Condition": "empty in a baseline file",
        "Proposed Strategic Significance": "empty in a baseline file",
        "Habitat Created/Enhanced in advance/years": "empty in a baseline file",
        "Delay in starting habitat creation/enhancement in years":
            "empty in a baseline file",
        "Spatial risk category": "empty in a baseline file",
    },
}

TREE_PI = {
    "CARRY": {
        "Baseline Tree Size": "Baseline Tree Size",
        "Baseline Tree Type": "Baseline Tree Type",
        "Baseline Rural or Urban Tree": "Baseline Rural or Urban Tree",
        "Retention Category": "Retention Category",
        "Category": "Category",
        "Proposed Tree Size": "Proposed Tree Size",
        "Proposed Tree Type": "Proposed Tree Type",
        "Proposed Rural or Urban Tree": "Proposed Rural or Urban Tree",
        "Habitat Created/Enhanced in advance/years":
            "Habitat Created/Enhanced in advance/years",
        "Delay in starting habitat creation/enhancement in years":
            "Delay in starting habitat creation/enhancement in years",
        "Spatial risk category": "Spatial risk category",
    },
    "COMPOSE": {
        "Baseline Strategic Significance": significance(
            "Baseline Strategic Significance", trees=True, type_column="Category"),
        "Proposed Strategic Significance": significance("Proposed Strategic Significance", trees=True),
        "Tree Ref": (("Parent Ref", "Habitat Ref"), linear_reference,
                        "the parent's reference, or the feature's own when it\n                         was created from nothing"),
        "Baseline Condition": numbered(
            "Baseline Condition", TREE_CONDITION, "Category",
            fallback=EXISTING_TREE),
    },
    "CHANGE": {
        "Proposed Condition": (
            "Proposed Condition", words_without_number,
            "the same words with no number: the Natural England template "
            "stores a tree's proposed condition as words"),
        "Count": ("Count", rounded_to_whole, "whole trees either way"),
    },
    "DROP": {
        "parent_uuid": "lineage key",
        "parent_geom": "lineage",
    },
    "INVENT": {
        "Location": "site detail", "Site Name": "site detail",
        "Survey Date": "site detail", "Survey Details": "site detail",
        "Mapped by": "site detail", "Company": "site detail",
        "Base Map": "site detail",
        "Comment": "carries the lineage note when asked for",
    },
}

# staged table -> (legacy table, stage, mapping, geometry column in legacy)
LAYERS = [
    ("Area Habitats Baseline", "Habitats", "baseline", AREA_BASELINE, "geom"),
    ("Area Habitats Post-Intervention", "Habitats", "pi", AREA_PI, "geom"),
    ("Hedgerows Baseline", "Hedgerows", "baseline", HEDGEROW_BASELINE, "geom"),
    ("Hedgerows Post-Intervention", "Hedgerows", "pi", HEDGEROW_PI, "geom"),
    ("Watercourses Baseline", "Rivers", "baseline", WATERCOURSE_BASELINE, "geom"),
    ("Watercourses Post-Intervention", "Rivers", "pi", WATERCOURSE_PI, "geom"),
    ("Individual Trees Baseline", "Urban Trees", "baseline", TREE_BASELINE,
     "geometry"),
    ("Individual Trees Post-Intervention", "Urban Trees", "pi", TREE_PI,
     "geometry"),
]

# Rows legacy needs that the staged file does not hold. The staged template
# records a removal by leaving the feature out; legacy has to say so in a row.
SYNTHESISED = {
    "Hedgerows": "Lost", "Rivers": "Lost", "Urban Trees": "Lost",
}

# Whole layers with nowhere to go.
DROPPED_LAYERS = {
    "Vertical Area Habitats Baseline":
        "the legacy template has no vertical area habitat layer",
    "Vertical Area Habitats Post-Intervention":
        "the legacy template has no vertical area habitat layer",
}

# The red line is not a habitat row and does not follow the pattern above.
REDLINE = {
    "CARRY": {"Site Name": "Site Name"},
    "DROP": {
        "Location": "kept on every feature row instead",
        "Survey Date": "kept on every feature row instead",
        "Survey Details": "kept on every feature row instead",
        "Mapped by": "kept on every feature row instead",
        "Company": "kept on every feature row instead",
        "Base Map": "kept on every feature row instead",
    },
    "INVENT": {"Area": "measured from the boundary; legacy has the column"},
}
