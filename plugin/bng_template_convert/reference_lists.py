"""
The drop-down values the two QGIS templates write differently.

The Natural England template stores some drop-down values with the metric's
own list number in front: "4. Fairly Poor", "2. Retained", "1. Major/Major".
The BNG Service template stores the words alone. Both templates read their
drop-down lists from CSV files in a "CSV References" folder, and this module
reads the same files. A change to a list therefore reaches the converter
without a change to the code.

Two directions:

    service_form   legacy value -> BNG Service value. The number comes off
                   when the words are a value of the list.
    legacy_form    BNG Service value -> legacy value. The number is looked up
                   in the Natural England list, with the same filter the
                   Natural England drop-down uses (for example, the condition
                   list is filtered by habitat type).

A value that is already numbered is not changed by legacy_form.

Strategic significance is stored differently too. The BNG Service template
stores "Low" or "High". Natural England and the Statutory Metric store the
metric's wording. to_legacy_significance and service_significance convert
between the two.

The BNG Service template also fills some values itself from its lists: the
distinctiveness of a habitat type, a condition when the habitat allows only
one, and Irreplaceable Habitat when the habitat allows only one answer.
TEMPLATE_RULES reads those lists, so old_to_new can fill the same values.

WHERE THE LISTS ARE READ FROM
    The plugin zip carries a copy of each list in `reference_lists/`, written
    by build_plugin.py. Run from the repository, the module reads the lists in
    `templates/` directly.
"""

import csv
import os

try:
    from .gpkg_common import NUMBERED_LABEL, plain_label
except ImportError:  # pragma: no cover - running as a plain script
    from gpkg_common import NUMBERED_LABEL, plain_label

SERVICE_TEMPLATE = "bng-service"
LEGACY_TEMPLATE = "legacy-ne"
TEMPLATES = (SERVICE_TEMPLATE, LEGACY_TEMPLATE)

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_DIR = "reference_lists"
REPOSITORY_TEMPLATES = os.path.join(PACKAGE_DIR, "..", "..", "templates")
CSV_REFERENCES = "CSV References"


def list_folder(template):
    """The folder holding a template's lists: the bundled copy, else the repo's."""
    candidates = (
        os.path.join(PACKAGE_DIR, BUNDLED_DIR, template),
        os.path.join(REPOSITORY_TEMPLATES, template, CSV_REFERENCES),
    )
    for folder in candidates:
        if os.path.isdir(folder):
            return folder
    raise ValueError(
        f"Cannot find the {template} drop-down lists. Looked in "
        f"{' and '.join(os.path.normpath(folder) for folder in candidates)}. "
        "Reinstall the plugin, or run the script from its place in the "
        "repository."
    )


def read_rows(folder, relative_path):
    """Every row of one list in `folder`, as dicts keyed by the CSV header."""
    path = os.path.join(folder, relative_path)
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def read_list(template, relative_path):
    """Every row of one list of a template."""
    return read_rows(list_folder(template), relative_path)


class LabelList:
    """One drop-down list, as the two templates each store it.

    `service_key` is the column the BNG Service template stores. The legacy
    side is read with `legacy_filter`, the column its drop-down filters on,
    and `legacy_key`, the column it stores. `gaps` gives the legacy value for
    a BNG Service value the Natural England list does not hold in that
    context.
    """

    def __init__(self, path, service_key, legacy_filter, legacy_key,
                 gaps=None):
        self.path = path
        self.service_key = service_key
        self.legacy_filter = legacy_filter
        self.legacy_key = legacy_key
        self.gaps = gaps or {}
        self._loaded = False
        self._service_values = set()
        self._legacy_by_context = {}
        self._legacy_by_value = {}

    def _load(self):
        if self._loaded:
            return
        for row in read_list(SERVICE_TEMPLATE, self.path):
            value = row.get(self.service_key)
            if value:
                self._service_values.add(value)
        for row in read_list(LEGACY_TEMPLATE, self.path):
            label = row.get(self.legacy_key)
            if not label:
                continue
            words = plain_label(label)
            context = row.get(self.legacy_filter)
            self._legacy_by_context.setdefault((context, words), set()).add(label)
            self._legacy_by_value.setdefault(words, set()).add(label)
        self._loaded = True

    def service_form(self, value):
        """The words alone, when they are a value of either template's list."""
        if not isinstance(value, str) or not NUMBERED_LABEL.match(value):
            return value
        self._load()
        words = plain_label(value)
        if words in self._service_values or words in self._legacy_by_value:
            return words
        return value

    def legacy_form(self, value, context):
        """The value as the Natural England list stores it in this context.

        The number is taken from the list row with the same filter value.
        Failing that, from a gap entry, and failing that, from the only
        numbered form the list has for those words. A value the list does not
        know is returned unchanged.
        """
        if not isinstance(value, str) or not value or NUMBERED_LABEL.match(value):
            return value
        self._load()
        labels = self._legacy_by_context.get((context, value))
        if labels and len(labels) == 1:
            return next(iter(labels))
        if value in self.gaps:
            return self.gaps[value]
        labels = self._legacy_by_value.get(value)
        if labels and len(labels) == 1:
            return next(iter(labels))
        return value


