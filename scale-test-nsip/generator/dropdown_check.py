#!/usr/bin/env python3
"""Check every drop-down value in a site against the template's own lists.

The template's drop-downs come from two places: short fixed lists held in the
QGIS project, and reference lists (CSV files) filtered by an earlier choice,
so that a condition list offers only the conditions the Metric allows for the
chosen habitat. A value written straight into the GeoPackage, as the
generator does, never passes through a drop-down, so nothing stops it being
one the list would not have offered. This reads the drop-downs from the
project, applies each filter to each row exactly as QGIS would, and reports
every value the list would not have offered.

A blank is always accepted: it is a missing value, which the service reports
as such, not an invalid one.

Some columns the template fills itself, from the habitat type or a fixed
rule, and shows read-only: distinctiveness, strategic significance, spatial
risk and Irreplaceable Habitat. Those are checked against the lists and the
rules directly, whatever widget the project gives them, and a blank there is
wrong wherever the template would have filled a value.

    python3 dropdown_check.py <site folder>     # exits 1 on any invalid value

Standard library only. The filter language is the small subset the template
uses: a column compared with a string, current_value(), concat() and
coalesce(). Anything else stops the check rather than being guessed at.
"""

import csv
import glob
import os
import re
import sqlite3
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

EXAMPLES_PER_FIELD = 3
TOKEN = re.compile(r"\s*(?:(\"[^\"]*\")|('(?:[^']|'')*')|([A-Za-z_]+)|(.))")


