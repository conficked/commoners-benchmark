"""Lived-in learning pass for Hermes, run inside the finished task container.

Reopens the task's session (by id: the newest one-shot session by start time; `--continue` picks the
most recently *active* session, which after a /refine is the previously refined one) in Hermes's interactive CLI (on a pseudo-terminal, as a user would),
types /refine - Hermes's own on-demand run of the post-turn memory/skill review - waits for its
"Background review complete" log line, then /exit. Prints that line (it carries the review's usage).

usage: python3 refine.py <workdir>
"""
import os
import pty
import re
import select
import sqlite3
import sys
import time
from pathlib import Path

LOGS = Path("/tmp/hermes/logs")
DONE = re.compile(r"Background review complete:.*|Background memory/skill review failed:.*")


def log_sizes():
    return {p: p.stat().st_size for p in LOGS.glob("**/*.log")} if LOGS.exists() else {}


def new_log_match(before):
    for p in LOGS.glob("**/*.log"):
        with p.open("rb") as f:
            f.seek(before.get(p, 0))
            m = DONE.search(f.read().decode("utf-8", "replace"))
            if m:
                return m.group(0)
    return None


def task_session():
    db = sqlite3.connect("file:/tmp/hermes/state.db?mode=ro", uri=True)
    row = db.execute("select id from sessions where source = 'oneshot' order by started_at desc limit 1").fetchone()
    return row[0] if row else None


def main():
    workdir = sys.argv[1]
    session = task_session()
    if not session:
        print("NO TASK SESSION")
        sys.exit(1)
    env = dict(os.environ, TERM="xterm-256color", COLUMNS="160", LINES="50",
               HERMES_HOME="/tmp/hermes", PATH=f"/root/.local/bin:{os.environ.get('PATH', '')}")
    out = bytearray()
    line = None
    # A session cut off by the task timeout reopens with its killed turn still marked running, and
    # /refine is refused ("can't run mid-turn"; /stop doesn't clear it). Hermes resolves that turn as
    # interrupted when the session is closed, so close it and reopen once.
    for attempt in range(2):
        line, refused = refine_once(session, workdir, env, out)
        if not refused:
            break
    Path("/tmp/refine-pty.txt").write_bytes(bytes(out))
    print(f"{line or 'REVIEW NOT OBSERVED'} session={session}")
    sys.exit(0 if line and "complete" in line else 1)


def refine_once(session, workdir, env, out):
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(workdir)
        os.execvpe("hermes", ["hermes", "--yolo", "chat", "--resume", session], env)

    def pump(seconds):
        end = time.time() + seconds
        got = False
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.5)
            if r:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    return got
                if not chunk:
                    return got
                out.extend(chunk)
                got = True
        return got

    first = len(out)
    start = time.time()
    while time.time() - start < 180 and "\u276f".encode() not in out[first:]:
        pump(2)
    pump(5)
    before = log_sizes()
    started = refused = False
    for _ in range(3):
        mark = len(out)
        os.write(fd, b"/refine")
        pump(1)
        os.write(fd, b"\r")
        end = time.time() + 30
        while time.time() < end and b"Reviewing this conversation" not in out[mark:] and b"can't run mid-turn" not in out[mark:]:
            pump(2)
        if b"Reviewing this conversation" in out[mark:]:
            started = True
            break
        if b"can't run mid-turn" in out[mark:]:
            refused = True
            break

    line = None
    if started:
        end = time.time() + 900
        while time.time() < end and not line:
            pump(3)
            line = new_log_match(before)

    os.write(fd, b"/exit\r")
    end = time.time() + 60
    while time.time() < end:
        pump(2)
        if os.waitpid(pid, os.WNOHANG)[0]:
            break
    else:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
    return line, refused and not started


if __name__ == "__main__":
    main()