# The lists whose stored value carries a number in the Natural England
# template. The other lists store plain words in both templates, as do the
# vertical area habitat lists, which have no legacy layer.
AREA_CONDITION = LabelList(
    "Habitats/Habitat Condition.csv", "Label", "UKHAB", "Label")
WATERCOURSE_CONDITION = LabelList(
    "Watercourses/Watercourse Condition.csv", "Label", "Habitat", "Label")
RIPARIAN_ENCROACHMENT = LabelList(
    "Watercourses/Riparian Encroachment.csv", "Label", "Value", "Label")
# For an existing watercourse, the fourth option of the Natural England list is
# "4. Lost". The BNG Service list puts "Created" in that place, and the Natural
# England list has no "Created" for an existing watercourse. The value keeps
# the number of its place, which is how earlier versions of the BNG Service
# template stored it: "4. Created".
WATERCOURSE_RETENTION = LabelList(
    "Watercourses/Watercourse Retention Options.csv", "Label", "Value",
    "Label", gaps={"Created": "4. Created"})
TREE_CONDITION = LabelList(
    "Individual trees/Individual tree Condition - pre.csv", "Label",
    "Category", "Label")
# Natural England stores a tree's proposed condition from its "New" column,
# which has no numbers. The filter joins the baseline condition, as the
# legacy template stores it, and the retention category.
TREE_PROPOSED_CONDITION = LabelList(
    "Individual trees/Individual tree Condition - options.csv", "Label",
    "ID", "New")

LABEL_LISTS = (
    AREA_CONDITION,
    WATERCOURSE_CONDITION,
    RIPARIAN_ENCROACHMENT,
    WATERCOURSE_RETENTION,
    TREE_CONDITION,
    TREE_PROPOSED_CONDITION,
)


def reference_files():
    """(template, path in its CSV References folder) for every list read here.

    build_plugin.py copies exactly these into the plugin zip.
    """
    files = [(template, label_list.path)
             for template in TEMPLATES for label_list in LABEL_LISTS]
    files += [(SERVICE_TEMPLATE, lookup.path) for lookup in RULE_LISTS]
    return list(dict.fromkeys(files))


# ---------------------------------------------------------------------------
# Which columns use which list, and what the legacy drop-down filters on
# ---------------------------------------------------------------------------

WATERCOURSE_TO_BE_CREATED = "To be created"
TREE_EXISTING = "Existing"
NOT_APPLICABLE = "N/A"


def column(name):
    return lambda row: row.get(name)


def column_or(name, fallback):
    return lambda row: row.get(name) or fallback


def tree_condition_id(row):
    """The legacy filter for a tree's proposed condition: condition + retention.

    Reads the baseline condition after it has been converted, which is why
    that column comes first in COLUMN_LISTS.
    """
    baseline = row.get("Baseline Condition") or NOT_APPLICABLE
    return f"{baseline}{row.get('Retention Category') or ''}"


