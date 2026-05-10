# Lemma — Server Implementation Reference (draft)

This document describes how the reference Lemma server is organized to deliver the wire contract in `SPEC.md`. It is **non-normative** for clients: any server that implements `SPEC.md` correctly is conformant, regardless of whether it follows the layout below. This doc captures the design we have in mind for the first implementation, plus the implementation-level invariants that make the protocol's security and durability claims hold.

## 1. Persistence layout

```
~/.lemma/
  worlds/<name>/
    log.edn        ; append-only transaction log — source of truth
    meta.edn       ; uuid, packs, persistence config
    index.db/      ; derived store (Datalevin/LMDB), rebuildable from log
  packs/<name>/<version>/
    pack.edn       ; manifest + predicates + rules + verb definitions (all data)
    skill.md       ; agent-facing guidance
```

- The transaction log is canonical. Indexes are derived and rebuildable from the log alone — nothing in `index.db/` is load-bearing for correctness.
- `cp worlds/<name>/log.edn elsewhere.edn` is a complete world export by construction: the export format (`:format :log`) is the live-log format. This is an admin shortcut that bypasses the protocol; clients still go through `export`.
- A world's `meta.edn` records installed packs and their declared versions. Opening a world whose declared packs are not present on disk is a hard error at `welcome` time (returned to the client as `:error :reason :missing-pack` per `SPEC.md` §10).

### 1.1 Log framing

`log.edn` is **a sequence of top-level EDN values** with arbitrary whitespace between records. No special delimiter, no length-prefix, no per-record envelope — just one EDN value after another, exactly as `clojure.edn/read` already consumes any EDN stream. The format preserves the `cp log.edn` admin invariant by construction: the file *is* an EDN stream, and any standard EDN reader yields each tx record in order without a custom framing layer.

Records are pretty-printed (multi-line, indented) and separated by a blank line for human readability. The blank line is idiomatic, not load-bearing — `clojure.edn/read` skips any whitespace between values.

**Per-record shape:**

```clojure
{:tx-id     "t-1024"
 :session   "s-3"
 :timestamp #inst "2026-05-04T12:34:56.789Z"
 :ops       [{:op :assert  :predicate equivalent
              :subject #entity "a" :object #entity "b"}
             {:op :retract :ref "r-78"}
             …]
 :metadata  {…}}

{:tx-id     "t-1025"
 …}
```

`:ops` carries the canonical sequence of effects the tx applied — both explicit operations and any implicit cardinality-driven retracts (per `SPEC.md` §7). Reading the log replays the world from scratch by applying each op in order.

**fsync per tx.** The transactor writes the record's bytes, then fsyncs, then acknowledges the commit upstream. A crash before fsync returns leaves the tx un-committed (its bytes may or may not be on disk; either way the protocol layer didn't acknowledge); a crash after fsync returns means the tx is durable. This matches Lemma's provenance-first ethos — every committed tx is recoverable from the log alone.

**Crash recovery via forward parse.** On startup the server reads `log.edn` from the beginning, parsing one top-level EDN value at a time and tracking the byte position immediately after each successful read. If `clojure.edn/read` raises on a partial or malformed value (the trailing record from a crash mid-write), the server **truncates the file at the position of the last successful read** — discarding the unparseable trailing bytes. Those bytes were never fsynced through to a commit acknowledgment, so nothing client-visible is lost. The truncation is recorded in operator-side logs but not surfaced over the wire (no client could have observed the un-acked tx).

The forward-parse cost is O(log size), but the server already reads the whole log on boot to populate or verify indexes — so the framing choice adds no startup cost beyond what's already required. If logs ever grow large enough that the boot scan is itself the bottleneck, a checkpoint (last-good-position recorded in `meta.edn`) lets recovery start from the checkpoint rather than the beginning; this is an additive optimization and not part of the v1 contract.

**Tx-id allocation.** The tx-id sequence is monotonic within a world and is reconstructed at startup from the highest `:tx-id` in the log. Tx-ids are not gap-free across crashes (a truncated tx had reserved a tx-id that's now skipped); clients should not assume gap-freeness, only monotonicity.

**Index rebuild.** After log recovery, `index.db/` may be inconsistent with the log (an LMDB write that landed but whose log record was truncated, or vice versa). The server rebuilds the index from the log on detected mismatch — `meta.edn` carries the last log tx-id known to be reflected in the index; if the log's tail is ahead of that, replay forward; if the index is ahead (shouldn't happen given fsync ordering, but defensible), wipe and replay from scratch. The full rebuild is the "safe fallback" — slow but correct.

