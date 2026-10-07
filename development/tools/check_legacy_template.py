"""Re-check the faults this project claims the legacy Natural England template has.

Run it against a fresh download to confirm nothing here is stale:

    python3 development/tools/check_legacy_template.py

Reads only. Every finding prints the evidence it was drawn from, so a reader
can follow it back into the file rather than take the verdict on trust.
"""

import csv
import glob
import os
import pathlib
import re
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

HERE = pathlib.Path(__file__).resolve().parent.parent.parent
PROJECT = HERE / "templates/legacy-ne/Net Gain Habitat Mapping.qgz"
LEGACY_CSV = HERE / "templates/legacy-ne/CSV References/Habitats"
SERVICE_CSV = HERE / "templates/bng-service/CSV References/Habitats"
METRIC = HERE / "reference/The_Statutory_Metric_Macro_Enabled_1.0.4.xlsm"

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

# The ellipsoid the project measures on. Airy 1830 is the one the British
# National Grid is built on, and it is not what the service measures against.
AIRY_1830 = "EPSG:7001"


def load_project():
    """The project XML out of the zipped .qgz."""
    tmp = tempfile.mkdtemp(prefix="legacy-ne-")
    with zipfile.ZipFile(PROJECT) as archive:
        archive.extractall(tmp)
    return ET.parse(glob.glob(os.path.join(tmp, "*.qgs"))[0]).getroot()


def value_relations(root):
    """Every dropdown backed by a lookup layer, with whether that layer exists."""
    present = {layer.findtext("id") for layer in root.iter("maplayer")}
    found = []
    for layer in root.iter("maplayer"):
        config = layer.find("fieldConfiguration")
        if config is None:
            continue
        for field in config.findall("field"):
            widget = field.find("editWidget")
            if widget is None or widget.get("type") != "ValueRelation":
                continue
            options = {
                option.get("name"): option.get("value")
                for option in widget.iter("Option")
                if option.get("name")
            }
            found.append({
                "layer": layer.findtext("layername"),
                "field": field.get("name"),
                "works": options.get("Layer") in present,
                "source": options.get("LayerSource", ""),
            })
    return found


def check_dropdowns(root):
    """Count dropdowns whose stored layer id is stale.

    A STALE ID IS NOT A BROKEN DROPDOWN, and reading it as one is a mistake
    this project already made once. When the id misses, QGIS looks for a
    lookup layer of the same name, finds the copy the template ships, and
    fills the list correctly. Deciding whether a dropdown actually works
    means asking QGIS, which needs the QGIS Python bindings rather than the
    project XML alone. See the note this prints.
    """
    rows = value_relations(root)
    stale = [row for row in rows if not row["works"]]
    print(f"1. Dropdowns backed by a lookup layer : {len(rows)}")
    print(f"   Carrying a stale layer id          : {len(stale)}")
    for name in sorted({r["layer"] for r in rows if "EDIT ME" in r["layer"]}):
        here = [r for r in rows if r["layer"] == name]
        bad = [r for r in here if not r["works"]]
        state = ", ".join(r["field"] for r in bad) if bad else "all ids current"
        print(f"     {name:42} {len(bad)}/{len(here)}  {state}")
    print("   Stale means the id no longer matches; QGIS recovers these by")
    print("   layer name, so the lists still populate. Confirm in QGIS by")
    print("   editing a feature and opening the field.")
    return bool(stale)


def check_dead_sources(root):
    """The addresses the stale links remember. Inert, but they are provenance."""
    folders = set()
    for row in value_relations(root):
        if row["works"] or not row["source"]:
            continue
        path = urllib.parse.unquote(row["source"].split("?")[0])
        folders.add(re.sub(r"/[^/]+$", "", path))
    print(f"\n2. Distinct folders the stale links remember : {len(folders)}")
    for folder in sorted(folders):
        print(f"     {folder}")
    return bool(folders)


