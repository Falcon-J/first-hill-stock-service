"""Strict final holdout runner. A mismatch is a failing check, never a fabricated pass.

Run after starting compose.final-replay.yaml with fresh private volumes.
Every order is submitted once as a whole basket through the gateway over TCP.
"""
import csv
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from checks.final_replay_support import (load_inputs, mismatch_reasons,
                                        observed_outcome, boundary_failures)  # noqa: E402
from checks.live_overselling import credential  # noqa: E402
from checks.final_events import load_events, prepare_checkout  # noqa: E402

COMPOSE = ['docker', 'compose', '-p', 'first-hill-final-replay', '-f', 'compose.final-replay.yaml']


def stock_event(action, data):
    try:
        result = subprocess.run(COMPOSE + ['exec', '-T', 'stock', 'python', '/checks/stock_replay_event.py'],
            cwd=ROOT, input=json.dumps({'action': action, 'data': data}), capture_output=True,
            text=True, encoding='utf-8', timeout=30)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('Stock replay operator timed out') from error
    if result.returncode:
        raise RuntimeError('Stock replay operator failed')
    return json.loads(result.stdout)


def owner_effects(key):
    result = subprocess.run(COMPOSE + ['exec', '-T', 'order', 'python', '/checks/order_inspect.py'],
        cwd=ROOT, input=json.dumps({'idempotency_key': key}), capture_output=True,
        text=True, encoding='utf-8', timeout=30)
    if result.returncode:
        raise RuntimeError('Order-owner inspector failed: ' + result.stderr)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'final-replay-results')
    parser.add_argument('--events', type=Path, help='Provenance/source-hash-bound stock event manifest')
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    names = ['results.csv', 'responses.json', 'summary.json']
    if any((directory / name).exists() for name in names):
        raise ValueError('Use a fresh output directory; refusing to reuse stale replay evidence')
    source = ROOT / 'docs/final-replay'
    run = {'state': 'in_progress', 'completed_baskets': 0,
           'github_run_id': os.getenv('GITHUB_RUN_ID'), 'github_sha': os.getenv('GITHUB_SHA')}
    def progress():
        (directory / 'run.json').write_text(json.dumps(run, indent=2), encoding='utf-8')
    progress()
    rows, groups, coverage = load_inputs(source)
    event_path = args.events or (source / 'events.json' if (source / 'events.json').exists() else None)
    events, event_provenance = load_events(event_path, source, groups)
    if len(rows) != 40:
        raise ValueError('Final holdout must contain exactly 40 source lines')
    reports, responses, guard_results, scenario_results = [], [], [], []
    with httpx.Client(base_url='http://127.0.0.1:18083', trust_env=False, timeout=15) as client:
        for order_id, group in groups.items():
            key = 'final-' + order_id + '-' + uuid4().hex
            payload, sequence, scenario_errors = prepare_checkout(group, events, stock_event)
            response = client.post('/v1/orders', json=payload, headers={
                'Authorization': 'Bearer ' + credential('GATEWAY_CUSTOMER_TOKEN'),
                'Idempotency-Key': key, 'X-Request-ID': 'req-' + order_id})
            body = response.json()
            effects = owner_effects(key)
            error = body.get('error', {})
            if sequence['feed_applied'] and (response.status_code != 409 or error.get('code') != 'STOCK_CHANGED'):
                scenario_errors.append('Menu/feed/checkout sequence did not return STOCK_CHANGED')
            scenario_results.append({'order_id': order_id, 'sequence': sequence, 'failures': scenario_errors})
            actual = observed_outcome(response.status_code, body)
            guards = boundary_failures(response.status_code, body, effects, 'req-' + order_id, group[0]['store_id'])
            guard_results.append({'order_id': order_id, 'failures': guards})
            responses.append({'order_id': order_id, 'http_status': response.status_code,
                              'body': body, 'effects': effects, 'scenario': sequence,
                              'scenario_failures': scenario_errors})
            for row in group:
                reasons = mismatch_reasons(row, response.status_code, body)
                diagnosis = ('Store absent from supplied stock snapshot' if row['store_id'] in coverage['missing_stores']
                             else 'Store present; provider response shown without synthetic catalogue or stock overrides')
                reports.append({'csv_line': row['csv_line'], 'order_id': order_id,
                    'line_item_number': row['line_item_number'], 'store_id': row['store_id'],
                    'expected': row['expected_outcome'], 'actual': actual,
                    'http_status': response.status_code, 'code': error.get('code', ''),
                    'expected_component': row['expected_missing_component'],
                    'actual_component': error.get('missing_component') or '',
                    'expected_message': row['expected_message'], 'actual_message': error.get('message', ''),
                    'payment_rows': effects['payment_rows'], 'queue_rows': effects['outbox_rows'],
                    'result': 'FAIL' if reasons else 'PASS', 'reason': '; '.join(reasons),
                    'boundary_failures': '; '.join(guards), 'scenario_failures': '; '.join(scenario_errors),
                    'diagnosis': diagnosis})
            run['completed_baskets'] = len(responses)
            progress()
    with (directory / 'results.csv').open('w', encoding='utf-8', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=list(reports[0]))
        writer.writeheader()
        writer.writerows(reports)
    (directory / 'responses.json').write_text(json.dumps(responses, indent=2, ensure_ascii=False), encoding='utf-8')
    summary = {**coverage, 'matched': sum(row['result'] == 'PASS' for row in reports),
               'mismatched': sum(row['result'] == 'FAIL' for row in reports),
               'match_fields': ['expected_outcome', 'expected_missing_component'],
               'boundary_failures': sum(bool(item['failures']) for item in guard_results),
               'mid_order_baskets': sum(item['sequence']['required'] for item in scenario_results),
               'mid_order_exercised': sum(item['sequence']['feed_applied'] and not item['failures'] for item in scenario_results),
               'scenario_failures': sum(bool(item['failures']) for item in scenario_results),
               'event_source': event_provenance,
               'source_sha256': {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                                 for name in ['orders.csv', 'stock.csv']}}
    (directory / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    for row in reports:
        print(f"{row['order_id']} line {row['line_item_number']}: {row['result']} "
              f"expected={row['expected']} actual={row['http_status']}/{row['code']} {row['diagnosis']}")
    run['state'] = 'completed'
    run['matched'], run['mismatched'] = summary['matched'], summary['mismatched']
    run['boundary_failures'] = summary['boundary_failures']
    run['scenario_failures'] = summary['scenario_failures']
    progress()
    return 1 if summary['mismatched'] or summary['boundary_failures'] or summary['scenario_failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
