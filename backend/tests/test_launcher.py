"""Launcher tests never import the backend, run migrations, or access project data."""

from __future__ import annotations

import errno
import importlib.util
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("rspace_launcher", ROOT / "app.py")
launcher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = launcher
SPEC.loader.exec_module(launcher)


@pytest.fixture
def services():
    return [
        launcher.Service("API", ("python", "-m", "uvicorn", "app.main:app"), ROOT / "backend", 8321),
        launcher.Service("Web", ("node", "next", "dev"), ROOT / "frontend", 3000),
    ]


@pytest.fixture
def platform(monkeypatch):
    def set_platform(name):
        fake = SimpleNamespace(name=name, kill=Mock(), killpg=Mock())
        monkeypatch.setattr(launcher, "os", fake)
        monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
        monkeypatch.setattr(signal, "CTRL_BREAK_EVENT", 1, raising=False)
        monkeypatch.setattr(signal, "SIGKILL", 9, raising=False)
        return fake
    return set_platform


@pytest.fixture
def supervisor(monkeypatch, platform):
    platform("posix")
    requested = []

    @contextmanager
    def signals():
        yield requested

    monkeypatch.setattr(launcher, "shutdown_signals", signals)
    cleanup = Mock(return_value=True)
    monkeypatch.setattr(launcher, "stop_children", cleanup)
    monkeypatch.setattr(launcher.time, "sleep", Mock(side_effect=AssertionError("unexpected wait")))
    return requested, cleanup


def process(pid, code=None):
    child = Mock(pid=pid)
    child.poll.return_value = code
    return child


@pytest.mark.parametrize("name,parts", [("nt", ("Scripts", "python.exe")), ("posix", ("bin", "python"))])
def test_prefers_backend_venv_without_activation(monkeypatch, platform, name, parts):
    platform(name)
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="3.13.7\n", stderr=""))
    monkeypatch.setattr(subprocess, "run", run)
    expected = str(ROOT / "backend" / ".venv" / Path(*parts))
    assert launcher.backend_python(ROOT) == expected
    assert all(call.args[0][0] == expected for call in run.call_args_list)
    assert all(call.kwargs["cwd"] == ROOT / "backend" for call in run.call_args_list)
    assert run.call_args_list[1].args[0][2] == "import uvicorn"


def test_falls_back_to_current_interpreter_only_when_venv_absent(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    monkeypatch.setattr(subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0)))
    assert launcher.backend_python(ROOT) == sys.executable


@pytest.mark.parametrize("failure", [
    OSError("broken interpreter"),
    subprocess.TimeoutExpired("python", 15),
    SimpleNamespace(returncode=1, stdout="3.12.9\n", stderr=""),
])
def test_bad_selected_interpreter_fails_without_fallback(monkeypatch, failure):
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    run = Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(launcher.LaunchError, match="Python|Python 3.13"):
        launcher.backend_python(ROOT)
    assert run.call_count == 1


def test_missing_backend_dependencies_has_explicit_setup_error(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=[
        SimpleNamespace(returncode=0),
        SimpleNamespace(returncode=1, stderr="No module named uvicorn"),
    ]))
    with pytest.raises(launcher.LaunchError, match="README backend installation"):
        launcher.backend_python(ROOT)


def test_build_commands_keep_cwds_import_target_and_fixed_ports(monkeypatch):
    monkeypatch.setattr(launcher, "backend_python", lambda root: "backend-python")
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "node-executable")
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    definitions = launcher.build_services(ROOT)
    api, web = definitions
    assert api.cwd == ROOT / "backend"
    assert api.command == (
        "backend-python", "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1", "--port", "8321",
    )
    assert web.cwd == ROOT / "frontend"
    assert web.command == (
        "node-executable", str(ROOT / "frontend" / "node_modules" / "next" / "dist" / "bin" / "next"),
        "dev", "--hostname", "127.0.0.1", "--port", "3000",
    )
    assert [service.port for service in definitions] == [8321, 3000]


@pytest.mark.parametrize("node,next_installed,message", [
    (None, True, "Node.js is not on PATH"),
    ("node", False, "npm install"),
])
def test_missing_frontend_prerequisites_do_not_install(monkeypatch, node, next_installed, message):
    monkeypatch.setattr(launcher, "backend_python", lambda root: "python")
    monkeypatch.setattr(launcher.shutil, "which", lambda name: node)
    monkeypatch.setattr(Path, "is_file", lambda self: next_installed)
    with pytest.raises(launcher.LaunchError, match=message):
        launcher.build_services(ROOT)


