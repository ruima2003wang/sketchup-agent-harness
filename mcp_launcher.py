"""stdio entry point for the capability pack.

The host's pack contract spawns exactly one script file from the pack root with an
allowlisted interpreter, so the launcher lives here and hands the session to the
harness' own uv-managed environment. `os.execv` keeps the stdio pipes untouched
(no wrapper process between the host and the server).
"""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.join(ROOT, "mcp_server")


def main() -> None:
    uv = shutil.which("uv")
    if not uv:
        sys.stderr.write("sketchup-agent-harness: `uv` is required to start the MCP server\n")
        raise SystemExit(2)
    os.chdir(SERVER_DIR)
    os.execv(uv, [uv, "run", "--quiet", "python", "-m", "mcp_server.server", *sys.argv[1:]])


if __name__ == "__main__":
    main()
