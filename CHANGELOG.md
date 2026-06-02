# Changelog

All notable changes to the Lemma protocol specification will be documented in
this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Pre-1.0, the minor version tracks the SPEC; patch versions cover editorial and
amendment work that does not change the wire surface.

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
