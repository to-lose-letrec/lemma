# Lemma — Why a New Protocol

## The question

"Wherefore a new protocol for THIS?" — when MCP exists, when RDF/SPARQL exists, when Datomic exists, when JSON-RPC over a database is straightforward to build, why introduce another wire format and ask anyone to learn it?

The short answer: because LLM-to-knowledge interaction is a distinct category, and no existing protocol satisfies the properties that category requires.

## The category

This is no longer machine-machine interaction (those protocols optimize for efficiency at the cost of human comprehensibility) and no longer human-machine interaction (those are too imprecise for cohesion-checked writes). It is **LLM-to-knowledge interaction**: an agent of unbounded language production, working against a structured knowledge base that must remain coherent across many such agents and across time.

That category has six structural properties that distinguish it from anything that came before:

### 1. Generative client, structured server

The client composes requests dynamically from natural-language goals rather than from a programmer's pre-written code. The protocol must therefore be self-describing (introspection verbs, predicate metadata, rule visibility), forgiving of novel-but-valid usage, and diagnostic when usage goes wrong. Traditional APIs assume a programmed client and let docs do the work; that assumption breaks when the client is a generative model with bounded context.

### 2. Cohesion as ground truth, not consistency as eventual property

When an agent commits a fact, that fact must reconcile with everything else *at commit time*. Eventual consistency is the wrong model for this use case — it lets the LLM "remember" things that contradict other things, then surface the contradiction too late, after downstream reasoning has already used the bad fact. Cohesion at commit is the only model where an LLM's subsequent reasoning is grounded in a consistent world-state.

### 3. Bitemporality as a first-class affordance

Agents reason about "what was true when" constantly — debugging their own decisions, reconstructing context for users, explaining outcomes after the fact. A protocol that makes time-travel queries cheap is a force multiplier; one that doesn't punishes the agent on every historical question. `:as-of` and `:between` are not power-user features; they are table stakes for the category.

### 4. Multi-agent without coordination

Multiple agent sessions read and write the same shared world. LLMs are poor at locks, race conditions, and cooperative protocols. The transactor-per-world, serialize-by-arrival model is the simplest design that delivers shared-state semantics without exposing concurrency primitives the client can misuse. No client-visible locks, no queue inspection, no cross-session proposal sharing.

### 5. On-rail design as the protocol's job

Traditional APIs say: "the docs explain how to use this; misuse is your bug." LLM-to-knowledge protocols must *assume* the client will misuse the surface sometimes and design the surface so correct usage is the path of least resistance — affordances pulling toward natural next steps, diagnostic rejections that teach, cheap queries that reward exploration. The protocol is a teacher, not a wall.

### 6. Auditability for humans

When an agent commits something it shouldn't, or queries return surprising results, a human operator has to follow the trail. EDN-on-the-wire, human-readable predicate names, rule-name violations, queryable provenance — these are not aesthetic concessions. They are the only way the system stays operable when something goes wrong.

## Why existing protocols don't fit

| Protocol | (1) | (2) | (3) | (4) | (5) | (6) |
|---|---|---|---|---|---|---|
| MCP | partial | no | no | no | partial | no |
| RDF/SPARQL | no | no | yes | no | no | yes |
| Datomic wire | no | yes | yes | partial | no | partial |
| REST + DB | no | no | no | no | no | partial |
| JSON-RPC + tool calling | partial | no | no | no | partial | no |
| **Lemma** | **yes** | **yes** | **yes** | **yes** | **yes** | **yes** |

**MCP** is for LLM-to-tool, not LLM-to-knowledge. Tools are stateless; knowledge is stateful, cohesion-checked, bitemporal, and shared. Building Lemma on top of MCP would mean reimplementing 90% of Lemma above MCP's abstraction layer, with the protocol stack's overhead dwarfing whatever MCP contributed.

**RDF/SPARQL** has the data model but the protocol is for machines, not generative agents. No multi-agent semantics, no commit-time cohesion check, no affordance design, no skill docs. Data model right; interaction model wrong.

**Datomic's wire protocol** is closed and proprietary, and even setting that aside, it does not carry agent-affordance design or cohesion-as-protocol-property. It is a database first; agent interaction is something added on the client side.

**REST over a database** misses the point entirely. Relational stores do not carry equivalence-substitution, predicate-level cardinality, intensional/extensional distinction, or bitemporal-by-default. Implementing Datalog semantics inside SQL is possible and uniformly worse than the alternative.

**JSON-RPC + tool calling** ("MCP plus a knowledge base") gets you maybe (1) and (5) at best, and you reinvent the rest.

The pattern is consistent: any attempt to assemble these properties out of existing pieces produces something worse than building the right protocol from the start.

## The thesis

LLM-to-knowledge interaction has six structural properties — generative client, cohesion-at-commit, first-class bitemporality, lock-free multi-agent, on-rail by design, human-auditable — that no existing protocol satisfies together, and any attempt to assemble them out of existing pieces produces something worse than building the right protocol from the start.

That is the answer to "wherefore a new protocol for this." The skeptic's burden is to either deny the category, deny the properties matter, or show an existing protocol meets the bar. None of those is easy.

## What the thesis depends on

Two empirical bets, named honestly:

**Adoption gravity.** A new protocol always fights inertia. Lemma's answer to "why move?" has to be that the existing options *force* clients to reimplement most of Lemma above them, badly — and that the reimplementation is worse than just using Lemma. The argument is true; it requires people to try the alternatives long enough to feel the pain.

**The affordance thesis.** Property (5) — the protocol pulling agents toward correct usage rather than just refusing incorrect usage — is the load-bearing claim and the empirically unproven one. If affordances do not work in practice, properties (2)–(4)–(6) still justify the protocol, but the agentic value is reduced. The bet should pay off; if it does not, Lemma remains useful but more narrowly.

The category itself is durable. Properties (1), (2), and (5) describe the *agentic* relationship to knowledge, which does not go away as LLMs improve. Better LLMs need more structural support for cohesion and audit, not less.

## Constraints the thesis imposes on the design

The properties are not free; each costs something in the spec, and the cost shows up as a deliberate constraint:

- (1) costs introspection-verb surface area — `predicates`, `verbs`, `rules`, `capabilities` exist because the client needs to learn the world.
- (2) costs commit-time computation — every `propose` runs the rule engine over a hypothetical post-state.
- (3) costs storage — every committed fact is preserved, indexed by tx-id, and reconstructible into any historical snapshot.
- (4) costs coordination simplicity — single transactor per world, no write-side replication.
- (5) costs design discipline — every response shape is reviewed for whether it teaches the agent something useful.
- (6) costs efficiency — EDN over the wire is more verbose than binary protocols would be.

Each is a deliberate trade. The shape of the protocol is what falls out of taking the six properties seriously rather than accepting any of their negations.
