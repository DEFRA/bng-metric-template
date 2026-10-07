#!/usr/bin/env python3
"""
Package the QGIS plugin into an installable .zip.

The code the plugin needs lives in the package folder beside this script. The
conversion modules in it are plain Python with no QGIS imports, which is why
they also run from a command line without the plugin being installed.

The zip also carries a copy of the drop-down lists the converter reads (see
reference_lists.py), taken from both templates in ../templates. Run from the
repository, the converter reads those lists in place, so the copy exists only
in the zip.

    python3 build_plugin.py            ->  dist/bng_template_convert.zip
"""

import os
import sys
import zipfile

PACKAGE = "bng_template_convert"
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(ROOT, PACKAGE))

import reference_lists  # noqa: E402

DIST_DIR = "dist"
DOCS = ("README.md",)
PLUGIN_FILES = (
    "__init__.py",
    "metadata.txt",
    "plugin.py",
    "provider.py",
    "algorithms.py",
    "icon.svg",
    "gpkg_common.py",
    "new_to_old.py",
    "old_to_new.py",
    "reference_lists.py",
    "to_metric.py",
)
TEMPLATES_DIR = os.path.join("..", "templates")


def bundled_lists(root):
    """(source path, path in the zip) for every drop-down list the plugin reads."""
    pairs = []
    for template, relative in reference_lists.reference_files():
        source = os.path.join(
            root, TEMPLATES_DIR, template, reference_lists.CSV_REFERENCES,
            relative)
        if not os.path.exists(source):
            raise SystemExit(f"missing drop-down list: {source}")
        target = os.path.join(
            PACKAGE, reference_lists.BUNDLED_DIR, template, relative)
        pairs.append((source, target))
    return pairs


def build(root):
    package_dir = os.path.join(root, PACKAGE)
    dist = os.path.join(root, DIST_DIR)
    os.makedirs(dist, exist_ok=True)
    archive = os.path.join(dist, f"{PACKAGE}.zip")
    if os.path.exists(archive):
        os.remove(archive)

    lists = bundled_lists(root)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in PLUGIN_FILES:
            source = os.path.join(package_dir, name)
            if not os.path.exists(source):
                raise SystemExit(f"missing plugin file: {source}")
            bundle.write(source, os.path.join(PACKAGE, name))
        for source, target in lists:
            bundle.write(source, target)
        # The instructions travel with the plugin, so a copy passed on by
        # itself still says what it needs and how to install it.
        for name in DOCS:
            source = os.path.join(root, name)
            if os.path.exists(source):
                bundle.write(source, os.path.join(PACKAGE, name))

    size_kb = os.path.getsize(archive) / 1024
    print(f"built {archive} ({size_kb:.0f} KB, {len(lists)} drop-down lists)")
    print(
        "install in QGIS: Plugins > Manage and Install Plugins… > Install from ZIP"
    )
    return archive


if __name__ == "__main__":
    sys.exit(0 if build(ROOT) else 1)
