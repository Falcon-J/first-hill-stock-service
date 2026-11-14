# Corrected decision: display text is diagnostic

The prior version treated MO-20250310-0167's two display messages as contradictory acceptance requirements. That was my comparator error. The final task compares **outcome and missing component only**; it does not compare display text. Both source strings and the existing v1 response remain unchanged, and the supposed message-conflict blocker is closed.

The matcher no longer reads expected_message, scenario_tag or line_item_number as expected-result predicates. Independent frozen-contract and no-charge guards remain enforced separately. See `resubmission.md` for the corrected oracle and fresh snapshot confirmation.

The seven missing stores and unsupported/missing components remain actual data failures. No count, mapping or recipe was created from an expected label.

Request ownership: Falcon-J owns tracking this PR request. The platform intake contact has not been identified; Amara was asked for the route and directed the request to the platform team lead. Do not invent a person's identity or claim that an external feed owner received a message when no contact destination is available.
