"""Draw Enhanced trees on the Individual Trees Post-Intervention layer.

The tree style comes from the Natural England template, whose list offers no
`Enhanced`, so it has rules for `Created` and `Retained` only. An Enhanced
tree matched no rule and was not drawn. This adds one `Enhanced` rule for
each `Retained` rule: the same shape and size for the tree's size and its
Urban or Rural setting, in the purple Natural England gives `Enhanced` in its
tree retention view. The yellow of `Retained` becomes that purple, and the
dark yellow outline a dark purple.

    python3 development/tools/style_enhanced_trees.py [--check] <project.qgz>

Safe to run again. It changes only the renderer of that one layer, as text,
so every other byte of the project stays as it is.
"""
import argparse
import re
import sys
import uuid

import qgz_actions

LAYER = "Individual Trees Post-Intervention"
RETAINED, ENHANCED = "Retained", "Enhanced"
# Retained yellow and its outline -> Natural England's Enhanced purple, and a
# darker purple for the outline.
COLOURS = {(251, 243, 83): (92, 1, 115), (178, 172, 58): (61, 1, 77)}
# Keys and ids made from a fixed namespace, so a run gives the same bytes.
NAMESPACE = uuid.UUID("6f1c1d7e-2b8a-4d5e-9c71-3a0e5b1f4c21")
RULE_RE = re.compile(r"[ \t]*<rule\b[^>]*/>\n?")
NO_CHANGE = "no change needed"


def colour(rgb, alpha, with_rgb_part):
    """A colour as QGIS writes it, with the fractions part when it has one."""
    text = ",".join(str(v) for v in (*rgb, alpha))
    if not with_rgb_part:
        return text
    fractions = ",".join(f"{v / 255:.17g}" for v in rgb)
    return f"{text},rgb:{fractions},{alpha / 255:.17g}"


def recolour(symbol):
    def swap(match):
        rgb = tuple(int(v) for v in match.group(1, 2, 3))
        if rgb not in COLOURS:
            return match.group(0)
        return colour(COLOURS[rgb], int(match.group(4)),
                      match.group(5) is not None)
    return re.sub(r"\b(\d+),(\d+),(\d+),(\d+)(,rgb:[^\"]*)?", swap, symbol)


def new_id(*parts):
    return "{" + str(uuid.uuid5(NAMESPACE, "/".join(parts))) + "}"


def renderer_span(xml):
    marker = f"<layername>{LAYER}</layername>"
    if xml.count(marker) != 1:
        raise SystemExit(f"expected one layer named {LAYER!r}")
    at = xml.index(marker)
    start = xml.index("<renderer-v2", at)
    end = xml.index("</renderer-v2>", start)
    if end > xml.index("</maplayer>", at):
        raise SystemExit(f"no renderer in layer {LAYER!r}")
    return start, end


def symbol_block(renderer, name):
    match = re.search(
        rf'[ \t]*<symbol\b[^>]*\bname="{re.escape(name)}"[^>]*>.*?</symbol>\n?',
        renderer, re.DOTALL)
    if match is None:
        raise SystemExit(f"no symbol named {name!r} in layer {LAYER!r}")
    return match.group(0)


def add_enhanced_rules(xml):
    """Return the project XML with the Enhanced rules, and whether it changed."""
    start, end = renderer_span(xml)
    renderer = xml[start:end]
    rules = [m for m in RULE_RE.finditer(renderer)]
    if any(f"'{ENHANCED}'" in m.group(0) for m in rules):
        return xml, False
    retained = [m for m in rules if f"'{RETAINED}'" in m.group(0)]
    if not retained:
        raise SystemExit(f"no {RETAINED} rule in layer {LAYER!r}")
    names = [int(n) for n in re.findall(r'<symbol\b[^>]*\bname="(\d+)"', renderer)]
    next_name = max(names) + 1
    new_rules, new_symbols = [], []
    for match in retained:
        rule = match.group(0)
        old = re.search(r'\bsymbol="([^"]*)"', rule).group(1)
        name = str(next_name)
        next_name += 1
        rule = re.sub(r'\bsymbol="[^"]*"', f'symbol="{name}"', rule)
        rule = rule.replace(f"'{RETAINED}'", f"'{ENHANCED}'")
        rule = re.sub(r'\blabel="Retained', 'label="Enhanced', rule)
        rule = re.sub(r'\bkey="[^"]*"', f'key="{new_id("rule", name)}"', rule)
        new_rules.append(rule if rule.endswith("\n") else rule + "\n")
        symbol = symbol_block(renderer, old)
        symbol = re.sub(r'\bname="[^"]*"', f'name="{name}"', symbol, count=1)
        count = iter(range(1000))
        symbol = re.sub(r'\bid="\{[^"]*\}"',
                        lambda _m: f'id="{new_id("layer", name, str(next(count)))}"',
                        symbol)
        new_symbols.append(recolour(symbol))
    after_rules = retained[-1].end()
    renderer = (renderer[:after_rules] + "".join(new_rules)
                + renderer[after_rules:])
    close = renderer.rindex("</symbols>")
    line_start = renderer.rindex("\n", 0, close) + 1
    renderer = (renderer[:line_start] + "".join(
        s if s.endswith("\n") else s + "\n" for s in new_symbols)
        + renderer[line_start:])
    return xml[:start] + renderer + xml[end:], True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("project")
    parser.add_argument("--check", action="store_true",
                        help="write nothing; exit 1 if a change is needed")
    args = parser.parse_args(argv)
    qgs, payload = qgz_actions.read_project(args.project)
    xml, changed = add_enhanced_rules(payload[qgs].decode("utf-8"))
    if not changed:
        print(f"{NO_CHANGE}: {args.project}")
        return 0
    if args.check:
        print(f"Enhanced trees are not drawn: {args.project}")
        return 1
    backup = qgz_actions.write_project(args.project, qgs, payload, xml)
    print(f"added the Enhanced tree rules to {args.project} (backup {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
