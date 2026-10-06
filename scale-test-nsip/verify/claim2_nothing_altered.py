#!/usr/bin/env python3
"""Claim 2: nothing is altered, except by a rule written down.

    python3 verify/claim2_nothing_altered.py

Compares the staged site against the legacy pair converted from it, value by
value, against the manifest in claim2_manifest.py. Three things have to hold,
and the third is the one that catches drift:

  1. every value the manifest says is carried arrives unchanged;
  2. every value it says is transformed arrives transformed by that rule;
  3. every column on both sides is accounted for by the manifest.

Rows are paired by position and the pairing is then proved by comparing
geometry, which conversion copies across. A pair whose shapes differ is
reported rather than compared, because comparing the attributes of two
features that are not the same feature proves nothing.

The BNG Service lists hold a label with no number, "Moderate". Some Natural
England lists put a number in front of it, "3. Moderate". The manifest names
each column where that happens. The legacy value must hold the same words and
be a label that the Natural England list offers for that row, number included.
"""

import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "plugin",
                                "bng_template_convert"))

from gpkg_common import blob_geometry                              # noqa: E402
import claim2_manifest as manifest                                 # noqa: E402

SITE = os.path.join(HERE, "..")
STAGED = os.path.join(SITE, "hs2-phase2a-subsection", "Layers",
                      "BNG Service Layers.gpkg")
LEGACY_DIR = os.path.join(SITE, "legacy")
BASELINE = os.path.join(LEGACY_DIR,
                        "Net Gain Habitat Mapping Layers - Baseline.gpkg")
PI = os.path.join(LEGACY_DIR,
                  "Net Gain Habitat Mapping Layers - Post-intervention.gpkg")
SAMPLE = 3


def columns(conn, table):
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]


def read(conn, table, geom_column):
    cols = [c for c in columns(conn, table) if c not in ("fid", geom_column)]
    quoted = ", ".join(f'"{c}"' for c in cols + [geom_column])
    rows = []
    for values in conn.execute(f'SELECT {quoted} FROM "{table}" ORDER BY fid'):
        rows.append((dict(zip(cols, values[:-1])), values[-1]))
    return cols, rows


def points(blob):
    """Every coordinate in a geometry, flattened, so a polygon promoted to a
    multipolygon still compares equal to the polygon it came from."""
    if blob is None:
        return None
    _type, coords = blob_geometry(blob)
    out = []
    stack = [coords]
    while stack:
        node = stack.pop()
        if node and isinstance(node[0], (int, float)):
            out.append((round(node[0], 6), round(node[1], 6)))
        else:
            stack.extend(reversed(node))
    return out


class Findings:
    def __init__(self):
        self.problems = []

    def add(self, layer, kind, detail):
        self.problems.append((layer, kind, detail))

    def report(self):
        if not self.problems:
            print("\nCLAIM 2 HOLDS: every difference is on the list.")
            return 0
        print(f"\nCLAIM 2 FAILS: {len(self.problems)} finding(s).")
        for layer, kind, detail in self.problems:
            print(f"  [{layer}] {kind}: {detail}")
        return 1


def check_coverage(findings, layer, staged_cols, legacy_cols, rules):
    """Every column on both sides must be named by the manifest."""
    carry, change = rules.get("CARRY", {}), rules.get("CHANGE", {})
    drop, invent = rules.get("DROP", {}), rules.get("INVENT", {})
    compose = rules.get("COMPOSE", {})

    declared_staged = set(carry) | set(change) | set(drop)
    for sources, _rule, _why in compose.values():
        declared_staged |= set(sources)
    for column in staged_cols:
        if column not in declared_staged:
            findings.add(layer, "staged column not in the manifest", column)
    for column in declared_staged:
        if column not in staged_cols:
            findings.add(layer, "manifest names a staged column that is gone",
                         column)

    targets = set(carry.values()) | {t for t, _, _ in change.values()}
    declared_legacy = targets | set(invent) | set(compose)
    for column in legacy_cols:
        if column not in declared_legacy:
            findings.add(layer, "legacy column not in the manifest", column)
    for column in declared_legacy:
        if column not in legacy_cols:
            findings.add(layer, "manifest names a legacy column that is gone",
                         column)


