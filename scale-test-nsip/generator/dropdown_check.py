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

An advance or delay column offers blank, 0 to 30 and 30+. When the other
column is a year above 0, it offers only a blank. Text such as N/A is not
a year above 0.

Some columns the template fills itself, from the habitat type or a fixed
rule, and shows read-only: distinctiveness, strategic significance, spatial
risk and Irreplaceable Habitat. Those are checked against the lists and the
rules directly, whatever widget the project gives them, and a blank there is
wrong wherever the template would have filled a value.

    python3 dropdown_check.py <site folder>     # exits 1 on any invalid value

Standard library only. The filter language is the small subset the template
uses: comparisons with `=` or `IN (...)` between list columns, strings,
current_value(), concat() and coalesce(), joined by AND, OR and NOT. Anything else stops the
check rather than being guessed at.
"""

import csv
import glob
import os
import sqlite3
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

EXAMPLES_PER_FIELD = 3


def _word_char(char):
    return char == "_" or "A" <= char <= "Z" or "a" <= char <= "z"


def _double_quoted(text, start):
    end = text.find('"', start + 1)
    if end < 0:
        return None
    return end + 1


def _single_quoted(text, start):
    """End of a single-quoted token, or None when it never closes.

    A doubled quote is one quote. The scan remembers the last place a
    closing quote could sit, so a run of quotes is not retried.
    """
    j = start + 1
    last_good = None
    n = len(text)
    while j < n:
        if text[j] != "'":
            j += 1
            continue
        if j + 1 < n and text[j + 1] == "'":
            last_good = j + 1
            j += 2
            continue
        return j + 1
    return last_good


def _word_end(text, start):
    j = start + 1
    n = len(text)
    while j < n and _word_char(text[j]):
        j += 1
    return j


def _take_quoted(tokens, text, start, quote, scan):
    end = scan(text, start)
    if end is None:
        tokens.append(("", "", "", quote))
        return start + 1
    if quote == '"':
        tokens.append((text[start:end], "", "", ""))
    else:
        tokens.append(("", text[start:end], "", ""))
    return end


def tokenize(text):
    """The filter's tokens as (double quote, single quote, word, other).

    Whitespace is skipped. Each character is read once.
    """
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        if char.isspace():
            i += 1
            continue
        if char == '"':
            i = _take_quoted(tokens, text, i, char, _double_quoted)
            continue
        if char == "'":
            i = _take_quoted(tokens, text, i, char, _single_quoted)
            continue
        if _word_char(char):
            end = _word_end(text, i)
            tokens.append(("", "", text[i:end], ""))
            i = end
            continue
        tokens.append(("", "", "", char))
        i += 1
    return tokens


class Filter:
    """A parsed filter, evaluated against a list row and the feature's row.

    Comparisons are `=` or `IN (...)` between a list column ("Name"), a
    string and the functions current_value(), concat() and coalesce(),
    joined by AND, OR and NOT, with brackets. A comparison with a blank side is NULL, as in
    QGIS, and NULL keeps a list row out.
    """

    def __init__(self, text):
        self.text = text
        self.tokens = tokenize(text.strip())
        self.pos = 0
        self.tree = self._or()
        if self.pos != len(self.tokens):
            self._fail()

    def _fail(self):
        raise ValueError(f"unsupported filter: {self.text!r}")

    def _peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _take(self):
        if self.pos >= len(self.tokens):
            self._fail()
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def _keyword(self, word):
        token = self._peek()
        if token and token[2].upper() == word:
            self.pos += 1
            return True
        return False

    def _or(self):
        terms = [self._and()]
        while self._keyword("OR"):
            terms.append(self._and())
        return ("or", terms) if len(terms) > 1 else terms[0]

    def _and(self):
        terms = [self._not()]
        while self._keyword("AND"):
            terms.append(self._not())
        return ("and", terms) if len(terms) > 1 else terms[0]

    def _not(self):
        if self._keyword("NOT"):
            return ("not", self._not(), None)
        token = self._peek()
        if token and token[3] == "(":
            self.pos += 1
            inner = self._or()
            if self._take()[3] != ")":
                self._fail()
            return inner
        left = self._operand()
        if self._keyword("IN"):
            return ("in", left, self._operand_list())
        if self._take()[3] != "=":
            self._fail()
        return ("eq", left, self._operand())

    def _operand_list(self):
        if self._take()[3] != "(":
            self._fail()
        items = [self._operand()]
        while True:
            punct = self._take()[3]
            if punct == ")":
                return items
            if punct != ",":
                self._fail()
            items.append(self._operand())

    def _operand(self):
        column, string, name, _ = self._take()
        if column:
            return ("column", column.strip('"'))
        if string:
            return ("str", string[1:-1].replace("''", "'"))
        if name not in ("current_value", "concat", "coalesce"):
            raise ValueError(f"unsupported function {name!r} in {self.text!r}")
        if self._take()[3] != "(":
            self._fail()
        args = [self._operand()]
        while True:
            punct = self._take()[3]
            if punct == ")":
                return (name, args)
            if punct != ",":
                self._fail()
            args.append(self._operand())

    def fields(self, node=None):
        """The feature's columns the filter reads through current_value()."""
        node = node or self.tree
        kind = node[0]
        if kind in ("str", "column"):
            return set()
        if kind == "current_value":
            return {node[1][0][1]}
        if kind == "not":
            return self.fields(node[1])
        if kind == "eq":
            return self.fields(node[1]) | self.fields(node[2])
        if kind == "in":
            return self.fields(node[1]).union(
                *(self.fields(item) for item in node[2]))
        return set().union(*(self.fields(a) for a in node[1]))

    def value(self, entry, row, node):
        """Evaluate an operand as QGIS does: concat() treats a blank as
        empty text."""
        kind, args = node
        if kind == "str":
            return args
        if kind == "column":
            return blank_to_none(entry.get(args))
        if kind == "current_value":
            return blank_to_none(row.get(args[0][1]))
        values = [self.value(entry, row, a) for a in args]
        if kind == "coalesce":
            return next((v for v in values if v is not None), None)
        return "".join(v or "" for v in values)

    def _same(self, entry, row, node):
        left = self.value(entry, row, node[1])
        right = self.value(entry, row, node[2])
        if left is None or right is None:
            return None
        return left == right

    def _member(self, entry, row, node):
        left = self.value(entry, row, node[1])
        items = [self.value(entry, row, item) for item in node[2]]
        if left is None:
            return None
        if left in items:
            return True
        if None in items:
            return None
        return False

    def truth(self, entry, row, node=None):
        """True, False or None (NULL), with SQL's three-valued logic."""
        node = node or self.tree
        kind = node[0]
        if kind == "eq":
            return self._same(entry, row, node)
        if kind == "in":
            return self._member(entry, row, node)
        if kind == "not":
            inner = self.truth(entry, row, node[1])
            if inner is None:
                return None
            return not inner
        results = [self.truth(entry, row, term) for term in node[1]]
        decisive = kind == "or"
        if decisive in results:
            return decisive
        if None in results:
            return None
        return not decisive

    def matches(self, entry, row):
        return self.truth(entry, row) is True


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
        _add_dropdowns(checks, site, layers, layer)
    for table, fields in rule_checks(site).items():
        checks.setdefault(table, []).extend(fields)
    return checks


