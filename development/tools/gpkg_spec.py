"""Generate the specification of the BNG Service template's GeoPackage format.

Reads the template itself, its GeoPackage and its QGIS project, and writes
spec/gpkg-spec.json, for tools, and spec/gpkg-spec.md, for people. Third
parties that write BNG plans in the template's format read it to know what a
file must hold: every table, with its geometry type and coordinate system;
every column, with its type, width, whether it may be blank, its default and
its drop-down; the values each drop-down list allows; the lineage columns;
and the version record that names the format and its version.

    python3 development/tools/gpkg_spec.py            # write both files
    python3 development/tools/gpkg_spec.py --check    # write nothing

It reads no clock and nothing outside the template, so an unchanged template
gives the same bytes. With --check it writes nothing, prints how the
committed files differ from what the template gives, and exits 1 if they
differ. CI runs it so, and a template change cannot merge without its
specification. publish_spec.py publishes the Markdown to Confluence.
"""
import argparse
import csv
import difflib
import json
import re
import sqlite3
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_DIR = REPO_ROOT / "plugin" / "bng_template_convert"
sys.path.insert(0, str(PLUGIN_DIR))

import gpkg_common                                             # noqa: E402

TEMPLATE_DIR = REPO_ROOT / "templates" / "bng-service"
GPKG_PATH = TEMPLATE_DIR / "Layers" / "BNG Service Layers.gpkg"
PROJECT_PATH = TEMPLATE_DIR / "BNG Service Habitat Mapping.qgz"
SPEC_DIR = REPO_ROOT / "spec"
JSON_NAME = "gpkg-spec.json"
MARKDOWN_NAME = "gpkg-spec.md"

# Fixed, not read from git, so the output is the same everywhere.
REPO_URL = "https://github.com/DEFRA/bng-metric-template"
REPO_BRANCH = "main"
JSON_URL = f"{REPO_URL}/blob/{REPO_BRANCH}/spec/{JSON_NAME}"
BACKEND_MAPPING_URL = ("https://github.com/DEFRA/bng-metric-backend/blob/"
                       "main/data-dictionary/template-mapping.md")

RED_LINE = "Red Line Boundary"
STAGES = ("Baseline", "Post-Intervention")
BOTH_STAGES = "both"

# What each lineage column holds. The generator refuses a template whose
# lineage columns are not these.
LINEAGE_COLUMNS = {
    "feature_uuid": (
        "Baseline",
        "A UUID naming the baseline feature. Each baseline feature of a "
        "table has its own."),
    "Parent Ref": (
        "Post-Intervention",
        "The Habitat Ref of the baseline feature the row continues, for "
        "people to read."),
    "parent_uuid": (
        "Post-Intervention",
        "The feature_uuid of the baseline feature the row continues, on the "
        "baseline table of the same habitat layer. Blank on a habitat "
        "created with no baseline parent."),
    "parent_geom": (
        "Post-Intervention",
        "The parent's shape when the row was copied from it, as WKT with "
        f"coordinates rounded to {gpkg_common.COORD_DECIMALS} decimal "
        "places. It shows whether the baseline changed after the copy."),
}

# QGIS's stored value for the blank choice of a Value Map.
VALUE_MAP_NULL = "{2839923C-8B7D-419E-B84B-CA2FE9B80EC7}"
# QgsFieldConstraints: the not-null constraint, and how strong it is.
CONSTRAINT_NOT_NULL = 1
STRENGTH = {"0": None, "1": "hard", "2": "soft"}
LITERAL_DEFAULT = re.compile(r"'((?:[^']|'')*)'\Z|(-?\d+(?:\.\d+)?)\Z")
TEXT_WIDTH = re.compile(r"TEXT\s*\(\s*(\d+)\s*\)\Z", re.I)
# A rule about the row's shape. QGIS can hold a rule only on a field, so the
# template holds this one on the first text column; it is the geometry's.
GEOMETRY_EXPRESSION = "$geometry"
CURRENT_VALUE = re.compile(r"current_value\('([^']+)'\)")
QUOTED_FIELD = re.compile(r'"([^"]+)"')

WIDGET_KINDS = {
    "": "text",
    "TextEdit": "text",
    "Hidden": "hidden",
    "ValueMap": "fixed list",
    "ValueRelation": "list",
}


class SpecError(Exception):
    """The template cannot be described: what is wrong, and where."""


