"""The Timestamp filter tree goes down to the HOUR, and the hour filter is exact.

Large corpora span weeks; narrowing to a day still leaves tens of thousands of
events.  The tree is now Year > Month > Day > Hour, and its leaves are
"YYYY-MM-DD HH" values in the DISPLAY timezone.

What must hold, and is checked here on real logs through the real MainWindow
in both engines (Normal = Python proxy, Juggernaut = DuckDB SQL):

  * the tree's hour counts add up to every loaded event -- no hour is dropped,
    including quiet ones (the generic top-1000 cap would cut those first);
  * keeping ONE hour leaves exactly that hour's events in the table, every one
    of them displayed inside that hour, and as many as the tree said;
  * the same holds in a non-whole-hour timezone (UTC+05:30), where every event
    lands in a different bucket than in UTC -- so the popup values and the
    filter must agree on the display timezone, in both engines.

Run: QT_QPA_PLATFORM=offscreen python tests/test_date_tree_hours.py [logs_dir]
"""
import os, sys, glob, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    from evtx_tool.gui.main_window import MainWindow, ColumnFilterPopup
    from evtx_tool.gui.models import COL_TS, set_tz_config, apply_tz
    from evtx_tool.gui.jm_col_worker import NormalColValueWorker, ColValueWorker

    res = []
    def check(name, ok, detail=""):
        res.append((name, bool(ok)))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"\n      {detail}" if detail else ""))

    def wait_for(pred, timeout_s=300):
        end = time.time() + timeout_s
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)
            try:
                if pred(): return True
            except Exception: pass
        return False

    def pump(s):
        end = time.time() + s
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)

    LOGS = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("EVTX_TEST_LOGS", "sample_logs")
    wanted = ["Security.evtx", "System.evtx", "Windows PowerShell.evtx"]
    files = [os.path.join(LOGS, f) for f in wanted if os.path.exists(os.path.join(LOGS, f))]
    if not files:
        files = sorted(glob.glob(os.path.join(LOGS, "*.evtx")))[:3]
    if not files:
        print("no logs — skipping"); return 0

    check("Timestamp column popup uses the hour key",
          ColumnFilterPopup.FILTERABLE.get(COL_TS) == "timestamp_hour")

    # The generic popup cap keeps the 1000 busiest values; hours must not be
    # capped that way (quiet hours would vanish).  1,500 one-event hours:
    from datetime import datetime, timedelta, timezone
    set_tz_config("utc")
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    synth = [{"timestamp": (t0 + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")}
             for i in range(1500)]
    box = {}
    wk = NormalColValueWorker(synth, "timestamp_hour")
    wk.finished.connect(box.update); wk.run()
    check("more than 1000 distinct hours are all kept", len(box) == 1500, f"{len(box)}")

    def values_normal(w):
        box = {}
        wk = NormalColValueWorker(list(w._active_events), "timestamp_hour")
        wk.finished.connect(box.update); wk.run()
        return box

    def values_jm(w):
        box = {}
        wk = ColValueWorker(w._hw_model._full_table, "timestamp_hour")
        wk.finished.connect(box.update); wk.run()
        return box

    def keep_one_hour(w, values, hour):
        """Drive the real popup: untick everything, tick one hour, press OK."""
        p = ColumnFilterPopup(COL_TS, values, parent=w)
        p.filterApplied.connect(w._on_col_filter_applied)
        p._check_none()
        leaf = next(c for c in p._checkboxes if c.property("filter_value") == hour)
        leaf.setChecked(True)
        n_leaves = len(p._checkboxes)
        sum_counts = sum(int(c._item.data(0, Qt.ItemDataRole.UserRole + 3) or 0)
                         for c in p._checkboxes)
        depth = 0
        node = leaf._item
        while node.parent() is not None:
            depth += 1; node = node.parent()
        p._apply()
        return n_leaves, sum_counts, depth

    def displayed_hours(model, n):
        out = set()
        for r in range(n):
            out.add(str(model.index(r, COL_TS).data() or "")[:13])
        return out

    def run_mode(label, w, get_values, get_model, total):
        for tz_label, cfg in (("UTC", ("utc",)), ("UTC+05:30", ("custom", "UTC", 330))):
            w._on_col_filter_applied(COL_TS, "clear", []); pump(0.5)
            set_tz_config(*cfg)
            w._col_value_cache = {}
            vals = get_values(w)
            check(f"{label} {tz_label}: hour values are 'YYYY-MM-DD HH'",
                  vals and all(len(k) == 13 and k[10] == " " for k in vals),
                  f"{len(vals)} hours, e.g. {sorted(vals)[:2]}")
            check(f"{label} {tz_label}: hour counts cover every event (no hour dropped)",
                  sum(vals.values()) == total, f"{sum(vals.values()):,} of {total:,}")
            # pick the QUIETEST hour: the one a top-N cap would have dropped
            hour, expect = min(vals.items(), key=lambda kv: (kv[1], kv[0]))
            n_leaves, leaf_sum, depth = keep_one_hour(w, vals, hour)
            check(f"{label} {tz_label}: every hour is a leaf at Year>Month>Day>Hour depth",
                  n_leaves == len(vals) and leaf_sum == total and depth == 4,
                  f"{n_leaves} leaves, depth {depth}")
            m = get_model(w)
            ok = wait_for(lambda: m().rowCount() == expect, 120)
            n = m().rowCount()
            check(f"{label} {tz_label}: keeping one hour shows exactly its events",
                  ok, f"hour {hour!r}: table {n:,}, tree said {expect:,}")
            hrs = displayed_hours(m(), n)
            check(f"{label} {tz_label}: every row shown is inside that hour",
                  hrs == {hour}, f"{sorted(hrs)[:3]}")
        w._on_col_filter_applied(COL_TS, "clear", []); pump(0.5)
        set_tz_config("utc")

    # ── Normal mode ──────────────────────────────────────────────────────────
    w = MainWindow()
    for f in files:
        w._add_path(f)
    w._on_parse_clicked()
    ok = wait_for(lambda: w._active_proxy is not None and w._active_proxy.rowCount() > 0, 420)
    pump(2)
    total = len(w._active_events)
    check("Normal: real logs parsed", ok and total > 0, f"{total:,} events")
    if ok:
        run_mode("Normal", w, values_normal, lambda w: (lambda: w._active_proxy), total)
    w.close(); pump(1)

    # ── Juggernaut mode ──────────────────────────────────────────────────────
    w2 = MainWindow()
    w2._launch_juggernaut_mode(files)
    ok = wait_for(lambda: w2._hw_model is not None and w2._hw_model.rowCount() > 0, 420)
    pump(2)
    total2 = w2._hw_model._full_table.num_rows if ok else 0
    check("Juggernaut: real logs loaded", ok and total2 > 0, f"{total2:,} events")
    if ok:
        run_mode("Juggernaut", w2, values_jm, lambda w: (lambda: w._hw_model), total2)
    w2.close(); pump(1)

    print("\n" + "=" * 60)
    bad = [n for n, ok in res if not ok]
    print(f"RESULT: {len(res)-len(bad)}/{len(res)} passed")
    for n in bad:
        print("  FAILED:", n)
    sys.stdout.flush()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
