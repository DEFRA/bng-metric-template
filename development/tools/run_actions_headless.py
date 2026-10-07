"""Run the template's buttons outside QGIS, so their logic can be tested.

The buttons are Python stored inside the project file. They are hard to test
because they talk to the QGIS interface, and they save as they go. This loads
a project with pyqgis, stands in for the parts of the interface they use, and
runs a button against a copy of a real site.

    /Applications/QGIS.app/Contents/MacOS/bin/python3 \
        tools/run_actions_headless.py <project.qgz> <action prefix> <layer>

The answer given to any question the button asks is set with --answer.
"""
import argparse
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qgis.core import QgsApplication, QgsProject           # noqa: E402
from qgis.PyQt import QtWidgets                            # noqa: E402
import qgis.utils                                          # noqa: E402

from qgz_actions import iter_actions, read_project          # noqa: E402


class FakeBar:
    """Collects what the button would have shown the user."""

    def __init__(self):
        self.messages = []

    def _push(self, kind):
        def push(title, text=None):
            self.messages.append((kind, title, text))
        return push

    def __getattr__(self, name):
        if name.startswith("push"):
            return self._push(name[4:].lower())
        raise AttributeError(name)


class FakeIface:
    def __init__(self):
        self.bar = FakeBar()

    def messageBar(self):
        return self.bar

    def mainWindow(self):
        return None

    def mapCanvas(self):
        return FakeCanvas()


class FakeCanvas:
    def renderFlag(self):
        return False

    def setRenderFlag(self, _value):
        pass


class FakeProgress:
    """A progress dialog that records its labels instead of drawing."""

    seen = []

    def __init__(self, label, _cancel, _low, _high, _parent):
        self.labels = [label]
        FakeProgress.seen.append(self)

    def setLabelText(self, text):
        self.labels.append(text)

    def wasCanceled(self):
        return False

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def load_action(project_path, prefix, layer_name):
    qgs, payload = read_project(project_path)
    xml = payload[qgs].decode("utf-8")
    marks = [(m.start(), m.group(1))
             for m in re.finditer(r"<layername>([^<]*)</layername>", xml)]

    def owner(pos):
        earlier = [n for p, n in marks if p < pos]
        return earlier[-1] if earlier else ""

    for name, start, end in iter_actions(xml):
        if name.startswith(prefix) and owner(start) == layer_name:
            return html.unescape(xml[start:end])
    raise SystemExit(f"no action {prefix!r} on layer {layer_name!r}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("prefix")
    parser.add_argument("layer")
    parser.add_argument("--answer", choices=("yes", "no"), default="no")
    parser.add_argument("--prefix-path",
                        default="/Applications/QGIS.app/Contents/MacOS")
    args = parser.parse_args()

    QgsApplication.setPrefixPath(args.prefix_path, True)
    app = QgsApplication([], False)
    app.initQgis()
    try:
        project = QgsProject.instance()
        if not project.read(args.project):
            raise SystemExit(f"could not read {args.project}")

        answered = []

        class FakeMessageBox:
            Yes, No = 1, 0

            @staticmethod
            def question(_parent, title, text, _buttons=None, _default=None):
                answered.append((title, text))
                return (FakeMessageBox.Yes if args.answer == "yes"
                        else FakeMessageBox.No)

        QtWidgets.QProgressDialog = FakeProgress
        QtWidgets.QMessageBox = FakeMessageBox
        iface = FakeIface()
        qgis.utils.iface = iface

        body = load_action(args.project, args.prefix, args.layer)
        exec(compile(body, "<action>", "exec"), {"__name__": "__action__"})

        for title, text in answered:
            print(f"ASKED [{title}] {' '.join(text.split())[:180]}")
        for kind, title, text in iface.bar.messages:
            print(f"{kind.upper()} [{title}] {text}")
        if not answered:
            print("ASKED nothing")
    finally:
        app.exitQgis()


if __name__ == "__main__":
    main()
