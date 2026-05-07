# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Background local server management for the ``run`` command."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import click

_PID_DIR = ".google-agents-cli"
_PID_FILENAME = "run_server.json"
_LOG_FILENAME = "run_server.log"
_BASE_PORT = 18080
_MAX_PORT_ATTEMPTS = 10
_DEFAULT_IDLE_TIMEOUT = 1800  # 30 minutes


def ensure_server(
    project_root: Path,
    agent_dir: str,
    *,
    idle_timeout: int = _DEFAULT_IDLE_TIMEOUT,
) -> int:
    """Return the port of a running local server, starting one if needed.

    If an existing server has been idle longer than *idle_timeout* seconds
    (based on the ``last_activity`` timestamp in the PID file), it is
    stopped and a fresh one is started.

    Args:
        project_root: The project root directory (cwd when running).
        agent_dir: The agent directory name (e.g. ``"investment_agent"``).
        idle_timeout: Seconds of inactivity before the server is considered
            stale and replaced.  Defaults to 30 minutes.

    Returns:
        The port number the server is listening on.
    """
    info = _read_pid_file(project_root)

    if info and _is_server_alive(info["pid"], info["port"]):
        # Check idle timeout — stop the server if it's been idle too long.
        if _is_idle(info, idle_timeout):
            _cleanup(project_root, info)
        else:
            _update_activity(project_root)
            return info["port"]

    # Stale PID file — clean up before starting fresh.
    if info:
        _cleanup(project_root, info)

    port = _find_free_port()
    pid = _start_server(project_root, agent_dir, port)
    _wait_for_port(port, pid=pid)
    _write_pid_file(project_root, pid=pid, port=port)
    click.secho(f"Local server started on port {port} (PID {pid})", dim=True)
    click.secho("  Stop with: agents-cli run --stop-server", dim=True)
    return port


def stop_server(project_root: Path) -> bool:
    """Stop the background server.

    Returns:
        ``True`` if a server was found and stopped.
    """
    info = _read_pid_file(project_root)
    if not info:
        return False
    _cleanup(project_root, info)
    click.secho("Local server stopped.", dim=True)
    return True


def get_server_port(project_root: Path) -> int | None:
    """Return the port of the running local server, or ``None`` if absent.

    Returns ``None`` when no server has been started for *project_root*,
    or when the recorded process is no longer alive.
    """
    info = _read_pid_file(project_root)
    if not info:
        return None
    if not _is_server_alive(info["pid"], info["port"]):
        return None
    return info["port"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_free_port(
    base: int = _BASE_PORT, max_attempts: int = _MAX_PORT_ATTEMPTS
) -> int:
    """Find a free local port starting from *base*."""
    for offset in range(max_attempts):
        port = base + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise click.ClickException(
        f"No free port found in range {base}–{base + max_attempts - 1}.\n"
        "  Stop other servers or use --url to query a remote agent."
    )


def _start_server(
    project_root: Path,
    agent_dir: str,
    port: int,
) -> int:
    """Start ``adk api_server`` as a detached background process.

    Returns the PID.
    """
    adk_dir = project_root / _PID_DIR
    adk_dir.mkdir(exist_ok=True)
    log_path = adk_dir / _LOG_FILENAME

    cmd = [
        "uv",
        "run",
        "adk",
        "api_server",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--reload_agents",
        ".",
    ]

    # Use in-memory sessions locally so the server can start without
    # cloud dependencies (e.g. Agent Runtime session type).
    env = os.environ.copy()
    env.setdefault("USE_IN_MEMORY_SESSION", "true")

    log_file = open(log_path, "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(project_root),
            stdout=log_file,
            stderr=log_file,
            env=env,
            # Detach from the CLI process so the server survives after exit.
            start_new_session=True,
        )
    finally:
        # Close the parent's copy of the fd — the child inherits its own.
        log_file.close()
    return proc.pid


def _wait_for_port(port: int, timeout: int = 30, pid: int | None = None) -> None:
    """Wait until a local server is ready to handle HTTP requests.

    Polls with an HTTP GET so the server's lifespan (which registers
    routes like A2A endpoints) has time to complete.
    """
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # Fail fast if the server process has already crashed.
        if pid is not None:
            try:
                os.kill(pid, 0)
            except OSError:
                raise click.ClickException(
                    "Local server process exited during startup.\n"
                    f"  Check logs: {_PID_DIR}/{_LOG_FILENAME}"
                ) from None
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return
        except urllib.error.HTTPError:
            # Any HTTP response (even 404/405) means the server is ready.
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    raise click.ClickException(
        f"Local server did not start within {timeout}s.\n"
        f"  Check logs: {_PID_DIR}/{_LOG_FILENAME}"
    )


# --- PID file helpers ---


def _pid_file_path(project_root: Path) -> Path:
    return project_root / _PID_DIR / _PID_FILENAME


def _read_pid_file(project_root: Path) -> dict | None:
    path = _pid_file_path(project_root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_pid_file(project_root: Path, *, pid: int, port: int) -> None:
    now = datetime.now(UTC).isoformat()
    data = {
        "pid": pid,
        "port": port,
        "started_at": now,
        "last_activity": now,
    }
    path = _pid_file_path(project_root)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _update_activity(project_root: Path) -> None:
    """Stamp ``last_activity`` so idle detection resets."""
    path = _pid_file_path(project_root)
    try:
        data = json.loads(path.read_text())
        data["last_activity"] = datetime.now(UTC).isoformat()
        path.write_text(json.dumps(data, indent=2) + "\n")
    except (json.JSONDecodeError, OSError):
        pass


def _is_idle(info: dict, idle_timeout: int) -> bool:
    """Return ``True`` if the server has been idle longer than *idle_timeout*."""
    try:
        last = datetime.fromisoformat(info["last_activity"])
        idle = (datetime.now(UTC) - last).total_seconds()
        return idle > idle_timeout
    except (KeyError, ValueError):
        # Treat missing or unparseable timestamps as stale.
        return True


def _is_server_alive(pid: int, port: int) -> bool:
    """Return ``True`` if the process exists AND the port is open."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        with socket.create_connection(("localhost", port), timeout=1):
            return True
    except OSError:
        return False


def _cleanup(project_root: Path, info: dict) -> None:
    """Terminate the server process and remove the PID file."""
    pid = info.get("pid")
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        else:
            # Wait briefly for the process to release its port.
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                # Not a direct child — fall back to a short sleep so the
                # port is freed before we attempt to bind a new one.
                time.sleep(0.3)
    path = _pid_file_path(project_root)
    try:
        path.unlink()
    except OSError:
        pass
