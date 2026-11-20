# BNG Template Convert: a QGIS plugin

The plugin has three tools for a site drawn in the **BNG Service habitat
mapping template**:

- **Export to the Statutory Metric (Excel)** fills a copy of the Statutory
  Biodiversity Metric workbook from the GeoPackage.
- **Convert from legacy template (into the BNG Service template)** joins a
  Natural England baseline and post-intervention GeoPackage into one BNG
  Service GeoPackage.
- **Convert to legacy template (for the older service)** splits a BNG Service
  GeoPackage into the Natural England files, and can write the CSV files of
  the Excel GIS import tool.

The tools run inside QGIS, with no internet connection.

**How to use the tools is in the user guide,**
`BNG Service template - User Guide.docx`, which ships in the template folder
(`templates/bng-service/` in this repository). Section 3 covers the export to
the metric, and section 4 the two conversions.

---

## Install the plugin

1. Open QGIS 3.22 or later.
2. Select **Plugins** → **Manage and Install Plugins...** → **Install from
   ZIP**.
3. Select **`bng_template_convert.zip`**, then **Install Plugin**. Accept the
   warning about an untrusted source.

The **Plugins** menu and the **Processing Toolbox** (`Ctrl+Alt+T`) then show
**BNG Template Convert** with three tools. To upgrade, install the new zip. If
the menu does not change, uninstall the plugin, install it again and restart
QGIS.

---

## Command line

The plugin uses only the Python standard library. The conversion scripts also
run without QGIS:

```
python3 new_to_old.py INPUT.gpkg -o OUT_DIR [--format gpkg|csv|both] [--consolidate] [--carry-lineage]
python3 old_to_new.py --baseline BASE.gpkg [--post-intervention PI.gpkg] -o OUT_DIR [--into TEMPLATE.gpkg]
python3 to_metric.py  INPUT.gpkg --metric METRIC.xlsm|.xlsx -o OUT [--consolidate]
```

Add `--dry-run` to `new_to_old.py` or `old_to_new.py` to see the report and
write nothing.

The two conversion scripts read the drop-down lists of both templates, and
`old_to_new.py` also reads the BNG Service distinctiveness, condition and
irreplaceable lists. Run from the repository, they read them from
`templates/`. The plugin zip carries a copy of each list, which
`build_plugin.py` adds.