WATERCOURSE_COLUMNS = (
    ("Baseline Condition", WATERCOURSE_CONDITION, column("Baseline River Type")),
    ("Proposed Condition", WATERCOURSE_CONDITION, column("Proposed River Type")),
    ("Baseline Encroachment into riparian zone", RIPARIAN_ENCROACHMENT,
     column("Baseline River Type")),
    ("Proposed Encroachment into riparian zone", RIPARIAN_ENCROACHMENT,
     column("Proposed River Type")),
    ("Retention Category", WATERCOURSE_RETENTION,
     column_or("Baseline River Type", WATERCOURSE_TO_BE_CREATED)),
)

# Layer -> (column, list, legacy filter value), in the order they must be
# converted. The keys are the staged layer names new_to_old uses, and the
# legacy layer names old_to_new uses, which share their columns.
COLUMN_LISTS = {
    "areas": (
        ("Baseline Condition", AREA_CONDITION, column("Baseline Habitat Type")),
        ("Proposed Condition", AREA_CONDITION, column("Proposed Habitat Type")),
    ),
    "watercourses": WATERCOURSE_COLUMNS,
    "meanders": WATERCOURSE_COLUMNS,
    "trees": (
        ("Baseline Condition", TREE_CONDITION,
         column_or("Category", TREE_EXISTING)),
        ("Proposed Condition", TREE_PROPOSED_CONDITION, tree_condition_id),
    ),
}


def _convert_rows(rows, columns, convert):
    changed = 0
    for row in rows:
        for name, label_list, context in columns:
            if name not in row:
                continue
            value = row[name]
            converted = convert(label_list, value, context(row))
            if converted != value:
                row[name] = converted
                changed += 1
    return changed


def _legacy(label_list, value, context):
    return label_list.legacy_form(value, context)


def _service(label_list, value, _context):
    return label_list.service_form(value)


def to_legacy_labels(layers):
    """Number every listed value in place, as the legacy template stores it.

    `layers` maps a key of COLUMN_LISTS to a list of row dicts, or to a dict
    of such lists by stage. Returns how many values changed.
    """
    return _convert_layers(layers, _legacy)


def to_service_labels(layers):
    """Take the list number off every listed value in place. Returns the count."""
    return _convert_layers(layers, _service)


def _convert_layers(layers, convert):
    changed = 0
    for key, columns in COLUMN_LISTS.items():
        stages = layers.get(key)
        if not stages:
            continue
        if isinstance(stages, dict):
            stages = stages.values()
        else:
            stages = (stages,)
        for rows in stages:
            changed += _convert_rows(rows, columns, convert)
    return changed


# ---------------------------------------------------------------------------
# Values the BNG Service template fills itself from its lists
# ---------------------------------------------------------------------------


class ListLookup:
    """The values one BNG Service list allows, by the value it is keyed on."""

    def __init__(self, path, key_column, value_column):
        self.path = path
        self.key_column = key_column
        self.value_column = value_column
        self._values = None

    def values(self, key):
        """Every value the list gives for `key`, in list order."""
        if self._values is None:
            self._values = {}
            for row in read_list(SERVICE_TEMPLATE, self.path):
                value = row.get(self.value_column)
                if value:
                    found = self._values.setdefault(row.get(self.key_column), [])
                    if value not in found:
                        found.append(value)
        return self._values.get(key, [])

    def only(self, key):
        """The value, when the list gives exactly one for `key`; else None."""
        values = self.values(key)
        return values[0] if len(values) == 1 else None


def _lookup(path, key_column, value_column):
    return ListLookup(path, key_column, value_column)


# Layer key -> {column filled: (list, column holding the habitat type)}.
DISTINCTIVENESS_LISTS = {
    "areas": {
        "Baseline Distinctiveness": (_lookup(
            "Habitats/Habitat Distinctiveness- pre.csv", "Habitat",
            "Baseline Distinctivness"), "Baseline Habitat Type"),
        "Proposed Distinctiveness": (_lookup(
            "Habitats/Habitat Distinctiveness- post.csv", "Habitat",
            "Proposed Distinctivness"), "Proposed Habitat Type"),
    },
    "hedgerows": {
        "Baseline Distinctiveness": (_lookup(
            "Hedgerows/Hedgerow Distinctiveness- pre.csv", "Value",
            "Distinctiveness"), "Baseline Hedge Type"),
        "Proposed Distinctiveness": (_lookup(
            "Hedgerows/Hedgerow Distinctiveness - post.csv", "Value",
            "Distinctiveness"), "Proposed Hedge Type"),
    },
    "watercourses": {
        "Baseline Distinctiveness": (_lookup(
            "Watercourses/Watercourse Distinctiveness- pre.csv", "Value",
            "Distinctiveness"), "Baseline River Type"),
        "Proposed Distinctiveness": (_lookup(
            "Watercourses/Watercourse Distinctiveness- post.csv", "Value",
            "Distinctiveness"), "Proposed River Type"),
    },
}
AREA_CONDITIONS = _lookup("Habitats/Habitat Condition.csv", "UKHAB", "Label")
HEDGEROW_CONDITIONS = _lookup(
    "Hedgerows/Hedgerow Condition.csv", "Habitat", "Condition")
