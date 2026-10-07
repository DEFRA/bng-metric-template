"""Read and rewrite the action bodies stored in a .qgz, by raw XML edit.

Going through QgsProject.write() would be the obvious route and is the wrong
one: it drops action shortTitles set in XML, and it rewrites 3 MB of project
for the sake of five attributes. This edits the five attributes and leaves
every other byte alone.
"""
import html
import os
import re
import shutil
import time
import zipfile

OPEN_RE = re.compile(r'<actionsetting\s+name="(?P<name>[^"]*)"')


def iter_actions(xml):
    """Yield (name, body_start, body_end) for every action in the project.

    The body ends at the first unescaped double quote after `action="`. There
    is always exactly one: a quote inside the body is written `&quot;`. That
    is simpler and safer than matching whatever attribute comes next, which
    differs between the self-closing actions and the ones carrying an
    <actionScope> child.
    """
    opens = [m for m in OPEN_RE.finditer(xml)]
    for index, match in enumerate(opens):
        limit = opens[index + 1].start() if index + 1 < len(opens) else len(xml)
        marker = xml.find(' action="', match.end(), limit)
        if marker < 0:
            continue
        body_start = marker + len(' action="')
        body_end = xml.index('"', body_start)
        yield match.group("name"), body_start, body_end


def escape(text):
    """Escape exactly as QGIS writes an attribute, so a round trip is a no-op."""
    # QGIS leaves `>` alone, so escaping it here would rewrite bytes that are
    # not ours to rewrite. Verified by round-tripping all twenty actions.
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace('"', "&quot;")
                .replace("\n", "&#xa;").replace("\t", "&#x9;"))


def read_project(path):
    with zipfile.ZipFile(path) as archive:
        qgs = [n for n in archive.namelist() if n.endswith(".qgs")][0]
        payload = {n: archive.read(n) for n in archive.namelist()}
    return qgs, payload


def write_project(path, qgs, payload, xml):
    """Rewrite the project, keeping a timestamped copy of what was there.

    Timestamped rather than a fixed `.backup`, which a second run would
    overwrite with the already-changed file, destroying the only copy of the
    original. It also matches how the template's own backups are named.
    """
    payload[qgs] = xml.encode("utf-8")
    stamp = f"{path}.backup-{time.strftime('%Y%m%d-%H%M%S')}"
    # Tools run one after another can write twice in the same second. A
    # second backup under the same name would replace the first.
    backup, count = stamp, 1
    while os.path.exists(backup):
        count += 1
        backup = f"{stamp}-{count}"
    shutil.copyfile(path, backup)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        for name, data in payload.items():
            out.writestr(name, data)
    return backup


def replace_bodies(xml, action_name, make_body):
    """Swap the body of every action with this name. Returns (xml, count)."""
    edits = [(s, e) for name, s, e in iter_actions(xml) if name == action_name]
    for body_start, body_end in reversed(edits):     # right to left: offsets hold
        old = html.unescape(xml[body_start:body_end])
        xml = xml[:body_start] + escape(make_body(old)) + xml[body_end:]
    return xml, len(edits)