def check_rows(findings, layer, staged_rows, legacy_rows, rules, synthesised):
    carry, change = rules.get("CARRY", {}), rules.get("CHANGE", {})
    compose = rules.get("COMPOSE", {})
    extra = len(legacy_rows) - len(staged_rows)
    if extra < 0:
        findings.add(layer, "rows lost",
                     f"{len(staged_rows)} in, {len(legacy_rows)} out")
        return
    if extra and not synthesised:
        findings.add(layer, "rows appeared with nothing to explain them",
                     f"{extra} more out than in")

    mismatches = {}
    geometry_problems = 0
    for index, ((staged, sgeom), (legacy, lgeom)) in enumerate(
            zip(staged_rows, legacy_rows)):
        if points(sgeom) != points(lgeom):
            geometry_problems += 1
            continue
        for source, target in carry.items():
            if not manifest.same(staged.get(source), legacy.get(target)):
                record(mismatches, source, target, index, staged, legacy)
        for source, (target, rule, _why) in change.items():
            if not rule(staged.get(source), legacy.get(target)):
                record(mismatches, source, target, index, staged, legacy)
        for target, (sources, rule, _why) in compose.items():
            if not rule(staged, legacy.get(target)):
                shown = " + ".join(f"{s}={staged.get(s)!r}" for s in sources)
                mismatches.setdefault((" + ".join(sources), target), []).append(
                    f"row {index + 1}: {shown} -> {legacy.get(target)!r}")

    if geometry_problems:
        findings.add(layer, "rows whose shapes do not match",
                     f"{geometry_problems} of {len(staged_rows)}; those rows "
                     "were not compared")
    for (source, target), hits in mismatches.items():
        findings.add(layer, f"value changed: {source} -> {target}",
                     f"{len(hits)} row(s), e.g. " + "; ".join(hits[:SAMPLE]))

    # The rows legacy has to invent must all say what they are.
    if extra and synthesised:
        wrong = [row for row, _ in legacy_rows[len(staged_rows):]
                 if manifest.unnumbered(row.get("Retention Category"))
                 != synthesised]
        print(f"    {extra} synthesised '{synthesised}' row(s), "
              f"{len(wrong)} not marked as such")
        if wrong:
            findings.add(layer, f"synthesised rows not marked {synthesised}",
                         f"{len(wrong)} row(s)")


def record(store, source, target, index, staged, legacy):
    store.setdefault((source, target), []).append(
        f"row {index + 1}: {staged.get(source)!r} -> {legacy.get(target)!r}")


def main():
    findings = Findings()
    staged_conn = sqlite3.connect(STAGED)
    conns = {"baseline": sqlite3.connect(BASELINE),
             "pi": sqlite3.connect(PI)}

    staged_tables = {row[0] for row in staged_conn.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type='features'")}
    for table, why in manifest.DROPPED_LAYERS.items():
        rows = staged_conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        print(f"{table}: {rows} row(s) dropped, {why}")
        if rows:
            findings.add(table, "dropped layer is not empty",
                         f"{rows} row(s) would be lost without notice")

    for staged_table, legacy_table, stage, rules, geom in manifest.LAYERS:
        conn = conns[stage]
        staged_cols, staged_rows = read(staged_conn, staged_table, "geom")
        legacy_cols, legacy_rows = read(conn, legacy_table, geom)
        print(f"\n{staged_table} -> {legacy_table} ({stage}): "
              f"{len(staged_rows)} -> {len(legacy_rows)} rows, "
              f"{len(staged_cols)} -> {len(legacy_cols)} columns")
        check_coverage(findings, staged_table, staged_cols, legacy_cols, rules)
        check_rows(findings, staged_table, staged_rows, legacy_rows, rules,
                   manifest.SYNTHESISED.get(legacy_table) if stage == "pi"
                   else None)

    # The red line, which is one row and does not follow the pattern.
    staged_cols, staged_rows = read(staged_conn, "Red Line Boundary", "geom")
    legacy_cols, legacy_rows = read(conns["baseline"], "Red Line Boundary",
                                    "geometry")
    print(f"\nRed Line Boundary: {len(staged_rows)} -> {len(legacy_rows)} rows")
    check_coverage(findings, "Red Line Boundary", staged_cols, legacy_cols,
                   manifest.REDLINE)
    check_rows(findings, "Red Line Boundary", staged_rows, legacy_rows,
               manifest.REDLINE, None)

    staged_conn.close()
    for conn in conns.values():
        conn.close()
    return findings.report()


if __name__ == "__main__":
    sys.exit(main())
