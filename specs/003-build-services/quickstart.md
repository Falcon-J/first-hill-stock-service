# Run and verify locally

Install Python 3.12 and Docker Desktop with its Linux engine running. From the
repository root, create/activate a Python virtual environment, then run:

```powershell
python -m pip install -r requirements-contracts.txt
python -m pytest -q
python -m ruff check .
python scripts/init_demo_env.py
docker compose up --build --detach --wait --wait-timeout 180
python scripts/demo_gateway.py
docker compose logs --no-color
```

The environment initializer creates random local credentials in ignored .env
and never prints them. Keep that file private. Compose publishes only gateway
on 127.0.0.1:18080; stock and order have private separate volumes and no public
ports. Each image copies only its own implementation and dependencies; only
stock includes the source CSV. Three containers run separately; payments use an
explicit local development adapter with no charges or outside payment service.

The gateway demonstration must return 409 BASE_OUT_OF_STOCK, line 1, Oatmilk.
Its exact body and request metadata are saved in evidence/gateway-oat-refusal.json
without credentials. Container access logs show gateway -> order POST /v1/orders
and order -> stock POST /v1/reservations; no payment/queue path is reached.

Claude Code's .claude/settings.json Stop hook invokes scripts/stop_gate.py. Run
Claude from this activated Python environment. The hook runs full pytest and
ruff and exits 2 on any failure or inability to run checks. A hook check is not a
substitute for the independently required latest-SHA contract-tests CI gate.
Hook exit semantics: https://code.claude.com/docs/en/hooks#exit-code-2
The PreToolUse Edit/Write guard also checks quality before spec/contract edits;
it reports BLOCKED SPEC EDIT while checks are red, so a failing provider cannot
be hidden by weakening its specification. Implementation edits remain available.

The historical seed and explicit small demo recipes are not a live store feed or
validated commercial recipe catalogue. Unknown stores/recipes fail closed.
Stock runs one worker per private state file; horizontal inventory scaling and
load/overselling hardening are separate work. HTTP calls and normal retry safety
are implemented and tested now; this does not claim a production deployment.
