from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from typing import Any


def _registry(app: Any) -> tuple[Any, dict[str, subprocess.Popen[Any]]]:
    lock = getattr(app.state, "runtime_task_process_lock", None)
    processes = getattr(app.state, "runtime_task_processes", None)
    if not isinstance(processes, dict):
        processes = {}
        app.state.runtime_task_processes = processes
    return lock, processes


def _native_registry(app: Any) -> tuple[Any, dict[str, dict[str, Any]]]:
    lock = getattr(app.state, "runtime_task_process_lock", None)
    panes = getattr(app.state, "runtime_task_native_panes", None)
    if not isinstance(panes, dict):
        panes = {}
        app.state.runtime_task_native_panes = panes
    return lock, panes


def register_runtime_task_process(app: Any, *, task_id: str, process: subprocess.Popen[Any]) -> dict[str, Any]:
    lock, processes = _registry(app)
    key = str(task_id or "").strip()
    if lock is None:
        processes[key] = process
    else:
        with lock:
            processes[key] = process
    return runtime_task_process_snapshot(app, task_id=key)


def register_runtime_task_native_pane(app: Any, *, task_id: str, native_pane: dict[str, Any]) -> dict[str, Any]:
    lock, panes = _native_registry(app)
    key = str(task_id or "").strip()
    payload = dict(native_pane or {})
    payload["task_id"] = key
    if lock is None:
        panes[key] = payload
    else:
        with lock:
            panes[key] = payload
    return runtime_task_process_snapshot(app, task_id=key)


def unregister_runtime_task_process(app: Any, *, task_id: str, process: subprocess.Popen[Any] | None = None) -> None:
    lock, processes = _registry(app)
    key = str(task_id or "").strip()
    if lock is None:
        current = processes.get(key)
        if process is None or current is process:
            processes.pop(key, None)
        return
    with lock:
        current = processes.get(key)
        if process is None or current is process:
            processes.pop(key, None)


def unregister_runtime_task_native_pane(app: Any, *, task_id: str) -> None:
    lock, panes = _native_registry(app)
    key = str(task_id or "").strip()
    if lock is None:
        panes.pop(key, None)
        return
    with lock:
        panes.pop(key, None)


def runtime_task_process_snapshot(app: Any, *, task_id: str) -> dict[str, Any]:
    lock, processes = _registry(app)
    key = str(task_id or "").strip()
    if lock is None:
        process = processes.get(key)
    else:
        with lock:
            process = processes.get(key)
    if process is None:
        native_lock, native_panes = _native_registry(app)
        if native_lock is None:
            native_pane = native_panes.get(key)
        else:
            with native_lock:
                native_pane = native_panes.get(key)
        if not isinstance(native_pane, dict):
            return {"task_id": key, "registered": False}
        worker_pid = _native_worker_pid(native_pane)
        return {
            "task_id": key,
            "registered": True,
            "kind": "native_pane",
            "pid": worker_pid,
            "returncode": None,
            "running": True,
            "native_pane": dict(native_pane),
        }
    return {
        "task_id": key,
        "registered": True,
        "kind": "process",
        "pid": int(process.pid or 0),
        "returncode": process.poll(),
        "running": process.poll() is None,
    }


def kill_runtime_task_process(
    app: Any,
    *,
    task_id: str,
    reason: str,
    grace_seconds: float = 0.35,
) -> dict[str, Any]:
    lock, processes = _registry(app)
    key = str(task_id or "").strip()
    if lock is None:
        process = processes.get(key)
    else:
        with lock:
            process = processes.get(key)
    if process is None:
        native_lock, native_panes = _native_registry(app)
        if native_lock is None:
            native_pane = native_panes.get(key)
        else:
            with native_lock:
                native_pane = native_panes.get(key)
        if isinstance(native_pane, dict):
            result = kill_runtime_task_native_pane(app, task_id=key, native_pane=native_pane, reason=reason, grace_seconds=grace_seconds)
            result["task_id"] = key
            return result
        return {"task_id": key, "killed": False, "reason": "process_not_registered"}
    pid = int(process.pid or 0)
    if pid <= 0:
        unregister_runtime_task_process(app, task_id=key, process=process)
        return {"task_id": key, "killed": False, "reason": "process_pid_missing"}
    if process.poll() is not None:
        unregister_runtime_task_process(app, task_id=key, process=process)
        return {"task_id": key, "killed": False, "pid": pid, "reason": "process_already_exited", "returncode": process.returncode}
    result = kill_process_tree(process, reason=reason, grace_seconds=grace_seconds)
    unregister_runtime_task_process(app, task_id=key, process=process)
    result["task_id"] = key
    return result


