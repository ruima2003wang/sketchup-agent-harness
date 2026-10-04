"""SketchUp Ruby bridge installation helpers.

The bridge runs inside SketchUp's bundled Ruby. It installs into the
per-user SketchUp Plugins directory, which is macOS-specific on macOS
(``~/Library/Application Support/SketchUp <ver>/SketchUp/Plugins``) and
Windows-specific on Windows
(``%APPDATA%\\SketchUp\\SketchUp <ver>\\SketchUp\\Plugins``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_server.bridge.socket_bridge import (
    DEFAULT_BRIDGE_HOST,
    DEFAULT_BRIDGE_PORT,
    bridge_endpoint_available,
)


IGNORED_BRIDGE_PATTERNS = (
    ".bundle",
    "vendor",
    "*.gem",
    "*.log",
    ".DS_Store",
)
LOADER_FILENAME = "su_bridge.rb"
SKETCHUP_VERSION_RE = re.compile(r"\bSketchUp\s+(\d{4})\b")
SKETCHUP_EXE_NAME = "SketchUp.exe"


def is_windows() -> bool:
    """Return True when running on Windows."""
    return sys.platform.startswith("win")


def repo_root_from_package() -> Path:
    """Return the source checkout root when running from this repository."""
    return Path(__file__).resolve().parents[2]


def default_bridge_source() -> Path:
    """Return the default bridge source directory."""
    repo_source = repo_root_from_package() / "su_bridge"
    if repo_source.exists():
        return repo_source
    return packaged_bridge_source()


def packaged_bridge_source() -> Path:
    """Return the packaged bridge runtime directory from an installed wheel."""
    return Path(__file__).resolve().parent / "packaged" / "su_bridge"


def sketchup_version_from_name(name: str) -> str | None:
    """Return the SketchUp year version embedded in a file or directory name."""
    match = SKETCHUP_VERSION_RE.search(name)
    return match.group(1) if match else None


def version_sort_value(version: str | None) -> int:
    """Return a sortable integer for a SketchUp year version."""
    if version is None:
        return -1
    try:
        return int(version)
    except ValueError:
        return -1


def installed_sketchup_app_versions(
    applications_dir: str | Path = "/Applications",
    platform: str | None = "macos",
) -> list[str]:
    """Return detected SketchUp app versions, newest first.

    Defaults to the macOS layout; pass ``platform=resolve_platform()`` to scan
    the host platform, or ``platform="windows"`` for Windows explicitly.
    """
    if resolve_platform(platform) == "windows":
        return windows_installed_sketchup_app_versions()

    root = Path(applications_dir).expanduser()
    if not root.exists():
        return []

    versions: set[str] = set()
    for path in root.glob("SketchUp*"):
        version = sketchup_version_from_name(path.name)
        if version is None:
            continue
        if path.suffix == ".app" and path.is_dir():
            versions.add(version)
            continue
        if path.is_dir() and (path / "SketchUp.app").is_dir():
            versions.add(version)

    return sorted(versions, key=version_sort_value, reverse=True)


def sketchup_app_path(
    sketchup_version: str | None = None,
    applications_dir: str | Path = "/Applications",
    platform: str | None = "macos",
) -> Path | None:
    """Return the detected SketchUp executable path, newest first by default.

    Defaults to the macOS layout; pass ``platform=resolve_platform()`` to scan
    the host platform.
    """
    if resolve_platform(platform) == "windows":
        return windows_sketchup_app_path(sketchup_version)

    root = Path(applications_dir).expanduser()
    if not root.exists():
        return None

    candidates: list[tuple[int, str, Path]] = []
    for path in root.glob("SketchUp*"):
        version = sketchup_version_from_name(path.name)
        if version is None:
            continue
        if sketchup_version is not None and version != sketchup_version:
            continue
        app_path = path if path.suffix == ".app" else path / "SketchUp.app"
        if app_path.is_dir():
            candidates.append((version_sort_value(version), version, app_path))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def sketchup_version_from_app_path(app_path: str | Path) -> str | None:
    """Infer the SketchUp version from a SketchUp.app or SketchUp.exe path."""
    path = Path(app_path).expanduser()
    for candidate in (path.parent.name, path.name):
        version = sketchup_version_from_name(candidate)
        if version is not None:
            return version
    return None


def resolve_platform(platform: str | None = None) -> str:
    """Resolve the target platform, defaulting to the current one.

    The per-platform helpers below default to ``"macos"`` so their behavior is
    deterministic; top-level entrypoints call this to auto-detect the host.
    """
    if platform:
        return platform
    return "windows" if is_windows() else "macos"


def windows_program_files_dirs() -> list[Path]:
    """Return candidate Windows Program Files roots."""
    roots: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        value = os.environ.get(env_name)
        if not value:
            continue
        path = Path(value)
        if path not in roots:
            roots.append(path)
    return roots


def windows_installed_sketchup_app_versions(
    program_files_dirs: list[str | Path] | None = None,
) -> list[str]:
    """Return detected Windows SketchUp versions, newest first."""
    roots = (
        [Path(root) for root in program_files_dirs]
        if program_files_dirs is not None
        else windows_program_files_dirs()
    )
    versions: set[str] = set()
    for root in roots:
        sketchup_root = root / "SketchUp"
        if not sketchup_root.is_dir():
            continue
        for path in sketchup_root.glob("SketchUp *"):
            version = sketchup_version_from_name(path.name)
            if version is None:
                continue
            if (path / SKETCHUP_EXE_NAME).exists():
                versions.add(version)
    return sorted(versions, key=version_sort_value, reverse=True)


def windows_sketchup_app_path(
    sketchup_version: str | None = None,
    program_files_dirs: list[str | Path] | None = None,
) -> Path | None:
    """Return the detected Windows SketchUp.exe path, newest first by default."""
    roots = (
        [Path(root) for root in program_files_dirs]
        if program_files_dirs is not None
        else windows_program_files_dirs()
    )
    candidates: list[tuple[int, str, Path]] = []
    for root in roots:
        sketchup_root = root / "SketchUp"
        if not sketchup_root.is_dir():
            continue
        for path in sketchup_root.glob("SketchUp *"):
            version = sketchup_version_from_name(path.name)
            if version is None:
                continue
            if sketchup_version is not None and version != sketchup_version:
                continue
            exe = path / SKETCHUP_EXE_NAME
            if exe.exists():
                candidates.append((version_sort_value(version), version, exe))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def windows_sketchup_appdata_dir(appdata: str | Path | None = None) -> Path:
    """Return the Windows roaming AppData directory."""
    if appdata is not None:
        return Path(appdata).expanduser()
    value = os.environ.get("APPDATA")
    if value:
        return Path(value)
    return Path.home() / "AppData" / "Roaming"


def windows_sketchup_plugins_dir_for_version(
    version: str,
    appdata: str | Path | None = None,
) -> Path:
    """Return the canonical Windows Plugins directory for one SketchUp version."""
    return (
        windows_sketchup_appdata_dir(appdata)
        / "SketchUp"
        / f"SketchUp {version}"
        / "SketchUp"
        / "Plugins"
    )


def windows_installed_sketchup_plugin_dirs(
    appdata: str | Path | None = None,
) -> list[Path]:
    """Return detected Windows SketchUp plugin directories, newest first."""
    sketchup_root = windows_sketchup_appdata_dir(appdata) / "SketchUp"
    candidates: list[Path] = []
    if sketchup_root.is_dir():
        for app_dir in sketchup_root.glob("SketchUp *"):
            plugins_dir = app_dir / "SketchUp" / "Plugins"
            if plugins_dir.is_dir():
                candidates.append(plugins_dir)

    installed_versions = windows_installed_sketchup_app_versions()
    installed_rank = {version: index for index, version in enumerate(installed_versions)}

    def sort_key(path: Path) -> tuple[int, int, int, str]:
        version = sketchup_version_from_name(path.parent.parent.name)
        if version in installed_rank:
            return (0, installed_rank[version], 0, str(path))
        return (1, 0, -version_sort_value(version), str(path))

    return sorted(candidates, key=sort_key)


def windows_default_plugins_dir(
    sketchup_version: str | None = None,
    appdata: str | Path | None = None,
) -> Path:
    """Return the target Windows SketchUp Plugins directory."""
    if sketchup_version:
        return windows_sketchup_plugins_dir_for_version(sketchup_version, appdata)

    app_versions = windows_installed_sketchup_app_versions()
    if app_versions:
        return windows_sketchup_plugins_dir_for_version(app_versions[0], appdata)

    detected = windows_installed_sketchup_plugin_dirs(appdata)
    if detected:
        return detected[0]

    return windows_sketchup_plugins_dir_for_version("2022", appdata)


def windows_sketchup_template_path(app_exe: str | Path) -> Path | None:
    """Return a bundled Windows SketchUp template for launching a model window."""
    install_dir = Path(app_exe).expanduser().parent
    root = install_dir / "resources"
    if not root.exists():
        root = install_dir / "Resources"
    if not root.exists():
        return None

    preferred_locales = ["en-US", "en", "zh-cn", "zh_CN", "zh-CN", "zh-TW"]
    preferred_templates = ["Temp01b - Simple.skp", "Temp01a - Simple.skp"]
    for locale in preferred_locales:
        for template_name in preferred_templates:
            candidate = root / locale / "Templates" / template_name
            if candidate.exists():
                return candidate

    matches = sorted(root.glob("*/Templates/Temp01b - Simple.skp"))
    if matches:
        return matches[0]
    matches = sorted(root.glob("*/Templates/*.skp"))
    return matches[0] if matches else None


def quarantine_entries(path: str | Path, limit: int = 20) -> list[str]:
    """Return macOS quarantine xattr lines for a path, when xattr is available."""
    if shutil.which("xattr") is None:
        return []
    target = Path(path).expanduser()
    if not target.exists():
        return []
    completed = subprocess.run(
        ["xattr", "-lr", str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    entries = [
        line
        for line in output.splitlines()
        if "com.apple.quarantine" in line
    ]
    return entries[:limit]


def clear_quarantine(path: str | Path) -> dict[str, Any]:
    """Remove macOS quarantine xattrs from a SketchUp app path."""
    if shutil.which("xattr") is None:
        return {"cleared": False, "available": False, "error": "xattr is not available."}
    target = Path(path).expanduser()
    completed = subprocess.run(
        ["xattr", "-dr", "com.apple.quarantine", str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "cleared": completed.returncode == 0,
        "available": True,
        "returncode": completed.returncode,
        "stderr": completed.stderr.strip(),
    }


def sketchup_preferences_dir(
    sketchup_version: str | None = None,
    home: str | Path | None = None,
) -> Path:
    """Return the macOS SketchUp preferences directory for one version."""
    version = sketchup_version or "2024"
    return (
        (Path(home).expanduser() if home is not None else Path.home())
        / "Library"
        / "Application Support"
        / f"SketchUp {version}"
        / "SketchUp"
    )


def suppress_update_check(
    sketchup_version: str | None = None,
    home: str | Path | None = None,
) -> dict[str, Any]:
    """Suppress SketchUp update prompts that block non-interactive bridge startup."""
    preferences_dir = sketchup_preferences_dir(sketchup_version, home=home)
    result: dict[str, Any] = {
        "preferences_dir": str(preferences_dir),
        "updated": False,
        "files": [],
    }

    private_path = preferences_dir / "PrivatePreferences.json"
    if private_path.exists():
        data = json.loads(private_path.read_text(encoding="utf-8"))
        root = data.setdefault("This Computer Only", {})
        changes: dict[str, Any] = {}
        auto_update = root.setdefault("AutoUpdate", {})
        previous_remind_on = auto_update.get("RemindOn")
        auto_update["RemindOn"] = "2099-01-01T00:00:00"
        changes["AutoUpdate.RemindOn"] = {
            "previous": previous_remind_on,
            "current": auto_update["RemindOn"],
        }
        common = root.setdefault("Common", {})
        previous_suppress = common.get("SuppressVersionWarning")
        common["SuppressVersionWarning"] = True
        changes["Common.SuppressVersionWarning"] = {
            "previous": previous_suppress,
            "current": True,
        }
        preferences = root.setdefault("Preferences", {})
        previous_last_check = preferences.get("LastUpdateCheck")
        preferences["LastUpdateCheck"] = 9999999999.0
        changes["Preferences.LastUpdateCheck"] = {
            "previous": previous_last_check,
            "current": preferences["LastUpdateCheck"],
        }
        private_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        result["updated"] = True
        result["files"].append({"path": str(private_path), "changes": changes})

    shared_path = preferences_dir / "SharedPreferences.json"
    if shared_path.exists():
        data = json.loads(shared_path.read_text(encoding="utf-8"))
        preferences = data.setdefault("Shared for All Computers", {}).setdefault(
            "Preferences",
            {},
        )
        previous_check = preferences.get("CheckForUpdates")
        preferences["CheckForUpdates"] = False
        shared_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        result["updated"] = True
        result["files"].append(
            {
                "path": str(shared_path),
                "changes": {
                    "Preferences.CheckForUpdates": {
                        "previous": previous_check,
                        "current": False,
                    }
                },
            }
        )

    return result


def sketchup_template_path(app_path: str | Path) -> Path | None:
    """Return a bundled SketchUp template suitable for launching a model window."""
    if str(app_path).lower().endswith(".exe"):
        return windows_sketchup_template_path(app_path)

    root = Path(app_path).expanduser() / "Contents" / "Resources"
    if not root.exists():
        return None

    preferred_locales = ["en-US", "en", "zh-cn", "zh_CN", "zh-CN", "zh-TW"]
    preferred_templates = ["Temp01b - Simple.skp", "Temp01a - Simple.skp"]
    for locale in preferred_locales:
        for template_name in preferred_templates:
            candidate = root / locale / "Templates" / template_name
            if candidate.exists():
                return candidate

    matches = sorted(root.glob("*/Templates/Temp01b - Simple.skp"))
    if matches:
        return matches[0]
    matches = sorted(root.glob("*/Templates/*.skp"))
    return matches[0] if matches else None


def prepare_launch_model(
    app_path: str | Path,
    model_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a model path for SketchUp launch, copying a template when needed."""
    if model_path is not None:
        path = Path(model_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"SketchUp model not found: {path}")
        return {
            "model_path": str(path),
            "template_source": None,
            "copied_template": False,
        }

    template = sketchup_template_path(app_path)
    if template is None:
        raise FileNotFoundError(f"No bundled SketchUp template found in {app_path}")
    handle, target_name = tempfile.mkstemp(
        prefix="sketchup-agent-harness-launch-",
        suffix=".skp",
    )
    os.close(handle)
    Path(target_name).unlink(missing_ok=True)
    target = Path(target_name)
    shutil.copyfile(template, target)
    return {
        "model_path": str(target),
        "template_source": str(template),
        "copied_template": True,
    }


