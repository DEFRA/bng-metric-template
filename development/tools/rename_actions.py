"""Drop the list numbers from the template's buttons, and fix their order.

The buttons were named "1. Copy baseline to post-intervention" and so on. The
numbers were doing two jobs. They told a reader which to press first, and they
stood in for an order the menu does not actually have: QGIS lists buttons in
the order the project stores them, which on a post-intervention layer was 2, 4,
1. So the numbers promised a sequence and then contradicted it.

Taking the numbers out therefore means putting the stored order right, or the
menu offers the last step first. This does both, and running it twice changes
nothing.

    python3 development/tools/rename_actions.py <project.qgz> [<project.qgz> ...]
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qgz_actions import read_project, write_project     # noqa: E402

NUMBER = re.compile(r'^\s*\d+\.\s*')

# The order a user needs them in: copy the baseline across, tidy the references
# that copying and splitting produced, then bring later baseline edits over.
# Rename sits alone on the baseline layers.
ORDER = (
    "Copy baseline to post-intervention",
    "Tidy PI refs after splitting",
    "Refresh from baseline",
    "Rename a ref (updates post-intervention)",
)

BLOCK = re.compile(r"<attributeactions\b[^>]*>.*?</attributeactions>", re.S)
ELEMENT = re.compile(
    r"[ \t]*<actionsetting\b(?:[^>]*?/>|.*?</actionsetting>)\n?", re.S)
NAME_ATTR = re.compile(r'(\b(?:name|shortTitle)=")([^"]*)(")')


def plain_name(element):
    match = re.search(r'\bname="([^"]*)"', element)
    return NUMBER.sub("", match.group(1)) if match else ""


def renumber(element):
    """Strip the list number from the element's name and shortTitle."""
    return NAME_ATTR.sub(
        lambda m: m.group(1) + NUMBER.sub("", m.group(2)) + m.group(3), element)


def rewrite_block(block):
    elements = ELEMENT.findall(block)
    if not elements:
        return block, 0
    renamed = [renumber(element) for element in elements]
    rank = {name: index for index, name in enumerate(ORDER)}
    # An unknown button keeps its place at the end rather than disappearing.
    renamed.sort(key=lambda e: rank.get(plain_name(e), len(ORDER)))

    remainder = ELEMENT.sub("", block)
    closing = remainder.rindex("</attributeactions>")
    return remainder[:closing] + "".join(renamed) + remainder[closing:], len(renamed)


def main(paths):
    for path in paths:
        qgs, payload = read_project(path)
        xml = payload[qgs].decode("utf-8")

        total = 0

        def replace(match):
            nonlocal total
            block, count = rewrite_block(match.group(0))
            total += count
            return block

        new_xml = BLOCK.sub(replace, xml)
        if new_xml == xml:
            print(f"no change needed: {path}")
            continue
        write_project(path, qgs, payload, new_xml)
        print(f"renamed and reordered {total} button(s) in {path}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
