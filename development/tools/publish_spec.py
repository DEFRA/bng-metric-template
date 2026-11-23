"""Publish spec/gpkg-spec.md to its Confluence Cloud page.

Run by .github/workflows/publish-spec.yml on a merge to main that changes the
Markdown, whose `paths` filter means an unchanged specification is never
republished. The page is updated by its ID: the current version is read,
then the converted page is written with the version number one higher. It
follows scripts/publish-confluence.mjs in bng-metric-backend, which publishes
the data dictionary, and reads the same settings:

    CONFLUENCE_BASE_URL    the wiki, e.g. https://example.atlassian.net/wiki
    CONFLUENCE_PAGE_ID     the numeric ID of the page to update
    CONFLUENCE_USER_EMAIL  the Atlassian account's email (the user name)
    CONFLUENCE_API_TOKEN   the Atlassian API token (the password)

To print the page it would write, without contacting Confluence:

    python3 development/tools/publish_spec.py --dry-run
"""
import argparse
import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from markdown_to_confluence import markdown_to_storage        # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MARKDOWN_PATH = REPO_ROOT / "spec" / "gpkg-spec.md"
REPO_URL = "https://github.com/DEFRA/bng-metric-template"
REQUIRED_ENV = ("CONFLUENCE_BASE_URL", "CONFLUENCE_PAGE_ID",
                "CONFLUENCE_USER_EMAIL", "CONFLUENCE_API_TOKEN")
TIMEOUT_S = 60

# A Confluence info panel: the page is published by a machine, and an edit
# made there is lost on the next publish.
GENERATED_BANNER = (
    '<ac:structured-macro ac:name="info"><ac:rich-text-body><p>'
    f'Generated from the template in <a href="{REPO_URL}">'
    "bng-metric-template</a> and republished when it changes on "
    "<code>main</code>. Do not edit here: an edit is overwritten. Change the "
    "template and regenerate the specification instead.</p>"
    "</ac:rich-text-body></ac:structured-macro>")


def storage_body(markdown):
    return f"{GENERATED_BANNER}\n{markdown_to_storage(markdown)}"


def request(url, headers, method="GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
        return json.load(response)


def publish(body, env):
    base = env["CONFLUENCE_BASE_URL"].rstrip("/")
    page_id = env["CONFLUENCE_PAGE_ID"]
    credentials = (f"{env['CONFLUENCE_USER_EMAIL']}:"
                   f"{env['CONFLUENCE_API_TOKEN']}").encode("utf-8")
    headers = {
        "Authorization": f"Basic {base64.b64encode(credentials).decode()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = f"{base}/rest/api/content/{page_id}"
    page = request(f"{url}?expand=version", headers)
    request(url, headers, method="PUT", body={
        "id": page_id,
        "type": "page",
        "title": page["title"],
        "version": {
            "number": page["version"]["number"] + 1,
            "message": "Updated from the bng-metric-template specification",
        },
        "body": {"storage": {"value": body, "representation": "storage"}},
    })


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="print the page instead of publishing it")
    args = parser.parse_args(argv)
    body = storage_body(MARKDOWN_PATH.read_text(encoding="utf-8"))
    if args.dry_run:
        sys.stdout.write(f"{body}\n")
        return 0
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        print(f"Missing environment variable(s): {', '.join(missing)}",
              file=sys.stderr)
        return 1
    publish(body, os.environ)
    print("Published the specification to Confluence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