# ---------------------------------------------------------------------------
# The GeoPackage
# ---------------------------------------------------------------------------

def connect_read_only(path):
    return sqlite3.connect(gpkg_common.read_only_uri(path), uri=True)


def stage_of(table):
    for stage in STAGES:
        if table.endswith(f" {stage}"):
            return stage
    return BOTH_STAGES


def table_order(table):
    """Red Line Boundary first, then the habitat tables in file order."""
    return 0 if table == RED_LINE else 1


def read_columns(conn, table):
    columns = []
    for _cid, name, declared, notnull, default, pk in conn.execute(
            f"PRAGMA table_info({gpkg_common.quote_ident(table)})"):
        width = TEXT_WIDTH.match(declared or "")
        columns.append({
            "name": name,
            "type": declared,
            "width": int(width.group(1)) if width else None,
            "notNull": bool(notnull),
            "fileDefault": default,
            "primaryKey": bool(pk),
        })
    return columns


def read_tables(conn):
    rows = conn.execute(
        "SELECT c.table_name, g.column_name, g.geometry_type_name, g.srs_id, "
        "g.z, g.m FROM gpkg_contents c JOIN gpkg_geometry_columns g "
        "ON g.table_name = c.table_name WHERE c.data_type = 'features' "
        "ORDER BY c.rowid").fetchall()
    tables = [{
        "name": name,
        "stage": stage_of(name),
        "geometryColumn": column,
        "geometryType": kind,
        "srsId": srs,
        "hasZ": bool(z),
        "hasM": bool(m),
        "columns": read_columns(conn, name),
    } for name, column, kind, srs, z, m in rows]
    return sorted(tables, key=lambda table: table_order(table["name"]))


def read_coordinate_systems(conn, srs_ids):
    marks = ", ".join("?" for _ in srs_ids)
    return [{
        "srsId": srs_id,
        "name": name,
        "organization": organization,
        "organizationCoordsysId": coordsys,
    } for srs_id, name, organization, coordsys in conn.execute(
        "SELECT srs_id, srs_name, organization, organization_coordsys_id "
        f"FROM gpkg_spatial_ref_sys WHERE srs_id IN ({marks}) ORDER BY srs_id",
        sorted(srs_ids))]


def read_version_record(conn):
    rows = conn.execute(
        "SELECT m.id, m.md_scope, m.mime_type, m.metadata, "
        "r.reference_scope, r.table_name, r.column_name, r.row_id_value "
        "FROM gpkg_metadata m JOIN gpkg_metadata_reference r "
        "ON r.md_file_id = m.id WHERE m.md_standard_uri = ?",
        (gpkg_common.TEMPLATE_METADATA_URI,)).fetchall()
    if len(rows) != 1:
        raise SpecError(
            f"The template has {len(rows)} version records; it needs one. "
            "Run development/tools/set_template_version.py.")
    _id, scope, mime, metadata, ref_scope, ref_table, ref_column, ref_row = (
        rows[0])
    return {
        "metadataTable": "gpkg_metadata",
        "mdScope": scope,
        "mdStandardUri": gpkg_common.TEMPLATE_METADATA_URI,
        "mimeType": mime,
        "metadata": json.loads(metadata),
        "reference": {
            "table": "gpkg_metadata_reference",
            "referenceScope": ref_scope,
            "tableName": ref_table,
            "columnName": ref_column,
            "rowIdValue": ref_row,
        },
    }


def read_extensions(conn):
    return [{
        "table": table,
        "column": column,
        "extension": name,
        "scope": scope,
    } for table, column, name, scope in conn.execute(
        "SELECT table_name, column_name, extension_name, scope "
        "FROM gpkg_extensions ORDER BY extension_name, table_name")]


# ---------------------------------------------------------------------------
# The QGIS project
# ---------------------------------------------------------------------------

def read_project(path):
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".qgs")]
        if len(names) != 1:
            raise SpecError(f"{path.name} holds {len(names)} .qgs files")
        return ET.fromstring(archive.read(names[0]))


def gpkg_layer_table(datasource):
    """The GeoPackage table a layer reads, or None for another source."""
    marker = "|layername="
    if "Layers/" not in datasource or marker not in datasource:
        return None
    return datasource.split(marker, 1)[1].split("|", 1)[0]


