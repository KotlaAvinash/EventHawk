"""A file that cannot be opened must say WHY, and what to do, in both modes.

Reported: dropping logs Windows will not let a normal user read produced
"Access is denied. (os error 5)" in Normal mode and only "file could not be
opened" in Juggernaut mode -- exact, but no cause and no next step.  Juggernaut
also added "A parse ABORT means ..." although nothing aborted.

What must hold:

  * explain_open_errors() recognises the usual causes from the OS text
    (access denied, file in use, file not found), counts the files per cause,
    and says nothing for unrelated problems;
  * through the real MainWindow, with a real permission-locked copy of a log
    (Windows only -- the lock is a file ACL):
      - Normal and Juggernaut both show the explanation, with the readable
        file still loaded beside the locked one;
      - with ONLY the locked file, the error still explains itself;
      - Juggernaut keeps the OS reason on the file's line and does not show
        the ABORT note for a file that never opened;
      - a clean parse shows no popup at all.

Run: QT_QPA_PLATFORM=offscreen python tests/test_open_error_messages.py [logs_dir]
"""
import glob, os, shutil, subprocess, sys, tempfile, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    res = []
    def check(name, ok, detail=""):
        res.append((name, bool(ok)))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"\n      {detail}" if detail else ""))

    from evtx_tool.core.open_errors import explain_open_errors, open_error_causes

    # ── 1. the explanation itself ─────────────────────────────────────────────
    samples = {
        "Parse error A.evtx: Access is denied. (os error 5)": ["access"],
        "B.evtx: [Errno 13] Permission denied: 'B.evtx'": ["access"],
        "Parse error C.evtx: The process cannot access the file because it is "
        "being used by another process. (os error 32)": ["in_use"],
        "D.evtx: The system cannot find the file specified. (os error 2)": ["missing"],
        "E.evtx: The system cannot find the path specified. (os error 3)": ["missing"],
        "F.evtx: parse aborted mid-file (invalid chunk header)": [],
        "Timeout (300s): G.evtx": [],
    }
    for text, want in samples.items():
        got = open_error_causes(text)
        check(f"cause of {text[:48]!r}… is {want or 'none'}", got == want, f"{got}")
    why = explain_open_errors(list(samples))
    check("each cause is explained once, with its file count",
          why.count("2 file(s) — “Access is denied”") == 1
          and why.count("1 file(s) — “In use”") == 1
          and why.count("2 file(s) — “Not found”") == 1, why)
    check("the access explanation says what to do",
          "Copy the file to a normal folder" in why and "Administrator" in why)
    check("nothing to explain gives an empty string",
          explain_open_errors(["F.evtx: parse aborted mid-file"]) == ""
          and explain_open_errors([]) == "")

    # ── 2. end to end with a really locked file (Windows file ACL) ───────────
    LOGS = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("EVTX_TEST_LOGS", "sample_logs")
    def has_events(p):
        try:
            import evtx
            return next(iter(evtx.PyEvtxParser(p).records()), None) is not None
        except Exception:
            return False
    real = [p for p in sorted(glob.glob(os.path.join(LOGS, "*.evtx")), key=os.path.getsize)
            if os.path.getsize(p) > 200_000 and has_events(p)][:2]
    if os.name != "nt" or len(real) < 2:
        print("  (not Windows or no corpus — end-to-end part skipped)")
        return finish(res)

    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    from evtx_tool.gui.main_window import MainWindow

    tmp = tempfile.mkdtemp(prefix="eh_locked_")
    locked = os.path.join(tmp, "Locked.evtx")
    readable = os.path.join(tmp, "Readable.evtx")
    shutil.copyfile(real[0], locked)
    shutil.copyfile(real[1], readable)
    # Only SYSTEM may read the copy: exactly what a normal user meets on
    # Windows' own log folder or on ACL-preserving evidence copies.
    subprocess.run(["icacls", locked, "/inheritance:r", "/grant:r", "*S-1-5-18:F"],
                   capture_output=True, check=True)
    try:
        try:
            open(locked, "rb").close()
            check("the copy is really locked", False, "still readable — test would prove nothing")
            return finish(res)
        except PermissionError:
            check("the copy is really locked", True)

        seen = []
        orig = {n: getattr(QMessageBox, n) for n in ("warning", "critical", "information")}
        for n in orig:
            setattr(QMessageBox, n, staticmethod(
                lambda *a, _n=n, **k: (seen.append((_n, str(a[2]))), QMessageBox.StandardButton.Ok)[1]))

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
            return rows, list(seen)

        EXPL = "“Access is denied”: Windows blocked reading the file"
        try:
            for mode in ("normal", "jm"):
                rows, pops = run(mode, [locked, readable])
                text = "\n".join(t for _, t in pops)
                check(f"{mode}: the readable file still loads beside the locked one", rows > 0, f"{rows:,} rows")
                check(f"{mode}: the popup explains the locked file", EXPL in text, text[:300])
                if mode == "jm":
                    check("jm: the file's line keeps the OS reason",
                          "file could not be opened (Access is denied" in text)
                    check("jm: no ABORT note for a file that never opened",
                          "parse ABORT" not in text)

                rows, pops = run(mode, [locked])
                text = "\n".join(t for _, t in pops)
                check(f"{mode}: only the locked file — nothing loads, and it says why",
                      rows == 0 and EXPL in text, text[:200])

                rows, pops = run(mode, [readable])
                check(f"{mode}: a clean parse shows no popup", rows > 0 and not pops,
                      f"{rows:,} rows, popups: {[k for k, _ in pops]}")
        finally:
            for n, f in orig.items():
                setattr(QMessageBox, n, f)
    finally:
        subprocess.run(["icacls", locked, "/reset"], capture_output=True)
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
