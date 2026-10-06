"""Check that a filled metric workbook's conditions can actually be scored.

The metric scores a habitat row by finding its condition in a header row and
its habitat in a column, then reading the cell where they meet. A condition
the header does not carry scores nothing, the row reports "Check Data" and the
site's units come out as zero, with no error anywhere to say why.

This reads the values a filled workbook holds and answers the only question
that matters: would the workbook's own lookup find them.

    python3 development/tools/check_metric_lookups.py "Filled metric.xlsm"
"""
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# sheet, the column holding the condition, the lookup sheet and the row its
# condition headers sit on, and the first data row of each.
CHECKS = (
    ("A-1 On-Site Habitat Baseline", "K", 11, "G-8 Condition Look up", 3),
    ("A-2 On-Site Habitat Creation", "J", 11, "G-8 Condition Look up", 3),
    ("A-3 On-Site Habitat Enhancement", "Y", 12, "G-8 Condition Look up", 3),
    ("B-1 On-Site Hedge Baseline", "H", 10, "G-1 All Habitats", None),
    ("C-1 On-Site WaterC' Baseline", "H", 10, "G-7 WaterC' Data", 3),
    ("C-3 On-Site WaterC' Enhancement", "T", 12, "G-7 WaterC' Data", 3),
)

# B-1 reads its condition from a two-column list rather than a header row.
HEDGE_CONDITIONS = ("Good", "Moderate", "Poor", "N/A - Other",
                    "Condition Assessment N/A")


def strings(archive):
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(f"{NS}t"))
            for si in root.findall(f"{NS}si")]


def sheet_paths(archive):
    book = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels}
    rid = ("{http://schemas.openxmlformats.org/officeDocument/2006/"
           "relationships}id")
    out = {}
    for sheet in book.iter(f"{NS}sheet"):
        path = target[sheet.get(rid)]
        out[sheet.get("name")] = "xl/" + path.removeprefix("/xl/").lstrip("/")
    return out


def cells(archive, path, shared):
    """Every non-empty cell on a sheet, as {"K11": "Fairly Poor"}."""
    root = ET.fromstring(archive.read(path))
    found = {}
    for cell in root.iter(f"{NS}c"):
        kind = cell.get("t")
        if kind == "inlineStr":
            node = cell.find(f"{NS}is")
            value = "".join(t.text or "" for t in node.iter(f"{NS}t")) if node is not None else ""
        else:
            node = cell.find(f"{NS}v")
            value = node.text if node is not None else None
            if kind == "s" and value is not None:
                value = shared[int(value)]
        if value not in (None, ""):
            found[cell.get("r")] = value.strip() if isinstance(value, str) else value
    return found


def header_values(archive, paths, sheet, row, shared):
    if sheet not in paths:
        return set()
    found = cells(archive, paths[sheet], shared)
    return {v for ref, v in found.items()
            if re.fullmatch(rf"[A-Z]+{row}", ref) and isinstance(v, str)}


def main(path):
    archive = zipfile.ZipFile(path)
    shared = strings(archive)
    paths = sheet_paths(archive)
    failures = 0

    for sheet, column, first_row, lookup, header_row in CHECKS:
        if sheet not in paths:
            continue
        found = cells(archive, paths[sheet], shared)
        written = [(ref, value) for ref, value in found.items()
                   if re.fullmatch(rf"{column}\d+", ref)
                   and int(ref[len(column):]) >= first_row]
        if not written:
            print(f"{sheet:36s} no conditions written")
            continue
        allowed = (set(HEDGE_CONDITIONS) if header_row is None
                   else header_values(archive, paths, lookup, header_row, shared))
        bad = sorted({v for _ref, v in written if v not in allowed})
        status = "OK  " if not bad else "FAIL"
        if bad:
            failures += 1
        print(f"{status} {sheet:36s} {len(written):5d} rows, "
              f"{len(set(v for _r, v in written)):2d} distinct")
        for value in sorted({v for _r, v in written}):
            mark = "  no match in " + lookup if value in bad else ""
            print(f"       {value!r}{mark}")

    print()
    print("conditions the workbook can score" if not failures
          else f"{failures} sheet(s) carry conditions the workbook cannot score")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