def csv_list_path(datasource):
    """A CSV list's path under the template folder, from its layer source."""
    if not datasource.startswith("file:"):
        return None
    path = urllib.parse.unquote(datasource[len("file:"):].split("?", 1)[0])
    return path.removeprefix("./")


def options_of(widget):
    """The widget's options, by name, except the Value Map's list."""
    return {option.get("name"): option.get("value")
            for option in widget.iter("Option")
            if option.get("name") and option.get("type") != "List"}


def value_map_entries(widget):
    for entry in widget.iter("Option"):
        if entry.get("name") == "map" and entry.get("type") == "List":
            return [(item.get("name"), item.get("value"))
                    for option in entry for item in option]
    return []


def by_field(layer, path, attribute="field"):
    return {element.get(attribute): element
            for element in layer.findall(path)}


def read_layers(project):
    """Each GeoPackage table → its layer; each layer id → its CSV list."""
    tables, lists = {}, {}
    for layer in project.iter("maplayer"):
        source = layer.findtext("datasource") or ""
        table = gpkg_layer_table(source)
        if table:
            tables[table] = layer
        csv_path = csv_list_path(source)
        if csv_path:
            lists[layer.findtext("id")] = csv_path
    return tables, lists


# ---------------------------------------------------------------------------
# One column
# ---------------------------------------------------------------------------

def default_of(element):
    if element is None or not (element.get("expression") or "").strip():
        return None
    expression = element.get("expression").strip()
    literal = LITERAL_DEFAULT.match(expression)
    value = None
    if literal:
        value = (literal.group(1).replace("''", "'")
                 if literal.group(1) is not None else literal.group(2))
    return {
        "expression": expression,
        "value": value,
        "appliedOnUpdate": element.get("applyOnUpdate") == "1",
    }


def rule_of(constraint, expression):
    """A constraint expression the template holds the column to, or None."""
    if expression is None or not (expression.get("exp") or "").strip():
        return None
    strength = STRENGTH.get(constraint.get("exp_strength")) if (
        constraint is not None) else None
    return {
        "expression": expression.get("exp").strip(),
        "description": (expression.get("desc") or "").strip() or None,
        "strength": strength,
    }


def not_null_of(element):
    if element is None:
        return None
    if not int(element.get("constraints") or 0) & CONSTRAINT_NOT_NULL:
        return None
    return STRENGTH.get(element.get("notnull_strength"))


def value_map_drop_down(widget):
    entries = value_map_entries(widget)
    return {
        "kind": "fixed list",
        "blankOffered": any(value == VALUE_MAP_NULL for _, value in entries),
        "values": [{"stored": value, "shown": shown}
                   for shown, value in entries if value != VALUE_MAP_NULL],
    }


def value_relation_drop_down(widget, lists, where):
    options = options_of(widget)
    path = lists.get(options.get("Layer"))
    if path is None:
        raise SpecError(
            f"{where}: its drop-down reads layer {options.get('Layer')}, "
            "which is not a CSV list of the project")
    filter_expression = (options.get("FilterExpression") or "").strip()
    return {
        "kind": "list",
        "list": path,
        "storedColumn": options.get("Key"),
        "shownColumn": options.get("Value"),
        "filter": filter_expression or None,
        "dependsOn": sorted(set(CURRENT_VALUE.findall(filter_expression))),
        "blankOffered": options.get("AllowNull") == "true",
    }


def drop_down_of(widget, lists, where):
    kind = widget.get("type") if widget is not None else ""
    if kind == "ValueMap":
        return value_map_drop_down(widget)
    if kind == "ValueRelation":
        return value_relation_drop_down(widget, lists, where)
    return None


def describe_column(column, layer, lists, table):
    where = f"{table} / {column['name']}"
    settings = layer_settings(layer)
    field = settings["fields"].get(column["name"])
    widget = field.find("editWidget") if field is not None else None
    kind = widget.get("type") if widget is not None else ""
    if kind not in WIDGET_KINDS:
        raise SpecError(f"{where}: widget {kind!r} is not described")
    constraint = settings["constraints"].get(column["name"])
    not_null = not_null_of(constraint)
    alias = settings["aliases"].get(column["name"])
    editable = settings["editable"].get(column["name"])
    described = dict(column)
    described.update({
        "alias": (alias.get("name") or None) if alias is not None else None,
        "editable": editable is None or editable.get("editable") != "0",
        "widget": WIDGET_KINDS[kind],
        "notNullInTemplate": not_null,
        "mayBeBlank": not (column["notNull"] or not_null == "hard"),
        "default": default_of(settings["defaults"].get(column["name"])),
        "rule": rule_of(constraint,
                        settings["expressions"].get(column["name"])),
        "dropDown": drop_down_of(widget, lists, where),
        "lineage": column["name"] in LINEAGE_COLUMNS,
    })
    return described