WATERCOURSE_CONDITIONS = _lookup(
    "Watercourses/Watercourse Condition.csv", "Habitat", "Label")
CONDITION_LISTS = {
    "areas": {"Baseline Condition": (AREA_CONDITIONS, "Baseline Habitat Type"),
              "Proposed Condition": (AREA_CONDITIONS, "Proposed Habitat Type")},
    "hedgerows": {
        "Baseline Condition": (HEDGEROW_CONDITIONS, "Baseline Hedge Type"),
        "Proposed Condition": (HEDGEROW_CONDITIONS, "Proposed Hedge Type")},
    "watercourses": {
        "Baseline Condition": (WATERCOURSE_CONDITIONS, "Baseline River Type"),
        "Proposed Condition": (WATERCOURSE_CONDITIONS, "Proposed River Type")},
}
IRREPLACEABLE_LIST = _lookup(
    "Habitats/Habitat Irreplaceable.csv", "UKHAB", "Irreplaceable")
IRREPLACEABLE_COLUMN = "Irreplaceable Habitat"
IRREPLACEABLE_TYPE_COLUMN = "Baseline Habitat Type"

RULE_LISTS = tuple(
    [lookup for columns in DISTINCTIVENESS_LISTS.values()
     for lookup, _type in columns.values()]
    + [AREA_CONDITIONS, HEDGEROW_CONDITIONS, WATERCOURSE_CONDITIONS,
       IRREPLACEABLE_LIST])


def fill_template_values(key, rows):
    """Fill the blanks the BNG Service template would fill, in place.

    `key` is "areas", "hedgerows" or "watercourses". Only a blank is filled:
    distinctiveness from the habitat type, a condition when the habitat
    allows exactly one, and, for area habitats, Irreplaceable Habitat when
    the habitat allows only one answer. Returns {column: count filled}.
    """
    filled = {}
    rules = []
    for column, (lookup, type_column) in DISTINCTIVENESS_LISTS.get(
            key, {}).items():
        rules.append((column, lookup.values, type_column))
    for column, (lookup, type_column) in CONDITION_LISTS.get(key, {}).items():
        rules.append((column, lookup.values, type_column))
    if key == "areas":
        rules.append((IRREPLACEABLE_COLUMN, IRREPLACEABLE_LIST.values,
                      IRREPLACEABLE_TYPE_COLUMN))
    for row in rows:
        for column, values, type_column in rules:
            if column not in row or not _is_blank(row.get(column)):
                continue
            allowed = values(row.get(type_column))
            if len(allowed) == 1:
                row[column] = allowed[0]
                filled[column] = filled.get(column, 0) + 1
    return filled


def _is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


# ---------------------------------------------------------------------------
# Strategic significance
# ---------------------------------------------------------------------------

SIGNIFICANCE_LOW = "Low"
SIGNIFICANCE_HIGH = "High"
NE_SIGNIFICANCE_LOW = (
    "Area/compensation not in local strategy/ no local strategy")
NE_SIGNIFICANCE_MEDIUM = (
    "Location ecologically desirable but not in local strategy")
NE_SIGNIFICANCE_HIGH = "Formally identified in local strategy"
# Trees word formal identification differently from every other habitat type.
NE_SIGNIFICANCE_HIGH_TREES = "Within area formally identified in local strategy"
BASELINE_SIGNIFICANCE = "Baseline Strategic Significance"
PROPOSED_SIGNIFICANCE = "Proposed Strategic Significance"
# A type column holding one of these, or nothing, means no baseline part.
NO_HABITAT_TYPES = (WATERCOURSE_TO_BE_CREATED, NOT_APPLICABLE)
TREE_NEWLY_PLANTED = "Newly Planted"
TREE_LOST = "Lost"

