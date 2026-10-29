"""An EMPTY log is not missing evidence; a damaged one still is.

Reported: loading ordinary copied logs raised "Some evidence did NOT fully
load ... State.evtx: 1 record(s) declared in chunk headers were not parsed".
State.evtx is empty -- Windows initialises a log's first chunk before anything
is written, with the record-ID placeholder 0xFFFFFFFFFFFFFFFF as both first and
last ID.  The chunk-header accounting read that as a one-record range, so every
empty log (102 of 272 on the machine where this was found; 0 genuinely short)
reported a missing record.  A forensic tool that warns on a third of a case
teaches the examiner to click past the warning that matters.

What must hold:

  * read_chunk_index() treats a placeholder header over an empty record area
    as slack (no records), but a placeholder header over a record area that
    holds data as DAMAGED -- a header rewrite must not make data "empty";
  * expected_record_count() of an empty log is 0;
  * through the real MainWindow, in Normal and Juggernaut mode:
      - an empty log next to a clean one raises no integrity popup;
      - a log with one corrupted record still raises it (real findings kept);
      - a placeholder header over real records still loads every record.

Run: QT_QPA_PLATFORM=offscreen python tests/test_empty_log_integrity.py [logs_dir]
"""
import glob, os, re, shutil, struct, sys, tempfile, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ALL1 = 0xFFFFFFFFFFFFFFFF
HDR, CHUNK = 4096, 65536


def main() -> int:
    res = []
    def check(name, ok, detail=""):
        res.append((name, bool(ok)))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"\n      {detail}" if detail else ""))

    from evtx_tool.core.chunk_salvage import read_chunk_index, expected_record_count

    LOGS = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("EVTX_TEST_LOGS", "sample_logs")
    corpus = sorted(glob.glob(os.path.join(LOGS, "*.evtx")))

    def only_placeholder_chunks(p):
        try:
            with open(p, "rb") as fh:
                d = fh.read(HDR + CHUNK)
            return (len(d) >= HDR + 0x38 and d[HDR:HDR + 8] == b"ElfChnk\x00"
                    and struct.unpack_from("<QQ", d, HDR + 0x18) == (ALL1, ALL1))
        except OSError:
            return False

    empty_src = next((p for p in corpus if only_placeholder_chunks(p)), None)
    multi = [p for p in corpus if os.path.getsize(p) >= HDR + 6 * CHUNK]
    if empty_src is None or not multi:
        print("  (corpus lacks an empty log or a multi-chunk log — skipped)")
        return finish(res)
    multi_src = min(multi, key=os.path.getsize)

    tmp = tempfile.mkdtemp(prefix="eh_emptylog_")
    try:
        empty = os.path.join(tmp, "EmptyLog.evtx"); shutil.copyfile(empty_src, empty)
        clean = os.path.join(tmp, "CleanLog.evtx"); shutil.copyfile(multi_src, clean)

        def chunk_with_records(path):
            idx = read_chunk_index(path)
            return next(c for c, a, b in idx["valid"] if b - a >= 10)

        # one record's signature broken inside an otherwise valid chunk
        corrupt = os.path.join(tmp, "OneRecordCorrupt.evtx"); shutil.copyfile(clean, corrupt)
        c = chunk_with_records(corrupt)
        d = bytearray(open(corrupt, "rb").read())
        base = HDR + c * CHUNK
        sigs = [m.start() for m in re.finditer(rb"\x2a\x2a\x00\x00", bytes(d[base + 0x200:base + CHUNK]))]
        v = base + 0x200 + sigs[4]
        d[v:v + 4] = b"XXXX"
        open(corrupt, "wb").write(d)

        # placeholder IDs written over a chunk that holds records
        rewritten = os.path.join(tmp, "PlaceholderOverData.evtx"); shutil.copyfile(clean, rewritten)
        d = bytearray(open(rewritten, "rb").read())
        struct.pack_into("<QQ", d, HDR + c * CHUNK + 0x18, ALL1, ALL1)
        open(rewritten, "wb").write(d)

        # ── 1. chunk accounting ───────────────────────────────────────────────
        idx = read_chunk_index(empty)
        check("an empty log's placeholder chunk is slack, not a record range",
              0 in idx["slack"] and not idx["valid"] and not idx["damaged"], f"{idx}")
        check("an empty log is expected to hold 0 records",
              expected_record_count(empty) == (0, 0), f"{expected_record_count(empty)}")
        idx = read_chunk_index(rewritten)
        check("a placeholder header over real records is DAMAGED, not slack",
              c in idx["damaged"] and c not in idx["slack"], f"chunk {c}: {idx['damaged']}")

        # ── 2. through the real window, both engines ─────────────────────────
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication([])
        from evtx_tool.gui.main_window import MainWindow

        seen = []
        orig = {n: getattr(QMessageBox, n) for n in ("warning", "critical", "information")}
        for n in orig:
            setattr(QMessageBox, n, staticmethod(
                lambda *a, _n=n, **k: (seen.append(str(a[2])), QMessageBox.StandardButton.Ok)[1]))

        def pump(s, until=None):
            end = time.time() + s
            while time.time() < end:
                app.processEvents(); time.sleep(0.02)
                if until and until():
                    return True
            return False

        def run(mode, files):
            seen.clear()
            w = MainWindow()
            if mode == "normal":
                for f in files:
                    w._add_path(f)
                w._on_parse_clicked()
                pump(180, lambda: bool(seen) or (w._active_proxy is not None
                                                 and w._active_proxy.rowCount() > 0
                                                 and w._btn_parse.isEnabled()))
                pump(2)
                rows = w._active_proxy.rowCount() if w._active_proxy is not None else 0
            else:
                w._launch_juggernaut_mode(files)
                pump(240, lambda: bool(seen) or (w._hw_model is not None
                                                 and w._hw_model.rowCount() > 0))
                pump(3)
                rows = w._hw_model.rowCount() if w._hw_model is not None else 0
            w.close(); pump(0.5)
            return rows, "\n".join(seen)

        try:
            clean_rows, _ = run("normal", [clean])
            for mode in ("normal", "jm"):
                rows, text = run(mode, [empty, clean])
                check(f"{mode}: an empty log next to a clean one raises no popup",
                      rows == clean_rows and not text, text[:200])
                rows, text = run(mode, [corrupt])
                check(f"{mode}: one corrupted record is still reported",
                      "OneRecordCorrupt.evtx" in text and "not parsed" in text, text[:200])
                rows, text = run(mode, [rewritten])
                check(f"{mode}: a placeholder header over real records still loads them all",
                      rows == clean_rows, f"{rows:,} of {clean_rows:,}")
        finally:
            for n, f in orig.items():
                setattr(QMessageBox, n, f)
    finally:
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
