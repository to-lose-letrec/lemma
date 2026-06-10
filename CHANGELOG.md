# Changelog

All notable changes to the Lemma protocol specification will be documented in
this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Pre-1.0, the minor version tracks the SPEC; patch versions cover editorial and
amendment work that does not change the wire surface.

## [0.10.1] - 2026-06-09

Errata to the 0.10.0 batch, from a post-application coherence audit.
Clarifications of intent only — no new capability, no new vocabulary.

### Fixed

- §5.4's pack-load rejection routed through the **existing** `:missing-pack`
  error (`:detail {:reason :unsupported-value-type :pack "…" :tag …}`),
  surfaced at world-open time — the 0.10.0 text named a `:bad-pack` reason
  that §10 never reserved and gave no wire surfacing point. §10's
  `:missing-pack` bullet now covers validation failure alongside absence.
- §8.1's constants list admits **keywords** (and names `#inst` explicitly) —
  required for facts with `:keyword`-typed values (§5.4) to be queryable by
  value. The Lark grammar already admitted keyword atoms; the prose lagged.
- §9 watch-gap reconciliation: the tx-info-range replay is exact for `:all`
  watches and a **superset** for pattern watches (per-tx ops are not
  pattern-filtered; the client re-applies its pattern). The "exactly the
  delta stream" overclaim corrected.

### Changed (editorial)

- README brought to 0.10.x: status paragraph, tag-count language (ten handle
  types + the `#inst` value literal), contributing section, and the wire
  excerpt's two `query` examples rewritten to the canonical single-map form
  (the bare-kwargs form EA-1 retired; a conformant server rejects it).
- SPEC title drops "(draft)".
- §5.3's tag-mechanics analogy drops the rejected `#uuid`.
- §8.1's cursor-expiry recovery wording generalized to cover tx-info-range
  cursors.

[0.10.1]: https://github.com/to-lose-letrec/lemma/releases/tag/v0.10.1

## [0.10.0] - 2026-06-09

External-protocol-review revision batch (`LEMMA-REVISIONS.md`, R1–R11). This is
a **wire-surface change** — it supersedes 0.9.0's "no further wire-surface
changes anticipated" note. Two reserved-but-unemitted vocabulary items are
removed and two fields are added; all changes are additive or remove dead
vocabulary. R7 (`:foreign-proposal` / `:stale-proposal` adjudication) is
deferred to a later batch.

### Added

- `:tx-info-range` event and a `:between [#tx #tx]` range form for `tx-info`
  (§6, §10), giving §9 watch-gap reconciliation a delta-shaped recovery
  mechanism (R2b).
- `:as-of #tx` synchronization anchor on the `:watch-established` event (§9,
  §10), making the baseline-snapshot / delta-stream join gap-free and
  overlap-free (R3).
- `#inst` admitted to the closed tag set as a value literal (§3, §5); `#uuid`
  explicitly rejected in v1 with a required rejecting reader (R4).
- New §5.4 "Value types": enumerated `:value-types` tag vocabulary plus an
  accept-implies-storable conformance rule (R8).
- §14 v1.x backlog note for an affordance conformance surface (R11).

### Changed

- §8.1 result ordering split by row anchoring: EDB-anchored rows keep
  `(tx-id, ref-id)`; derivation-only rows order by a pinned total value order,
  with a normative cursor-freeze statement — derived-predicate queries are now
  paginable (R1).
- `:between` pinned to a single visible-at-any-point relation across
  `query`/`dump`; `export`'s asserted-within-window selection renamed to the
  distinct `:asserted-within` qualifier (§8.1, §11) (R2a).
- §7 uniqueness check no longer treats an identical live tuple as a conflict —
  re-asserting an already-true `{:cardinality :one :unique? true}` fact is the
  idempotent no-op the elision rule prescribes (R5).
- "Default world" defined: `:welcome` carries `:world` only when a default
  exists, else the key is absent and world-requiring verbs return
  `:bad-args :detail {:reason :no-current-world}` (§4, §10) (R10).

### Removed

- `:rejected :orphan-referent` — unsatisfiable under §5.3's
  reference-is-existence entity model (R6).
- `:cohesive?` / `:acceptable?` flags from the `:proposed` event (§10, README) —
  tautologically true, carried no information; aligns §10 with §7 (R9).

[0.10.0]: https://github.com/to-lose-letrec/lemma/releases/tag/v0.10.0

## [0.9.0] - 2026-06-01

First public release candidate. The specification is stable; a conformant
reference server ([Dianoia](https://github.com/to-lose-letrec/dianoia)) is
shipping in parallel. Remaining pre-1.0 work is operational hardening and the
RC review window — no further wire-surface changes are anticipated.

### Added

- Initial public SPEC.md covering the 23-verb v1 surface across six categories
  (sessions, writes, reads, watches, bulk, introspection).
- Ten tagged-literal types with defined shapes and lifecycles.
- Two transports: Unix domain socket and HTTP+SSE.
- Bitemporal query grammar with `:as-of` and `:between` qualifiers.
- Cohesion-at-commit semantics with `#violation` diagnostics on rejection.
- SERVER.md reference-implementation guide (non-normative).
- THESIS.md design rationale.
- GAPS.md resolved-design-questions log.
- Lark grammar under `grammar/` with CI verification.
- Apache 2.0 LICENSE.

[0.9.0]: https://github.com/to-lose-letrec/lemma/releases/tag/v0.9.0
