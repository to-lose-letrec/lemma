# Lemma SPEC pending amendments

Drafted during Dianoia Phase 9 alignment 2026-05-20. Two sentence-level clarifications to SPEC §9 to admit a shared-per-world-buffer implementation of watch backpressure while keeping every wire event in SPEC §10 verbatim. Origin: orchestrator + adversary (`mr-e2f365599c00`) alignment cycle, locked by user.

The amendments preserve every wire event (`:watch-event`, `:watch-gap`, `:watch-closed :reason :slow-consumer`) and every behavioral guarantee in §9 (bounded buffer with reconciliation, sustained-slow disconnect). They broaden §9's wording from prescribing a per-watch buffer datastructure to describing the per-watch *view* of an implementation-defined buffer mechanism.

## Amendment 1 — §9 line 300, "Each watch has a per-watch event buffer"

**Current text:**

> **Watch backpressure: bounded buffer with reconciliation.** Each watch has a per-watch event buffer with a server-default cap of **1000 events** (configurable per server; clients may not raise it above the server's max). When a slow consumer fills the buffer, the server stops accepting new events into it but tracks the tx range of dropped events. Once the consumer drains the buffer, the server emits a single `:watch-gap` event (per §10) carrying `:missed-since`, `:missed-until`, and `:event-count`; the watch then resumes normal delivery. The consumer reconciles by issuing a `query :where <pattern> :between [<missed-since> <missed-until>]` to recover the missed deltas. The bitemporal log makes this query trivially correct; the `:between` qualifier is exactly what's needed.

**Proposed text:**

> **Watch backpressure: bounded buffer with reconciliation.** Each watch has an **effective per-watch buffer view** with a server-default cap of **≈1000 events** (configurable per server; clients may not raise it above the server's max). Implementations MAY back this view with per-watch buffers or with a per-world buffer shared across watches; the observable behaviour is identical. When a slow consumer falls behind enough that the server can no longer surface intervening events, the server stops accepting new events for that consumer but tracks the tx range of dropped events. Once the consumer catches up, the server emits a single `:watch-gap` event (per §10) carrying `:missed-since`, `:missed-until`, and `:event-count`; the watch then resumes normal delivery. The consumer reconciles by issuing a `query :where <pattern> :between [<missed-since> <missed-until>]` to recover the missed deltas. The bitemporal log makes this query trivially correct; the `:between` qualifier is exactly what's needed.

**Diff summary:**

- "per-watch event buffer with a server-default cap of **1000 events**" → "**effective per-watch buffer view** with a server-default cap of **≈1000 events**"
- New sentence inserted: "Implementations MAY back this view with per-watch buffers or with a per-world buffer shared across watches; the observable behaviour is identical."
- "When a slow consumer fills the buffer" → "When a slow consumer falls behind enough that the server can no longer surface intervening events" (broader; covers both per-watch-buffer-full and per-world-ring-overwritten cases)
- "Once the consumer drains the buffer" → "Once the consumer catches up" (same broadening)

**Rationale:**

The original wording prescribed a per-watch buffer data structure. Implementations that prefer a shared per-world ring buffer with per-watch cursors (Kafka/NATS-style; lower memory footprint at many-subscriber scale; writer commit-path stays O(1) in subscriber count) cannot honour the literal "per-watch event buffer" without duplicating the writer-side state. The amendment broadens the wording to describe observable behaviour rather than prescribe internal layout. Every wire event, every reconciliation guarantee, every slow-consumer policy is preserved.

## Amendment 2 — §9 line 300, "default cap of 1000 events"

Bundled with Amendment 1 above (the `≈` change). Implementations buffering per-tx (rather than per-event) may exceed 1000 events momentarily if a single tx carries many ops; the `≈` admits this without exposing the granularity choice to clients.

## Application

When Dianoia's Phase 9.2 (watch surface) ships and we're ready to publish the amendments upstream, the SPEC.md change is a single edit to §9 line 300 incorporating Amendment 1's proposed text. No §10 changes. No new wire events. No removed wire events.

Amendments staged for individual commit (no co-author per user norm).

## Origin trace

- **Dianoia Phase 9 alignment** — 2026-05-20.
- **Adversary critique source**: `mr-e2f365599c00` (DeepSeek-V4-Pro) recommended a pull-based watch architecture (Kafka/NATS/Datomic-tx-report pattern). Orchestrator surfaced as a SPEC-level question; user chose path γ (hybrid — shared-ring internal mechanism with push wire interface) requiring only this minor §9 amendment.
- **Why not full pull-based pivot**: would require dropping `:watch-gap` and `:watch-closed :reason :slow-consumer` from §10 — a substantial wire change incompatible with the protocol's deltas-with-gap-reconciliation contract.
- **Why not stay literal SPEC push**: shared-ring is meaningfully simpler (O(1) writer commit; 1 ring per world vs N per-watch buffers) and the SPEC §9 wording isn't load-bearing for clients — only for implementations.

---

# §7 tuple-idempotency for `:cardinality :many` (Dianoia Phase 10.2.2.0)

Drafted during Dianoia Phase 10.2.2.0 alignment 2026-05-21. SPEC §7 line 175 spells out `:cardinality :one` `v_old=v_new` no-op elision in detail but is silent on the analogous case for `:cardinality :many` — namely, re-asserting an identical `(predicate, subject, object)` against a `:many` predicate. The natural Datalog reading is set-semantic (re-assert is a no-op); the natural commit-log reading is per-event accumulation. Two adversary passes during 10.2.2.0 alignment (one on the locked design, one steelman against the premise) confirmed the SPEC silence was ambiguous, with the set-semantic reading winning on every probe.

## Amendment — §7 line 175, "Cardinality `:one` replaces; `:many` accumulates"

**Current text (excerpt):**

> Predicates declared `:cardinality :many` do not auto-retract; multiple values for the same subject coexist normally.

**Proposed text:**

> Predicates declared `:cardinality :many` do not auto-retract; multiple **distinct** values for the same subject coexist normally. Re-asserting an identical `(predicate, subject, object)` against a `:many` predicate — where the same tuple is already live in the EDB — is a no-op, mirroring the `:one` `v_old=v_new` elision: the engine elides the op and `:asserted :refs []` returns; no new tx-id is burned. A previously-retracted-and-then-re-asserted `(p s o)` mints a fresh ref-id (a new bitemporal life), so retract-then-re-assert remains a recordable history change.

**Diff summary:**

- "multiple values" → "multiple **distinct** values" (one-word clarification).
- New sentence: re-assert of identical tuple is a no-op, paralleling the `:one` elision.
- New sentence: retract-then-re-assert mints fresh (preserves bitemporal history).

**Rationale:**

The SPEC's silence forced every implementer to invent a v_new=v_old policy for `:many`, with no guarantee of cross-server consistency. Dianoia's Phase 10.2.2.0 cohesion stage 3.5 makes this explicit: a single source of truth for tuple-idempotency across both cardinalities. The amendment removes the SPEC ambiguity without changing the wire surface — `:refs []` is already the response shape for `:one` v_old=v_new, and `:many` re-assert now produces the same envelope. The bitemporal retract-then-re-assert carve-out preserves the recordable-history contract.

## Application

Apply at Phase 10.2.2.0 close-out. The single edit to SPEC.md §7 line 175 incorporates the proposed text. No §10 changes. No new wire events. No removed wire events.

## Origin trace

- **Dianoia Phase 10.2.2.0 alignment** — 2026-05-21.
- **Adversary pass 1**: implementation-level critique of the locked design surfaced four amendments (Issues 2, 4, 6, 10), all applied pre-injection.
- **Adversary pass 2**: explicit steelman against the tuple-idempotency premise — 8 probes designed to defend per-assert-mints-ref-id. None mounted a credible argument; premise survived. Probe 2 (SPEC §7 silence) flagged this amendment as the SPEC hygiene tail of the ship.
- **Why now**: 10.2.2.0 is the prerequisite to 10.2.2.A (`import` verb). Without tuple-idempotency, re-importing an export onto its source world would double every fact. Fixing the under-specification at the SPEC level rather than burying the policy in a single server's implementation is the right hygiene step.
