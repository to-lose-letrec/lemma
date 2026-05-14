# Lemma Wire Grammar

`lemma.lark` is an executable form of [SPEC.md](../SPEC.md) §3 — the static,
session-independent shape of the Lemma client-to-server wire surface. It is
intended for use by *constrained-decoding* tooling (llguidance, outlines,
xgrammar) so that malformed Lemma messages are impossible for an LLM client to
emit.

## What it enforces

- **EDN syntax**: atoms (symbols, keywords, strings, numbers, booleans, `nil`),
  vectors, maps, sets, and tagged literals.
- **The §3 structural invariant**: lists appear only at the top level, as verb
  invocations. Nested lists in argument position are not derivable.
- **The §5 tagged-literal closure**: exactly the ten core tags — `#fact`,
  `#proposal`, `#tx`, `#ref`, `#cursor`, `#watch`, `#session`, `#world`,
  `#entity`, `#violation` — with their declared payload shapes.

## What it does not enforce

Semantics. Cohesion, intensional-predicate rejection, cardinality, uniqueness,
type-checking against declared `:value-types`, foreign-proposal rules, handle
validity, and every other domain-outcome check live server-side (SPEC §7, §8,
§10). Grammar enforcement reduces the *malformed-message* class to zero; it
does not reduce the *rejected* class to zero, and that is by design — a
well-formed proposal that fails cohesion is the rail the protocol is built on.

## Session specialization

The static grammar accepts any symbol for the verb head and any predicate or
tag for tagged-literal payloads. At session start a client receives
`:welcome`, which carries `:verbs` and `:predicates` (per SPEC §10), and can
narrow the grammar before sampling:

- The `LEMMA_VERB` placeholder narrows to the welcome's advertised verb names
  (core ∪ pack extensions).
- The `#fact` `:predicate` slot narrows to the welcome's predicate names.
- The accepted tag set narrows to the core ten plus any pack-advertised tags.

Re-specialization happens on `(use-world …)` and on any pack-install event
that changes the advertised surface.

## Compatibility

Targets the common subset of Lark consumed by both guidance-ai/llguidance and
outlines. No Lark-specific features (templates, `%declare`, ambiguity
directives) are used. The grammar should also load via xgrammar's Lark
importer.

## Status

Spec-tracking artifact, versioned alongside [SPEC.md](../SPEC.md). No
reference parser implementation yet.

## Verification

`verify.py` is the standing regression check while the project has no CI.
It parses a corpus of accept/reject cases derived from SPEC §3, §5, §5.1,
§5.3, §6, §7, §8.1, §9, and §11 under both Earley and LALR builds. Run it
after any change to `lemma.lark` or any normative SPEC section that
touches the wire surface:

```sh
python3 grammar/verify.py
```

Exit code 0 means full pass; 1 means at least one accept-or-reject case
diverged from expectation. Requires `lark` (any 1.x).

## License

Licensed under the Apache License, Version 2.0. See ../LICENSE.

## Acknowledgments

This grammar is designed to be useful to:

- **[guidance-ai/llguidance](https://github.com/guidance-ai/llguidance)** (MIT,
  Microsoft) — the constrained-decoding sampler whose token-mask discipline
  this grammar feeds. The primary intended consumer.
- **[guoqingbao/vllm.rs](https://github.com/guoqingbao/vllm.rs)** (MIT) — the
  Rust vLLM reimplementation that integrates llguidance, and a natural
  inference runtime for a Lemma client.

Lemma has no runtime dependency on either project; the grammar is published
in a form they happen to consume cleanly.
