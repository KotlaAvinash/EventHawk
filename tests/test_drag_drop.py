"""Dragging .evtx files / folders onto the window adds them to the Files list.

The docs promised drag-and-drop ("Supports drag-and-drop", "drag-and-drop
files directly onto the left panel") but the window never accepted drops.

What must hold:

  * a drag carrying .evtx files or folders is accepted ANYWHERE on the window
    -- the events table, the Files list, a search box -- not only on bare
    background.  Qt hands a drag to the deepest widget under the cursor and
    walks up to the first one that accepts it, so the events are sent to the
    CHILD widgets here and must reach the window through that walk;
  * a drag with nothing usable (a .txt, a web link) is refused;
  * dropping adds through the same path as "+ Files" / "+ Dir": .evtx files and
    folders, de-duplicated; other items are skipped and named in the status
    bar, never silently;
  * while hovering, the Files list is highlighted and the status bar says what
    a drop would add; a cancelled drag restores both exactly;
  * what was dropped actually parses.

Run: QT_QPA_PLATFORM=offscreen python tests/test_drag_drop.py [logs_dir]
"""
import glob, os, shutil, sys, tempfile, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QMimeData, QUrl, QPointF
    from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QDragLeaveEvent
    app = QApplication.instance() or QApplication([])
    from evtx_tool.gui.main_window import MainWindow

    res = []
    def check(name, ok, detail=""):
        res.append((name, bool(ok)))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"\n      {detail}" if detail else ""))

    def pump(s):
        end = time.time() + s
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)

    LOGS = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("EVTX_TEST_LOGS", "sample_logs")
    def has_events(p):
        try:
            import evtx
            return next(iter(evtx.PyEvtxParser(p).records()), None) is not None
        except Exception:
            return False
    # small real logs that actually contain events (the very smallest are
    # often empty or hold a single corrupt record, which would prove nothing)
    real = [p for p in sorted(glob.glob(os.path.join(LOGS, "*.evtx")), key=os.path.getsize)
            if os.path.getsize(p) > 200_000 and has_events(p)][:3]
    tmp = tempfile.mkdtemp(prefix="eh_dnd_")
    try:
        # Two small real logs if available (so the parse step means something),
        # else placeholder files -- the drop logic only looks at names / types.
        srcs = real[:2]
        evtx = []
        for i in range(2):
            dst = os.path.join(tmp, f"Dropped{i}.evtx")
            if i < len(srcs):
                shutil.copyfile(srcs[i], dst)
            else:
                open(dst, "wb").close()
            evtx.append(dst)
        folder = os.path.join(tmp, "case_folder")
        os.makedirs(folder)
        if len(real) > 2:
            shutil.copyfile(real[2], os.path.join(folder, "InFolder.evtx"))
        txt = os.path.join(tmp, "notes.txt")
        open(txt, "w").close()
        upper = os.path.join(tmp, "UPPER.EVTX")
        open(upper, "wb").close()

        w = MainWindow(); w.resize(1400, 860); w.show(); pump(0.5)
        check("the window accepts drops", w.acceptDrops())

        def mime(*paths, web=()):
            m = QMimeData()
            m.setUrls([QUrl.fromLocalFile(p) for p in paths] + [QUrl(u) for u in web])
            return m

        targets = {
            "events table": w._active_table.viewport(),
            "Files list": w._file_list.viewport(),
            "main window": w,
        }

        def enter(target, m):
            pos = QPointF(target.rect().center())
            ev = QDragEnterEvent(pos.toPoint(), Qt.DropAction.CopyAction, m,
                                 Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(target, ev)
            return ev

        def drop(target, m):
            enter(target, m)
            pos = QPointF(target.rect().center())
            mv = QDragMoveEvent(pos.toPoint(), Qt.DropAction.CopyAction, m,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(target, mv)
            ev = QDropEvent(pos, Qt.DropAction.CopyAction, m,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(target, ev)
            app.processEvents()
            return ev

        def listed():
            return [w._file_list.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(w._file_list.count())]

        # ── accepted anywhere, refused when unusable ─────────────────────────
        for name, tgt in targets.items():
            ev = enter(tgt, mime(evtx[0]))
            check(f"a .evtx drag over the {name} is accepted", ev.isAccepted())
            w.dragLeaveEvent(QDragLeaveEvent())
        from PySide6.QtWidgets import QLineEdit
        # A QLineEdit accepts drops itself (it takes dropped TEXT); a file drag
        # carries no text, so it must decline and let the window have it.
        le = QLineEdit(w)
        le.setGeometry(10, 10, 120, 24); le.show(); app.processEvents()
        check("a search box accepts drops itself (so this case is real)", le.acceptDrops())
        ev = enter(le, mime(evtx[0]))
        check("a .evtx drag over a search box still reaches the window", ev.isAccepted())
        w.dragLeaveEvent(QDragLeaveEvent())
        check("…and does not type the path into the box", le.text() == "", le.text())
        le.deleteLater()
        check("a drag with only a .txt is refused", not enter(w, mime(txt)).isAccepted())
        check("a drag with only a web link is refused",
              not enter(w, mime(web=["https://example.com/a.evtx"])).isAccepted())

        # ── hover feedback, and a cancelled drag leaves no trace ─────────────
        w._lbl_status.setText("Done · 12,345 events")
        style_before = w._file_list.styleSheet()
        enter(targets["events table"], mime(evtx[0], folder))
        check("while hovering the Files list is highlighted",
              "dashed" in w._file_list.styleSheet(), w._file_list.styleSheet())
        check("while hovering the status says what a drop adds",
              "1 EVTX file(s) and 1 folder(s)" in w._lbl_status.text(), w._lbl_status.text())
        w.dragLeaveEvent(QDragLeaveEvent()); app.processEvents()
        check("a cancelled drag restores the Files list look",
              w._file_list.styleSheet() == style_before)
        check("a cancelled drag restores the previous status text",
              w._lbl_status.text() == "Done · 12,345 events", w._lbl_status.text())
        check("a cancelled drag adds nothing", listed() == [])

        # ── dropping ──────────────────────────────────────────────────────────
        drop(targets["events table"], mime(evtx[0], evtx[1], folder, txt, upper,
                                            web=["https://example.com/x.evtx"]))
        got = listed()
        norm = lambda p: os.path.normcase(os.path.normpath(p))
        check("dropping adds the .evtx files and the folder",
              {norm(p) for p in got} == {norm(p) for p in (evtx[0], evtx[1], folder, upper)},
              f"{[os.path.basename(p) for p in got]}")
        check(".EVTX in capitals counts as an EVTX file", any(norm(p) == norm(upper) for p in got))
        st = w._lbl_status.text()
        check("the status names the skipped items",
              "skipped 2 non-EVTX item(s)" in st and "notes.txt" in st, st)
        check("the highlight is gone after the drop", "dashed" not in w._file_list.styleSheet())

        n = w._file_list.count()
        drop(targets["Files list"], mime(evtx[0], folder))
        check("dropping the same items again adds no duplicates", w._file_list.count() == n)
        check("…and says nothing new was added, 2 already listed",
              w._lbl_status.text() == "Nothing new added  ·  2 already in the list",
              w._lbl_status.text())

        # ── what was dropped parses ───────────────────────────────────────────
        if len(srcs) >= 2:
            # drop UPPER.EVTX (an empty placeholder) from the list before parsing
            for i in range(w._file_list.count() - 1, -1, -1):
                if norm(w._file_list.item(i).data(Qt.ItemDataRole.UserRole)) == norm(upper):
                    w._file_list.takeItem(i)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
            w._on_parse_clicked()
            end = time.time() + 300
            while time.time() < end and not (w._active_proxy is not None
                                             and w._active_proxy.rowCount() > 0
                                             and w._btn_parse.isEnabled()):
                app.processEvents(); time.sleep(0.02)
            pump(1)
            srcset = {os.path.basename(e.get("source_file", "")) for e in w._active_events}
            expect = {"Dropped0.evtx", "Dropped1.evtx"} | ({"InFolder.evtx"} if len(real) > 2 else set())
            check("the dropped files and the dropped folder's logs all parse",
                  expect <= srcset, f"sources parsed: {sorted(srcset)}; {len(w._active_events):,} events")
        else:
            print("  (no corpus — parse step skipped)")
        w.close(); pump(0.5)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 60)
    bad = [n for n, ok in res if not ok]
    print(f"RESULT: {len(res)-len(bad)}/{len(res)} passed")
    for n in bad:
        print("  FAILED:", n)
    sys.stdout.flush()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