def workbook_bands():
    """Habitat -> distinctiveness, straight off the metric's own G-1 sheet."""
    with zipfile.ZipFile(METRIC) as archive:
        shared = [
            "".join(t.text or "" for t in si.iter(NS + "t"))
            for si in ET.fromstring(archive.read("xl/sharedStrings.xml"))
        ]
        rels = {
            rel.get("Id"): rel.get("Target")
            for rel in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        targets = {
            sheet.get("name"): rels[sheet.get(REL + "id")]
            for sheet in book.iter(NS + "sheet")
        }
        part = "xl/" + targets["G-1 All Habitats"].replace("xl/", "").lstrip("/")
        sheet = ET.fromstring(archive.read(part))

    def value(cell):
        node = cell.find(NS + "v")
        if node is None:
            return ""
        return shared[int(node.text)] if cell.get("t") == "s" else node.text

    bands = {}
    for row in sheet.iter(NS + "row"):
        cells = {
            re.match(r"[A-Z]+", c.get("r")).group(0): value(c)
            for c in row.findall(NS + "c")
        }
        if cells.get("A") and cells.get("K"):
            bands[cells["A"]] = cells["K"]
    return bands


def check_bands():
    bands = workbook_bands()
    print("\n3. Distinctiveness shown, against the Statutory Metric's own table")
    disagreed = False
    for label, folder in (("legacy NE", LEGACY_CSV), ("service", SERVICE_CSV)):
        path = folder / "Habitat Distinctiveness- pre.csv"
        rows = list(csv.reader(path.open(encoding="utf-8-sig")))
        bad = [
            (r[0].strip(), r[1].strip(), bands[r[0].strip()])
            for r in rows[1:]
            if len(r) > 1
            and r[0].strip() in bands
            # A band differing only in capitalisation is the workbook's own
            # inconsistency, not the template's, so it is not a finding.
            and r[1].strip().lower() != bands[r[0].strip()].lower()
        ]
        disagreed = disagreed or bool(bad)
        print(f"     {label:10} {len(bad)} disagree")
        for habitat, shown, wanted in bad:
            print(f"        {habitat[:50]:52} shows {shown:7} workbook {wanted}")
    return disagreed


def check_recalculating_columns(root):
    print("\n4. Columns that rewrite themselves whenever a shape is edited")
    seen = set()
    for layer in root.iter("maplayer"):
        if "EDIT ME" not in (layer.findtext("layername") or ""):
            continue
        defaults = layer.find("defaults")
        if defaults is None:
            continue
        for default in defaults.findall("default"):
            if default.get("applyOnUpdate") == "1":
                seen.add((default.get("field"), default.get("expression")))
    for field, expression in sorted(seen):
        print(f"     {field:8} = {expression}")
    return bool(seen)


def check_constraints(root):
    constrained = set()
    for layer in root.iter("maplayer"):
        if "EDIT ME" not in (layer.findtext("layername") or ""):
            continue
        block = layer.find("constraints")
        if block is None:
            continue
        for rule in block.findall("constraint"):
            if rule.get("constraints") not in (None, "0"):
                constrained.add(rule.get("field"))
    print("\n5. Fields the file constrains, across every editable layer")
    print(f"     {sorted(constrained)}")
    # 'fid' is the hidden row number. Nothing a surveyor types is constrained.
    return constrained == {"fid"}


def check_ellipsoid(root):
    found = None
    for node in root.iter("Measure"):
        found = node.findtext("Ellipsoid")
    print(f"\n6. Ellipsoid the project measures on : {found}")
    return found == AIRY_1830


def main():
    for path in (PROJECT, METRIC):
        if not path.exists():
            print(f"missing: {path}")
            return 1
    root = load_project()
    results = [
        check_dropdowns(root),
        check_dead_sources(root),
        check_bands(),
        check_recalculating_columns(root),
        check_constraints(root),
        check_ellipsoid(root),
    ]
    print(f"\n{sum(results)} of {len(results)} findings still present.")
    print("Finding 1 is a fragility, not a fault. See its note above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