def _add_dropdowns(checks, site, layers, layer):
    source = layer.findtext("datasource") or ""
    configuration = layer.find("fieldConfiguration")
    if "layername=" not in source or configuration is None:
        return
    table = source.split("layername=")[1].split("|")[0]
    names = {f.get("name") for f in configuration}
    for field in configuration:
        check = _dropdown(site, layers, names, field)
        if check:
            checks.setdefault(table, []).append(check)


def _dropdown(site, layers, names, field):
    """One Value Map or Value Relation, or None when a rule owns the field.

    Advance and delay are Value Maps, but the pair rule decides which of
    blank, 0 to 30 and 30+ a row may hold.
    """
    name = field.get("name")
    if name in RULE_FIELDS or name in TIMING_FIELDS:
        return None
    widget = field.find("editWidget")
    kind = widget.get("type") if widget is not None else None
    if kind == "ValueMap":
        allowed = {o.get("value") for o in widget.iter("Option")
                   if o.get("type") == "QString" and o.get("name")}
        return (name, lambda row, values=allowed: values)
    if kind != "ValueRelation":
        return None
    opts = options(widget)
    rows = csv_rows(site, layers[opts["Layer"]].findtext("datasource"))
    text = (opts.get("FilterExpression") or "").strip()
    flt = Filter(text) if text else None
    # QGIS ignores a filter that reads a column the layer lacks, and offers
    # the whole list, so the check does the same.
    if flt and flt.fields() - names:
        flt = None
    return (name, allowed_by(rows, opts["Key"], flt))


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


