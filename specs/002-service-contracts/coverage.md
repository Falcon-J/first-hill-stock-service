# Acceptance criteria to executable checks

Source criteria: ../001-order-refusals/spec.md. Its historical flat examples are
adapted to the boundary review's compatible error envelope as explicitly noted
in that spec. Canonical wire outcomes are in contracts/refusal-cases.json. Every
refused CSV order has its own parametrized pytest case, with exact response body,
line and missing component. These are real provider contracts, not implementation
claims. All functions below live in tests/contracts/test_providers.py unless noted.

| Criterion / rule | Pytest test | Input and required outcome |
|---|---|---|
| AC-R1 / R1 store_closed | test_order_refuses_each_sample_without_payment_or_queue (4 cases) | Source closed stores; exact 409 STORE_CLOSED, no payment/queue |
| AC-R2 / R2 base_out_of_stock | same function (6 cases) | Source absent bases; exact 409 BASE_OUT_OF_STOCK with line/component |
| AC-R3 / R3 addin_out_of_stock | same function (5 cases) | Source absent add-ins; exact 409 ADD_IN_OUT_OF_STOCK with line/component |
| AC-R4 / R4 insufficient_quantity | same function (2 cases) | Source excessive quantity; exact 409 INSUFFICIENT_QUANTITY, no partial acceptance |
| AC-R5 / R5 stock_runs_out_mid_order | same function (4 cases); test_stock_menu_read_is_not_a_hold_and_token_does_not_hide_checkout_loss; test_stock_atomic_race_and_ownership_safe_rollback | Menu available, checkout oat gone; exact fixture 409 STOCK_CHANGED; winner preserved; loser adds no syrup/espresso hold (baselines 2/4) |
| AC-P1 | test_order_confirms_before_payment_and_replays_once[MO-250303-0002-SB-11937-2% Milk] | Grande latte at SB-11937; reserve, confirm allocation, authorize, capture, accepted 201 and queue once |
| AC-P2 | same function [MO-250307-0023-SB-10482-Oatmilk]; stock atomic race test | Winning latte at race store; same full sequence and one capture/queue, despite race tag |
| AC-E1 | test_stock_expires_at_exact_boundary_and_release_is_idempotent; test_order_expired_or_unknown_store_preserves_exact_refusal[RESERVATION_EXPIRED] | T+120 expires; exact 409 expiry refusal, zero payment/queue |
| AC-E2 | test_order_stock_timeout_never_requests_payment (5 cases) | Reserve/confirm timeout, malformed evidence, stock 500/auth error; exact 503 STOCK_CHECK_UNAVAILABLE, zero payment/queue |
| AC-E3 | test_order_expired_or_unknown_store_preserves_exact_refusal[STORE_NOT_FOUND]; test_stock_unknown_store_is_not_guessed_or_treated_as_zero | SB-99999 order/near-match stock; 404 STORE_NOT_FOUND, no payment/queue |
| AC-E4 | test_order_invalid_input_refuses_before_dependencies (6 cases); test_order_unknown_catalogue_refusal_is_not_replaced (4); test_gateway_invalid_basket_preserves_legacy_error_envelope | Empty/invalid quantity, absent store/key, unknown catalogue; exact 422 INVALID_ORDER; no payment/queue |
| AC-E5 | test_order_confirms_before_payment_and_replays_once; test_stock_replay_never_double_reserves_and_payload_change_conflicts | Identical key/basket returns original 201 once; changed basket 409 IDEMPOTENCY_CONFLICT, no new side effects |

Additional owner asks: test_stock_confirm_rechecks_external_changes covers POS
and closure; test_stock_confirm_consumes_once_and_release_restores_once covers
allocation accounting; test_order_terminal_payment_decline_restores_allocation_once
covers 402 cleanup; test_order_uncertain_payment_is_pending_not_stock_refusal
covers 202 reconciliation. Gateway tests preserve all five refusal tags, enforce
the absolute deadline, forbid stock routes and separate infrastructure timeouts.
test_stock_unauthenticated_mutation_is_rejected covers service authentication.
tests/contracts/test_documents.py validates OpenAPI, examples, shared schemas,
all 21 fixture envelopes, snapshot baselines and the Actions job settings.