class Filter:
    """A parsed filter: the reference column, and the expression it equals."""

    def __init__(self, text):
        self.text = text
        self.tokens = [t for t in TOKEN.findall(text.strip())]
        self.pos = 0
        column = self._take()[0]
        if not column or self._take()[3] != "=":
            raise ValueError(f"unsupported filter: {text!r}")
        self.column = column.strip('"')
        self.expr = self._expr()
        if self.pos != len(self.tokens):
            raise ValueError(f"unsupported filter: {text!r}")

    def _take(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def _expr(self):
        _, string, name, _ = self._take()
        if string:
            return ("str", string[1:-1].replace("''", "'"))
        if name not in ("current_value", "concat", "coalesce"):
            raise ValueError(f"unsupported function {name!r} in {self.text!r}")
        if self._take()[3] != "(":
            raise ValueError(f"unsupported filter: {self.text!r}")
        args = [self._expr()]
        while True:
            punct = self._take()[3]
            if punct == ")":
                return (name, args)
            if punct != ",":
                raise ValueError(f"unsupported filter: {self.text!r}")
            args.append(self._expr())

    def fields(self, node=None):
        node = node or self.expr
        if node[0] == "str":
            return set()
        if node[0] == "current_value":
            return {node[1][0][1]}
        return set().union(*(self.fields(a) for a in node[1]))

    def value(self, row, node=None):
        """Evaluate as QGIS does: concat() treats a blank as empty text."""
        node = node or self.expr
        kind, args = node
        if kind == "str":
            return args
        if kind == "current_value":
            return blank_to_none(row.get(args[0][1]))
        values = [self.value(row, a) for a in args]
        if kind == "coalesce":
            return next((v for v in values if v is not None), None)
        return "".join(v or "" for v in values)


def blank_to_none(value):
    return None if value is None or value == "" else value


def read_project(site):
    path = glob.glob(os.path.join(site, "*.qgz"))[0]
    with zipfile.ZipFile(path) as archive:
        name = [n for n in archive.namelist() if n.endswith(".qgs")][0]
        return ET.fromstring(archive.read(name))


def csv_rows(site, source):
    relative = urllib.parse.unquote(source.split("?")[0].replace("file:", ""))
    with open(os.path.join(site, relative), encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def options(widget):
    return {o.get("name"): o.get("value")
            for o in widget.iter("Option") if o.get("name")}


def build_checks(site, project):
    """Map GeoPackage table -> [(field, allowed(row) -> set of values)].

    A blank passes a drop-down check. A rule check says itself whether a
    blank is allowed, by putting None in the set.
    """
    layers = {ml.findtext("id"): ml for ml in project.iter("maplayer")}
    checks = {}
    for layer in layers.values():
        source = layer.findtext("datasource") or ""
        if "layername=" not in source or layer.find("fieldConfiguration") is None:
            continue
        table = source.split("layername=")[1].split("|")[0]
        names = {f.get("name") for f in layer.find("fieldConfiguration")}
        for field in layer.find("fieldConfiguration"):
            if field.get("name") in RULE_FIELDS:
                continue
            widget = field.find("editWidget")
            kind = widget.get("type") if widget is not None else None
            if kind == "ValueMap":
                allowed = {o.get("value") for o in widget.iter("Option")
                           if o.get("type") == "QString" and o.get("name")}
                checks.setdefault(table, []).append(
                    (field.get("name"), lambda row, a=allowed: a))
            elif kind == "ValueRelation":
                opts = options(widget)
                rows = csv_rows(site, layers[opts["Layer"]].findtext("datasource"))
                key = opts["Key"]
                text = (opts.get("FilterExpression") or "").strip()
                flt = Filter(text) if text else None
                # QGIS ignores a filter that reads a column the layer lacks,
                # and offers the whole list, so the check does the same.
                if flt and not flt.fields() <= names:
                    flt = None
                checks.setdefault(table, []).append(
                    (field.get("name"), allowed_by(rows, key, flt)))
    for table, fields in rule_checks(site).items():
        checks.setdefault(table, []).extend(fields)
    return checks


# ------------------------------------------------ columns the template fills

RULE_FIELDS = {
    "Baseline Distinctiveness", "Proposed Distinctiveness",
    "Baseline Strategic Significance", "Proposed Strategic Significance",
    "Spatial risk category", "Irreplaceable Habitat",
}
LOW, HIGH, NOT_APPLICABLE = "Low", "High", "N/A"
NO_HABITAT_TYPES = ("To be created", NOT_APPLICABLE)
BLANK = {None}

# Table stem -> (type column stem, distinctiveness lists as
# (path, key column, value column) for baseline and proposed).
AREA_LISTS = (
    ("Habitats/Habitat Distinctiveness- pre.csv", "Habitat",
     "Baseline Distinctivness"),
    ("Habitats/Habitat Distinctiveness- post.csv", "Habitat",
     "Proposed Distinctivness"))
KINDS = {
    "Area Habitats": ("Habitat Type", AREA_LISTS),
    "Vertical Area Habitats": ("Habitat Type", (
        ("Vertical Area Habitats/Vertical Area Habitat Distinctiveness- pre.csv",
         "Habitat", "Baseline Distinctivness"),
        ("Vertical Area Habitats/Vertical Area Habitat Distinctiveness- post.csv",
         "Habitat", "Proposed Distinctivness"))),
    "Hedgerows": ("Hedge Type", (
        ("Hedgerows/Hedgerow Distinctiveness- pre.csv", "Value",
         "Distinctiveness"),
        ("Hedgerows/Hedgerow Distinctiveness - post.csv", "Value",
         "Distinctiveness"))),
    "Watercourses": ("River Type", (
        ("Watercourses/Watercourse Distinctiveness- pre.csv", "Value",
         "Distinctiveness"),
        ("Watercourses/Watercourse Distinctiveness- post.csv", "Value",
         "Distinctiveness"))),
    "Individual Trees": ("Tree Type", None),
}
IRREPLACEABLE_LIST = ("Habitats/Habitat Irreplaceable.csv", "UKHAB",
                      "Irreplaceable")
STAGES = (("Baseline", False), ("Post-Intervention", True))


def list_values(site, path, key, value):
    """Key -> set of values, from one list in the site's CSV References."""
    out = {}
    full = os.path.join(site, "CSV References", path)
    with open(full, encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get(value):
                out.setdefault(row[key], set()).add(row[value])
    return out


def has_type(value):
    return value is not None and value != "" and value not in NO_HABITAT_TYPES


def from_type(values, type_column):
    """The value a list gives for the row's type. Blank when there is none."""
    def allowed(row):
        habitat = blank_to_none(row.get(type_column))
        return values.get(habitat, set()) if habitat is not None else BLANK
    return allowed


def irreplaceable_rule(values, type_column):
    """The only answer the habitat allows, or either answer or a blank."""
    def allowed(row):
        habitat = blank_to_none(row.get(type_column))
        if habitat is None:
            return BLANK
        options = values.get(habitat, set())
        return options if len(options) == 1 else options | BLANK
    return allowed


def baseline_significance(type_column, post):
    """Low on a baseline row, and on a post-intervention row with a baseline
    habitat. Blank on a row created from nothing."""
    if not post:
        return lambda row: {LOW}
    return lambda row: {LOW} if has_type(row.get(type_column)) else BLANK


class Anything:
    """Every value, for a column that a rule only limits in some rows."""

    def __contains__(self, value):
        return True


ANYTHING = Anything()
RETAINED = "Retained"
# Table stem -> (years created in advance, years of delay). Both above 0 is
# not allowed: a value above 0 in one blanks the other.
TIMING = {
    "Individual Trees": ("Habitat Created/Enhanced in advance/years",
                         "Delay in starting habitat creation/enhancement "
                         "in years"),
}
DEFAULT_TIMING = ("Habitat created in advance/years",
                  "Delay in starting habitat creation/years")


def above_zero(value):
    return blank_to_none(value) not in (None, "0")


def blank_while_other_set(other):
    return lambda row: BLANK if above_zero(row.get(other)) else ANYTHING


def proposed_significance(row):
    """Low on a Retained row, as its baseline; otherwise Low or High."""
    if blank_to_none(row.get("Retention Category")) == RETAINED:
        return {LOW}
    return {LOW, HIGH}


def rule_checks(site):
    """Map GeoPackage table -> [(field, allowed(row))] for RULE_FIELDS."""
    irreplaceable = list_values(site, *IRREPLACEABLE_LIST)
    checks = {}
    for stem, (type_stem, lists) in KINDS.items():
        for stage, post in STAGES:
            table = f"{stem} {stage}"
            baseline_type = f"Baseline {type_stem}"
            fields = [("Baseline Strategic Significance",
                       baseline_significance(baseline_type, post))]
            if lists:
                fields.append(("Baseline Distinctiveness", from_type(
                    list_values(site, *lists[0]), baseline_type)))
            if post:
                fields.append(("Proposed Strategic Significance",
                               proposed_significance))
                advance, delay = TIMING.get(stem, DEFAULT_TIMING)
                fields.append((advance, blank_while_other_set(delay)))
                fields.append((delay, blank_while_other_set(advance)))
                fields.append(("Spatial risk category",
                               lambda row: {NOT_APPLICABLE}))
                if lists:
                    fields.append(("Proposed Distinctiveness", from_type(
                        list_values(site, *lists[1]),
                        f"Proposed {type_stem}")))
            if stem in ("Area Habitats", "Vertical Area Habitats"):
                fields.append(("Irreplaceable Habitat", irreplaceable_rule(
                    irreplaceable, baseline_type)))
            checks[table] = fields
    return checks


def allowed_by(rows, key, flt):
    if flt is None:
        every = {r[key] for r in rows}
        return lambda row: every
    by_column = {}
    for r in rows:
        by_column.setdefault(r[flt.column], set()).add(r[key])
    return lambda row: by_column.get(flt.value(row), set())


def check_site(site):
    """Return {(table, field): (count, [examples])} for every invalid value."""
    checks = build_checks(site, read_project(site))
    gpkg = glob.glob(os.path.join(site, "Layers", "*.gpkg"))[0]
    conn = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    invalid = {}
    for table, fields in sorted(checks.items()):
        for record in conn.execute(f'SELECT * FROM "{table}"'):
            row = dict(record)
            for field, allowed in fields:
                value = blank_to_none(row.get(field))
                if value is None and field not in RULE_FIELDS:
                    continue
                if value in allowed(row):
                    continue
                count, examples = invalid.get((table, field), (0, []))
                if len(examples) < EXAMPLES_PER_FIELD:
                    examples.append(value)
                invalid[(table, field)] = (count + 1, examples)
    conn.close()
    return invalid


def report(invalid):
    for (table, field), (count, examples) in sorted(invalid.items()):
        shown = ", ".join(repr(e) for e in examples)
        print(f"  {table} / {field}: {count} invalid, e.g. {shown}")


def main(argv):
    if len(argv) != 1:
        raise SystemExit("usage: dropdown_check.py <site folder>")
    invalid = check_site(argv[0])
    if invalid:
        print("values the template's drop-downs would not offer:")
        report(invalid)
        return 1
    print("every drop-down value is one the template offers")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
