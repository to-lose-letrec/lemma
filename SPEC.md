# Lemma — Protocol Requirements & Spec (draft)

## 1. Goals

- **EDN-native successor to MCP** for multi-agent shared-fact systems.
- **Cohesion before commitment**: every normal write passes through a server-side cohesion check. No bypass path during routine operation.
- **Provenance-first**: every committed transaction is attributable to a session; history is queryable.
- **Time-travel queries**: point-in-time and interval reads are first-class.
- **Concurrency without client-visible locks**: the transactor serializes per-world writes; clients never hold, acquire, or see locks.
- **Composable via packs**: predicates, rules, and new verbs can be added by extension without forking the protocol.
- **Transport-agnostic semantics**: identical EDN grammar whether local (Unix socket) or remote (HTTP+SSE).
- **Keeps agents on-rail through design, not coercion**: skill docs + rich responses pull agents toward the resource; the protocol does not dictate user-facing output.

## 2. Non-goals (v1)

- Streaming import/export.
- Rebase or merge of divergent worlds.
- Client-visible locking primitives.
- A protocol-advertised "usage transcript" in `hello`.
- Cross-session proposal sharing.
- Any constraint on the LLM's user-facing response format.
- Distributed / sharded worlds. (A world lives on one server.)
- Native-code packs. v1 has no host-language execution path reachable from the wire; verb dispatch resolves only to query/rule semantics. Adapter packs are a v2 conversation (see `SERVER.md`).

## 3. Wire format & transport

