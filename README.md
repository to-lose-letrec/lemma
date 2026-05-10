# Lemma

**An EDN-native protocol for LLM-to-knowledge interaction.**

Lemma is a wire protocol for multi-agent systems that share a structured, cohesion-checked, bitemporal fact-store. It is designed for the case where the "client" is a generative language model rather than a programmed system — and where the resulting interaction needs to be efficient, human-debuggable, and structurally resistant to misuse.

## Status

**Pre-implementation. Specification stable.** The protocol is fully spec'd; the reference server has not yet been built. Every load-bearing design decision has been made and recorded; the remaining work is implementation, not specification. See [GAPS.md](./GAPS.md) for the paper trail of resolved questions.

## Why a new protocol?

The short answer is that LLM-to-knowledge interaction is a distinct category from machine-machine and human-machine interaction, with structural properties no existing protocol satisfies together:

1. **Generative client, structured server** — clients compose requests dynamically rather than from pre-written code.
2. **Cohesion as ground truth** — facts must reconcile with everything else *at commit time*, not eventually.
3. **First-class bitemporality** — agents reason about "what was true when" constantly.
4. **Multi-agent without coordination** — shared worlds without client-visible locks.
5. **On-rail design** — the protocol pulls agents toward correct usage rather than just refusing incorrect usage.
6. **Auditable by humans** — operators can follow the trail when something goes wrong.

The full argument, including comparisons to MCP, RDF/SPARQL, Datomic, and JSON-RPC, is in [THESIS.md](./THESIS.md).

## What it looks like

A session interacts with a world through a small set of verbs over EDN. Wire excerpts:

```clojure
;; A client opens a session.
client → (hello)
server → {:event :welcome :version 1
          :session #session "s-1" :world #world "default"
          :capabilities #{:lemma/v1 :lemma/tls :lemma/watch …}
          :predicates {:core #{equivalent implies member-of subset-of disjoint inconsistent}
                       :extensions {…}}
          :verbs       {:core #{hello use-world propose assert retract query …}
                        :extensions {…}}}

;; The client proposes a fact. The server runs the cohesion check.
client → (propose #fact{:predicate member-of
                        :subject #entity "alice"
                        :object  #entity "managers"})
server → {:event :proposed :proposal #proposal "p-1"
          :cohesive? true :acceptable? true
          :expires-at #inst "2026-05-09T12:34:56.789Z"}

;; The client asserts the proposal; the server commits the tx.
client → (assert #proposal "p-1")
server → {:event :asserted :refs [#ref "r-1"] :tx #tx "t-1024"}

;; The client queries the world.
client → (query :find [?x]
                :where [[member-of ?x #entity "managers"]])
server → {:event :result :rows [[#entity "alice"]] :done? true}

;; Time-travel queries are first-class.
client → (query :find [?x]
                :where [[member-of ?x #entity "managers"]]
                :as-of #tx "t-512")
server → {:event :result :rows [] :done? true}
```

A `propose` that would create a contradiction returns `:rejected` with `#violation` records explaining what fired and why; the agent learns and tries again.

## Documents

- **[SPEC.md](./SPEC.md)** — The wire-protocol contract. Verbs, response shapes, query grammar, error semantics, write semantics, concurrency model. Normative.
- **[SERVER.md](./SERVER.md)** — Reference server-implementation guide. Persistence layout, log framing, message decoding, pack mechanics. Non-normative; any server that implements `SPEC.md` correctly is conformant regardless of layout.
- **[THESIS.md](./THESIS.md)** — The argument for why Lemma exists. The six-property characterization of LLM-to-knowledge interaction; comparison to existing protocols.
- **[GAPS.md](./GAPS.md)** — Resolved-design-questions log. Useful as a paper trail; everything currently shows as resolved.

## Design principles

Some load-bearing decisions, distilled:

- **EDN over the wire**, in the `clojure.edn` dialect specifically. Tagged-literal closure (only known tags accepted; unknown tags are `:malformed`). The wire is human-readable, distinguishes lists from vectors, and is parseable safely without any code-execution path.
- **Lists are verb invocations, structurally.** A list can appear only as the top-level verb form; nested lists are rejected as malformed. This forecloses an entire class of code-execution bugs by construction, regardless of what the engine underneath might do.
- **Cohesion at commit, not eventually.** Every `propose` runs the rule engine over a hypothetical post-state; rejections come with diagnostic violations.
- **Single transactor per world.** Writes serialize by arrival; reads are concurrent via MVCC. Different worlds proceed in parallel. No client-visible locks.
- **Pure-data packs.** Domain-specific predicates, rules, and verbs are declared in EDN manifests. No host-language code path on the wire; the verb language has no syntax for filesystem, network, or cross-world operations.
- **Engine-as-implementation-detail.** The reference server uses Datalevin (which uses LMDB underneath), but the wire surface is Lemma's own; clients never see engine-native syntax. A future server backed by a different rule engine remains protocol-conformant.
- **Bitemporal by default.** Every committed transaction is preserved; `:as-of` and `:between` queries are first-class. The transaction log is canonical; indexes are derived and rebuildable.
- **Out-of-band trust.** Pack installation and world creation happen on the server filesystem, not over the wire. No client verb can install code or create worlds. Imports carry facts only; never code-shaped payloads.

## Core pack

Every world includes a `core` pack defining the relations any domain is likely to need: `equivalent`, `implies`, `member-of`, `subset-of`, `disjoint`, and the intensional `inconsistent` flag. The pack is pure first-order predicate logic with elementary set theory — standard relational vocabulary intentionally chosen to be domain-neutral and minimal.

Domain-specific reasoning lives in additional packs the operator installs.

## What's in v1

23 verbs across six categories: `hello` and `use-world` for sessions; `propose`, `assert`, `retract`, `cancel` for writes; `query`, `continue`, `inconsistencies` for reads; `watch`, `watch-pattern`, `unwatch` for subscriptions; `export`, `import` for bulk operations; nine introspection verbs (`capabilities`, `predicates`, `verbs`, `rules`, `stats`, `worlds`, `provenance`, `tx-info`, `dump`).

Ten tagged-literal types: `#fact`, `#proposal`, `#tx`, `#ref`, `#cursor`, `#watch`, `#session`, `#world`, `#entity`, `#violation`. Each has a defined shape and lifecycle.

Two transports: Unix domain socket (local; identity-via-`SO_PEERCRED` optional) and HTTP+SSE (remote; TLS strongly preferred for any non-localhost deployment).

## What's deferred to v1.x and beyond

- Auth/authz for remote deployments (per-session principals, per-world ACLs, capability grants).
- Streaming import/export.
- Session resume after disconnect.
- Cross-world reads (a session sees one world at a time in v1; a hypothesis-world that reads from a base world is a recognized gap).
- Rebase/merge of divergent worlds.
- Native-code "adapter" packs (logic packs only in v1).
- Pack version migration.

## Reference implementation

Not yet written. The intended substrate is Clojure on top of Datalevin (LMDB-backed Datalog). The wire protocol is engine-agnostic; alternative implementations are expected to be possible.

## License

Apache License 2.0. See [LICENSE](./LICENSE).

## Contributing

The specification is currently stable but pre-implementation. Design discussion is welcome via issues; substantive feedback on the resolved-design-questions log in [GAPS.md](./GAPS.md) is particularly useful. The reference implementation has not yet started.