def test_missing_application_directory(monkeypatch):
    monkeypatch.setattr(Path, "is_dir", lambda self: False)
    with pytest.raises(launcher.LaunchError, match="Missing application directory"):
        launcher.build_services(ROOT)


def test_port_preflight_checks_both_localhost_families_and_releases_sockets(monkeypatch, services, platform):
    platform("posix")
    sockets = [Mock() for _ in range(4)]
    for sock in sockets:
        sock.__enter__ = Mock(return_value=sock)
        sock.__exit__ = Mock(return_value=False)
    factory = Mock(side_effect=sockets)
    monkeypatch.setattr(socket, "socket", factory)
    launcher.check_ports(services)
    assert [s.bind.call_args.args[0] for s in sockets] == [
        ("127.0.0.1", 8321), ("::1", 8321), ("127.0.0.1", 3000), ("::1", 3000),
    ]
    assert all(s.__exit__.called for s in sockets)


def test_occupied_port_never_starts_or_stops_a_server(monkeypatch, services):
    monkeypatch.setattr(sys, "argv", ["app.py"])
    monkeypatch.setattr(launcher, "build_services", lambda: services)
    start = Mock()
    monkeypatch.setattr(launcher, "supervise", start)
    sock = Mock()
    sock.bind.side_effect = OSError(errno.EADDRINUSE, "Address already in use")
    sock.__enter__ = Mock(return_value=sock)
    sock.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(socket, "socket", Mock(return_value=sock))
    assert launcher.main() == 1
    start.assert_not_called()


def test_ipv6_unavailable_is_allowed(monkeypatch, services, platform):
    platform("posix")
    sock = Mock()
    sock.__enter__ = Mock(return_value=sock)
    sock.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(socket, "socket", Mock(side_effect=[
        sock, OSError(errno.EAFNOSUPPORT, "No IPv6"),
        sock, OSError(errno.EAFNOSUPPORT, "No IPv6"),
    ]))
    launcher.check_ports(services)
    assert sock.bind.call_count == 2


@pytest.mark.parametrize("status,expected", [(7, 7), (0, 1), (-15, 143)])
def test_child_exit_stops_both_and_surfaces_failure(monkeypatch, services, supervisor, status, expected):
    _requested, cleanup = supervisor
    api, web = process(101), process(102)
    api.poll.side_effect = [None, status]
    popen = Mock(side_effect=[api, web])
    monkeypatch.setattr(subprocess, "Popen", popen)
    assert launcher.supervise(services) == expected
    cleanup.assert_called_once_with([(services[0], api), (services[1], web)], None)
    for call, service in zip(popen.call_args_list, services):
        assert call.args[0] == service.command
        assert call.kwargs["cwd"] == service.cwd
        assert call.kwargs["start_new_session"] is True
        assert call.kwargs["shell"] is False
        assert "env" not in call.kwargs


@pytest.mark.parametrize("first_started", [False, True])
def test_start_failure_cleans_already_started_children(monkeypatch, services, supervisor, first_started):
    _requested, cleanup = supervisor
    api = process(101)
    results = [api, OSError("start failed")] if first_started else [OSError("start failed")]
    monkeypatch.setattr(subprocess, "Popen", Mock(side_effect=results))
    assert launcher.supervise(services) == 1
    cleanup.assert_called_once_with([(services[0], api)] if first_started else [], None)


def test_early_exit_does_not_start_second_server(monkeypatch, services, supervisor):
    api = process(101, 2)
    popen = Mock(return_value=api)
    monkeypatch.setattr(subprocess, "Popen", popen)
    assert launcher.supervise(services) == 1
    assert popen.call_count == 1


def test_interrupt_stops_both(monkeypatch, services, supervisor):
    requested, cleanup = supervisor
    api, web = process(101), process(102)

    def start(*args, **kwargs):
        if not start.started:
            start.started = True
            return api
        requested.append(signal.SIGINT)
        return web

    start.started = False
    monkeypatch.setattr(subprocess, "Popen", start)
    assert launcher.supervise(services) == 130
    cleanup.assert_called_once_with([(services[0], api), (services[1], web)], None)