def launch_bridge(
    sketchup_version: str | None = None,
    app_path: str | Path | None = None,
    model_path: str | Path | None = None,
    host: str = DEFAULT_BRIDGE_HOST,
    port: int = DEFAULT_BRIDGE_PORT,
    timeout: float = 90.0,
    clear_app_quarantine: bool = False,
    suppress_app_update_check: bool = False,
    platform: str | None = None,
) -> dict[str, Any]:
    """Launch SketchUp with a model file and wait for the bridge endpoint.

    On macOS the app bundle is opened with ``open -a``; on Windows the
    ``SketchUp.exe`` path is launched directly. The bridge is then awaited as
    a loopback TCP endpoint.
    """
    resolved_platform = resolve_platform(platform)
    app = (
        Path(app_path).expanduser().resolve()
        if app_path is not None
        else sketchup_app_path(sketchup_version, platform=resolved_platform)
    )
    if app is None or not app.exists():
        raise FileNotFoundError("SketchUp app was not found.")
    effective_version = sketchup_version or sketchup_version_from_app_path(app)

    quarantine_before = quarantine_entries(app)
    quarantine_clear_result = None
    if clear_app_quarantine and quarantine_before:
        quarantine_clear_result = clear_quarantine(app)
    quarantine_after = quarantine_entries(app)
    update_check_result = None
    # Update prompts are a macOS-only blocker for non-interactive startup.
    if suppress_app_update_check and resolved_platform != "windows":
        update_check_result = suppress_update_check(effective_version)
    launch_model = prepare_launch_model(app, model_path)

    if resolved_platform == "windows":
        # Launch the GUI without blocking; SketchUp keeps running after this
        # returns.
        subprocess.Popen([str(app), launch_model["model_path"]])
        open_returncode = None
    else:
        completed = subprocess.run(
            ["open", "-a", str(app), launch_model["model_path"]],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
        open_returncode = completed.returncode

    started = time.monotonic()
    socket_ready = bridge_endpoint_available(
        host=host,
        port=port,
    )
    while timeout > 0 and not socket_ready:
        if time.monotonic() - started >= timeout:
            break
        time.sleep(1)
        socket_ready = bridge_endpoint_available(
            host=host,
            port=port,
        )

    possible_blockers: list[str] = []
    if not socket_ready:
        possible_blockers.extend(
            [
                "SketchUp may still be on the welcome screen instead of a model window.",
                "A modal dialog such as an update prompt, sign-in prompt, or license prompt may be blocking plugin loading.",
                "The Ruby bridge may not be installed or enabled in the selected SketchUp version.",
            ]
        )
        if quarantine_after:
            possible_blockers.append(
                "macOS quarantine attributes are still present; rerun with --clear-quarantine."
            )
        if suppress_app_update_check and resolved_platform != "windows":
            possible_blockers.append(
                "If SketchUp shows an update prompt, rerun with --suppress-update-check."
            )

    return {
        "app_path": str(app),
        "sketchup_version": effective_version,
        "platform": resolved_platform,
        "model_path": launch_model["model_path"],
        "template_source": launch_model["template_source"],
        "copied_template": launch_model["copied_template"],
        "host": host,
        "port": port,
        "endpoint": f"tcp://{host}:{port}",
        "socket_ready": socket_ready,
        "timeout": timeout,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "quarantine_present": bool(quarantine_after),
        "quarantine_entries": quarantine_after,
        "quarantine_cleared": quarantine_clear_result,
        "update_check_suppressed": update_check_result,
        "open_returncode": open_returncode,
        "possible_blockers": possible_blockers,
    }


def sketchup_plugins_dir_for_version(home: str | Path, version: str) -> Path:
    """Return the canonical macOS Plugins directory for one SketchUp version."""
    return (
        Path(home).expanduser()
        / "Library"
        / "Application Support"
        / f"SketchUp {version}"
        / "SketchUp"
        / "Plugins"
    )


def installed_sketchup_plugin_dirs(
    home: str | Path | None = None,
    applications_dir: str | Path = "/Applications",
    platform: str | None = "macos",
    appdata: str | Path | None = None,
) -> list[Path]:
    """Return detected SketchUp plugin directories, newest first.

    Defaults to the macOS layout; pass ``platform=resolve_platform()`` to scan
    the host platform.
    """
    if resolve_platform(platform) == "windows":
        return windows_installed_sketchup_plugin_dirs(appdata)

    home_path = Path(home).expanduser() if home is not None else Path.home()
    app_support = home_path / "Library" / "Application Support"
    candidates: list[Path] = []

    for app_dir in app_support.glob("SketchUp *"):
        if not app_dir.is_dir():
            continue
        plugins_dir = app_dir / "SketchUp" / "Plugins"
        if plugins_dir.exists():
            candidates.append(plugins_dir)

    legacy_root = app_support / "SketchUp"
    if legacy_root.exists():
        for app_dir in legacy_root.glob("SketchUp *"):
            plugins_dir = app_dir / "SketchUp" / "Plugins"
            if plugins_dir.exists():
                candidates.append(plugins_dir)

    installed_versions = installed_sketchup_app_versions(applications_dir)
    installed_rank = {version: index for index, version in enumerate(installed_versions)}

    def sort_key(path: Path) -> tuple[int, int, int, str]:
        version = sketchup_version_from_name(path.parent.parent.name)
        if version in installed_rank:
            return (0, installed_rank[version], 0, str(path))
        return (1, 0, -version_sort_value(version), str(path))

    return sorted(candidates, key=sort_key)


def default_plugins_dir(
    sketchup_version: str | None = None,
    home: str | Path | None = None,
    applications_dir: str | Path = "/Applications",
    platform: str | None = "macos",
    appdata: str | Path | None = None,
) -> Path:
    """Return the target SketchUp Plugins directory.

    Defaults to the macOS layout; pass ``platform=resolve_platform()`` to target
    the host platform.
    """
    if resolve_platform(platform) == "windows":
        return windows_default_plugins_dir(sketchup_version, appdata)

    home_path = Path(home).expanduser() if home is not None else Path.home()
    if sketchup_version:
        return sketchup_plugins_dir_for_version(home_path, sketchup_version)

    app_versions = installed_sketchup_app_versions(applications_dir)
    if app_versions:
        return sketchup_plugins_dir_for_version(home_path, app_versions[0])

    detected = installed_sketchup_plugin_dirs(home_path, applications_dir)
    if detected:
        return detected[0]

    return sketchup_plugins_dir_for_version(home_path, "2024")


def bridge_loader_content() -> str:
    """Return the SketchUp Plugins root loader for the installed bridge."""
    return """# frozen_string_literal: true

require "tmpdir"

log_path = ENV.fetch("SU_BRIDGE_LOADER_LOG", File.join(Dir.tmpdir, "su_bridge_loader.log"))

# Logging must never break bridge startup (the temp directory may be
# unwritable on locked-down hosts).
su_bridge_log = lambda do |message|
  File.open(log_path, "a") { |file| file.puts(message) }
rescue StandardError
  nil
end

begin
  require "sketchup.rb"
  require "extensions.rb"

  extension = SketchupExtension.new(
    "SketchUp Agent Harness Bridge",
    "su_bridge/lib/su_bridge"
  )
  extension.description = "Loopback TCP bridge for SketchUp Agent Harness."
  extension.version = "1.0.0"
  extension.creator = "SketchUp Agent Harness"
  Sketchup.register_extension(extension, true)

  bridge_path = File.expand_path("su_bridge/lib/su_bridge.rb", __dir__)
  su_bridge_log.call("[#{Time.now.utc}] loading #{bridge_path}")
  require bridge_path
  SuBridge.start if defined?(SuBridge)
  su_bridge_log.call("[#{Time.now.utc}] started")
rescue Exception => error
  su_bridge_log.call("[#{Time.now.utc}] #{error.class}: #{error.message}")
  su_bridge_log.call(error.backtrace.join("\\n")) if error.backtrace
  raise
end
"""


def enable_bridge_loader_preference(plugins_dir: Path) -> dict[str, Any]:
    """Enable the bridge root loader in SketchUp macOS preferences when present."""
    preferences_path = plugins_dir.parent / "PrivatePreferences.json"
    result = {
        "path": str(preferences_path),
        "exists": preferences_path.exists(),
        "enabled": False,
        "updated": False,
    }
    if not preferences_path.exists():
        return result

    data = json.loads(preferences_path.read_text(encoding="utf-8"))
    extensions = data.setdefault("This Computer Only", {}).setdefault("Extensions", {})
    previous_value = extensions.get(LOADER_FILENAME)
    extensions[LOADER_FILENAME] = 1
    result["enabled"] = True
    result["updated"] = previous_value != 1
    if result["updated"]:
        preferences_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return result


def timestamped_backup_path(path: Path, timestamp: str) -> Path:
    """Return an unused backup path next to an existing plugin path."""
    candidate = path.parent / f"{path.name}.backup-{timestamp}"
    if not candidate.exists():
        return candidate

    counter = 1
    while True:
        next_candidate = path.parent / f"{path.name}.backup-{timestamp}-{counter}"
        if not next_candidate.exists():
            return next_candidate
        counter += 1


def install_bridge(
    plugins_dir: str | Path | None = None,
    source_dir: str | Path | None = None,
    sketchup_version: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    platform: str | None = None,
) -> dict[str, Any]:
    """Install the Ruby bridge into a SketchUp Plugins directory.

    Without ``plugins_dir`` the target is the newest detected SketchUp install
    for the host platform (macOS Application Support or Windows %APPDATA%).
    """
    source = Path(source_dir).expanduser().resolve() if source_dir else default_bridge_source()
    if not source.exists():
        raise FileNotFoundError(f"Bridge source not found: {source}")
    if not (source / "lib" / "su_bridge.rb").exists():
        raise FileNotFoundError(f"Invalid bridge source: {source}")

    target_root = (
        Path(plugins_dir).expanduser().resolve()
        if plugins_dir
        else default_plugins_dir(
            sketchup_version,
            platform=resolve_platform(platform),
        ).expanduser().resolve()
    )
    target = target_root / "su_bridge"
    loader = target_root / LOADER_FILENAME
    backup_path = None
    loader_backup_path = None
    if target.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        backup_path = timestamped_backup_path(target, timestamp)
        if loader.exists():
            loader_backup_path = timestamped_backup_path(loader, timestamp)
    elif loader.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        loader_backup_path = timestamped_backup_path(loader, timestamp)

    result = {
        "source": str(source),
        "plugins_dir": str(target_root),
        "target": str(target),
        "loader": str(loader),
        "loader_preference": None,
        "target_exists": target.exists(),
        "loader_exists": loader.exists(),
        "backup_path": str(backup_path) if backup_path else None,
        "loader_backup_path": str(loader_backup_path) if loader_backup_path else None,
        "dry_run": dry_run,
        "installed": False,
        "force": force,
        "load_command": f"load '{loader}'",
    }

    if dry_run:
        return result

    if (target.exists() or loader.exists()) and not force:
        raise FileExistsError(
            f"Bridge already exists in {target_root}. Use --force to replace it."
        )

    target_root.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert backup_path is not None
        shutil.move(str(target), str(backup_path))
    if loader.exists():
        assert loader_backup_path is not None
        shutil.move(str(loader), str(loader_backup_path))
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns(*IGNORED_BRIDGE_PATTERNS),
    )
    loader.write_text(bridge_loader_content(), encoding="utf-8")
    result["loader_preference"] = enable_bridge_loader_preference(target_root)
    result["installed"] = True
    return result