RETAINED = "Retained"
# Table stem -> (years created in advance, years of delay). A year above 0
# in one blanks the other. Otherwise each allows blank, 0 to 30 and 30+.
TIMING = {
    "Individual Trees": ("Habitat Created/Enhanced in advance/years",
                         "Delay in starting habitat creation/enhancement "
                         "in years"),
}
DEFAULT_TIMING = ("Habitat created in advance/years",
                  "Delay in starting habitat creation/years")
TIMING_FIELDS = {field for pair in (*TIMING.values(), DEFAULT_TIMING)
                 for field in pair}
# Blank, 0 to 30 and 30+. 30+ is the only text the list holds. A year above
# 0 is any of those except 0. Text such as N/A is not one.
TIMING_YEARS = {str(year) for year in range(31)} | {"30+"}
YEARS_ABOVE_ZERO = TIMING_YEARS - {"0"}


def year_above_zero(value):
    return blank_to_none(value) in YEARS_ABOVE_ZERO


def timing_allowed(other):
    """Blank while `other` is a year above 0; otherwise the years list."""
    def allowed(row):
        if year_above_zero(row.get(other)):
            return BLANK
        return TIMING_YEARS | BLANK
    return allowed


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
            checks[f"{stem} {stage}"] = _rule_fields(
                site, stem, type_stem, lists, post, irreplaceable)
    return checks


def _rule_fields(site, stem, type_stem, lists, post, irreplaceable):
    baseline_type = f"Baseline {type_stem}"
    fields = [("Baseline Strategic Significance",
               baseline_significance(baseline_type, post))]
    if lists:
        fields.append(("Baseline Distinctiveness", from_type(
            list_values(site, *lists[0]), baseline_type)))
    if post:
        advance, delay = TIMING.get(stem, DEFAULT_TIMING)
        fields.append(("Proposed Strategic Significance",
                       proposed_significance))
        fields.extend((
            (advance, timing_allowed(delay)),
            (delay, timing_allowed(advance)),
            ("Spatial risk category", lambda row: {NOT_APPLICABLE}),
        ))
        if lists:
            fields.append(("Proposed Distinctiveness", from_type(
                list_values(site, *lists[1]), f"Proposed {type_stem}")))
    if stem in ("Area Habitats", "Vertical Area Habitats"):
        fields.append(("Irreplaceable Habitat", irreplaceable_rule(
            irreplaceable, baseline_type)))
    return fields


def allowed_by(rows, key, flt):
    if flt is None:
        every = {r[key] for r in rows}
        return lambda row: every
    # The list a row is offered depends only on the columns the filter
    # reads, so each combination of them is worked out once.
    fields = sorted(flt.fields())
    cache = {}

    def allowed(row):
        values = tuple(blank_to_none(row.get(f)) for f in fields)
        if values not in cache:
            cache[values] = {r[key] for r in rows if flt.matches(r, row)}
        return cache[values]
    return allowed


def check_site(site):
    """Return {(table, field): (count, [examples])} for every invalid value."""
    checks = build_checks(site, read_project(site))
    gpkg = glob.glob(os.path.join(site, "Layers", "*.gpkg"))[0]
    conn = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    invalid = {}
    for table, fields in sorted(checks.items()):
        for record in conn.execute(f'SELECT * FROM "{table}"'):
            _collect_invalid(invalid, table, fields, dict(record))
    conn.close()
    return invalid


def _collect_invalid(invalid, table, fields, row):
    for field, allowed in fields:
        value = blank_to_none(row.get(field))
        if value is None and field not in RULE_FIELDS:
            continue
        if value in allowed(row):
            continue
        _note_invalid(invalid, table, field, value)


def _note_invalid(invalid, table, field, value):
    count, examples = invalid.get((table, field), (0, []))
    if len(examples) < EXAMPLES_PER_FIELD:
        examples.append(value)
    invalid[(table, field)] = (count + 1, examples)


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
