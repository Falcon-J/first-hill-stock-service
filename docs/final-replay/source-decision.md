# One basket, two source messages: decision and tradeoffs

MO-20250310-0167 has two source rows (CSV lines 6–7) but is one complete order. The first requires `Caffè Latte (line 1) is unavailable: this store is not taking mobile orders right now.` The second requires `Cold Brew (line 2) is unavailable: this store is not taking mobile orders right now.` The frozen v1 envelope has one `error.message` and structured failure details, not a collection of per-line message strings.

| Option | What it preserves | What it breaks / costs | Decision |
|---|---|---|---|
| Keep v1 store-level STORE_CLOSED response, with its existing message policy and no ingredient-specific selected line. | Frozen contracts, existing exact refusal tests, whole-basket rejection and no charge. | Both source display-message expectations need an authoritative order-level comparison clarification. Does not create the missing store stock/hours row. | KEEP runtime behavior; request owner clarification. |
| Pick the first row's drink message (or the second row's). | At most one source display message. | The other row necessarily fails; arbitrary row choice changes existing message policy and cannot prove both expectations. | REJECT. The adapter must not select one. |
| Split the basket into two order calls. | Could produce two separate display messages. | Breaks atomic whole-basket ordering, idempotency and the multi-line refusal rule. Risks accepting/charging a partial order. | REJECT. |
| Add per-line message arrays or a new response shape. | Could model separate line displays explicitly. | Breaking frozen wire/consumer expectations requires a new API version and reviewed consumer/provider changes, outside this stage. | DEFER to owning-team versioned design. |

I chose to preserve the current v1 runtime contract and the original source values. The strict replay continues to show the contradiction; it does not rewrite an expected message, weaken assertions or claim a final pass. The owning team must confirm the authoritative order-level expectation (or approve a future versioned line-display contract). The missing seven-store feed and recipe/event inputs remain separate blockers.

Request ownership: Falcon-J owns tracking this PR request. The platform intake contact has not been identified; Amara was asked for the route and directed the request to the platform team lead. Do not invent a person's identity or claim that an external feed owner received a message when no contact destination is available.
