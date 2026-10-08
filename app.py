"""Start the existing backend and frontend without changing their working directories."""

from __future__ import annotations

import errno
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
BACKEND_PORT = 8321
FRONTEND_PORT = 3000
SHUTDOWN_TIMEOUT = 3.0

# On Windows, wait for job assignment before spawning any server descendants.
# This is a Python subprocess, not a command shell; arguments remain separate.
WINDOWS_CHILD = (
    "import subprocess, sys; "
    "ready = sys.stdin.buffer.readline() == b'start\\n'; "
    "sys.exit(subprocess.call(sys.argv[1:], stdin=subprocess.DEVNULL) if ready else 1)"
)


class LaunchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Service:
    name: str
    command: tuple[str, ...]
    cwd: Path
    port: int


def backend_python(root: Path) -> str:
    backend = root / "backend"
    venv = backend / ".venv"
    candidate = venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"
    executable = str(candidate) if candidate.is_file() else sys.executable
    if not executable:
        raise LaunchError("Python 3.13+ is required; create backend/.venv first.")
    try:
        result = subprocess.run(
            [
                executable,
                "-c",
                "import sys; "
                "print('.'.join(map(str, sys.version_info[:3]))); "
                "sys.exit(0 if sys.version_info >= (3, 13) else 1)",
            ],
            cwd=backend,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LaunchError(f"Cannot run backend Python {executable}: {exc}") from exc
    if result.returncode:
        raise LaunchError(
            f"Backend requires Python 3.13+; {executable} reported "
            f"{result.stdout.strip() or result.stderr.strip() or 'an execution failure'}. "
            "Repair backend/.venv or run with Python 3.13+."
        )
    try:
        result = subprocess.run(
            [executable, "-c", "import uvicorn"],
            cwd=backend,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LaunchError(f"Cannot check backend dependencies: {exc}") from exc
    if result.returncode:
        raise LaunchError(
            "Backend dependencies are unavailable. Complete the README backend "
            f"installation with {executable} first.\n{result.stderr.strip()}"
        )
    return executable


def build_services(root: Path = ROOT) -> list[Service]:
    backend = root / "backend"
    frontend = root / "frontend"
    for folder in (backend, frontend):
        if not folder.is_dir():
            raise LaunchError(f"Missing application directory: {folder}")
    executable = backend_python(root)
    node = shutil.which("node")
    if node is None:
        raise LaunchError("Node.js is not on PATH. Install Node.js 22 and restart your terminal.")
    next_cli = frontend / "node_modules" / "next" / "dist" / "bin" / "next"
    if not next_cli.is_file():
        raise LaunchError(
            "Frontend dependencies are unavailable. Run npm install in frontend first."
        )
    return [
        Service(
            "API",
            (
                executable, "-m", "uvicorn", "app.main:app",
                "--host", HOST, "--port", str(BACKEND_PORT),
            ),
            backend,
            BACKEND_PORT,
        ),
        Service(
            "Web",
            (
                node, str(next_cli), "dev",
                "--hostname", HOST, "--port", str(FRONTEND_PORT),
            ),
            frontend,
            FRONTEND_PORT,
        ),
    ]


def check_ports(services: list[Service]) -> None:
    """Check both localhost families; never adopt or terminate an existing server."""
    with ExitStack() as stack:
        for service in services:
            for family, address in (
                (socket.AF_INET, HOST),
                (socket.AF_INET6, "::1"),
            ):
                try:
                    sock = stack.enter_context(socket.socket(family, socket.SOCK_STREAM))
                    if family == socket.AF_INET6:
                        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                    if os.name == "nt":
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    sock.bind((address, service.port))
                except OSError as exc:
                    if family == socket.AF_INET6 and exc.errno in (
                        errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT, errno.EADDRNOTAVAIL,
                    ):
                        continue
                    raise LaunchError(
                        f"{service.name} cannot use localhost:{service.port}: {exc}. "
                        "Stop the existing server yourself or resolve the port conflict."
                    ) from exc


class WindowsJob:
    """Own only this launcher's process trees, including descendants of exited parents."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong) for name in (
                    "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
                )
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self._ctypes = ctypes
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
                wintypes.BOOL,
            ),
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self._kernel, name)
            function.argtypes = args
            function.restype = result
        self._handle = self._kernel.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._kernel.SetInformationJobObject(
            self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process: subprocess.Popen) -> None:
        handle = self._kernel.OpenProcess(0x0101, False, process.pid)
        if not handle:
            raise self._ctypes.WinError(self._ctypes.get_last_error())
        try:
            if not self._kernel.AssignProcessToJobObject(self._handle, handle):
                raise self._ctypes.WinError(self._ctypes.get_last_error())
        finally:
            self._kernel.CloseHandle(handle)

    def close(self) -> None:
        if self._handle:
            if not self._kernel.CloseHandle(self._handle):
                raise self._ctypes.WinError(self._ctypes.get_last_error())
            self._handle = None


@contextmanager
def shutdown_signals():
    requested: list[int] = []
    previous = {}

    def request_stop(signum, _frame):
        if not requested:
            requested.append(signum)

    try:
        signals = [signal.SIGINT, signal.SIGTERM]
        if os.name == "nt":
            signals.append(signal.SIGBREAK)
        for signum in signals:
            previous[signum] = signal.signal(signum, request_stop)
        yield requested
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def stop_children(
    children: list[tuple[Service, subprocess.Popen]], job: WindowsJob | None,
) -> bool:
    clean = True

    def report(exc: Exception) -> None:
        nonlocal clean
        clean = False
        print(f"Cleanup failed: {exc}", file=sys.stderr, flush=True)

    for _service, process in children:
        try:
            if os.name == "nt":
                if process.poll() is None:
                    os.kill(process.pid, signal.CTRL_BREAK_EVENT)
            else:
                # The leader may have exited while a reload/Node child is still alive.
                os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as exc:
            # A Windows console signal may be unavailable (e.g. a GUI terminal).
            # The owned job below is still the authoritative tree cleanup.
            if os.name != "nt":
                report(exc)
            else:
                print(f"Graceful shutdown unavailable: {exc}; closing owned job.",
                      file=sys.stderr, flush=True)
    deadline = time.monotonic() + SHUTDOWN_TIMEOUT
    for _service, process in children:
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
        except OSError as exc:
            report(exc)
    if job is not None:
        try:
            job.close()
        except OSError as exc:
            report(exc)
    for _service, process in children:
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                # Also covers a gated wrapper whose job assignment failed.
                process.kill()
        except ProcessLookupError:
            pass
        except OSError as exc:
            report(exc)
        try:
            process.wait(timeout=SHUTDOWN_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            report(exc)
    return clean


def supervise(services: list[Service]) -> int:
    children: list[tuple[Service, subprocess.Popen]] = []
    job = None
    exit_code = 1
    with shutdown_signals() as requested:
        try:
            if os.name == "nt":
                job = WindowsJob()
            for service in services:
                if requested:
                    break
                for previous, process in children:
                    code = process.poll()
                    if code is not None:
                        raise LaunchError(f"{previous.name} exited during startup (status {code}).")
                print(
                    f"Starting {service.name} in {service.cwd}:\n"
                    f"  {subprocess.list2cmdline(service.command)}",
                    flush=True,
                )
                if job is not None:
                    # A Windows venv redirector can spawn Python before job assignment.
                    # Use the base interpreter without site hooks for the gated wrapper.
                    bootstrap = getattr(sys, "_base_executable", None)
                    if not bootstrap:
                        raise LaunchError("Cannot locate the base Python interpreter for Windows supervision.")
                    process = subprocess.Popen(
                        [bootstrap, "-S", "-c", WINDOWS_CHILD, *service.command],
                        cwd=service.cwd,
                        stdin=subprocess.PIPE,
                        shell=False,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                    )
                    children.append((service, process))
                    try:
                        job.assign(process)
                        process.stdin.write(b"start\n")
                        process.stdin.flush()
                    finally:
                        process.stdin.close()
                else:
                    process = subprocess.Popen(
                        service.command,
                        cwd=service.cwd,
                        stdin=subprocess.DEVNULL,
                        shell=False,
                        start_new_session=True,
                    )
                    children.append((service, process))
            print(
                "API: http://localhost:8321 | Web: http://localhost:3000\n"
                "Watch the server logs for readiness. Press Ctrl+C to stop both.",
                flush=True,
            )
            while not requested:
                for service, process in children:
                    code = process.poll()
                    if code is not None:
                        print(f"{service.name} exited (status {code}); stopping both.",
                              file=sys.stderr, flush=True)
                        exit_code = code if code > 0 else (128 - code if code < 0 else 1)
                        break
                else:
                    time.sleep(0.1)
                    continue
                break
            if requested:
                print("Stopping both application servers.", flush=True)
                exit_code = 128 + requested[0]
        except KeyboardInterrupt:
            exit_code = 130
        except (OSError, LaunchError) as exc:
            print(f"Launch failed: {exc}", file=sys.stderr, flush=True)
        finally:
            if not stop_children(children, job):
                exit_code = 1
    return exit_code


def main() -> int:
    if len(sys.argv) != 1:
        print("Usage: python app.py", file=sys.stderr)
        return 2
    try:
        services = build_services()
        check_ports(services)
        return supervise(services)
    except KeyboardInterrupt:
        return 130
    except (LaunchError, OSError) as exc:
        print(f"Launch failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
