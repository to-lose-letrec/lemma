#!/usr/bin/env python3
"""Verify lemma.lark against a corpus derived from SPEC.md.

This script is the standing regression check for the wire grammar while
the project has no CI: run it whenever lemma.lark, SPEC.md §3/§5/§8.1,
or the tagged-literal set changes. Both Earley and LALR parsers are
exercised because constrained-decoder consumers (llguidance, outlines)
rely on the grammar being in the unambiguous LR-suitable subset.

Usage:
    python3 grammar/verify.py

Requires: lark (any 1.x). Exit code 0 on full pass, 1 otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import lark

GRAMMAR_PATH = Path(__file__).resolve().parent / "lemma.lark"
GRAMMAR = GRAMMAR_PATH.read_text()

# (label, input)
ACCEPT_CASES: list[tuple[str, str]] = [
    # --- SPEC §3 / §6 verbs ---
    ("hello — anonymous handshake", "(hello)"),
    ("use-world with world handle", '(use-world #world "default")'),
    ("worlds introspection", "(worlds)"),
    ("capabilities introspection", "(capabilities)"),
    ("predicates introspection with world qualifier",
     '(predicates :world #world "default")'),

    # --- SPEC §5.1 #fact shapes ---
    ("propose with binary fact",
     '(propose #fact{:predicate member-of '
     ':subject #entity "alice" :object #entity "managers"})'),
    ("propose with unary fact (no :object)",
     '(propose #fact{:predicate inconsistent :subject #entity "alice"})'),
    ("propose with n-ary fact via :args",
     '(propose #fact{:predicate my-pack/triple '
     ':args [#entity "a" #entity "b" 42]})'),
    ("propose batch of multiple facts",
     '(propose #fact{:predicate member-of :subject #entity "a" :object #entity "g"} '
     '#fact{:predicate member-of :subject #entity "b" :object #entity "g"})'),
    ("namespaced predicate symbol",
     '(propose #fact{:predicate core/equivalent '
     ':subject #entity "x" :object #entity "y"})'),
    ("fact with confidence metadata",
     '(propose ^{:confidence 0.9} #fact{:predicate member-of '
     ':subject #entity "alice" :object #entity "managers"})'),

    # --- SPEC §7 assert / retract / cancel ---
    ("assert by proposal handle", '(assert #proposal "p-42")'),
    ("retract by ref", '(retract #ref "r-1")'),
    ("retract by tx", '(retract #tx "t-1024")'),
    ("retract :where clause",
     '(retract :where [[member-of ?x #entity "managers"]])'),
    ("cancel by proposal handle", '(cancel #proposal "p-42")'),

    # --- SPEC §8.1 query grammar ---
    ("query — managers members",
     '(query :find [?x] '
     ':where [[member-of ?x #entity "managers"]])'),
    ("query — inconsistencies (unary predicate)",
     '(query :find [?x] :where [[inconsistent ?x]])'),
    ("query with :not operator",
     '(query :find [?x] '
     ':where [[member-of ?x #entity "managers"] '
     '[:not [member-of ?x #entity "interns"]]])'),
    ("query with :count aggregation",
     '(query :find [?s [:count ?x]] '
     ':where [[member-of ?x ?s]])'),
    ("query — predicate-variable pattern",
     '(query :find [?p ?y] '
     ':where [[?p #entity "alice" ?y]])'),
    ("query — bitemporal :as-of",
     '(query :find [?x] '
     ':where [[member-of ?x #entity "managers"]] '
     ':as-of #tx "t-1024")'),
    ("query — bitemporal :between",
     '(query :find [?x] '
     ':where [[member-of ?x #entity "managers"]] '
     ':between [#tx "t-100" #tx "t-200"])'),
    ("query — chained patterns (transitive)",
     '(query :find [?x] '
     ':where [[implies ?x ?y] '
     '[equivalent ?y #entity "deprecated"]])'),
    ("query — comparison operator",
     '(query :find [?x] '
     ':where [[has-age ?x ?a] [:> ?a 18]])'),
    ("query — :or operator with two branches",
     '(query :find [?x] '
     ':where [[:or [member-of ?x #entity "managers"] '
     '[member-of ?x #entity "leads"]]])'),
    ("query — empty :where with constant :find",
     '(query :find [42] :where [])'),
    ("query with :limit",
     '(query :find [?x] :where [[member-of ?x ?s]] :limit 10)'),
    ("continue with cursor handle",
     '(continue #cursor "c-1")'),

    # --- SPEC §9 subscribe ---
    ("watch :inconsistencies", '(watch :inconsistencies)'),
    ("watch-pattern", '(watch-pattern :pattern '
     '[[member-of ?x #entity "managers"]])'),
    ("unwatch", '(unwatch #watch "w-1")'),

    # --- SPEC §11 import / export ---
    ("export with file qualifier",
     '(export :file "/tmp/world.edn" :format :log)'),
    ("import with file qualifier",
     '(import :file "/tmp/world.edn" :format :log)'),

    # --- SPEC §8 introspection (handle args) ---
    ("provenance by ref", '(provenance #ref "r-7")'),
    ("provenance by tx",  '(provenance #tx "t-7")'),
    ("tx-info", '(tx-info #tx "t-7")'),

    # --- SPEC §3 / §5.3 entity and atom variety ---
    ("entity with namespace in name",
     '(query :find [?x] :where [[is-a ?x #entity "user/alice"]])'),
    ("entity with non-ASCII",
     '(query :find [?x] :where [[is-a ?x #entity "Ålice"]])'),
    ("strings with escapes",
     '(propose #fact{:predicate label :subject #entity "alice" '
     ':object "she said \\"hi\\""})'),

    # --- EDN niceties ---
    ("comma as whitespace",
     '(query :find [?x], :where [[member-of ?x #entity "managers"]])'),
    ("line comment ignored",
     '(query :find [?x] ; just a comment\n'
     ':where [[member-of ?x #entity "managers"]])'),
    ("nested map in metadata",
     '(propose ^{:source-tag :ingest :confidence 0.7} '
     '#fact{:predicate member-of '
     ':subject #entity "alice" :object #entity "managers"})'),
    ("set literal in argument position",
     '(propose #fact{:predicate tags-with :subject #entity "alice" '
     ':object #{:admin :ops}})'),
    ("map literal in argument position",
     '(propose #fact{:predicate profile :subject #entity "alice" '
     ':object {:role "lead" :years 5}})'),

    # --- characters and numerics ---
    ("character literals",
     '(query :find [?x] :where [[picked ?x \\newline]])'),
    ("negative integer in arg",
     '(query :find [?x] :where [[scored ?x -3]])'),
    ("floating-point number",
     '(query :find [?x] :where [[scored ?x 3.14e2]])'),

    # --- session-relevant ---
    ("hello returns no args; bare verb form",
     '(hello)'),
    ("violation appears as round-trippable value",
     '(provenance #ref "r-1")'),
]

REJECT_CASES: list[tuple[str, str]] = [
    # --- SPEC §3 hard rule: lists only at top level ---
    ("nested list in vector",
     '(propose [(member-of ?x ?y)])'),
    ("nested list in map value",
     '(propose {:x (foo)})'),
    ("nested list in set",
     '(propose #{(foo)})'),
    ("nested list in #fact :args vector",
     '(propose #fact{:predicate p :args [(bad)]})'),
    ("verb-form inside metadata map",
     '(propose ^{:x (bad)} #fact{:predicate p :subject #entity "a"})'),

    # --- SPEC §3: top-level must be a list ---
    ("top-level bare map", '{:foo :bar}'),
    ("top-level bare vector", '[member-of ?x #entity "a"]'),
    ("top-level bare atom", '42'),
    ("top-level bare entity tag", '#entity "alice"'),
    ("top-level keyword", ':hello'),

    # --- SPEC §5.3 empty entity name ---
    ("empty entity name", '(propose #fact{:predicate member-of '
     ':subject #entity "" :object #entity "managers"})'),

    # --- malformed EDN ---
    ("unterminated string",
     '(propose #fact{:predicate p :subject #entity "alice})'),
    ("mismatched bracket",
     '(propose #fact{:predicate p :subject #entity "a"]'),
    ("verb form not closed", '(hello'),
    ("verb-form must have a head", '( )'),
    ("integer-prefixed symbol head", '(123foo)'),
    ("variable in head position", '(?verb)'),
]


def run_for(parser_kind: str) -> tuple[int, int, list[str]]:
    """Build the grammar with the given parser, run all cases.

    Returns (accept_pass_count, reject_pass_count, failure_messages).
    """
    parser = lark.Lark(GRAMMAR, parser=parser_kind, start="start")
    accept_pass = 0
    reject_pass = 0
    failures: list[str] = []

    for label, src in ACCEPT_CASES:
        try:
            parser.parse(src)
            accept_pass += 1
        except lark.LarkError as e:
            failures.append(
                f"  [{parser_kind}] ACCEPT FAILED  {label!r}\n"
                f"    input: {src!r}\n"
                f"    error: {e.__class__.__name__}: "
                f"{str(e).splitlines()[0]}"
            )

    for label, src in REJECT_CASES:
        try:
            parser.parse(src)
            failures.append(
                f"  [{parser_kind}] REJECT FAILED  {label!r}\n"
                f"    input: {src!r}\n"
                f"    expected parse error, parser accepted"
            )
        except lark.LarkError:
            reject_pass += 1

    return accept_pass, reject_pass, failures


def main() -> int:
    print(f"Grammar: {GRAMMAR_PATH}")
    print(f"Cases:   {len(ACCEPT_CASES)} accept, {len(REJECT_CASES)} reject")
    total_failures: list[str] = []
    for parser_kind in ("earley", "lalr"):
        try:
            ap, rp, failures = run_for(parser_kind)
        except lark.LarkError as e:
            print(f"\n[{parser_kind}] grammar build FAILED: {e}")
            total_failures.append(f"  [{parser_kind}] build: {e}")
            continue
        print(
            f"\n[{parser_kind}] accept: {ap}/{len(ACCEPT_CASES)}  "
            f"reject: {rp}/{len(REJECT_CASES)}  "
            f"failures: {len(failures)}"
        )
        for f in failures:
            print(f)
        total_failures.extend(failures)

    print()
    if total_failures:
        print(f"VERIFICATION FAILED — {len(total_failures)} issue(s)")
        return 1
    print("VERIFICATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
