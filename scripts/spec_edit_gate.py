"""Reject specification edits while implementation tests or lint are red."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def quality_checks():
    try:
        return subprocess.run([sys.executable, str(ROOT / 'scripts/stop_gate.py')],
                              cwd=ROOT, check=False, timeout=400).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 2


def check_edit(payload, checks=quality_checks):
    candidate = payload.get('tool_input', {}).get('file_path')
    if not candidate:
        return 0
    path = Path(candidate)
    if not path.is_absolute():
        path = ROOT / path
    try:
        relative = path.resolve().relative_to(ROOT)
    except ValueError:
        return 0
    protected = relative.parts[0] in {'specs', 'contracts', '.specify'} or relative.name == 'CLAUDE.md'
    if protected and checks() != 0:
        print(f'BLOCKED SPEC EDIT: {relative.as_posix()}; fix failing tests/lint before changing the specification. Do not weaken contracts to make tests pass.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    try:
        payload = json.load(sys.stdin)
        raise SystemExit(check_edit(payload))
    except (ValueError, TypeError, AttributeError):
        print('BLOCKED SPEC EDIT: invalid hook input.', file=sys.stderr)
        raise SystemExit(2)