def kill_runtime_task_native_pane(
    app: Any,
    *,
    task_id: str,
    native_pane: dict[str, Any] | None = None,
    reason: str,
    grace_seconds: float = 0.35,
) -> dict[str, Any]:
    key = str(task_id or "").strip()
    pane = dict(native_pane or {})
    if not pane:
        lock, panes = _native_registry(app)
        if lock is None:
            pane = dict(panes.get(key) or {})
        else:
            with lock:
                pane = dict(panes.get(key) or {})
    if not pane:
        return {"task_id": key, "killed": False, "reason": "native_pane_not_registered"}
    backend = str(pane.get("native_backend_type") or pane.get("backend_type") or "").strip()
    pane_id = str(pane.get("native_pane_id") or "").strip()
    worker_pid = _native_worker_pid(pane)
    pid_signal = _terminate_native_worker_pid(worker_pid, grace_seconds=grace_seconds) if worker_pid > 0 else {"attempted": False}
    if not backend or not pane_id:
        unregister_runtime_task_native_pane(app, task_id=key)
        return {
            "task_id": key,
            "killed": bool(pid_signal.get("killed")),
            "reason": "native_pane_missing_backend_or_id",
            "worker_pid": worker_pid,
            "pid_signal": pid_signal,
        }
    if backend == "tmux":
        cmd = ["tmux", "kill-pane", "-t", pane_id]
    elif backend in {"iterm2", "iterm"}:
        cmd = ["it2", "session", "close", "-f", "-s", pane_id]
    else:
        unregister_runtime_task_native_pane(app, task_id=key)
        return {
            "task_id": key,
            "killed": bool(pid_signal.get("killed")),
            "reason": "unsupported_native_pane_backend",
            "backend": backend,
            "native_pane_id": pane_id,
            "worker_pid": worker_pid,
            "pid_signal": pid_signal,
        }
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    unregister_runtime_task_native_pane(app, task_id=key)
    return {
        "task_id": key,
        "killed": result.returncode == 0 or bool(pid_signal.get("killed")),
        "reason": str(reason or "runtime_native_pane_kill"),
        "backend": backend,
        "native_pane_id": pane_id,
        "worker_pid": worker_pid,
        "pid_signal": pid_signal,
        "pane_kill_returncode": result.returncode,
        "stderr": str(result.stderr or "")[-500:],
    }


def _native_worker_pid(native_pane: dict[str, Any]) -> int:
    direct = native_pane.get("worker_pid")
    try:
        if direct is not None:
            return max(0, int(direct))
    except Exception:
        pass
    pid_path = str(native_pane.get("worker_pid_path") or native_pane.get("native_start_path") or "").strip()
    if not pid_path:
        return 0
    try:
        payload = json.loads(open(pid_path, "r", encoding="utf-8").read())
        if isinstance(payload, dict):
            return max(0, int(payload.get("worker_pid") or payload.get("pid") or 0))
    except Exception:
        return 0
    return 0


def _terminate_native_worker_pid(pid: int, *, grace_seconds: float) -> dict[str, Any]:
    if pid <= 0:
        return {"attempted": False}
    try:
        os.kill(pid, signal.SIGTERM if os.name == "posix" else signal.SIGTERM)
    except ProcessLookupError:
        return {"attempted": True, "killed": False, "pid": pid, "reason": "process_not_found"}
    except Exception as exc:  # noqa: BLE001
        return {"attempted": True, "killed": False, "pid": pid, "reason": f"terminate_failed:{exc.__class__.__name__}:{exc}"}
    deadline = time.monotonic() + max(0.0, float(grace_seconds or 0.0))
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return {"attempted": True, "killed": True, "pid": pid, "signal": "SIGTERM"}
        except Exception:
            break
        time.sleep(0.02)
    try:
        os.kill(pid, signal.SIGKILL if os.name == "posix" else signal.SIGTERM)
    except ProcessLookupError:
        return {"attempted": True, "killed": True, "pid": pid, "signal": "SIGTERM"}
    except Exception as exc:  # noqa: BLE001
        return {"attempted": True, "killed": False, "pid": pid, "reason": f"kill_failed:{exc.__class__.__name__}:{exc}"}
    return {"attempted": True, "killed": True, "pid": pid, "signal": "SIGKILL" if os.name == "posix" else "terminate"}


def kill_process_tree(
    process: subprocess.Popen[Any],
    *,
    reason: str,
    grace_seconds: float = 0.35,
) -> dict[str, Any]:
    pid = int(process.pid or 0)
    if pid <= 0:
        return {"killed": False, "reason": "process_pid_missing"}
    if process.poll() is not None:
        return {"killed": False, "pid": pid, "reason": "process_already_exited", "returncode": process.returncode}

    terminated = False
    killed = False
    try:
        if os.name == "posix":
            os.killpg(pid, signal.SIGTERM)
        else:
            process.terminate()
        terminated = True
    except ProcessLookupError:
        return {"killed": False, "pid": pid, "reason": "process_not_found"}
    except Exception as exc:  # noqa: BLE001
        return {"killed": False, "pid": pid, "reason": f"terminate_failed:{exc.__class__.__name__}:{exc}"}

    deadline = time.monotonic() + max(0.0, float(grace_seconds or 0.0))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return {
                "killed": True,
                "pid": pid,
                "reason": str(reason or "runtime_process_kill"),
                "signal": "SIGTERM" if os.name == "posix" else "terminate",
                "returncode": process.returncode,
            }
        time.sleep(0.02)

    if process.poll() is None:
        try:
            if os.name == "posix":
                os.killpg(pid, signal.SIGKILL)
            else:
                process.kill()
            killed = True
        except ProcessLookupError:
            pass
        except Exception as exc:  # noqa: BLE001
            return {
                "killed": terminated,
                "pid": pid,
                "reason": f"kill_failed:{exc.__class__.__name__}:{exc}",
                "terminated": terminated,
            }
    try:
        process.wait(timeout=1.0)
    except Exception:
        pass
    return {
        "killed": True,
        "pid": pid,
        "reason": str(reason or "runtime_process_kill"),
        "signal": "SIGKILL" if killed and os.name == "posix" else "terminate",
        "terminated": terminated,
        "returncode": process.returncode,
    }
