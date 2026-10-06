# bng-metric-template

The **BNG Service QGIS habitat mapping template**, and the tools around it. A
surveyor maps a site's baseline and post-intervention habitats in the
template, then uploads the single GeoPackage it produces to the Biodiversity
Net Gain (BNG) service.

The repo also holds:

- **BNG Template Convert**, a QGIS plugin that converts sites between this
  template, the Natural England template and the Statutory Biodiversity Metric
  workbook
- **two site generators**, one at the scale of a Nationally Significant
  Infrastructure Project (NSIP) and one for small sites
- **the reference material** that every drop-down list is checked against
- **the maintenance tools** that keep the template's project file in step

The conversion code and the generators use only the Python standard library.
Only the plugin needs QGIS.

## What is where

| Folder | What it holds | Who it is for |
| --- | --- | --- |
| `templates/bng-service/` | **The template.** An empty QGIS project, its GeoPackage, its reference lists, and `HOW TO USE THIS TEMPLATE.md`, the step-by-step guide | Surveyors |
| `templates/legacy-ne/` | The Natural England template, as Natural England publishes it | Comparison and conversion |
| `plugin/` | **The plugin.** Source, `build_plugin.py`, and `README.md`, the guide to install and use it | Surveyors and maintainers |
| `reference/` | The Statutory Metric workbooks, the Excel GIS import tool and the published guidance | Maintainers |
| `scale-test-nsip/` | The NSIP-scale test site: generator, claim checks, `README.md` and `VERIFICATION.md`, the runbook | Maintainers and testers |
| `site-generator/` | Builds small synthetic sites (1 to 50 parcels) from inputs such as the area and the location | Testers |
| `development/tools/` | The tools that maintain the template's project file. Nothing here is needed to use the template | Maintainers |

**[`MAINTAINERS.md`](MAINTAINERS.md) is the guide for maintainers.** Read it
before changing the template, the plugin or the generators.

## Using the template

1. Copy the whole `templates/bng-service/` folder. The data lives in the
   GeoPackage and the reference lists are found by relative path, so the
   project needs the folder around it.
2. Open `BNG Service Habitat Mapping.qgz` in QGIS. It was built in QGIS 3.42.
3. Follow `HOW TO USE THIS TEMPLATE.md` in the same folder.

Keep `templates/bng-service/` itself unchanged. Work in copies.

## Building the plugin

```sh
cd plugin && python3 build_plugin.py   # -> plugin/dist/bng_template_convert.zip
```

In QGIS, select **Plugins** > **Manage and Install Plugins...** > **Install
from ZIP**. `plugin/README.md` explains each tool.

**A change to a reference list needs a new plugin build.** The build copies
the drop-down lists the converter reads into the zip, and fails if one is
missing.

## Generating test sites

The generated sites are not committed. Each one is rebuilt from the template,
to the same bytes, in a few seconds:

```sh
python3 scale-test-nsip/generator/generate.py      # NSIP-scale rail corridor, about 100 MB
python3 site-generator/generate_site.py --habitats 10 --area-ha 3 --centre 451000,206000
```

## Rules for changing the template

- **Never save the template from QGIS.** The template's Action buttons are
  Python stored in the project XML, and a save from QGIS loses parts of them.
  Change the project only with the tools in `development/tools/`.
- **Check the generated settings after any change.** `MAINTAINERS.md` lists
  the `--check` commands. Then generate the NSIP site again: its run checks
  every value against the drop-down lists.
- **Rebuild and redistribute the plugin** after a change to a reference list.

## Working with the BNG service

This repo is a sibling of the BNG service repos. The
[bng-metric-harness](https://github.com/DEFRA/bng-metric-harness) links to it
as `template`, beside the frontend and backend. The verification scripts in
`scale-test-nsip/verify/` load the service's own validation from a backend
checkout beside this repo (`../bng-metric-backend`), or from the folder that
`BACKEND_DIR` names.

The harness also holds Defra's Statutory Biodiversity Metric User Guide in
Markdown (`reference/metric-user-guide/`), and the `/metric-guidance` Claude
Code skill that answers questions from it.
