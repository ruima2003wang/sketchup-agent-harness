"""stdio entry point for the capability pack.

The host spawns exactly one script file from the pack root with an allowlisted
interpreter, so the launcher lives here and hands the session to the harness'
own uv-managed environment. ``os.execv`` keeps the stdio pipes untouched (no
wrapper process between the host and the server).
"""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(ROOT, "mcp_server")
MISSING_UV_MESSAGE = "sketchup-agent-harness: `uv` is required to start the MCP server\n"


def resolve_uv():
    """Absolute path of uv, or None when it is not on PATH."""
    return shutil.which("uv")


def build_argv(uv, extra=()):
    """argv for the harness server; `uv run` owns the environment and the sync."""
    return [uv, "run", "--quiet", "python", "-m", "mcp_server.server", *extra]


def main(argv=None):
    uv = resolve_uv()
    if not uv:
        sys.stderr.write(MISSING_UV_MESSAGE)
        raise SystemExit(2)
    os.chdir(SERVER_DIR)
    os.execv(uv, build_argv(uv, sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    main()
