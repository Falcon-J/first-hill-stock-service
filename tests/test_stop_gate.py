"""The finish gate must refuse failing tests, lint failures and runner errors."""
import importlib.util
from pathlib import Path
import subprocess

import pytest


def gate_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'stop_gate.py'
    assert path.exists(), 'Stop gate implementation is missing'
    spec = importlib.util.spec_from_file_location('stop_gate', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('results', [(1, 0), (0, 1), (1, 1)])
def test_stop_gate_blocks_failed_checks_and_runs_both(results, capsys):
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, results[len(calls)-1])
    assert gate_module().run_checks(runner=runner) == 2
    assert len(calls) == 2
    assert calls[0][1:3] == ['-m', 'pytest']
    assert calls[1][1:3] == ['-m', 'ruff']
    assert 'BLOCKED' in capsys.readouterr().err


def test_stop_gate_allows_only_both_green():
    assert gate_module().run_checks(runner=lambda command, **kwargs: subprocess.CompletedProcess(command, 0)) == 0


def test_stop_gate_fails_closed_if_runner_cannot_start(capsys):
    def runner(*args, **kwargs):
        raise OSError('synthetic missing executable')
    assert gate_module().run_checks(runner=runner) == 2
    assert 'BLOCKED' in capsys.readouterr().err
