"""Unit tests for the pack launcher (no uv, no network, no server)."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_PATH = ROOT / "mcp_launcher.py"


def load_launcher():
    spec = importlib.util.spec_from_file_location("mcp_launcher", LAUNCHER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = load_launcher()


def test_argv_boots_the_server_module_quietly():
    argv = launcher.build_argv("/usr/bin/uv")

    assert argv == ["/usr/bin/uv", "run", "--quiet", "python", "-m", "mcp_server.server"]


def test_argv_forwards_extra_arguments():
    assert launcher.build_argv("uv", ["--help"])[-1] == "--help"


def test_server_directory_sits_next_to_the_launcher():
    assert launcher.SERVER_DIR == str(ROOT / "mcp_server")
    assert (Path(launcher.SERVER_DIR) / "mcp_server" / "server.py").is_file()


def test_missing_uv_fails_with_an_actionable_message(monkeypatch, capsys):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)

    with pytest.raises(SystemExit) as exit_info:
        launcher.main([])

    assert exit_info.value.code == 2
    assert launcher.MISSING_UV_MESSAGE in capsys.readouterr().err


def test_main_chdirs_and_execs_uv(monkeypatch):
    calls = {}
    monkeypatch.setattr(launcher, "resolve_uv", lambda: "/opt/uv")
    monkeypatch.setattr(launcher.os, "chdir", lambda path: calls.setdefault("cwd", path))
    monkeypatch.setattr(
        launcher.os, "execv", lambda path, argv: calls.setdefault("exec", (path, argv))
    )

    launcher.main([])

    assert calls["cwd"] == launcher.SERVER_DIR
    assert calls["exec"] == ("/opt/uv", launcher.build_argv("/opt/uv"))
