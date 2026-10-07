"""Make text edits to the template's buttons, by raw XML edit.

Each button is stored once per layer, and the copies come from one template:
they differ only in the layer names and a few lines. An edit is therefore
written once, as an exact piece of old text and its replacement, and made in
every button with that name.

    python3 development/tools/patch_actions.py <project.qgz> <edits.py>

<edits.py> is Python that defines EDITS, a list of (button name, old text,
new text) tuples, made in list order. Each old text must occur exactly once
in each body of that button. An edit whose new text is already in place
counts as made, so running the same edits twice changes nothing. Any other
mismatch stops the run before anything is written.

Leaves every byte outside the edited text alone, for the same reasons as
qgz_actions.py.
"""
import os
import runpy
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qgz_actions import read_project, replace_bodies, write_project     # noqa: E402

PREVIEW_CHARS = 60
USAGE = "usage: patch_actions.py <project.qgz> <edits.py>"


def already_made(body, old, new):
    """True when the edit is in place: the new text once, the old text gone.

    New text that contains the old text, as an insertion beside an anchor
    does, leaves the old text in place as many times as the new text holds it.
    """
    if not new:
        return old not in body
    return body.count(new) == 1 and body.count(old) == new.count(old)


def preview(text):
    first = text.strip().splitlines()[0] if text.strip() else "(empty)"
    return first[:PREVIEW_CHARS]


class Edit:
    """One edit, made in each body of a button, counting what happened."""

    def __init__(self, number, action, old, new):
        self.number, self.action, self.old, self.new = number, action, old, new
        self.made = 0
        self.skipped = 0
        self.errors = []

    def __call__(self, body):
        if already_made(body, self.old, self.new):
            self.skipped += 1
            return body
        found = body.count(self.old)
        if found != 1:
            self.errors.append(
                f"edit {self.number} ({preview(self.old)!r}): old text found "
                f"{found} time(s) in a {self.action!r} body")
            return body
        self.made += 1
        return body.replace(self.old, self.new, 1)


def apply_edits(xml, edits):
    """Return (xml, report lines, errors). The xml is only usable if no errors."""
    report, errors = [], []
    for number, (action, old, new) in enumerate(edits, start=1):
        edit = Edit(number, action, old, new)
        xml, count = replace_bodies(xml, action, edit)
        errors += edit.errors
        if not count:
            errors.append(f"edit {number}: no button named {action!r}")
        report.append(f"edit {number} on {action!r}: made in {edit.made}, "
                      f"already made in {edit.skipped}")
    return xml, report, errors


def main(argv):
    if len(argv) != 2:
        print(USAGE, file=sys.stderr)
        return 2
    project, edits_path = argv
    edits = runpy.run_path(edits_path)["EDITS"]
    qgs, payload = read_project(project)
    xml = payload[qgs].decode("utf-8")
    new_xml, report, errors = apply_edits(xml, edits)
    print("\n".join(report))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print("nothing written", file=sys.stderr)
        return 1
    if new_xml == xml:
        print(f"no change needed: {project}")
        return 0
    backup = write_project(project, qgs, payload, new_xml)
    print(f"edited {project} (backup: {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
