# Owner-local records

Stock owns Store (string ID, explicit aliases, open state), Component (on-hand,
reserved), Recipe (validated basket-to-component demand), AvailabilityToken
(opaque basket/store-bound advisory decision), Reservation (ID, owner, order,
canonical basket, timestamps, allocations, state), and idempotency tombstones.
State transitions: reserved -> confirmed/released/expired. Confirm atomically
rechecks stock/hours, converts to allocation, decrements on-hand and reserved
once. Confirmed allocations remain pinned through payment uncertainty. Terminal
unpaid cancellation restores once; captured allocations cannot be unpaid releases.
Expiry is now >= created_at+120 seconds; release/expiry cannot affect other owners.

Order owns Attempt (owner/key, canonical basket, durable result), PaymentAttempt
(stable provider key, authorization/capture/unknown result) and QueueOutbox
(unique order ID). Same key and basket replays; changed basket conflicts.
No stock quantities, authoritative hours cache or stock database access exists
in order. Accepted requires confirmed allocation then successful capture.

Gateway owns request correlation/deadline context only. It overwrites client
deadlines, forwards stable identity/key and never derives business decisions.
All error contracts preserve error.code, error.message and request_id. Line
numbers and missing components identify refusals; details lists multiple failures.
