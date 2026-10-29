"""Export > Specific files: search the list, select several, tick them at once.

Reported: with many logs loaded, picking files for export meant scrolling a
plain checklist and ticking each box by hand.  The list now has a search box
and Explorer-style multi-selection.

What must hold:

  * search narrows the list (file name, any case) and never changes what is
    ticked -- files hidden by the search stay exactly as they were, and the
    count says how many ticked files the search is hiding;
  * All / None act only on the files shown;
  * Ctrl/Shift-highlighted rows are ticked/unticked together by Space, by
    clicking one highlighted row's box, and by the Tick/Untick buttons --
    driven with REAL mouse/key events, because Qt's own click handling can
    collapse a multi-selection before the box toggles;
  * selected_files() returns exactly the ticked paths, and OK with nothing
    ticked is refused.

Run: QT_QPA_PLATFORM=offscreen python tests/test_export_file_search.py [logs_dir]
"""
import glob, os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox, QStyle, QStyleOptionViewItem
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    app = QApplication.instance() or QApplication([])
    from evtx_tool.gui.main_window import _ExportScopeDialog

    res = []
    def check(name, ok, detail=""):
        res.append((name, bool(ok)))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"\n      {detail}" if detail else ""))

    LOGS = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("EVTX_TEST_LOGS", "sample_logs")
    paths = sorted(glob.glob(os.path.join(LOGS, "*.evtx")))
    if len(paths) < 20:   # the dialog never opens the files, so names suffice
        paths = [os.path.join("C:\\logs", n) for n in (
            ["Security.evtx", "System.evtx", "Application.evtx", "Windows PowerShell.evtx",
             "Microsoft-Windows-PowerShell%4Operational.evtx"]
            + [f"Microsoft-Windows-Component{i:03d}%4Operational.evtx" for i in range(60)])]
    N = len(paths)

    d = _ExportScopeDialog(paths, paths[0], "separate", 1000)
    d._rb_specific.setChecked(True)
    d.show(); app.processEvents()
    lst = d._file_list

    def ticked():
        return {lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(lst.count())
                if lst.item(i).checkState() == Qt.CheckState.Checked}

    check("every loaded file is listed and ticked", lst.count() == N and ticked() == set(paths),
          f"{lst.count()} of {N}")
    check("count reads 'N of N'", d._files_count.text().startswith(f"{N} of {N}"),
          d._files_count.text())
    check("there is a search box above the list",
          d._file_search.isVisible() and d._file_search.geometry().bottom() < lst.geometry().top())

    # ── search ────────────────────────────────────────────────────────────────
    QTest.keyClicks(d._file_search, "POWERSHELL"); app.processEvents()
    shown = [lst.item(i) for i in range(lst.count()) if not lst.item(i).isHidden()]
    expect = [p for p in paths if "powershell" in os.path.basename(p).lower()]
    check("search narrows the list, any case",
          len(shown) == len(expect) and len(expect) > 0
          and all("powershell" in it.text().lower() for it in shown),
          f"{len(shown)} shown: {[it.text() for it in shown][:3]}")
    check("search alone changes nothing that is ticked", ticked() == set(paths))

    # None with a search active: only the shown files are unticked
    from PySide6.QtWidgets import QPushButton
    btn = {b.text(): b for b in d._files_box.findChildren(QPushButton)}
    QTest.mouseClick(btn["None"], Qt.MouseButton.LeftButton); app.processEvents()
    check("None unticks only the files shown", ticked() == set(paths) - set(expect),
          f"{N - len(ticked())} unticked, expected {len(expect)}")
    txt = d._files_count.text()
    check("count reports ticked files hidden by the search",
          f"{N - len(expect)} of {N}" in txt and "hidden by the search" in txt, txt)

    d._file_search.clear(); app.processEvents()
    check("clearing the search shows every file again, ticks kept",
          all(not lst.item(i).isHidden() for i in range(N)) and ticked() == set(paths) - set(expect))
    QTest.mouseClick(btn["All"], Qt.MouseButton.LeftButton); app.processEvents()
    check("All with no search ticks everything", ticked() == set(paths))

    # ── multi-selection with real input ───────────────────────────────────────
    def row_center(i):
        return lst.visualItemRect(lst.item(i)).center()

    def box_point(i):
        opt = QStyleOptionViewItem()
        idx = lst.indexFromItem(lst.item(i))
        opt.rect = lst.visualRect(idx); opt.widget = lst
        lst.itemDelegate().initStyleOption(opt, idx)
        r = lst.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, opt, lst)
        return r.center()

    vp = lst.viewport()
    lst.scrollToTop(); app.processEvents()
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, row_center(1))
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, row_center(4))
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, row_center(6))
    sel_rows = sorted(lst.row(it) for it in lst.selectedItems())
    check("click, Shift+click, Ctrl+click highlight several files", sel_rows == [1, 2, 3, 4, 6],
          f"{sel_rows}")
    check("highlighting alone ticks nothing", ticked() == set(paths))

    lst.setFocus()
    QTest.keyClick(lst, Qt.Key.Key_Space); app.processEvents()
    sel_paths = {lst.item(r).data(Qt.ItemDataRole.UserRole) for r in sel_rows}
    check("Space unticks every highlighted file", ticked() == set(paths) - sel_paths,
          f"{N - len(ticked())} unticked")
    QTest.keyClick(lst, Qt.Key.Key_Space); app.processEvents()
    check("Space again ticks them all back", ticked() == set(paths))

    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, box_point(3))
    app.processEvents()
    check("clicking one highlighted row's box unticks all highlighted rows",
          ticked() == set(paths) - sel_paths,
          f"{N - len(ticked())} unticked, selection now {sorted(lst.row(it) for it in lst.selectedItems())}")
    QTest.mouseClick(btn["Tick selected"], Qt.MouseButton.LeftButton); app.processEvents()
    check("'Tick selected' ticks the highlighted rows", ticked() == set(paths))
    QTest.mouseClick(btn["Untick selected"], Qt.MouseButton.LeftButton); app.processEvents()
    check("'Untick selected' unticks the highlighted rows", ticked() == set(paths) - sel_paths)

    # a box clicked on a row that is NOT highlighted affects only that row
    QTest.mouseClick(btn["All"], Qt.MouseButton.LeftButton); app.processEvents()
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, box_point(9))
    app.processEvents()
    check("clicking an un-highlighted row's box changes only that row",
          ticked() == set(paths) - {paths[9]}, f"{N - len(ticked())} unticked")

    QTest.keyClick(lst, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier); app.processEvents()
    check("Ctrl+A highlights every shown file", len(lst.selectedItems()) == N)

    # search drops hidden rows from the highlight
    QTest.keyClicks(d._file_search, "security"); app.processEvents()
    check("rows hidden by the search are no longer highlighted",
          all(not it.isHidden() for it in lst.selectedItems()))
    d._file_search.clear(); app.processEvents()

    # ── OK / selected_files ───────────────────────────────────────────────────
    QTest.mouseClick(btn["All"], Qt.MouseButton.LeftButton)
    QTest.mouseClick(btn["None"], Qt.MouseButton.LeftButton); app.processEvents()
    warned = []
    orig = QMessageBox.warning
    QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[1:3]))
    try:
        d._on_ok()
        check("OK with nothing ticked is refused", warned and d.result() == 0, f"{warned}")
        lst.item(0).setCheckState(Qt.CheckState.Checked)
        lst.item(2).setCheckState(Qt.CheckState.Checked)
        d._on_ok()
        check("OK returns exactly the ticked files",
              d.selected_scope() == "specific" and d.selected_files() == {paths[0], paths[2]},
              f"{d.selected_files()}")
    finally:
        QMessageBox.warning = orig

    print("\n" + "=" * 60)
    bad = [n for n, ok in res if not ok]
    print(f"RESULT: {len(res)-len(bad)}/{len(res)} passed")
    for n in bad:
        print("  FAILED:", n)
    sys.stdout.flush()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
