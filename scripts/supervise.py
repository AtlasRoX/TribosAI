"""Keep one Tribos server running: start it, and start it again if it stops.

    python scripts/supervise.py --name backend --log logs/backend.log -- <command ...>

The server runs in its own process group (CREATE_NEW_PROCESS_GROUP on Windows, a new session on POSIX), so a
Ctrl+C sent to a console it shares cannot reach it, and the supervisor ignores Ctrl+C itself. When the server exits
for any reason it is started again after a short pause (a crash loop backs off up to 60 s). Stop it with
scripts/stop-tribos.ps1, which ends the supervisors before the servers.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import signal
import subprocess
import sys
import time


def _detach(log_path: str) -> bool:
    """Windows: start this supervisor again as an independent process and let the caller exit.

    Started through WMI and the venv launcher, the supervisor sat in a job object that ended a few minutes later
    (when the launcher or its WMI host exited), killing it without a trace while its server ran on unsupervised. The
    copy runs on the base interpreter (this script needs only the standard library), outside that job where Windows
    allows it, in its own process group with no console. Its lifetime is the same: until stopped or reboot."""
    base = getattr(sys, "_base_executable", None) or sys.executable
    pythonw = os.path.join(os.path.dirname(base), "pythonw.exe")
    exe = pythonw if os.path.exists(pythonw) else base
    argv = [exe, os.path.abspath(__file__), "--detached", *sys.argv[1:]]
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x8)
    for extra in (getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000), 0):
        try:
            subprocess.Popen(argv, creationflags=flags | extra, close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _log_exit(log_path, f"detached ({'outside the job' if extra else 'job breakaway refused; same job'})")
            return True
        except OSError:
            continue  # breakaway refused by the job: start the copy without it
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--detached", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        ap.error("no server command after --")
    if os.name == "nt" and not args.detached and _detach(args.log):
        return 0

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)

    os.makedirs(os.path.dirname(os.path.abspath(args.log)), exist_ok=True)
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True

    backoff = 2.0
    while True:
        started = time.monotonic()
        with open(args.log, "ab", buffering=0) as log:
            log.write(f"\n[supervise {dt.datetime.now():%Y-%m-%d %H:%M:%S}] starting {args.name}\n".encode())
            proc = subprocess.Popen(command, cwd=args.cwd, stdout=log, stderr=subprocess.STDOUT, **kwargs)
            code = proc.wait()
            log.write(f"[supervise {dt.datetime.now():%Y-%m-%d %H:%M:%S}] {args.name} exited with {code}; "
                      f"restarting in {backoff:.0f} s\n".encode())
        # A server that ran for a while restarts at once; one that keeps failing at start backs off.
        backoff = 2.0 if time.monotonic() - started > 60 else min(60.0, backoff * 2)
        time.sleep(backoff)


def _log_exit(log_path: str, what: str) -> None:
    try:
        with open(log_path, "ab", buffering=0) as log:
            log.write(f"[supervise {dt.datetime.now():%Y-%m-%d %H:%M:%S}] supervisor {what}\n".encode())
    except OSError:
        pass


if __name__ == "__main__":
    # A supervisor has no console: an exception or an exit would otherwise leave no trace at all.
    _log_path = next((sys.argv[i + 1] for i, a in enumerate(sys.argv[:-1]) if a == "--log"), "supervise.log")
    try:
        code = main()
    except BaseException as exc:  # noqa: BLE001 - recorded, then re-raised
        import traceback

        _log_exit(_log_path, "crashed:\n" + "".join(traceback.format_exception(exc)))
        raise
    _log_exit(_log_path, f"exited with {code}")
    sys.exit(code)