- **Encoding**: EDN as defined by the edn-format spec (https://github.com/edn-format/edn). Tagged literals are required for a compliant parser. The reference implementation of the dialect is Clojure's `clojure.edn` (specifically `clojure.edn/read` and `clojure.edn/read-string`); where the public spec is ambiguous, `clojure.edn`'s behavior is normative. Note that this is `clojure.edn`, *not* `clojure.core/read-string` — the former is safe by default and rejects code-shaped reader extensions (`#=`, var literals, function literals, regex literals); the latter executes them and must not be used to parse client input under any circumstances.
- **Tagged-literal closure.** The set of accepted tags is closed: exactly the table in §5 (plus tags advertised by loaded pack extensions). Unknown tags cause `:error :reason :malformed`. This is stricter than `clojure.edn`'s default behavior — which preserves unknown tags as `tagged-literal` records — and is enforced by installing explicit readers for each known tag and a `:default` reader that throws on anything else.
- **Local transport**: Unix domain socket. Connection identity = session identity. No per-request session envelope. Filesystem permissions on the socket path control connection-level access. Servers MAY use `SO_PEERCRED` (or platform equivalent) to bind a session to the connecting OS user; if they do, the credential is recorded in `#session` server-side and surfaces on `:welcome` via the `:lemma/peer-cred` capability flag and a `:peer` field carrying `{:uid N :gid N}`. Full auth/authz is deferred per §14; v1 treats peer-cred as a hint, not a permission gate.
- **Remote transport**: HTTP + SSE. Session id lives in URL path (`POST /v1/sessions/{id}/messages`) or header (`X-Lemma-Session: …`). EDN body is identical to Unix-socket form.
- **TLS is strongly preferred for `Remote transport`.** v1 does not mandate TLS at the wire level (there is no in-protocol negotiation), but any non-localhost HTTP+SSE deployment SHOULD enforce TLS at the transport layer. Servers MUST advertise TLS-on-this-connection via the `:lemma/tls` capability flag (§10) when applicable; clients SHOULD refuse to send credentials, proposals, or write verbs over a non-TLS HTTP connection unless the operator has explicitly opted in to plaintext. TLS 1.2 minimum, 1.3 preferred; certificate validation REQUIRED. (Unix socket has no analogous concern — filesystem permissions are the access boundary.)
- **Body shape**: one top-level EDN value per message. Client sends s-expression verbs; server sends maps keyed by `:event`.
- **Lists appear only as the top-level verb form.** A client message is one EDN value; if that value is a list, it is the verb invocation, and its first element MUST resolve to a verb name advertised on the current session (core or pack extensions). Lists nested anywhere else — inside an argument, a map value, a vector — are a structural error and the message is rejected with `:error :reason :malformed` without further parsing of the form. Collections in argument position are built from vectors, maps, keywords, and tagged literals; the parenthesized list syntax is reserved for verb invocation alone. This is structural defense in depth: §2 already forbids any host-language execution path on the wire, but the rule keeps a "looks like a function call" payload from ever reaching a position the server might be tempted to interpret, and it forecloses nested-verb evaluation ambiguity by construction. Pairs with §11's import-transports-facts-only guarantee — between them, no code-shaped value on the wire can survive past dispatch validation.
- **Metadata** (`^{…}`) is reserved for operation-semantic annotations (confidence, source tagging), capture-time stamping, and client-supplied request correlation. Session routing never rides in metadata.
- **Request correlation.** A client MAY attach `^{:request-id "…"}` to any verb form. If present, the server echoes the value as `:in-reply-to` on the response event for that request. Required for HTTP+SSE when running concurrent requests (POSTs and SSE events are not order-correlated); optional over a Unix socket, where FIFO request/response ordering already suffices. For verbs that establish a stream (e.g. `watch`), `:in-reply-to` appears on the establishment event; subsequent stream events carry their own handle (`#watch`, `#cursor`) and do not echo it.

## 4. Session model

- `hello` upgrades an anonymous connection to a named session; server returns `{:event :welcome …}` with `#session`, default world, capabilities, predicates, verbs (core + pack extensions).
- **`hello` is the only verb permitted on an anonymous connection.** Any other verb sent before `hello` returns `{:event :error :reason :no-session}`. The client always initiates; the server does not push pre-session events. (v1 — auth/handshake extensions deferred per §14.)
- **Per-session state** (torn down on disconnect): open proposals, watch subscriptions, query cursors, current `use-world` selection.
- **Shared state**: committed facts, tx log, indexes, rules, packs. Each committed tx records its originating `#session`.
- Proposals are bound to the creating session; cross-session assert of a `#proposal` is rejected.
- **A session sees exactly one world's facts at a time.** The current `use-world` selection is exclusive — there is no implicit cross-world visibility. Queries return only the current world's EDB (plus its IDB derived from its loaded packs); rules from the current world's packs apply only to the current world's facts; proposals and asserts commit to the current world only. Multiple worlds may coexist on a server (and the `worlds` verb lists them), but composition across worlds — read-only references, snapshot imports, hypothesis-world overlays on a base world — is **not** in v1. Workflows that need cross-world reasoning today must do it client-side: query world A, switch with `use-world`, propose into world B with the queried results re-asserted as fresh facts (losing A's tx-ids and refs in the process). A protocol mechanism for cross-world reads is a recognized gap and will be revisited; v1 is single-world-per-session by design.
- **World creation is out-of-band**, parallel to pack installation (§12, `SERVER.md` §3.6). The operator creates a world by placing a `meta.edn` (and an empty `log.edn`) under `~/.lemma/worlds/<name>/` on the server filesystem. **No client verb creates, deletes, renames, or otherwise modifies the world inventory.** The `worlds` introspection verb lists existing worlds; that is the full extent of world-management surface on the wire. The same trust rationale as for packs applies: world creation establishes shared state with cohesion semantics and pack dependencies; it must be an operator decision, not something a hostile or buggy client can effect.

## 5. Tagged literal handles

| Tag | Lifecycle stage |
|---|---|
| `#fact{…}` | Inline fact (pre-commit payload) |
| `#proposal "p-N"` | Pending, cohesion-checked, not yet committed |
| `#tx "t-N"` | Committed transaction |
| `#ref "r-N"` | Committed fact reference |
| `#cursor "c-N"` | Query pagination handle |
| `#watch "w-N"` | Subscription handle |
| `#session "s-N"` | Session identifier |
| `#world "…"` | World name |
| `#entity "…"` | Domain entity |
| `#violation{…}` | Inconsistency record |

### 5.1 Inline fact shape (`#fact{…}`)

The `#fact{…}` payload denotes a single fact destined for the EDB (per §10). The shape is a predicate triple:

```
#fact{:predicate <name> :subject <s> :object <o>}
```

Specifics:

- `:predicate` — symbol identifying the predicate. Bare symbols name core predicates (`equivalent`); namespaced symbols name pack-extension predicates (`my-pack/foo`). Must resolve to a declared predicate in the session's current world; otherwise `:error :reason :bad-args :detail {:reason :unknown-predicate :predicate '…}`.
- `:subject` — the first positional argument. Type must match the predicate's declared `:value-types[0]` (per the §10 predicate-event metadata).
- `:object` — the second positional argument, present for binary predicates. Type must match `:value-types[1]`.
- **Unary (1-arity) predicates omit `:object`**: the fact carries `:subject` alone. (Used in core for `inconsistent`; pack authors may declare other unary predicates.)
- **Higher-arity (3+) predicates** — uncommon, pack-defined — use `:args [<a1> <a2> <a3> …]` in place of `:subject` / `:object`. Length of `:args` must equal the predicate's declared `:arity`. A `#fact` carrying both `:subject`/`:object` and `:args` is `:bad-args`.

Arity mismatch — `:object` present for a unary predicate, missing for a binary predicate, or `:args` length disagreeing with the declared `:arity` — is `:bad-args`.

Optional metadata may attach via EDN's `^{…}` syntax (e.g. `^{:confidence 0.9}`, `^{:source-tag :ingest}`) per §3. Metadata is preserved as proposal-time provenance and is queryable via the `provenance` verb (§8).

A `#fact` whose predicate is flagged `:intensional? true` is rejected per the §10 intensional-predicate rule.

**Wire form for entity references.** All entity references on the wire use the `#entity "name"` tagged literal uniformly, regardless of whether the predicate position is declared `:id` or `:set` (or other sub-kinds packs may introduce). The pack-level type distinction is *semantic* — used at pack-load time to validate rule body shapes and documented in predicate metadata — not wire-structural. An agent inspecting a fact or violation derives type semantics from the predicate's declared `:value-types`, not from the wire form.

### 5.2 Violation shape (`#violation{…}`)

A `#violation{…}` is a derived inconsistency, produced when a rule whose head predicate is `inconsistent` (or, for packs, another predicate the engine treats as a violation predicate) fires. Violations appear in:

- `:rejected` events from `propose` / `assert`, when the cohesion check derives a new violation from the proposed facts;
- `:inconsistencies` events from the `inconsistencies` verb, when the world's existing facts already derive violations.

The `:violations` field of either event is **a vector** — a single rule firing produces one entry, but multiple rules or multiple bindings of a single rule produce one entry each.

The shape:

```
#violation{:rule     <pack-qualified rule name>
           :anchor   <entity bound at the head's primary position>
           :bindings {<?var> <value>, …}
           :message  <string, with bindings substituted>}
```

Specifics:

- `:rule` — symbol naming the rule that fired, namespaced by its pack (`core/disjoint-membership`). If the pack manifest did not give the rule an explicit `:name`, the server fabricates `<pack>/rule-<index>` from the rule's position in the manifest; agents should not rely on fabricated names being stable across pack versions.
- `:anchor` — the entity-reference value bound at the rule head's primary position. For an `inconsistent(?x)` rule, this is the bound `?x`. The anchor is the entity that the violation "is about." Its wire form is `#entity "…"` per §5.1's uniform-entity-reference rule.
- `:bindings` — map keyed by the rule's body variables (as symbols, including the `?` prefix to match the rule body verbatim), with values rendered as full tagged literals (`#entity "…"`, primitives as their EDN literals). Round-trippable; an agent can paste a binding value back into a query.
- `:message` — human-readable string. Pack-supplied template with `?var` interpolation; entity-typed bindings substitute as their bare name (e.g. `alice`) for readability. Primitives substitute as their EDN literal. If the pack rule did not supply `:message`, the server falls back to a generic rendering of the rule head with bindings.

Rules in pack manifests that derive `inconsistent` (or pack-defined violation predicates) MAY carry two optional keys:

- `:name <symbol>` — local name used as the suffix in `:rule` (`core/<name>`). Stable across pack versions; recommended for any rule that produces violations.
- `:message <string>` — template string for the violation's `:message` field. Template variables are body variables (`?x`, `?a`, etc.); entity values substitute as bare names, primitives as EDN literals.

Both default to fabricated values if omitted. Substitution rules and other non-violation rules typically do not need `:name` or `:message`.

### 5.3 Entity identity (`#entity "…"`)

`#entity "<name>"` is a tagged literal whose value is a string treated as a **name**. The protocol's entity-identity model has four properties:

**Structural identity.** Two `#entity` references are the same entity iff their name strings are byte-equal. There is no server-side allocation, no minting verb, no per-entity registry. `#entity` works the way `#uuid` and `#inst` work — the tag carries the type (entity reference, distinct from a plain string), the value carries the data (the name). The bare string `"alice"` and `#entity "alice"` are *not* equivalent on the wire; the tag is what lets `:value-types [:id :string]` be a meaningful predicate signature (subject is an entity reference; object is a plain string).

**Per-world scope.** Entity identity is local to a world. `#entity "alice"` in world X and world Y are unrelated; the per-world isolation from §9 extends to entity references. Cross-world reference flows only through `export`/`import`, and import treats every entity reference as new in the receiving world (an isomorphic-but-distinct entity), consistent with `import`'s tx-id reassignment.

**Implicit lifecycle.** An entity is "in" a world iff at least one fact references it. There is no `(create-entity …)` verb, no `(delete-entity …)` verb. To bring an entity into being, assert a fact about it; to remove it from the world, retract every fact that mentions it. Names never collide structurally, but **clients are responsible for namespacing** when collision risk matters semantically — e.g., `#entity "user/alice"` and `#entity "company/alice"` if both meanings are needed in the same world.

**Equivalent ≠ same.** Asserting `equivalent #entity "a" #entity "b"` does *not* unify the two references into one canonical form. Both remain distinct entity references; the substitution rules from §5.2 / core's pack make them interchangeable across all other relations (Leibniz's law), but queries return both. Consumers that want one-row-per-equivalence-class implement that themselves (post-processing or a domain-pack-defined canonicalization predicate). v1 does not provide a built-in canonicalization mechanism.