## 2. Message decoding (wire ingress)

The "lists appear only as the top-level verb form" invariant in `SPEC.md` §3 has a parser-side obligation: the server must rule on list-position validity *before* any domain code touches the message. The natural implementation is two-phase:

1. **Decode** the EDN bytes into an AST that faithfully preserves the list-vs-vector distinction (most EDN readers already do — just don't collapse the two during read).
2. **Walk** the resulting form once, top-down. The top-level value's head is checked against the session's verb registry; any list discovered below the top level is a structural rejection (`:error :reason :malformed` per `SPEC.md` §10). Reject on the first offender; do not continue the walk.

Only after the walk passes does the form reach verb dispatch and argument validation.

The `SPEC.md` §3 phrasing ("rejected … without further parsing of the form") is a *semantic* commitment — no domain handler, symbol lookup, handle resolver, or predicate evaluator sees the form past the offending position — not a literal byte-stream halt. In practice the bytes are already decoded into an AST; what matters is the walk-then-dispatch boundary is the single place the rule is enforced, and nothing past that boundary can see a rejected form.

Implementation notes:

- The verb registry must be populated before message intake begins. `welcome` already requires this, so the rule adds no new ordering constraint.
- "Stop parsing" on transport: for HTTP+SSE, drain the rest of the request body to preserve framing but discard; for the Unix socket, abandon the current message and resume reading at the next message boundary.
- The registry is the source of truth — pack-defined verbs become legal top-level heads the moment the pack loads; there is no hard-coded core list in the parser.

## 3. Packs (v1: logic packs only)

Packs add world-specific predicates, rules, and verbs without forking the protocol. In v1, **packs are pure data** — `pack.edn` is an EDN manifest containing predicate declarations, rule definitions, and verb definitions. There is no host-language code path.

### 3.1 Verbs as data

A verb definition is an EDN form describing a parameterized query, a rule application, or a composition of those. When a pack is loaded, the server compiles each verb definition into whatever internal representation it uses for the core `query` / `inconsistencies` machinery. When `(pack-ns/verb-name …args)` arrives from a client, the server resolves the invocation against the registered form and runs it through the same engine as core verbs.

There is no `eval`, no host-language hook, no escape hatch.

### 3.2 Sealed by construction

Because the only operations a verb body can express are query and rule application within the current world, the seal-by-default guarantees (no filesystem, no network, no cross-world reach) hold without any sandboxing — the verb language simply has no syntax for those operations.

### 3.3 Validation

- Pack manifests are validated structurally at load time: predicate shapes, rule heads/bodies, verb-body forms. Malformed packs fail to load and the world refuses to open.
- Client invocations are validated against the advertised signature (arity, qualifier names, argument types) before dispatch — this is also a wire-level invariant per `SPEC.md` §12.
- The protocol never executes client-supplied EDN as code. Clients send verb *invocations*; verb *bodies* live only in `pack.edn` files placed by the operator.

### 3.4 Extensional vs. intensional predicates

A predicate declaration may carry `:intensional? true` to mark it as IDB-only — produced by rule derivation, never assertable by users. The flag is enforced at three boundaries:

- **Fact-supplying paths** (`propose`, `import`): an inline `#fact{:predicate …}` whose predicate is intensional is rejected per `SPEC.md` §10. `assert` takes only `#proposal` handles, so it sees no inline facts; the firewall is at proposal-creation time.
- **Import**: a `:facts` payload carrying an intensional predicate fails the import atomically. Exports never write intensional facts in the first place — only the EDB is round-trippable; the IDB is recomputed from the EDB and the loaded pack rules at import time. See `SPEC.md` §11.
- **Storage**: the persistent `log.edn` records only EDB tx records. The LMDB-backed indexes do hold derived facts for query performance, but they are derived state, rebuildable from log + rules. Wiping `index.db/` and replaying the log reproduces the same IDB.

This distinction lets the IDB float across pack-version upgrades: changing a rule's body changes what gets derived, but never invalidates the EDB. It also matches Datalog's standard EDB/IDB separation (Ullman 1988), so the terminology will not surprise readers from the database-theory direction.

### 3.5 Substitution rules and the Leibniz pattern

A **substitution rule** propagates an equivalence (or any other identity-flavored relation) through some other predicate's argument positions. The canonical reading is Leibniz's law: `∀P. (a ≡ b) → (P(a) ↔ P(b))`. Datalog cannot quantify over predicates directly, so the law is enumerated per-predicate-and-position. For a binary predicate `p(x, y)` whose first argument is type-compatible with `equivalent`'s positions, the substitution rule on the first argument is:

```
{:head [p ?b ?y]
 :body [[equivalent ?a ?b]
        [p ?a ?y]]}
```

and symmetrically on the second argument. Substitution rules are otherwise just rules — the engine does not need special support, and the resulting facts are intensional (substitution-derived facts are not user-asserted, so the `:intensional?` invariants apply transitively through the rule's body).

Three things to know when authoring or reading substitution rules:

- **Type alignment is required.** A substitution rule on `p(?_, ?s)` where `?s` is a `:set` cannot use `equivalent` at that position unless `:set` is a subtype of `equivalent`'s argument type (`:id` in core). Pack authors who want substitution into a non-`:id` position declare it explicitly or define a same-typed equivalence relation on their own.
- **Closure size is proportional to equivalence-class size.** A class of *n* equivalent entities adds *O(n)* substitution-derived facts per containing relation. Pathological cases (large equivalence classes, many predicates with substitution rules) can blow up the IDB; bound the worst case during design rather than in production.
- **Equivalence on the equivalence relation itself is redundant.** `equivalent`'s own algebraic properties (symmetry, transitivity, optionally reflexivity) are sufficient — no separate substitution rule on `equivalent` is needed.

Core uses three substitution rules, covering the two `:id`-typed positions of `implies` and the first argument of `member-of`. Substitution into `subset-of`, `disjoint`, and `member-of`'s second (set-typed) argument is deliberately left to domain packs that need it; core does not enumerate set-typed substitution because the type signature crosses the `:id`/`:set` boundary, and forcing the choice in core would commit every world that loads `core` to a particular reading of set-equivalence.

### 3.6 Trust model & installation

- Pack installation is **strictly out-of-band**: the server operator places `pack.edn` and `skill.md` into `~/.lemma/packs/<name>/<version>/`. **No client verb installs, fetches, activates, or modifies a pack.** There is no `install-pack` verb, by design.
- **World creation is likewise strictly out-of-band**: the operator creates a world by placing `meta.edn` (and an empty `log.edn`) under `~/.lemma/worlds/<name>/`. **No client verb creates, deletes, renames, or otherwise modifies the world inventory.** The `worlds` verb lists; that is the full wire surface for world management. This is restated in `SPEC.md` §4 as a wire guarantee. Same rationale as pack installation: world creation establishes shared state with cohesion semantics and pack dependencies, and must be an operator decision rather than something a hostile or buggy client can effect.
- A world's `meta.edn` *names* required packs and versions but does not carry their bodies. Opening a world whose declared packs are absent fails at `welcome` time.
- `import` transports facts only — never packs, verb bodies, or any other code-shaped payload (this invariant is restated in `SPEC.md` §11 as a wire guarantee). Even though logic packs contain no native code, this matters: rule definitions can have unbounded compute cost, and predicates affect cohesion semantics. Pack installation must be an operator decision.

## 4. Open implementation questions

These are server-implementation concerns that don't affect the wire contract, but need answers before a production-grade server ships.

- **Log compaction.** Bitemporal logs grow unbounded. Snapshot + truncate? History-preserving rollup? Garbage-collection of orphaned facts? Whatever is chosen must preserve the `cp log.edn` admin invariant — or break it deliberately.
- **Pack version migration.** Upgrading a pack whose rules or predicate shapes have changed may invalidate existing facts in worlds that declare it. Migration protocol TBD: in-place rewrite, side-by-side versioning, or fail-loud and require an operator-driven re-import.
- **Adapter packs (v2).** Native-code packs for verbs not expressible as query/rule compositions (parsing, hashing, format conversion). Requires a sandboxing mechanism (subprocess+stdio, WASM, host-language capability grants — none chosen) and an explicit operator trust-grant flow at install time. v1 deliberately ships without any native-code path; this is the v2 conversation, not a v1 omission.
