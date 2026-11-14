"""Claude Stop gate: only passing pytest and lint permit a normal finish."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run_checks(runner=subprocess.run):
    commands = [
        [sys.executable, '-m', 'pytest', 'tests', '-q'],
        [sys.executable, '-m', 'ruff', 'check', '.'],
    ]
    passed = True
    for command in commands:
        try:
            result = runner(command, cwd=ROOT, check=False, timeout=180)
            passed = result.returncode == 0 and passed
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f'Check could not complete: {error}', file=sys.stderr)
            passed = False
    if not passed:
        print('BLOCKED: fix the failing tests/linter before finishing. Do not skip tests or weaken assertions.', file=sys.stderr)
        return 2
    print('Stop gate passed: pytest and lint are green.')
    return 0


if __name__ == '__main__':
    raise SystemExit(run_checks())
