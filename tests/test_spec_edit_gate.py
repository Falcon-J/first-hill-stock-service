"""A red implementation must not be bypassed by rewriting its specification."""
import importlib.util
from pathlib import Path


def guard_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'spec_edit_gate.py'
    assert path.exists(), 'Spec edit guard is missing'
    spec = importlib.util.spec_from_file_location('spec_edit_gate', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_spec_edit_is_blocked_when_checks_fail(capsys):
    module = guard_module()
    payload = {'tool_name': 'Edit', 'tool_input': {'file_path': str(module.ROOT / 'specs/003-build-services/spec.md')}}
    assert module.check_edit(payload, checks=lambda: 2) == 2
    assert 'BLOCKED SPEC EDIT' in capsys.readouterr().err


def test_implementation_edits_can_fix_red_checks():
    module = guard_module()
    payload = {'tool_name': 'Edit', 'tool_input': {'file_path': str(module.ROOT / 'services/order/app.py')}}
    assert module.check_edit(payload, checks=lambda: (_ for _ in ()).throw(AssertionError('must not run checks'))) == 0


def test_green_checks_allow_reviewable_spec_amendment():
    module = guard_module()
    payload = {'tool_name': 'Write', 'tool_input': {'file_path': str(module.ROOT / 'contracts/order-service.openapi.yaml')}}
    assert module.check_edit(payload, checks=lambda: 0) == 0