**Name validity.**

- Empty names are **rejected**: `#entity ""` returns `:error :reason :bad-args :detail {:reason :empty-entity-name}`. An empty name has no referent, which the protocol cannot model.
- All other EDN-string-valid contents are accepted: whitespace, control characters, Unicode, namespaces (`"user/alice"`), and any other operator-chosen convention. The server treats names as opaque strings.
- A self-equivalence fact (`equivalent #entity "a" #entity "a"`) is accepted as a vacuous no-op — it's trivially true and harmless. The cardinality / no-op elision rules from §7 apply: it commits without effect.

**Type tags `:id` and `:set` are semantic, not runtime-enforced.** Pack predicate declarations using `:value-types [:id :set]` etc. enforce rule-body shape at *pack-load time* (a rule body putting an `:id` argument into a `:set` slot is a pack-load error per `SERVER.md` §3.5). At runtime the server treats all entity references uniformly through `#entity`. There is no entity-kind registry; `:id` and `:set` do not gate `propose` / `assert`. Domain packs that genuinely need runtime kind enforcement implement it via predicates and rules — e.g., a `(is-a ?e :set)` predicate plus violation rules that fire `inconsistent` on misuse. The mechanism is available; core does not impose it.

## 6. Client verbs (23)

**Introspect** — `capabilities`, `predicates`, `verbs`, `rules`, `stats`, `worlds`, `provenance`, `tx-info`, `dump`
**Bulk** — `export`, `import`
**Write** — `propose`, `assert`, `retract`, `cancel`
**Query** — `query`, `continue`, `inconsistencies`
**Subscribe** — `watch`, `watch-pattern`, `unwatch`
**Session** — `hello`, `use-world`

Introspection verbs that return world-scoped data (`predicates`, `verbs`, `rules`, `stats`) accept an optional `:world #world "…"` qualifier; default is the session's current world. This lets an agent survey a world without `use-world`-ing into it.

**Welcome carries names; introspection verbs carry detail.** `:welcome` advertises only the *names* of available predicates and verbs (split into `:core` and `:extensions {pack-name …}`). To learn signatures, types, cardinality, or doc, call `predicates` / `verbs` / `rules` / `capabilities` directly. This keeps `hello` cheap on connection and lets agents fetch detail only for the surface they actually intend to use.

## 7. Write semantics

Exactly one write path during normal operation:

```clojure
(propose #fact{…} #fact{…} …)   ; cohesion checked server-side
(assert #proposal "p-42")        ; single-shape; promotes a handle
```

