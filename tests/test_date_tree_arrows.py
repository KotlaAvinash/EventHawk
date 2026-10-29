"""The date tree must SHOW that it can be expanded, and show what is checked.

Reported: in the Timestamp column filter the Year -> Month -> Day tree had no
expand arrows (the app stylesheet styles QTreeWidget::branch without an image,
which removes Qt's own), so users could not tell there was anything to open.
The checkboxes were plain filled squares, so "all / some / none of this month"
differed only by a shade of amber.

These checks render the real popup and look at the pixels, because the bug was
purely visual -- the tree expanded fine when you happened to click the right
spot, so any check on expand/collapse state would have passed throughout.

Run: QT_QPA_PLATFORM=offscreen python tests/test_date_tree_arrows.py
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATE_COL = 3   # timestamp -> tree
VALUES = {"2026-10-25": 4120, "2026-10-26": 5210, "2026-09-30": 611, "2025-12-31": 77}


def main() -> int:
    from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    app = QApplication.instance() or QApplication([])
    from evtx_tool.gui.theme import apply_theme, COLORS
    apply_theme(app)
    from evtx_tool.gui.main_window import ColumnFilterPopup, _ExpandArrowTree, _contrast_ink

    res = []
    def check(name, ok, detail=""):
        res.append((name, bool(ok)))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"\n      {detail}" if detail else ""))

    p = ColumnFilterPopup(DATE_COL, dict(VALUES))
    p.resize(320, 420); p.show(); app.processEvents()
    t = p._tree
    check("date column uses the arrow-drawing tree", isinstance(t, _ExpandArrowTree))

    root = t.topLevelItem(0)
    years = {root.child(i).text(0).split()[0]: root.child(i) for i in range(root.childCount())}
    y2026, y2025 = years["2026"], years["2025"]
    y2026.setExpanded(True)
    months = {y2026.child(i).text(0).split()[0]: y2026.child(i) for i in range(y2026.childCount())}
    octo = months["October"]
    octo.setExpanded(True)
    app.processEvents()

    img = t.viewport().grab().toImage()

    def count_near(rect, target: QColor, tol=60):
        n = 0
        for x in range(max(0, rect.left()), min(img.width(), rect.right() + 1)):
            for y in range(max(0, rect.top()), min(img.height(), rect.bottom() + 1)):
                c = img.pixelColor(x, y)
                if (abs(c.red() - target.red()) + abs(c.green() - target.green())
                        + abs(c.blue() - target.blue())) < tol:
                    n += 1
        return n

    arrow_col = QColor(COLORS["text_dim"])
    def branch_rect(item):
        r = t.visualItemRect(item)
        r.setLeft(r.left() - t.indentation())
        r.setRight(r.left() + t.indentation() - 1)
        return r

    n_closed = count_near(branch_rect(y2025), arrow_col)
    n_open   = count_near(branch_rect(y2026), arrow_col)
    leaf = octo.child(0)
    n_leaf   = count_near(branch_rect(leaf), arrow_col)
    check("a collapsed year shows an arrow", n_closed >= 8, f"{n_closed} arrow pixels")
    check("an expanded year shows an arrow", n_open >= 8, f"{n_open} arrow pixels")
    check("a day (nothing to expand) shows no arrow", n_leaf <= 2, f"{n_leaf} arrow pixels")

    # the arrow points a different way once expanded
    y2025.setExpanded(True); app.processEvents()
    img_open = t.viewport().grab().toImage()
    r = branch_rect(y2025)
    differs = any(img.pixelColor(x, y) != img_open.pixelColor(x, y)
                  for x in range(r.left(), r.right() + 1) for y in range(r.top(), r.bottom() + 1))
    check("expanding changes the arrow (closed > vs open v)", differs)
    y2025.setExpanded(False); app.processEvents()

    # ticks: checked box carries ink, unchecked box does not, partial has a dash
    leaf.setCheckState(0, Qt.CheckState.Unchecked); app.processEvents()
    img = t.viewport().grab().toImage()

    def box_rect(item):
        opt = QStyleOptionViewItem()
        idx = t.indexFromItem(item)
        opt.rect = t.visualRect(idx)
        opt.widget = t
        t.itemDelegate().initStyleOption(opt, idx)
        return t.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, opt, t)

    tick_ink = _contrast_ink(QColor(COLORS["accent"]))
    dash_ink = _contrast_ink(QColor(COLORS["border_focus"]))
    checked_leaf = octo.child(1)
    n_tick = count_near(box_rect(checked_leaf), tick_ink, 90)
    # unchecked: the box interior is one plain colour -- nothing drawn on it
    inner = box_rect(leaf).adjusted(3, 3, -3, -3)
    plain = img.pixelColor(inner.left(), inner.top())
    n_none = sum(1 for x in range(inner.left(), inner.right() + 1)
                 for y in range(inner.top(), inner.bottom() + 1)
                 if img.pixelColor(x, y) != plain)
    n_dash = count_near(box_rect(octo), dash_ink, 90)
    check("a checked day shows a tick", n_tick >= 4, f"{n_tick} ink pixels")
    check("an unchecked day shows no tick", n_none == 0, f"{n_none} non-plain pixels")
    check("a partly checked month shows a dash", octo.checkState(0) == Qt.CheckState.PartiallyChecked
          and n_dash >= 4, f"{n_dash} ink pixels")

    # the tree still emits exactly the same day values (painting only)
    vals = sorted(cb.property("filter_value") for cb in p._checkboxes)
    check("filter values are unchanged (days only)", vals == sorted(VALUES), f"{vals}")

    p.close()

    # ── deep rows are never cut off ───────────────────────────────────────────
    # Reported: at the 4th level an hour row read "20:00 – 2…" with no way to
    # see the rest.  The column must be as wide as its widest row, and when
    # that is wider than the popup a horizontal scrollbar must reach it.
    big = {"2026-08-05 20": 1_234_567, "2026-08-05 21": 7, "2025-12-31 23": 3}
    p = ColumnFilterPopup(DATE_COL, big)
    p.show(); app.processEvents()
    t = p._tree
    t.expandAll(); app.processEvents()
    check("the Timestamp popup opens at least 320 px wide", p.width() >= 320, f"{p.width()} px")
    check("rows are not elided", t.textElideMode() == Qt.TextElideMode.ElideNone)
    check("the bottom scrollbar is always shown, like the right one",
          t.horizontalScrollBar().isVisible())
    fm = t.fontMetrics()
    hour = next(c._item for c in p._checkboxes if c.property("filter_value") == "2026-08-05 20")
    # x where the row's content starts (after indentation + arrow) + checkbox + text
    needed = t.visualItemRect(hour).left() + 16 + fm.horizontalAdvance(hour.text(0))
    check("the column is wide enough for the deepest, longest row",
          t.columnWidth(0) >= needed, f"column {t.columnWidth(0)} px, row needs {needed} px")
    hbar = t.horizontalScrollBar()
    vp = t.viewport().width()
    if t.columnWidth(0) > vp:
        check("a horizontal scrollbar appears when a row is wider than the popup",
              hbar.isVisible() and hbar.maximum() > 0, f"max {hbar.maximum()}")
        hbar.setValue(hbar.maximum()); app.processEvents()
        check("scrolling right brings the end of the row into view",
              needed - hbar.value() <= vp, f"row ends at {needed - hbar.value()}, viewport {vp}")
    else:
        check("the deepest row fits without scrolling", needed <= vp,
              f"needs {needed}, viewport {vp}")
    # force it narrow: the scrollbar must take over
    p.setMinimumWidth(0); p.resize(200, p.height()); app.processEvents()
    vp = t.viewport().width()
    check("squeezed narrow, the tree scrolls sideways instead of cutting text",
          t.columnWidth(0) > vp and hbar.maximum() > 0,
          f"column {t.columnWidth(0)} px, viewport {vp} px, scroll max {hbar.maximum()}")
    p.close()

    print("\n" + "=" * 60)
    bad = [n for n, ok in res if not ok]
    print(f"RESULT: {len(res)-len(bad)}/{len(res)} passed")
    for n in bad:
        print("  FAILED:", n)
    sys.stdout.flush()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
