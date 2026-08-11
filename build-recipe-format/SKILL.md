---
name: build-recipe-format
description: >
  Write or restructure a step-by-step build recipe for an artifact assembled by hand in a
  GUI — a Power Automate flow, a Power Apps canvas screen, a list/table schema, a CI
  pipeline built in a web console. Use this when asked to write a build recipe, to make an
  existing one clearer or easier to follow, when a recipe is described as dense/hard to
  follow/difficult to read, or when documenting a procedure whose reader will be
  click-building one step at a time in another window. Covers what actually helps — lead
  with a structure tree, collapse N-way repeats into a table of literal values, give every
  expression its own complete pasteable block, state a value for every required field — and
  why fill-in-the-blank templates are the wrong trade in a document people paste from.
---

# Build recipes that can actually be followed

A build recipe is read **while building**, in a second window, one action at a time. That is a
different job from a design doc, and it fails in specific ways.

The reader needs, for each step: *what is this called, what type is it, what exactly do I put
in it, and where does it sit.* Anything that makes them hold two places in their head at once —
prose that describes nesting, an expression buried mid-sentence, a value they must assemble
themselves — costs them the thread at the worst moment.

## The two jobs, and which one wins

A recipe serves **comprehension** (what is this and why) and **transcription** (get the exact
string into the box). They pull against each other, and when they conflict **transcription
wins** — comprehension failures are noticed and asked about, transcription failures are silent
and land in production.

That single trade decides most of what follows.

## 1. Lead with a structure tree

Before any detail, show the shape. Nesting and depth are the hardest things to recover from
prose and the easiest to draw.

```
If_Due                            length(body('Filter_Gate')) > 0
├─ Yes
│   ├─ 4 × Filter array           split the rows by category
│   ├─ 4 × Select                 one <li> per row
│   ├─ 4 × Compose                one section, omitted when empty
│   ├─ Compose_Body               intro + the four sections
│   └─ Send an email
└─ No                             nothing — already sent today
```

The right-hand column is the *why*, one clause. A reader who reads only the tree should be able
to explain the artifact. Add a depth note when nesting approaches a platform limit.

## 2. Collapse N-way repeats into a table — of literal values only

The dominant pattern in click-built work is *the same few actions, N times, with different
values*. Longhand it is N near-identical paragraphs the reader must diff by eye.

A table fixes that — but **only put things in it that are typed into a box as-is**: an action
name, a column name, a literal a condition matches. State the shared part once above the table:

> Each Filter array is From `@{body('Filter_Rows')}`, condition `@{item()?['Category']}` **is
> equal to** the value below — a plain string, not an expression.

| Filter array | `Category` is equal to |
|---|---|
| `Filter_A` | `Type-A` |
| `Filter_B` | `Type-B` |

⚠️ **Never put fragments of an expression in the table.** The moment a cell is something the
reader must splice into a formula, the table has become a fill-in-the-blank form — see §4.

## 3. One expression per block, complete

Every expression gets its own fenced block, under a label naming the action it belongs to, with
the sentence above saying what it does in plain words. Never inline in a sentence: an inline
expression cannot be copied cleanly and hides its own length.

If four Composes need four different expressions, print **four complete blocks**. The repetition
is the point — each one is a unit of work the reader performs once, in isolation, and never has
to reason about.

Add a *reads as* line for anything non-obvious: *"reads as: first detected today → prefix the
badge; otherwise append — since MM/dd."*

## 4. Never make the reader substitute anything

It is tempting to write one template with `«TOKEN»` placeholders plus a table of substitutions.
It reads beautifully and it is the wrong trade.

Hand-substituting a token across N instances invites three failures, all of them quiet:

- **Wrong value** — the right shape carrying the wrong literal
- **Mismatched values within one instance** — the filter from block 3 and the select from block 2,
  which type-checks fine and produces subtly wrong output
- **Syntax damage** — a dropped quote or paren inside an expression the builder never saw whole,
  surfacing later as an error pointing at the wrong place

All three are found at runtime, in a designer whose error messages rarely name the real cause. The
reader's window for noticing is exactly when they are least able to.

**Naming a repeated fragment is fine for explanation** — *"the 🆕 test appears in all four
filters"* helps. It must never become an instruction to assemble. Explain by name; publish in
full.

## Author with a template, publish the expansion

The template idea is right — just apply it to yourself, not the reader.

1. Write the template and the substitution table **in your working notes**
2. **Generate** the N expansions from it, so they are consistent by construction
3. **Verify** each expansion appears verbatim in the source you are rewriting —
   `scripts/verify_template_lossless.py`
4. **Publish the expansions**, fully written out. The template does not ship

You get the consistency a template buys and the safety of complete text, and the reader never
does string surgery.

Expect a few legitimate verification misses: places where the **source** used shorthand ("same as
above but with X") and never wrote the expression out. Those are where the rewrite is strictly
better — confirm each against the source and say so, rather than leaving it ambiguous. Report the
count: *"13/15 reconstruct byte-for-byte; the 2 that don't were abbreviated in the original and
are now explicit."*

## State a value for every required field

Platforms mark some fields mandatory, and a form will not save until each has a value — including
on an *update* that means to change one thing. A recipe that lists only the interesting fields
strands the builder at a required box the document never mentions, where they will invent
something.

List **every** field the action needs, and for a required field being carried through unchanged,
give the expression that writes its existing value back and say that is what it is:

> **`Exception_Key`** — ⚠️ required column, so the action will not save without it. Write the row's
> own value straight back; you are not changing it:
> ```
> @{items('ForEach_StampNotified')?['Exception_Key']}
> ```

The same fact read from the other side: an action carrying fields it plainly does not change is
usually satisfying required fields, not writing carelessly. Don't "simplify" it.

## Smaller rules that keep paying off

- **Warnings attach to the step they threaten.** A gotcha in a trailing section is read after the
  mistake. Put it inline, at the action it applies to.
- **Flag silent-failure branches loudly.** A condition whose No branch does nothing deserves a ⚠️
  naming who does not get told — nothing in the tool will ever surface it.
- **Record name drift.** When as-built names differ from the doc (a prefix added, a suffix
  dropped), note it once near the top, or the next reader diffs names against the live artifact
  and concludes something is missing.
- **State each action's type.** "Filter array", "Select (text mode)", "Compose" — the reader is
  choosing from a menu of hundreds.
- **Make a fixed order explicit.** If sections must appear in a set order, say **FIXED** and give
  it; a table implies no ordering on its own.

## Anti-patterns

| Smell | Why it hurts |
|---|---|
| A template plus a table of substitutions | Turns transcription into string surgery; three silent failure modes, all found at runtime |
| "same with `'Other-Value'`" | The reader reconstructs an expression mid-build |
| "Four Filter arrays over X, condition …: `A` (a), `B` (b), `C` (c)" | Four actions in one bullet; nothing scannable at action granularity |
| Expression inline in a sentence | Cannot be copied cleanly; its length is disguised |
| Prose describing nesting | Makes the reader build the tree you could have drawn |
| Trailing "Gotchas" section | Read after the mistake it would have prevented |
| Only the interesting fields listed | Builder hits a required box the doc never mentions and invents a value |
