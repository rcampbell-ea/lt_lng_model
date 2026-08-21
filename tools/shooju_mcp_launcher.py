"""
shooju_mcp_launcher.py
-----------------------
Runs upstream's ``tools/shooju_mcp_server.py`` from this project's .mcp.json.

A stdio MCP server is a subprocess of the client, so its cwd and sys.path are
whatever the client gave it. Pointing this project's ``.mcp.json`` straight at
upstream's server script would start it with THIS project's working directory,
and it would then fail to find its own relative config and credentials — not
by crashing, but silently (see Appendix A.6 of the build plan). This launcher
resolves the upstream project directory, chdir's into it, puts it on
sys.path, and then execs upstream's server exactly as upstream would.

Credentials stay in the upstream ``.env`` on this machine; this launcher never
reads or copies them — that is entirely upstream's ``engine.env_config``.

Usage:
    python tools/shooju_mcp_launcher.py             # start the server
    python tools/shooju_mcp_launcher.py --check      # verify resolution only
"""

from __future__ import annotations

import argparse
import os
import runpy
import sys
from pathlib import Path

DEFAULT_UPSTREAM_DIR = r"C:\Users\robert.campbell\PycharmProjects\upstream"


def resolve_upstream_dir() -> Path:
    raw = os.environ.get("UPSTREAM_DIR", DEFAULT_UPSTREAM_DIR)
    return Path(raw).resolve()


def resolve_server_script(upstream_dir: Path) -> Path:
    return upstream_dir / "tools" / "shooju_mcp_server.py"


def check(upstream_dir: Path, server_script: Path) -> bool:
    ok = True
    if not upstream_dir.is_dir():
        print(f"UPSTREAM_DIR does not resolve to a directory: {upstream_dir}", file=sys.stderr)
        ok = False
    if not server_script.is_file():
        print(f"upstream server script not found: {server_script}", file=sys.stderr)
        ok = False
    if ok:
        print(f"resolved upstream dir:    {upstream_dir}")
        print(f"resolved server script:   {server_script}")
        print(f"running interpreter:      {sys.executable}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Launcher for upstream's Shooju MCP server")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the upstream server resolves, then exit without starting it.",
    )
    args = parser.parse_args()

    upstream_dir = resolve_upstream_dir()
    server_script = resolve_server_script(upstream_dir)

    if args.check:
        sys.exit(0 if check(upstream_dir, server_script) else 1)

    if not server_script.is_file():
        print(f"upstream server script not found: {server_script}", file=sys.stderr)
        sys.exit(1)

    os.chdir(upstream_dir)
    sys.path.insert(0, str(upstream_dir))
    runpy.run_path(str(server_script), run_name="__main__")


if __name__ == "__main__":
    main()