def test_cleanup_failure_is_not_hidden(monkeypatch, services, supervisor):
    requested, cleanup = supervisor
    requested.append(signal.SIGINT)
    cleanup.return_value = False
    assert launcher.supervise(services) == 1


def test_windows_children_are_gated_until_job_owns_them(monkeypatch, services, supervisor, platform):
    platform("nt")
    monkeypatch.setattr(sys, "_base_executable", "base-python", raising=False)
    _requested, cleanup = supervisor
    job = Mock()
    monkeypatch.setattr(launcher, "WindowsJob", Mock(return_value=job))
    api, web = process(101), process(102)
    api.poll.side_effect = [None, 8]
    events = []
    job.assign.side_effect = lambda child: events.append(("assign", child.pid))
    for child in (api, web):
        child.stdin.write.side_effect = lambda data, pid=child.pid: events.append(("start", pid, data))
    popen = Mock(side_effect=[api, web])
    monkeypatch.setattr(subprocess, "Popen", popen)
    assert launcher.supervise(services) == 8
    assert events == [
        ("assign", 101), ("start", 101, b"start\n"),
        ("assign", 102), ("start", 102, b"start\n"),
    ]
    for call, service in zip(popen.call_args_list, services):
        assert call.args[0] == ["base-python", "-S", "-c", launcher.WINDOWS_CHILD, *service.command]
        assert call.kwargs["cwd"] == service.cwd
        assert call.kwargs["creationflags"] == subprocess.CREATE_NEW_PROCESS_GROUP
        assert call.kwargs["shell"] is False
    cleanup.assert_called_once_with([(services[0], api), (services[1], web)], job)


def test_windows_job_assignment_failure_never_releases_child(monkeypatch, services, supervisor, platform):
    platform("nt")
    _requested, cleanup = supervisor
    job, api = Mock(), process(101)
    job.assign.side_effect = OSError("job denied")
    monkeypatch.setattr(launcher, "WindowsJob", Mock(return_value=job))
    popen = Mock(return_value=api)
    monkeypatch.setattr(subprocess, "Popen", popen)
    assert launcher.supervise(services) == 1
    api.stdin.write.assert_not_called()
    api.stdin.close.assert_called_once()
    assert popen.call_count == 1
    cleanup.assert_called_once_with([(services[0], api)], job)


def test_windows_job_creation_failure_starts_nothing(monkeypatch, services, supervisor, platform):
    platform("nt")
    monkeypatch.setattr(launcher, "WindowsJob", Mock(side_effect=OSError("job denied")))
    popen = Mock()
    monkeypatch.setattr(subprocess, "Popen", popen)
    assert launcher.supervise(services) == 1
    popen.assert_not_called()


def test_windows_missing_base_interpreter_fails_before_start(monkeypatch, services, supervisor, platform):
    platform("nt")
    monkeypatch.setattr(sys, "_base_executable", None, raising=False)
    job = Mock()
    monkeypatch.setattr(launcher, "WindowsJob", Mock(return_value=job))
    popen = Mock()
    monkeypatch.setattr(subprocess, "Popen", popen)
    assert launcher.supervise(services) == 1
    popen.assert_not_called()
    supervisor[1].assert_called_once_with([], job)


def test_posix_cleanup_signals_tree_even_when_leader_has_exited(services, platform):
    fake_os = platform("posix")
    child = process(101, 0)
    assert launcher.stop_children([(services[0], child)], None)
    assert [call.args for call in fake_os.killpg.call_args_list] == [
        (101, signal.SIGTERM), (101, signal.SIGKILL),
    ]


def test_windows_cleanup_closes_job_even_when_all_leaders_exited(services, platform):
    fake_os = platform("nt")
    job, child = Mock(), process(101, 0)
    assert launcher.stop_children([(services[0], child)], job)
    fake_os.kill.assert_not_called()
    job.close.assert_called_once()


def test_windows_cleanup_kills_unassigned_wrapper_after_grace_timeout(services, platform):
    fake_os = platform("nt")
    fake_os.kill.side_effect = OSError("no console")
    job, child = Mock(), process(101)
    child.wait.side_effect = [subprocess.TimeoutExpired("wrapper", 3), 1]
    assert launcher.stop_children([(services[0], child)], job)
    job.close.assert_called_once()
    child.kill.assert_called_once()


