"""Build a variant of the BNG Service template, and check it is in step.

A variant is `templates/bng-service/` with a changed project: the same
GeoPackage, reference lists and user guide, byte for byte, and a project
whose XML a function changes. `build_ukhab_template.py` and
`build_labels_template.py` are variants. Each gives this module its target
folder, its project name and its change; this module copies the folder,
writes the project with fixed zip dates so a build gives the same bytes, and
compares a fresh build with the committed copy for `--check`.
"""
import argparse
import filecmp
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES = REPO_ROOT / "templates"
SOURCE_DIR = TEMPLATES / "bng-service"
SOURCE_PROJECT = "BNG Service Habitat Mapping.qgz"

# Files of the source folder that are never part of the template.
SKIP_RE = re.compile(r"\.backup-\d|^\.DS_Store$|^~\$")

# A zip entry is dated, so a fixed date makes the build give the same bytes.
ZIP_DATE = (2026, 1, 1, 0, 0, 0)


def fail(tool, message):
    print(f"{tool}: {message}", file=sys.stderr)
    sys.exit(1)


def read_qgz(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        qgs = next(n for n in names if n.endswith(".qgs"))
        return qgs, names, {n: archive.read(n) for n in names}


def write_qgz(path, names, payload):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        for name in names:
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            out.writestr(info, payload[name])


def layer_span(xml, name, tool="template_copy"):
    """Return (start, end) of the one <maplayer> named `name` in the project."""
    marker = f"<layername>{name}</layername>"
    if xml.count(marker) != 1:
        fail(tool, f"expected one layer named {name!r}, found {xml.count(marker)}")
    at = xml.index(marker)
    start = xml.rfind("<maplayer ", 0, at)
    end = xml.index("</maplayer>", at) + len("</maplayer>")
    return start, end


def set_layer_attribute(block, name, value):
    """Set an attribute on the opening <maplayer> tag of a layer block."""
    head_end = block.index(">") + 1
    head = block[:head_end]
    if f' {name}="' in head:
        head = re.sub(rf' {name}="[^"]*"', f' {name}="{value}"', head)
    else:
        head = head.replace("<maplayer ", f'<maplayer {name}="{value}" ', 1)
    return head + block[head_end:]


def set_title(xml, title):
    return xml.replace("  <title></title>", f"  <title>{title}</title>", 1)


def source_files():
    for path in sorted(SOURCE_DIR.rglob("*")):
        relative = path.relative_to(SOURCE_DIR)
        if path.is_file() and not any(SKIP_RE.search(p) for p in relative.parts):
            yield relative


def build(target, project_name, change):
    """Copy the template into `target`, with its project changed by
    `change(xml) -> xml` and saved as `project_name`."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for relative in source_files():
        if relative.name == SOURCE_PROJECT:
            continue
        (target / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE_DIR / relative, target / relative)
    qgs, names, payload = read_qgz(SOURCE_DIR / SOURCE_PROJECT)
    xml = change(payload[qgs].decode("utf-8"))
    ET.fromstring(xml.encode("utf-8"))      # the result must be well formed
    new_qgs = project_name.replace(".qgz", ".qgs")
    payload[new_qgs] = xml.encode("utf-8")
    names = [new_qgs if n == qgs else n for n in names]
    write_qgz(target / project_name, names, payload)


def differences(built, committed):
    def listing(root):
        return {p.relative_to(root) for p in root.rglob("*")
                if p.is_file()
                and not any(SKIP_RE.search(x) for x in p.relative_to(root).parts)}
    have = listing(committed) if committed.exists() else set()
    want = listing(built)
    changed = [str(p) for p in sorted(have & want)
               if not filecmp.cmp(built / p, committed / p, shallow=False)]
    return (changed, [str(p) for p in sorted(want - have)],
            [str(p) for p in sorted(have - want)])


def main(argv, doc, tool, target, project_name, change):
    """The command line of a variant: build it, or `--check` it."""
    parser = argparse.ArgumentParser(description=doc.split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="write nothing; exit 1 if the committed copy is "
                             "out of step")
    args = parser.parse_args(argv)
    if not args.check:
        build(target, project_name, change)
        print(f"built {target.relative_to(REPO_ROOT)}")
        return 0
    with tempfile.TemporaryDirectory() as scratch:
        built = Path(scratch) / target.name
        build(built, project_name, change)
        changed, missing, extra = differences(built, target)
    for label, paths in (("differs", changed), ("missing", missing),
                         ("not built", extra)):
        for path in paths:
            print(f"{label}: {path}")
    if changed or missing or extra:
        print(f"out of step: run python3 development/tools/{tool}")
        return 1
    print("no change needed")
    return 0