# Layer key -> (baseline type column, proposed type column).
TYPE_COLUMNS = {
    "areas": ("Baseline Habitat Type", "Proposed Habitat Type"),
    "verticalAreas": ("Baseline Habitat Type", "Proposed Habitat Type"),
    "hedgerows": ("Baseline Hedge Type", "Proposed Hedge Type"),
    "watercourses": ("Baseline River Type", "Proposed River Type"),
    "meanders": (None, "Proposed River Type"),
    "trees": ("Baseline Tree Type", "Proposed Tree Type"),
}


def has_habitat_type(value):
    """True when a type column names a habitat, not a creation or nothing."""
    return not _is_blank(value) and value not in NO_HABITAT_TYPES


def has_baseline_part(key, row):
    """Whether a post-intervention row carries a baseline habitat."""
    column = TYPE_COLUMNS[key][0]
    return bool(column) and has_habitat_type(row.get(column))


def _legacy_blank(key, column, row):
    """What the earlier BNG Service template held where the new one is NULL.

    Its significance drop-downs offered only "N/A" for a hedgerow or
    watercourse type of "To be created" or "N/A", for a newly planted tree's
    baseline, and for a lost tree's proposal. Elsewhere they held a blank.
    """
    if key in ("hedgerows", "watercourses"):
        baseline_type, proposed_type = TYPE_COLUMNS[key]
        type_column = (baseline_type if column == BASELINE_SIGNIFICANCE
                       else proposed_type)
        if row.get(type_column) in NO_HABITAT_TYPES:
            return NOT_APPLICABLE
    if key == "trees":
        if (column == BASELINE_SIGNIFICANCE
                and row.get("Category") == TREE_NEWLY_PLANTED):
            return NOT_APPLICABLE
        if (column == PROPOSED_SIGNIFICANCE
                and plain_label(row.get("Retention Category")) == TREE_LOST):
            return NOT_APPLICABLE
    return None


def legacy_significance(key, column, row):
    """A row's significance as Natural England and the metric word it."""
    value = row.get(column)
    if _is_blank(value):
        return _legacy_blank(key, column, row)
    if value == SIGNIFICANCE_LOW:
        return NE_SIGNIFICANCE_LOW
    if value == SIGNIFICANCE_HIGH:
        return (NE_SIGNIFICANCE_HIGH_TREES if key == "trees"
                else NE_SIGNIFICANCE_HIGH)
    return value


def to_legacy_significance(layers):
    """Write every significance in place as Natural England words it.

    `layers` maps a layer key ("areas", "hedgerows", ...) to a dict of row
    lists by stage. Returns how many values changed.
    """
    changed = 0
    for key, stages in layers.items():
        if key not in TYPE_COLUMNS:
            continue
        for rows in stages.values():
            for row in rows:
                for column in (BASELINE_SIGNIFICANCE, PROPOSED_SIGNIFICANCE):
                    if column not in row:
                        continue
                    value = legacy_significance(key, column, row)
                    if value != row[column]:
                        row[column] = value
                        changed += 1
    return changed


# Natural England wording -> the BNG Service value. Medium has no place in
# the BNG Service template, so it reads as NULL, and so do "N/A" and blank.
SERVICE_SIGNIFICANCE = {
    NE_SIGNIFICANCE_LOW: SIGNIFICANCE_LOW,
    NE_SIGNIFICANCE_HIGH: SIGNIFICANCE_HIGH,
    NE_SIGNIFICANCE_HIGH_TREES: SIGNIFICANCE_HIGH,
    NE_SIGNIFICANCE_MEDIUM: None,
    NOT_APPLICABLE: None,
}


def service_significance(value):
    """(BNG Service value, whether the wording was known) for an NE value."""
    if _is_blank(value):
        return None, True
    words = plain_label(value)
    if words in SERVICE_SIGNIFICANCE:
        return SERVICE_SIGNIFICANCE[words], True
    return None, False