_SETTINGS = {}


def layer_settings(layer):
    """The settings of a layer's fields, read once."""
    key = id(layer)
    if key not in _SETTINGS:
        _SETTINGS[key] = {
            "fields": by_field(layer, "fieldConfiguration/field", "name"),
            "aliases": by_field(layer, "aliases/alias"),
            "defaults": by_field(layer, "defaults/default"),
            "constraints": by_field(layer, "constraints/constraint"),
            "expressions": by_field(layer, "constraintExpressions/constraint"),
            "editable": by_field(layer, "editable/field", "name"),
        }
    return _SETTINGS[key]


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------

def read_csv(path, where):
    try:
        with open(TEMPLATE_DIR / path, newline="",
                  encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            rows = [row for row in reader if any(cell for cell in row)]
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        raise SpecError(f"{where}: cannot read its list {path}: {error}") \
            from error
    if not header:
        raise SpecError(f"{where}: its list {path} is empty")
    return header, rows


def check_list_columns(path, header, uses):
    """Every column a drop-down stores, shows or filters on is in its list."""
    for use in uses:
        needed = {use["storedColumn"], use["shownColumn"],
                  *QUOTED_FIELD.findall(use["filter"] or "")}
        missing = sorted(name for name in needed if name not in header)
        if missing:
            raise SpecError(
                f"{use['table']} / {use['column']}: its list {path} has no "
                f"column {', '.join(missing)}")


def list_columns(header, uses):
    """The columns of a list its drop-downs store, show or filter on."""
    wanted = set()
    for use in uses:
        wanted.update({use["storedColumn"], use["shownColumn"]})
        wanted.update(QUOTED_FIELD.findall(use["filter"] or ""))
    return [name for name in header if name in wanted]


def describe_list(path, uses):
    where = "; ".join(sorted({f"{use['table']} / {use['column']}"
                              for use in uses}))
    header, rows = read_csv(path, where)
    check_list_columns(path, header, uses)
    columns = list_columns(header, uses)
    indexes = [header.index(name) for name in columns]
    seen, kept = set(), []
    for row in rows:
        values = tuple(row[index] if index < len(row) else "" for index in
                       indexes)
        if values not in seen:
            seen.add(values)
            kept.append(list(values))
    stored = sorted({use["storedColumn"] for use in uses})
    return {
        "list": path,
        "columns": columns,
        "storedColumns": stored,
        "usedBy": sorted({f"{use['table']} / {use['column']}"
                          for use in uses}),
        "rows": kept,
    }


def collect_lists(tables):
    uses = {}
    for table in tables:
        for column in table["columns"]:
            drop_down = column["dropDown"]
            if drop_down and drop_down["kind"] == "list":
                uses.setdefault(drop_down["list"], []).append(
                    dict(drop_down, table=table["name"],
                         column=column["name"]))
    return [describe_list(path, uses[path]) for path in sorted(uses)]


def move_geometry_rules(table):
    """Report a rule about the row's shape against the geometry column."""
    geometry = next(column for column in table["columns"]
                    if column["name"] == table["geometryColumn"])
    for column in table["columns"]:
        rule = column["rule"]
        if column is geometry or not rule or (
                GEOMETRY_EXPRESSION not in rule["expression"]):
            continue
        if geometry["rule"]:
            raise SpecError(
                f"{table['name']}: more than one rule about the shape")
        geometry["rule"] = dict(rule, heldOn=column["name"])
        column["rule"] = None
        if rule["strength"] == "hard":
            geometry["mayBeBlank"] = False


def check_lineage(tables):
    for name, (stage, _) in LINEAGE_COLUMNS.items():
        for table in tables:
            has = any(column["name"] == name for column in table["columns"])
            expected = table["stage"] == stage
            if has != expected:
                raise SpecError(
                    f"{table['name']}: lineage column {name} is "
                    f"{'there' if has else 'missing'}; LINEAGE_COLUMNS "
                    f"puts it on the {stage} tables only")


# ---------------------------------------------------------------------------
# The specification
# ---------------------------------------------------------------------------

def build_spec(gpkg_path=GPKG_PATH, project_path=PROJECT_PATH):
    _SETTINGS.clear()
    conn = connect_read_only(gpkg_path)
    try:
        tables = read_tables(conn)
        coordinate_systems = read_coordinate_systems(
            conn, {table["srsId"] for table in tables})
        version_record = read_version_record(conn)
        extensions = read_extensions(conn)
    finally:
        conn.close()
    layers, lists = read_layers(read_project(project_path))
    for table in tables:
        layer = layers.get(table["name"])
        if layer is None:
            raise SpecError(
                f"{table['name']}: the project has no layer for it")
        table["columns"] = [describe_column(column, layer, lists,
                                            table["name"])
                            for column in table["columns"]]
        move_geometry_rules(table)
    check_lineage(tables)
    return {
        "format": version_record["metadata"].get("format"),
        "templateVersion": version_record["metadata"].get("version"),
        "versionRecord": version_record,
        "coordinateSystems": coordinate_systems,
        "tables": tables,
        "lineageColumns": [{"column": name, "stage": stage,
                            "description": description}
                           for name, (stage, description)
                           in LINEAGE_COLUMNS.items()],
        "lists": collect_lists(tables),
        "extensions": extensions,
    }


def render_json(spec):
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def cell(value):
    text = "—" if value in (None, "") else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def code(value):
    return f"`{value}`"


def table_md(header, rows):
    lines = [f"| {' | '.join(header)} |",
             f"| {' | '.join('---' for _ in header)} |"]
    lines += [f"| {' | '.join(cell(value) for value in row)} |"
              for row in rows]
    return lines


def width_text(column):
    if column["width"] is not None:
        return str(column["width"])
    if column["type"].upper() == "TEXT":
        return "no limit"
    return None


def default_text(column):
    default = column["default"]
    if default is None:
        return None
    if default["value"] is not None:
        return code(default["value"])
    return "Filled in by the template"


def drop_down_text(column):
    drop_down = column["dropDown"]
    if drop_down is None:
        return None
    if drop_down["kind"] == "fixed list":
        return ", ".join(code(value["stored"])
                         for value in drop_down["values"])
    text = (f"List {code(drop_down['list'])}, "
            f"column {code(drop_down['storedColumn'])}")
    if drop_down["dependsOn"]:
        text += "; depends on " + ", ".join(drop_down["dependsOn"])
    return text


def notes_text(column):
    notes = []
    if column["primaryKey"]:
        notes.append("Primary key")
    if column["lineage"]:
        notes.append("Lineage")
    if column["alias"]:
        notes.append(f"Shown as {column['alias']}")
    if not column["editable"]:
        notes.append("Locked in the template's form")
    if column["widget"] == "hidden":
        notes.append("Hidden in the form")
    return "; ".join(notes) or None


def rules_md(table):
    """The template's rules on the table's columns, as a list."""
    lines = []
    for column in table["columns"]:
        rule = column["rule"]
        if rule:
            strength = f" ({rule['strength']})" if rule["strength"] else ""
            what = rule["description"] or code(rule["expression"])
            lines.append(f"- {code(column['name'])}{strength}: {what}")
    if not lines:
        return []
    return ["Rules the template's form holds the columns to (hard: the row "
            "cannot be saved without it; soft: a warning):", "", *lines, ""]


def columns_md(table):
    rows = [[code(column["name"]), code(column["type"]), width_text(column),
             "yes" if column["mayBeBlank"] else "no", default_text(column),
             drop_down_text(column), notes_text(column)]
            for column in table["columns"]]
    return [f"### {table['name']}", "",
            f"Stage: {table['stage']}. "
            f"Geometry: {code(table['geometryColumn'])}, "
            f"{table['geometryType']}, SRS {table['srsId']}.", "",
            *table_md(["Column", "Type", "Width", "May be blank", "Default",
                       "Drop-down", "Notes"], rows), "",
            *rules_md(table)]


def list_md(described):
    stored = ", ".join(code(name) for name in described["storedColumns"])
    return [f"### {described['list']}", "",
            f"Stored column: {stored}. "
            f"Used by: {'; '.join(described['usedBy'])}.", "",
            *table_md([code(name) for name in described["columns"]],
                      described["rows"]), ""]


def version_md(record):
    reference = record["reference"]
    return [
        "## Version record", "",
        "A file says which format it follows, and which version, in one row "
        "of the GeoPackage metadata extension, referenced to the whole "
        "GeoPackage. The BNG service refuses a file with none, with more "
        "than one, or with a version it does not support.", "",
        *table_md(["Table", "Column", "Value"], [
            ["gpkg_metadata", "md_scope", code(record["mdScope"])],
            ["gpkg_metadata", "md_standard_uri",
             code(record["mdStandardUri"])],
            ["gpkg_metadata", "mime_type", code(record["mimeType"])],
            ["gpkg_metadata", "metadata",
             code(json.dumps(record["metadata"]))],
            ["gpkg_metadata_reference", "reference_scope",
             code(reference["referenceScope"])],
        ]), "",
    ]


def render_markdown(spec):
    lines = [
        "# BNG Service template: GeoPackage specification", "",
        "> Generated by `python3 development/tools/gpkg_spec.py` from the "
        f"template in [bng-metric-template]({REPO_URL}). Do not edit by hand: "
        "change the template and regenerate.", "",
        f"Format `{spec['format']}`, version `{spec['templateVersion']}`. A "
        "file in this format is a GeoPackage with the tables and columns "
        "below and the version record. The same content, for tools, is in "
        f"[`spec/{JSON_NAME}`]({JSON_URL}).",
        "",
        "The service checks more than the format: how it reads each column, "
        "and what it refuses, is in the [template field mapping]"
        f"({BACKEND_MAPPING_URL}).", "",
        *version_md(spec["versionRecord"]),
        "## Coordinate system", "",
        *table_md(["SRS id", "Name", "Organisation", "Code"], [
            [system["srsId"], system["name"], system["organization"],
             system["organizationCoordsysId"]]
            for system in spec["coordinateSystems"]]), "",
        "## Tables", "",
        *table_md(["Table", "Stage", "Geometry", "SRS"], [
            [table["name"], table["stage"], table["geometryType"],
             table["srsId"]] for table in spec["tables"]]), "",
        "## Lineage columns", "",
        "Each post-intervention row names the baseline feature it continues.",
        "",
        *table_md(["Column", "Tables", "What it holds"], [
            [code(entry["column"]), entry["stage"], entry["description"]]
            for entry in spec["lineageColumns"]]), "",
        "## Columns", "",
        "**May be blank**: no when the file or the template requires a "
        "value. **Default**: a fixed value, or one the template works out "
        "(its expression is in the JSON). **Drop-down**: the values a fixed "
        "list offers, or the list a value comes from; a list that depends "
        "on another column offers only the rows that match it (its filter "
        "is in the JSON).", "",
    ]
    for table in spec["tables"]:
        lines += columns_md(table)
    lines += ["## Drop-down lists", "",
              "The rows of each list, with the columns a drop-down stores, "
              "shows or filters on.", ""]
    for described in spec["lists"]:
        lines += list_md(described)
    lines += ["## Extensions", "",
              *table_md(["Extension", "Table", "Column", "Scope"], [
                  [entry["extension"], entry["table"], entry["column"],
                   entry["scope"]] for entry in spec["extensions"]])]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Writing and checking
# ---------------------------------------------------------------------------

def outputs(spec):
    return {JSON_NAME: render_json(spec), MARKDOWN_NAME: render_markdown(spec)}


def differences(expected, spec_dir=SPEC_DIR):
    """A unified diff for each output that is not what the template gives."""
    found = []
    for name, text in expected.items():
        path = spec_dir / name
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != text:
            found.append("".join(difflib.unified_diff(
                current.splitlines(keepends=True),
                text.splitlines(keepends=True),
                f"committed spec/{name}", f"generated spec/{name}")))
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="write nothing; exit 1 if the files differ")
    args = parser.parse_args(argv)
    try:
        expected = outputs(build_spec())
    except SpecError as error:
        print(f"Cannot describe the template: {error}", file=sys.stderr)
        return 1
    if args.check:
        found = differences(expected)
        if found:
            print("The specification is out of date. Run "
                  "python3 development/tools/gpkg_spec.py and commit spec/.",
                  file=sys.stderr)
            print("\n".join(found), file=sys.stderr)
            return 1
        print("The specification is up to date.")
        return 0
    SPEC_DIR.mkdir(exist_ok=True)
    for name, text in expected.items():
        (SPEC_DIR / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"Wrote spec/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
