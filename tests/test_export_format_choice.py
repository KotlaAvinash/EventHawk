"""The export format is chosen IN the Export dialog, and the file matches it.

Before, the format hid in the Save window's "Save as type" list (all five in
Normal mode, no PDF in Juggernaut), and "All files separate" asked again in a
separate popup without PDF.  The Export dialog now has a Format box with all
five; the Save window offers only that format with a ready-made file name.

What must hold:

  * the box shows HTML / PDF / CSV / JSON / XML with a hint for the selected
    one, and remembers the last choice (the user's real setting is restored);
  * the Save window offers only the chosen format and pre-fills a dated name;
    a name typed without the extension gets it;
  * through the real MainWindow on real logs, each format writes a file that
    really IS that format (PDF magic, JSON / XML parse, CSV header, HTML);
  * "All files separate" uses the chosen format for every file, with no extra
    popup -- PDF included;
  * Juggernaut shows the same box with PDF disabled and the reason, and the
    other four still export valid files.

Run: QT_QPA_PLATFORM=offscreen python tests/test_export_format_choice.py [logs_dir]
"""
import csv, glob, json, os, shutil, sys, tempfile, time
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog, QDialog, QInputDialog
    from PySide6.QtCore import QSettings
    app = QApplication.instance() or QApplication([])
    import evtx_tool.gui.main_window as mw

    res = []
    def check(name, ok, detail=""):
        res.append((name, bool(ok)))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"\n      {detail}" if detail else ""))

    def pump(s, until=None):
        end = time.time() + s
        while time.time() < end:
            app.processEvents(); time.sleep(0.02)
            if until and until():
                return True
        return False

    settings = QSettings("EventHawk", "GUI")
    had = settings.contains(mw._EXPORT_FORMAT_KEY)
    prev = settings.value(mw._EXPORT_FORMAT_KEY)
    tmp = tempfile.mkdtemp(prefix="eh_exportfmt_")
    saved_patches = {}

    def patch(obj, name, fn):
        saved_patches.setdefault((obj, name), getattr(obj, name))
        setattr(obj, name, fn)

    try:
        settings.remove(mw._EXPORT_FORMAT_KEY)

        # ── 1. the dialog ─────────────────────────────────────────────────────
        d = mw._ExportScopeDialog(["C:\\logs\\A.evtx", "C:\\logs\\B.evtx"], None, "separate", 10)
        d.show(); app.processEvents()
        box = d._fmt_box
        labels = [box._buttons[k].text() for k, _l, _h in mw._EXPORT_FORMATS]
        check("the Format box offers all five formats",
              labels == ["HTML report", "PDF report", "CSV", "JSON", "XML"], f"{labels}")
        check("HTML is the default the first time", box.selected_format() == "html")
        check("the hint describes the selected format", "browser" in box._hint.text(), box._hint.text())
        box._buttons["pdf"].setChecked(True); app.processEvents()
        check("choosing PDF says it is a summary with the first 500 events",
              "first 500 events" in box._hint.text(), box._hint.text())
        box._buttons["csv"].setChecked(True); app.processEvents()
        d._on_ok()
        check("OK returns the chosen format", d.selected_format() == "csv")
        d2 = mw._ExportScopeDialog(["C:\\logs\\A.evtx"], None, "merged", 1)
        check("the next Export dialog remembers it", d2._fmt_box.selected_format() == "csv")
        d.close(); d2.close()

        jd = mw._ExportFormatDialog(1234)
        check("Juggernaut's dialog shows all five", len(jd._fmt._buttons) == 5)
        check("…with PDF disabled and the reason given",
              not jd._fmt._buttons["pdf"].isEnabled()
              and "Juggernaut" in jd._fmt._buttons["pdf"].toolTip(),
              jd._fmt._buttons["pdf"].toolTip())
        settings.setValue(mw._EXPORT_FORMAT_KEY, "pdf")
        jd2 = mw._ExportFormatDialog(1)
        check("a remembered PDF falls back to an available format in Juggernaut",
              jd2._fmt.selected_format() == "html", jd2._fmt.selected_format())
        jd.close(); jd2.close()

        # ── 2. the save window ────────────────────────────────────────────────
        seen = {}
        def fake_save(parent, title, default, filt, *a, **k):
            seen.update(default=default, filter=filt)
            return os.path.join(tmp, "typed_without_extension"), filt
        patch(QFileDialog, "getSaveFileName", staticmethod(fake_save))
        out = mw._export_save_path(None, "t", "json", "EventHawk_export")
        check("the Save window offers only the chosen format", seen["filter"] == "JSON (*.json)", seen["filter"])
        check("…with a dated default name", seen["default"].startswith("EventHawk_export_")
              and seen["default"].endswith(".json"), seen["default"])
        check("a name typed without the extension gets it", out.endswith("typed_without_extension.json"), out)

        # ── 3. real exports, Normal mode ──────────────────────────────────────
        LOGS = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("EVTX_TEST_LOGS", "sample_logs")
        def has_events(p):
            try:
                import evtx
                return next(iter(evtx.PyEvtxParser(p).records()), None) is not None
            except Exception:
                return False
        real = [p for p in sorted(glob.glob(os.path.join(LOGS, "*.evtx")), key=os.path.getsize)
                if os.path.getsize(p) > 200_000 and has_events(p)][:2]
        if len(real) < 2:
            print("  (no corpus — export runs skipped)")
            return finish(res)

        msgs = []
        for n in ("information", "warning", "critical"):
            patch(QMessageBox, n, staticmethod(
                lambda *a, _n=n, **k: (msgs.append((_n, str(a[2]))), QMessageBox.StandardButton.Ok)[1]))
        patch(QInputDialog, "getItem", staticmethod(
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("format asked again"))))

        def valid(path, fmt):
            with open(path, "rb") as fh:
                head = fh.read(64)
            if fmt == "pdf":
                return head.startswith(b"%PDF")
            if fmt == "json":
                json.load(open(path, encoding="utf-8")); return True
            if fmt == "xml":
                ET.parse(path); return True
            if fmt == "csv":
                rows = list(csv.reader(open(path, encoding="utf-8", newline="")))
                return len(rows) > 1 and len(rows[0]) > 3
            if fmt == "html":
                return b"<html" in head.lower() or b"<!doctype html" in head.lower()

        target = {}
        patch(QFileDialog, "getSaveFileName", staticmethod(
            lambda parent, title, default, filt, *a, **k: (target["path"], filt)))
        patch(QFileDialog, "getExistingDirectory", staticmethod(
            lambda *a, **k: target["dir"]))

        w = mw.MainWindow()
        # "All files separate" needs the per-file split, which EventHawk only
        # builds in the Separate Tabs view (in Merge All it lists 0 files --
        # pre-existing, unchanged here).
        w._radio_separate.setChecked(True)
        for f in real:
            w._add_path(f)
        w._on_parse_clicked()
        pump(300, lambda: w._active_proxy is not None and w._active_proxy.rowCount() > 0
             and w._btn_parse.isEnabled())
        pump(1)

        def drive(scope_rb, fmt):
            def fake_exec(dlg):
                getattr(dlg, scope_rb).setChecked(True)
                dlg._fmt_box._buttons[fmt].setChecked(True)
                dlg._on_ok()
                return QDialog.DialogCode.Accepted
            patch(mw._ExportScopeDialog, "exec", fake_exec)
            msgs.clear()
            w._on_export_clicked()

        for fmt in ("html", "pdf", "csv", "json", "xml"):
            target["path"] = os.path.join(tmp, f"combined.{fmt}")
            drive("_rb_combined", fmt)
            ok = os.path.exists(target["path"]) and valid(target["path"], fmt)
            check(f"Normal: {fmt.upper()} export writes a real {fmt.upper()} file", ok,
                  f"{[m[0] for m in msgs]} {os.path.getsize(target['path']) if os.path.exists(target['path']) else 'missing'} bytes")

        for fmt in ("csv", "pdf"):
            target["dir"] = os.path.join(tmp, f"separate_{fmt}"); os.makedirs(target["dir"])
            drive("_rb_separate", fmt)
            outs = sorted(os.listdir(target["dir"]))
            check(f"Normal: 'All files separate' writes one {fmt.upper()} per log, no extra popup",
                  len(outs) == len(real) and all(o.endswith("." + fmt) for o in outs)
                  and all(valid(os.path.join(target["dir"], o), fmt) for o in outs), f"{outs}")
        w.close(); pump(0.5)

        # ── 4. real exports, Juggernaut ───────────────────────────────────────
        w2 = mw.MainWindow()
        w2._launch_juggernaut_mode(real)
        pump(300, lambda: w2._hw_model is not None and w2._hw_model.rowCount() > 0)
        pump(2)
        for fmt in ("html", "csv", "json", "xml"):
            def fake_fmt_exec(dlg, _f=fmt):
                dlg._fmt._buttons[_f].setChecked(True); dlg._on_ok()
                return QDialog.DialogCode.Accepted
            patch(mw._ExportFormatDialog, "exec", fake_fmt_exec)
            target["path"] = os.path.join(tmp, f"jm.{fmt}")
            msgs.clear()
            w2._on_export_clicked()
            pump(120, lambda: any(k == "information" for k, _ in msgs) or any(k == "critical" for k, _ in msgs))
            ok = os.path.exists(target["path"]) and valid(target["path"], fmt)
            check(f"Juggernaut: {fmt.upper()} export writes a real {fmt.upper()} file", ok,
                  f"{[m for m in msgs][:1]}")
        w2.close(); pump(0.5)
    finally:
        for (obj, name), orig in saved_patches.items():
            setattr(obj, name, orig)
        if had:
            settings.setValue(mw._EXPORT_FORMAT_KEY, prev)
        else:
            settings.remove(mw._EXPORT_FORMAT_KEY)
        shutil.rmtree(tmp, ignore_errors=True)
    return finish(res)


def finish(res) -> int:
    print("\n" + "=" * 60)
    bad = [n for n, ok in res if not ok]
    print(f"RESULT: {len(res)-len(bad)}/{len(res)} passed")
    for n in bad:
        print("  FAILED:", n)
    sys.stdout.flush()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