def test_signal_handlers_are_restored(monkeypatch, platform):
    platform("posix")
    original = Mock()
    install = Mock(return_value=original)
    monkeypatch.setattr(signal, "signal", install)
    with launcher.shutdown_signals() as requested:
        handler = install.call_args_list[0].args[1]
        handler(signal.SIGINT, None)
        handler(signal.SIGINT, None)
        assert requested == [signal.SIGINT]
    assert install.call_args_list[-2].args == (signal.SIGINT, original)
    assert install.call_args_list[-1].args == (signal.SIGTERM, original)


def _listens(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


@pytest.mark.skipif(
    os.environ.get("RSPACE_LAUNCHER_RUNTIME_TEST") != "1",
    reason="Opt-in isolated process-tree smoke test; no real app or data is used.",
)
@pytest.mark.parametrize("shutdown", ["child-exit", "interrupt"])
@pytest.mark.parametrize("web_runtime", ["python", "node"])
def test_runtime_owned_descendants_release_ports(shutdown, web_runtime):
    """Use ephemeral-port dummy grandchildren, never FastAPI/Next/Ollama or a database."""
    with socket.socket() as first, socket.socket() as second, socket.socket() as control:
        first.bind(("127.0.0.1", 0))
        second.bind(("127.0.0.1", 0))
        control.bind(("127.0.0.1", 0))
        ports = [first.getsockname()[1], second.getsockname()[1]]
        control_port = control.getsockname()[1]
    listener = (
        "import socket, sys, time; "
        "s=socket.socket(); s.bind(('127.0.0.1', int(sys.argv[1]))); "
        "s.listen(128); time.sleep(60)"
    )
    spawn_listener = (
        "import socket, subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {listener!r}, sys.argv[1]]); "
    )
    api_code = (
        spawn_listener
        + f"control=socket.socket(); control.bind(('127.0.0.1', {control_port})); "
        "control.listen(1); control.accept()[0].close(); sys.exit(7)"
    )
    web_code = spawn_listener + "time.sleep(60)"
    web_command = (sys.executable, "-c", web_code, str(ports[1]))
    if web_runtime == "node":
        node = shutil.which("node")
        if node is None:
            pytest.skip("Node.js is required for the opt-in Node process-tree smoke test.")
        node_listener = (
            "require('node:net').createServer(s=>s.end()).listen(Number(process.argv[1]),'127.0.0.1');"
        )
        node_parent = (
            "require('node:child_process').spawn(process.execPath,"
            f"['-e', {node_listener!r}, process.argv[1]], {{stdio:'inherit'}});"
            "setTimeout(()=>{},60000);"
        )
        web_command = (node, "-e", node_parent, str(ports[1]))
    script = (
        "import importlib.util, pathlib, sys; "
        f"spec=importlib.util.spec_from_file_location('isolated_launcher', {str(ROOT / 'app.py')!r}); "
        "m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m); "
        "services=["
        f"m.Service('API', (sys.executable, '-c', {api_code!r}, '{ports[0]}'), "
        f"pathlib.Path.cwd(), {ports[0]}),"
        f"m.Service('Web', {web_command!r}, "
        f"pathlib.Path.cwd(), {ports[1]})]; "
        "sys.exit(m.supervise(services))"
    )
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
    child = subprocess.Popen(
        [sys.executable, "-c", script], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kwargs,
    )
    try:
        deadline = time.monotonic() + 20
        ready = set()
        while time.monotonic() < deadline and child.poll() is None:
            ready.update(port for port in ports if port not in ready and _listens(port))
            if len(ready) == len(ports):
                break
            time.sleep(0.05)
        else:
            if child.poll() is None:
                child.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
            output, _ = child.communicate(timeout=10)
            pytest.fail(f"Isolated dummy servers did not both become ready:\n{output}")
        if shutdown == "interrupt":
            child.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        else:
            with socket.create_connection(("127.0.0.1", control_port), timeout=2):
                pass
        output, _ = child.communicate(timeout=20)
        assert child.returncode == (
            7 if shutdown == "child-exit"
            else 128 + (signal.SIGBREAK if os.name == "nt" else signal.SIGINT)
        ), output
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and any(_listens(port) for port in ports):
            time.sleep(0.05)
        assert not any(_listens(port) for port in ports), output
    finally:
        if child.poll() is None:
            child.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
            try:
                child.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate(timeout=5)
