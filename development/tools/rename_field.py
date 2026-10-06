"""Rename a field everywhere a project names it.

A field's name is in its widget, alias, policy, default, constraint, table
column and form settings, in the expressions that read it and in the button
code. This replaces the name wherever it stands as a whole, quoted name:

- `name="<old>"` and `field="<old>"` in the field's settings;
- `&quot;<old>&quot;` in expressions and button code, as QGIS escapes it;
- `"<old>"` in element text, such as a layer's display expression.

A name that is only part of other text, such as `All PI Refs` in a message,
is not a quoted name, so it is left alone. The tool lists every place that
still holds the old name after the rename.

    python3 development/tools/rename_field.py <project.qgz> <old> <new>

Rename the column in the GeoPackage as well. Edits the text in place and
leaves every other byte alone, for the same reasons as qgz_actions.py. Running
it twice changes nothing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qgz_actions import escape, read_project, write_project     # noqa: E402

QUOTED_FORMS = ('name="{}"', 'field="{}"', "&quot;{}&quot;", '>"{}"<')


def rename(xml, old, new):
    """Return (xml, count of replacements)."""
    count = 0
    for form in QUOTED_FORMS:
        before, after = form.format(escape(old)), form.format(escape(new))
        count += xml.count(before)
        xml = xml.replace(before, after)
    return xml, count


def main(argv):
    if len(argv) != 3:
        print("usage: rename_field.py <project.qgz> <old> <new>",
              file=sys.stderr)
        return 2
    project, old, new = argv
    qgs, payload = read_project(project)
    xml = payload[qgs].decode("utf-8")
    new_xml, count = rename(xml, old, new)
    left = new_xml.count(escape(old))
    if left:
        print(f"{left} other place(s) still hold {old!r}, not as a quoted "
              "name. Check them by hand")
    if new_xml == xml:
        print(f"no change needed: {project}")
        return 0
    backup = write_project(project, qgs, payload, new_xml)
    print(f"renamed {old!r} to {new!r} in {count} place(s) in {project} "
          f"(backup: {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
