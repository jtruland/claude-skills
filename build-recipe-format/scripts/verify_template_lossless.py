#!/usr/bin/env python3
"""Verify a template + substitution table reproduces the original text exactly.

Use after rewriting N near-identical expressions in a build recipe as one template
plus a table. Reconstructs each instance and asserts it appears verbatim in the
pre-rewrite text, so the refactor is proven lossless rather than assumed.

    verify_template_lossless.py <original.md> <spec.json>

spec.json:
{
  "template": "@{if(empty(body('«FILTER»')),'',concat('<h3>«HEADING»</h3>'))}",
  "rows": [
    {"«FILTER»": "Filter_A", "«HEADING»": "Section A"},
    {"«FILTER»": "Filter_B", "«HEADING»": "Section B"}
  ]
}

Exit 0 = every row reconstructs byte-for-byte. Exit 1 = at least one did not:
either the template is wrong, or the original abbreviated that instance instead
of writing it out. Read the original before assuming the second.
"""
import json
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    original = open(sys.argv[1], encoding="utf-8").read()
    spec = json.load(open(sys.argv[2], encoding="utf-8"))
    template, rows = spec["template"], spec["rows"]

    ok, missing = 0, []
    for i, row in enumerate(rows, 1):
        built = template
        for token, value in row.items():
            built = built.replace(token, value)
        if "«" in built:
            print(f"  ? row {i}: unsubstituted token remains — {built[:90]}")
        if built in original:
            ok += 1
            print(f"  ok  row {i}: {next(iter(row.values()))}")
        else:
            missing.append((i, row, built))
            print(f"  XX  row {i}: {next(iter(row.values()))}")

    print(f"\n{ok}/{len(rows)} reconstruct byte-for-byte")
    for i, row, built in missing:
        print(f"\nrow {i} not found verbatim in the original:\n  {built}")
    if missing:
        print("\nEach miss is either a wrong template or a spot where the original "
              "abbreviated the expression. Check the original before claiming the latter.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