- `propose` returns `{:event :proposed :proposal #proposal "…" :expires-at #inst "…"}` **if and only if** the proposal passes all five write-time checks (see below). Otherwise `{:event :rejected :reason … :violations […]}` for domain failures (stages 3-5) or `{:event :error :reason :bad-args :detail {…}}` for protocol failures (stages 1-2), with no handle minted.
- `assert` takes exactly one argument: a `#proposal` handle. No inline-fact shape, no refs.
- **Cohesion is re-checked at assert time.** A proposal handle is a statement about the world at propose-time; intervening commits can invalidate it. Re-check at assert; on failure, return fresh violations.
- Import is the only path for "unconditional as long as valid" — restoration, migration, bootstrap. Not for routine writes.
- `retract` accepts `#ref`, `#tx`, `#proposal`, or `:where [<clause> …]` (clause-vector form per §8.1). A `:where` retraction matching no facts is a successful no-op, returning `{:event :retracted :refs []}` with **no `:tx` field** — the server elides the empty transaction rather than burning a tx-id on a write that didn't change the world. **Retraction is not cohesion-checked**: unlike `propose` / `assert`, a `retract` MAY leave the world inconsistent. Violations it introduces surface as new `inconsistencies` and the next `propose` will see them in its cohesion check. This asymmetry is deliberate — retraction is a corrective action that sometimes needs to break a temporarily-cohesive state to reach a better one, and gating it behind the cohesion check would create dead-ends from which a world cannot recover.
- `(propose)` with no facts is rejected `:reason :empty`.
- **Proposal expiry.** A `#proposal` lives server-side for an idle TTL after creation; if the client neither `assert`s nor `cancel`s before `:expires-at`, the proposal is dropped silently. The default TTL is **300 seconds**; servers MAY configure a different value per-world via `meta.edn` (the value used is reflected in every `:proposed` event's `:expires-at`, so clients always have ground truth). No proactive expiry event is pushed to the client — abandoned proposals fall off without notice. A subsequent `assert` or `cancel` against an expired handle returns `:error :reason :unknown-handle` per §10 (proposals are session-scoped per §4 and the handle ceases to refer once it is no longer pending — expired and never-existed are indistinguishable to the client).
- **Write-time check order.** A `propose` runs five checks against the inline facts before producing a proposal handle. Each check has its own failure mode and rejection reason; later checks only run if earlier checks pass.
  1. **Type-check** — each fact's argument types must match the predicate's declared `:value-types`. Failure: `:error :reason :bad-args :detail {:reason :type-mismatch :predicate '… :position N}`.
  2. **Intensional-predicate check** — no fact's predicate may be flagged `:intensional? true`. Failure: `:error :reason :bad-args :detail {:reason :intensional}` (per §10).
  3. **Uniqueness check** — for any predicate flagged `:unique? true`, the proposed fact's value must not already exist (under any subject) in the EDB, and the proposal batch must not contain two facts with the same value. Failure: `:rejected :reason :unique-conflict` with `:detail` carrying the offending predicate, value, and the conflicting `#ref` or in-batch fact index.
  4. **Cardinality / self-conflict check** — for any predicate flagged `:cardinality :one`, the proposal batch must not contain two facts with the same subject. Failure: `:rejected :reason :cardinality-self-conflict` with `:detail` identifying the offending pair.
  5. **Cohesion check** — run rules over the *post-state*: the EDB minus any facts implicitly retracted by `:cardinality :one` (see below), plus the proposed facts. Failure: `:rejected :reason :cohesion :violations [#violation{…}]`.

  Only after all five checks pass does the server mint a `#proposal` and return `:proposed`. The same five checks re-run at `assert` time, since intervening commits can invalidate the post-state.
- **Cardinality `:one` replaces; `:many` accumulates.** When a propose introduces a fact `(p s v_new)` for a predicate `p` declared `:cardinality :one`, and an existing fact `(p s v_old)` is in the EDB, the commit *implicitly retracts* `(p s v_old)` atomically with asserting `(p s v_new)` — both ops live in the same tx. The post-state seen by the cohesion check (step 5 above) reflects the retract. The `:asserted` response carries the retracted refs in a `:retracted-refs` field (per §10) so the agent knows what was auto-retracted. If `v_old = v_new`, the engine elides both ops and `:asserted :refs []` returns — a no-op write costs no tx. Predicates declared `:cardinality :many` do not auto-retract; multiple values for the same subject coexist normally.
- **`:unique?` is global.** A predicate flagged `:unique? true` enforces that its `:object` (or `:args[1]` etc., for non-binary cases) is unique across the entire EDB for this predicate — no two facts can have the same value, regardless of subject. Reject-on-conflict (no replace semantics; the engine cannot infer which existing subject to remove). `:cardinality` and `:unique?` are orthogonal and can both be set on the same predicate (e.g. `username` is typically `{:cardinality :one :unique? true}`).
- `cancel` takes exactly one argument: a `#proposal` handle. It drops a pending proposal explicitly rather than waiting for `:expires-at` to elapse, returning `{:event :cancelled :proposal #proposal "…"}`. Cancelling a proposal that does not exist, has already been asserted, has already been cancelled, has expired, or belongs to a different session returns `:error :reason :unknown-handle` — proposals are session-scoped (§4) and the handle simply ceases to refer once the proposal is no longer pending. `cancel` is purely advisory cleanup; nothing in the protocol depends on a client calling it.

## 8. Query semantics

- `query` takes `:find`, `:where`, plus qualifiers: `:as-of #tx`, `:between [#tx #tx]`, `:limit`, pagination via `continue #cursor`.
- `dump` accepts the same `:as-of` / `:between` qualifiers.
- `inconsistencies` supports one-shot (optional `:since #tx`) or continuous via `(watch :inconsistencies)`.
- `provenance` returns the session, tx, timestamp, and any proposal-time metadata attached to a fact or tx.
- **Negation is failure-as-negation (NAF) over stratified rules.** A `not` clause inside `:where` succeeds when the negated pattern cannot be derived from the EDB and the loaded packs' rules. Pack rule sets are stratified at load time so NAF has a well-defined fixed-point semantics. There is no classical negation: the protocol does not assert `¬P` as a fact; it derives "P is not derivable" by closed-world reasoning.
- **The query language is Lemma's, not the underlying engine's.** Clients only ever see Lemma's `:find` / `:where` grammar (specified in §8.1 below). The server compiles queries to whatever the configured engine accepts (the reference server uses Datalevin; see `SERVER.md`). There is no verb that passes engine-native syntax through; the wire surface stays narrow and engine-agnostic, and a future server backed by a different engine remains protocol-conformant.
- **Bitemporality is single-axis.** Lemma's time model is *transaction-time only* — `:as-of` and `:between` reference `#tx` values, which are commit-ordered identifiers. There is no separate *valid-time* axis; the protocol does not distinguish "when this fact was committed" from "when this fact was true in the world." Domains that need valid-time semantics model them as ordinary predicates carrying date arguments (e.g. `(employed-from ?p ?date)` / `(employed-until ?p ?date)`). This is a deliberate simplification — Datomic-trained readers should not assume a valid-time qualifier is implicit; only `:as-of` and `:between` against `#tx` are.

### 8.1 Query grammar

The grammar comprises three top-level constructs: a `:find` clause, a `:where` clause, and qualifiers. The same grammar is consumed by `query`, `watch-pattern` (the `:pattern` qualifier accepts a `:where` clause vector), and `retract :where` (likewise).

The grammar is intentionally distinct from Datomic / Datalevin native syntax: predicate-first fact patterns rather than subject-first, keyword-headed operator vectors rather than nested lists, and a single uniform result shape (relation rows). A reader familiar with Datomic should immediately notice the differences and not assume Datomic semantics carry over.

**Variables and constants.** Variables are symbols prefixed with `?` (e.g. `?x`, `?member-set`). Constants in argument position are tagged literals (`#entity "managers"`), strings (`"Alice"`), numbers (`30`), booleans, or `nil`. Bare unprefixed symbols in argument position are `:bad-args`; they are neither variables nor valid literals. (Bare symbols are reserved for predicate names and operator-clause heads.)

**Fact patterns** are vectors with a *symbol* at head:

```
[<predicate> <subject> <object>]    ; binary
[<predicate> <subject>]             ; unary
[<predicate> <a1> <a2> <a3> …]      ; n-ary (uncommon, pack-defined)
```

The predicate symbol resolves to a declared predicate (core or pack-extension; bare or namespaced as `my-pack/foo`). Argument count must match the predicate's `:arity`. A pattern with a `?`-prefixed symbol at head — `[?p ?x ?y]` — is a *predicate-variable pattern* matching any predicate; at least one variable in such a pattern must be otherwise bound by the rest of the `:where`, otherwise `:bad-args :detail {:reason :unbound-predicate-variable}`.

**Operator clauses** are vectors with a *keyword* at head:

```
[<:operator> <args> …]
```

The grammar dispatches on head type: keyword head → operator clause; symbol head → fact pattern. Reserved operators in v1:

- **Comparison** (arity 2; both args evaluate to values; bound variables expected): `:=`, `:!=`, `:>`, `:<`, `:>=`, `:<=`.
- **Logical** (args are clauses, applied recursively): `:not` (arity 1), `:and` (variadic ≥ 2), `:or` (variadic ≥ 2). `:not` implements failure-as-negation per the §8 NAF rule.

Pack-defined operators namespace as `:my-pack/op`. The bare-keyword namespace is reserved for core; future protocol versions may add operators under that namespace.

**The `:find` clause** is a vector of variables and aggregations:

```
:find [<var-or-aggregation> …]
```

Aggregations are operator-first vectors with aggregation-keyword heads. v1 reserves: `[:count <var>]`, `[:sum <var>]`, `[:max <var>]`, `[:min <var>]`, `[:distinct <var>]`. Aggregations group by the non-aggregated variables in `:find` (standard SQL/Datalog semantics — projection-implies-grouping).

The result is **always a relation** (vector of row vectors). There are no scalar / vector / tuple shape variants in `:find`; single-value queries use `:limit 1` and client-side destructuring of `[[<value>]]`. Empty `:find` is `:bad-args`.

**The `:where` clause** is a vector of clauses (fact patterns and operator clauses), implicitly conjoined:

```
:where [<clause> <clause> …]
```

A `:where` may be empty (`[]`); a query with empty `:where` and a `:find` consisting only of constants returns one row of those constants. (Mostly useful for trivial sanity checks; not for real workloads.)

**Qualifiers.**

- `:as-of #tx "…"` — point-in-time read at the given tx.
- `:between [#tx "…" #tx "…"]` — interval read.
- `:limit N` — cap result row count. With aggregations, `:limit` applies to the grouped result, not the pre-aggregation rows.
- `:offset N` — skip the first N rows; used with `:limit` for pagination via `continue` (server-managed cursor; clients do not paginate by `:offset` themselves).

Without `:as-of` / `:between`, the query reads the world at the current head tx.

**Cursor TTL.** A `#cursor` is held server-side as a bookmark (last-seen key + query metadata); it does *not* hold an open LMDB read transaction (see `SERVER.md` for the rationale). The default idle TTL is **300 seconds**, refreshed on each `continue`. A `continue` against a cursor that has expired (no activity within the TTL) returns `:error :reason :unknown-handle`; the client re-issues the underlying `query` with the same qualifiers to start fresh. Servers MAY configure a different idle TTL.

**Result ordering and cursor stability.** Non-aggregated query results are ordered deterministically by **(tx-id ascending, ref-id ascending)** of the underlying facts that satisfied the `:where` clause. This is the order in which facts entered the EDB; it is stable across runs of the same query against the same `:as-of` snapshot, and it makes `#cursor` pagination reliable — `continue #cursor` always picks up exactly where the previous `:result` left off, with no risk of duplicated or skipped rows. Aggregated queries (those whose `:find` contains any `[:count …]` / `[:sum …]` / `[:max …]` / `[:min …]` / `[:distinct …]` form) **cannot be paginated**; they return all groups in a single `:result` and `:limit` caps the group count. A `continue` on a `#cursor` returned from an aggregated query is `:error :reason :bad-args :detail {:reason :aggregated-cursor}`. v1 does not include an `:order-by` qualifier; clients that want a different sort post-process the `:rows` themselves. (Adding `:order-by` is additive and can come in v1.1.)

**Examples.**

```clojure
;; Members of the managers set.
(query :find [?x]
       :where [[member-of ?x #entity "managers"]])

;; All inconsistencies (intensional predicate; rule-derived).
(query :find [?x]
       :where [[inconsistent ?x]])

;; Members of managers who are NOT also in interns.
(query :find [?x]
       :where [[member-of ?x #entity "managers"]
               [:not [member-of ?x #entity "interns"]]])

;; Count members per set.
(query :find [?s [:count ?x]]
       :where [[member-of ?x ?s]])

;; Anything that implies an equivalent of "deprecated".
(query :find [?x]
       :where [[implies ?x ?y]
               [equivalent ?y #entity "deprecated"]])

;; Generic predicate-variable: any binary fact about #entity "alice".
(query :find [?p ?y]
       :where [[?p #entity "alice" ?y]])

;; Bitemporal: members as of an old tx.
(query :find [?x]
       :where [[member-of ?x #entity "managers"]]
       :as-of #tx "t-1024")
```

**Reuse by other verbs.**

- `watch-pattern :pattern [<clause> …]` accepts the same `:where`-style clause vector. The watch fires on assert/retract events that change the matching set.
- `retract :where [<clause> …]` retracts every fact matching the clause vector. Same grammar.

## 9. Concurrency model

- Transactor per world. Writes serialize by arrival; reads are concurrent.
- Different worlds proceed in parallel.
- No client-visible locks, no queue inspection, no cross-session proposal visibility.
- Optimistic cohesion check at assert time; on conflict, caller re-proposes with fresh context.
- Watches deliver per-session, no cross-talk.
- **Watch lifetime is session-scoped.** A `#watch` lives as long as the session that created it (per §4). There is no idle-watch TTL; an active watch with no events firing is not reaped. The only server-initiated termination is the sustained-slow-consumer disconnect documented below; the only client-initiated termination is `unwatch`. Disconnect ends the session, which tears down all its watches.
- **Watch establishment is deltas-only.** A new `watch` / `watch-pattern` subscription does *not* receive an initial snapshot of currently-matching state; events flow only for changes from the subscription point forward. Clients that need ground-truth initial state issue a synchronizing `query` against the same pattern at subscription time. This keeps the watch surface small and avoids confusing the "snapshot of matching facts" with "stream of deltas."
- **Watch backpressure: bounded buffer with reconciliation.** Each watch has a per-watch event buffer with a server-default cap of **1000 events** (configurable per server; clients may not raise it above the server's max). When a slow consumer fills the buffer, the server stops accepting new events into it but tracks the tx range of dropped events. Once the consumer drains the buffer, the server emits a single `:watch-gap` event (per §10) carrying `:missed-since`, `:missed-until`, and `:event-count`; the watch then resumes normal delivery. The consumer reconciles by issuing a `query :where <pattern> :between [<missed-since> <missed-until>]` to recover the missed deltas. The bitemporal log makes this query trivially correct; the `:between` qualifier is exactly what's needed.
- **Disconnect as failsafe.** A consumer that triggers gap events repeatedly across a sliding window is sustained-slow and the server MAY close the watch with `{:event :watch-closed :watch #watch "…" :reason :slow-consumer}`. The exact threshold is server policy and not pinned by the spec — the policy MUST be deterministic and documented by the server, but the wire contract only guarantees that a reason-`:slow-consumer` close means "you fell behind too many times." After `:watch-closed`, the `#watch` handle is `:unknown-handle` for any subsequent reference; the client re-establishes via a fresh `watch` / `watch-pattern`.

## 10. Response shape

Maps keyed by `:event`:

```clojure
{:event :welcome :version 1 :session #session "…" :world #world "…"
 :capabilities #{:lemma/<flag> … :pack-name/<flag> …}
 :limits       {:max-message-bytes N :max-fact-bytes N :max-facts-per-propose N
                :max-where-depth N :max-watch-buffer N …}
 :peer         {:uid N :gid N}                                  ; optional, Unix-socket peer-cred
 :predicates   {:core #{pred-name …} :extensions {pack-name #{pred-name …}}}
 :verbs        {:core #{verb-name …} :extensions {pack-name #{verb-name …}}}}

{:event :proposed   :proposal #proposal "…" :cohesive? true :acceptable? true
                    :expires-at #inst "…"}
{:event :asserted   :refs […] :retracted-refs […] :tx #tx "…"}
{:event :retracted  :refs […] :tx #tx "…"}
{:event :cancelled  :proposal #proposal "…"}
{:event :rejected   :reason … :violations [#violation{…}]}
{:event :error      :reason … :message "…" :detail {…}}

{:event :predicates :world #world "…"
                    :predicates {:core       {pred-name {:arity N :value-types […] :cardinality :one|:many
                                                         :unique? bool :required? bool :intensional? bool :doc "…"}}
                                 :extensions {pack-name {pred-name {…}}}}}

{:event :verbs      :world #world "…"
                    :verbs      {:core       {verb-name {:arity N :qualifiers {kw type} :returns :event-name :doc "…"}}
                                 :extensions {pack-name {verb-name {…}}}}}

{:event :result         :cursor #cursor "…" :rows [[…]] :done? false
                        :affordances [{:verb (…) :hint "…"}]}
{:event :inconsistencies :as-of #tx "…" :violations [#violation{…}]}
{:event :watch-event    :watch #watch "…" :type :added|:retracted :data …}
{:event :watch-gap      :watch #watch "…" :missed-since #tx "…" :missed-until #tx "…"
                        :event-count N}
{:event :watch-closed   :watch #watch "…" :reason :slow-consumer}

{:event :exported :file "…" :format :log :tx-range […]}
{:event :imported :tx-count N :fact-count N :new-tx-ids […]}

{:event :tx-info    :tx #tx "…" :session #session "…" :timestamp #inst "…"
                    :ops [{:op :assert  :ref #ref "…" :predicate p
                                        :subject … :object …}
                          {:op :retract :ref #ref "…"}
                          …]
                    :metadata {…}
                    :proposal #proposal "…"}                  ; :proposal optional

{:event :worlds     :worlds [{:world    #world "…"
                              :packs    [{:name "…" :version "…"} …]
                              :head-tx  #tx "…"} …]}

{:event :provenance :tx #tx "…" :session #session "…" :timestamp #inst "…"
                    :metadata {…}
                    :ref #ref "…"}                            ; :ref optional
```

- **`:capabilities` and `:limits`.** The capability set is open and namespaced: bare-keyword flags (`:lemma/<flag>`) are reserved for the protocol; pack-namespaced flags (`:pack-name/<flag>`) advertise pack-defined features. v1 reserves these protocol flags: `:lemma/v1` (always present; signals protocol version 1), `:lemma/tls` (TLS active on this connection), `:lemma/peer-cred` (Unix-socket peer-credential auth populated `#session`), `:lemma/cursor-pagination`, `:lemma/watch`, `:lemma/import`, `:lemma/export`. Pack flags are advertised whenever the pack contributes one. The `:limits` map carries server-policy resource caps: `:max-message-bytes` (single EDN message), `:max-fact-bytes` (single `#fact`), `:max-facts-per-propose` (batch size), `:max-where-depth` (`:where` clause nesting), `:max-watch-buffer` (per-watch event buffer; default 1000 per §9). Servers MUST advertise each limit they enforce; clients respect them or face `:limit-exceeded` rejection. Limit categories may grow in v1.x without breaking clients (additive).
- **`:tx-info`, `:worlds`, `:provenance` shapes.**
  - `:tx-info` is returned by `(tx-info #tx "…")`. `:ops` carries the canonical per-operation record (matching the `log.edn` `:ops` array in `SERVER.md` §1.1) so a client can reconstruct exactly what the tx applied — both explicit operations and any implicit cardinality-driven retracts. `:proposal` is present iff the tx was committed from a `propose` / `assert` flow (absent for direct `import` writes and for retracts whose `retract` invocation didn't go through propose).
  - `:worlds` is returned by `(worlds)` and lists every world the server hosts; clients with no `:capabilities` constraints see all worlds. Each entry carries the world's declared packs (per the world's `meta.edn`) and the current head tx-id so an agent can spot busy worlds at a glance. Pack bodies are not included.
  - `:provenance` is returned by `(provenance #ref "…")` or `(provenance #tx "…")`. `:ref` is present in the response iff the request was for a fact (`#ref`); absent for tx-level provenance. `:metadata` carries the proposal-time `^{…}` annotations from §3 and §5.1 (e.g. `:confidence`, `:source-tag`).

- **Affordances** are optional next-step suggestions the server embeds in query/result events. This is the primary mechanism by which the server keeps agents on-rail without dictating their voice. The `:verb` field of an affordance is **a complete, ready-to-send verb invocation** — a fully-formed s-expression the agent can paste into its next request without modification. If the server cannot construct a complete invocation (missing arguments the agent must decide on), it omits the affordance rather than emitting a template. Templates with placeholder syntax are deliberately out of scope: they introduce ambiguity (what's a placeholder vs. a literal?) and the server rarely has enough information to template usefully. The `:hint` field is a short human-readable string explaining why the affordance is suggested.

- **Extensional vs. intensional predicates.** A predicate flagged `:intensional? true` in its declaration is produced only by rule derivation; the protocol's fact-supplying paths (`propose`, `import`) reject any inline `#fact{…}` whose predicate is intensional. Without the flag (or with `:intensional? false`), the predicate is extensional — assertable on the wire and carried in the persistent fact base. The standard Datalog terminology is EDB (extensional database, the asserted facts) and IDB (intensional database, the rule-derived facts); the flag names that distinction at the predicate level. Sending an intensional predicate through `propose` or `import` returns `:error :reason :bad-args :detail {:predicate '…' :reason :intensional}`. `assert` is unaffected — it takes only `#proposal` handles, which cannot refer to intensional facts because `propose` would have rejected them at proposal-creation time.

- **`:asserted :retracted-refs`.** Auto-retracts implied by `:cardinality :one` (per §7) appear in this field; otherwise it is empty (`[]`) or omitted. A `:retracted` event is *not* additionally emitted for cardinality-driven retracts — the implicit retract is part of the same tx as the assert and rides in the `:asserted` event alone. Standalone retracts (the `retract` verb) emit `:retracted` as before.

- **No-op writes elide the tx.** A `propose`/`assert` whose committed effect is empty (cardinality-replace where `v_old = v_new`, per §7) returns `{:event :asserted :refs []}` *without* a `:tx` field — no transaction is recorded. A `retract :where […]` matching no facts likewise returns `{:event :retracted :refs []}` without `:tx`. The presence of `:tx` in any commit-event shape thus signals "an actual tx was written"; absence signals "the world did not change."

- **`:rejected` reasons.** `:rejected` is a *domain* outcome: the request was well-formed and the server understood it, but the world refused it. Reserved reasons include:
  - `:empty` — `(propose)` with no facts (§7).
  - `:cohesion` — the propose's post-state would derive new violations. `:violations` carries the `#violation{…}` records (§5.2).
  - `:unique-conflict` — a fact's value collides with an existing fact (or with another fact in the same propose batch) for a `:unique? true` predicate (§7). `:detail` carries the offending predicate, value, and either the conflicting `#ref` or the in-batch index.
  - `:cardinality-self-conflict` — the propose batch contains two facts with the same subject for a `:cardinality :one` predicate (§7). `:detail` carries the offending pair's batch indices.
  - `:foreign-proposal` — `assert` of a `#proposal` minted by a different session (§4).
  - `:stale-proposal` — `assert` of a `#proposal` whose re-checked cohesion now fails. `:violations` carries the fresh violations (§7).
  - `:orphan-referent` — `retract` would leave a fact referencing a no-longer-extant entity. (Note: cohesion is bypassed by `retract` per §7, but referential integrity is not.)

- **`:rejected` vs. `:error`.** `:rejected` is the domain outcome above. `:error` is a *protocol* outcome: the request never reached domain semantics. Reserved reasons include:
  - `:malformed` — EDN failed to parse, top-level value isn't a verb form, or a list appears anywhere other than as the top-level form (§3). The server stops parsing on the first offender; `:detail` carries the offending position.
  - `:unknown-verb` — top-level verb name not in core or any loaded pack's extensions.
  - `:bad-args` — wrong arity, missing required qualifier, or argument of wrong type. `:detail` carries the offending key/position.
  - `:no-session` — verb other than `hello` sent on an anonymous connection (§4).
  - `:unknown-handle` — a `#proposal`, `#ref`, `#tx`, `#cursor`, or `#watch` that the server doesn't recognize from the session's current world. Handles are world-scoped; a handle minted in world A is simply absent from world B, indistinguishable from one that never existed. The server does not maintain a cross-world handle registry and does not disclose which other world (if any) a handle might belong to.
  - `:missing-pack` — operation references a pack not installed on the server (e.g. `import` of a `:log` that names a pack the server doesn't have, or opening a world whose declared packs are absent). Never auto-fetched; installation is out-of-band (see `SERVER.md`).
  - `:limit-exceeded` — request would exceed a server-advertised limit (per the `:limits` map in `:welcome`). `:detail` carries the offending limit's keyword and the observed value, e.g. `{:limit :max-facts-per-propose :observed 1500 :max 1000}`.
  - `:internal` — server-side failure unrelated to the request shape; `:detail` may include a correlation id for log lookup.

  Pack verbs raise `:error :reason :pack/<symbol>` for pack-defined protocol failures; domain failures from pack verbs still use `:rejected`.

## 11. Import / export

- **Formats**: `:log` (full fidelity, round-trippable, canonical), `:facts` (flat, no history).
- `export` qualifiers: `:file`, `:format`, `:scope {:predicates […]}`, `:as-of`, `:between`, `:include [:provenance …]`.
- `import` assigns new tx-ids; originals preserved as `:original-tx` metadata. `:mode :preserve-tx-ids` legal only into an empty world (strict restore).
- Default on inconsistency during import: reject atomically. Overrides: `:on-inconsistency :propose | :skip`.
- **Import/export round-trip extensional facts only.** Intensional (rule-derived) predicates are never written to an export and never accepted from an import; on import, intensional facts are re-derived by running the loaded packs' rules over the imported EDB. This keeps exports compact, lets the IDB float to whatever the current rule set produces (so the export stays valid across pack-version upgrades that change derivation rules), and preserves the invariant that intensional predicates have no user-assertion path. An import payload containing a fact whose predicate is `:intensional?` is rejected per the §10 rule.
- **`import` transports facts only — never packs, verb bodies, or any code-shaped payload.** If a `:log` payload references a pack not already installed on the server, import fails with `:error :reason :missing-pack`. There is no install-by-import path; pack installation is strictly out-of-band (see `SERVER.md`). This invariant exists to prevent a hostile world export from achieving remote code execution.

## 12. Pack-extended verbs and predicates

Servers MAY load packs that extend the wire surface with namespaced verbs (`(audit/check-source #entity "…")`, `(security/check-principal #entity "…")`) and additional predicates. Extensions are advertised in `:welcome` under `:verbs {:extensions …}` and `:predicates {:extensions …}` (§10), and are validated identically to core verbs (signature, arity, qualifier names, argument types).

Pack-defined protocol failures use `:error :reason :pack/<symbol>` (§10); pack-defined domain failures use `:rejected` with violations. Beyond appearing in the welcome surface and the error namespace, packs do not change protocol semantics.

**Multi-pack rule interactions.** Datalog is monotonic: when multiple loaded packs each contribute rules whose bodies reference shared predicates (e.g., `core/equivalent`), all rules fire and the resulting IDB is independent of pack-load order. There is no rule-precedence mechanism, no shadowing, no per-pack rule-engine isolation; pack authors do not need to coordinate to avoid stepping on each other's rule sets. The cost of rule evaluation is, however, the *pack author's responsibility* — the engine does not sandbox pathological packs at runtime. A pack whose rules produce blow-up closures will slow every query in worlds that load it, and the operator's recourse is to remove the offending pack from the world's `meta.edn`.

Pack packaging, installation, validation, and isolation are server-implementation concerns — see `SERVER.md`.

## 13. Agent discipline

- The protocol's role in keeping LLMs on-rail is narrow: **be the path of least resistance.** Cheap queries, rich results, affordances pointing to natural next steps, diagnostic rejection messages.
- Everything else lives in the pack's skill doc (Triage Gate, trigger phrases, decision trees).
- The protocol does **not** constrain how the LLM talks to the user. No required response format, no mandated citation style.

## 14. Open questions (deferred)

Protocol-level deferrals only; server-implementation deferrals (log compaction, pack version migration, adapter packs) live in `SERVER.md`.

- **Auth / authz for remote deployments.** Session-level principals, per-world ACLs, pack capability grants. v1 assumes trusted local or VPN context. Hooks already in place that v1.x will build on: `:lemma/peer-cred` capability and `:peer` field for Unix-socket peer-credential auth (§3, §10); `:lemma/tls` capability flag for HTTP+SSE (§3); the `#session` handle as the durable principal anchor.
- **Capability grants beyond v1's reserved flags.** v1 reserves a small protocol-flag set (`:lemma/v1`, `:lemma/tls`, `:lemma/peer-cred`, `:lemma/cursor-pagination`, `:lemma/watch`, `:lemma/import`, `:lemma/export`) and lets packs advertise their own under `:pack-name/<flag>`. v1.x: per-session capability gating ("this session is granted `:lemma/import`"; "this session can write to world X but only read world Y"), tied to the auth/authz model above.
- **Resource-limit budgets per session / per pack.** v1's `:limits` map advertises server-wide caps. v1.x: per-session quotas (rate limits on `propose` per minute, total bytes per session) and per-pack rule-evaluation budgets (cap a pack's runaway closures from poisoning a world). Hook in place: `:limit-exceeded` reason (§10) is namespaced enough to carry per-session and per-pack subcategories without breaking clients.
- **Streaming import/export.** Cursor-based export, multi-message `import-begin` / `-batch` / `-end`.
- **Session resume after disconnect.** Currently: disconnect = session end. Should brief reconnects be rebindable?
- **Rebase / merge.** Reconciling divergent world copies (e.g., fork + edit + merge back).
- **Multi-world transactions.** Cross-world assert as an atomic unit. Probably never — it re-introduces the coordination we deliberately avoided — but worth naming as deliberate non-support.

---

The next useful exercise, pre-implementation: pick one or two realistic agent workflows (e.g., "an LLM seeds a fresh world from import, then proposes a refactor"; "two agents concurrently edit the same world during a live session") and walk them end-to-end against this surface. Anything that feels awkward to express in the verb grammar is a signal to revisit before any lines of code get written.
