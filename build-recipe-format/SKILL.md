---
name: build-recipe-format
description: >
  Write or restructure a step-by-step build recipe for an artifact assembled by hand in a
  GUI — a Power Automate flow, a Power Apps canvas screen, a list/table schema, a CI
  pipeline built in a web console. Use this when asked to write a build recipe, to make an
  existing one clearer or easier to follow, when a recipe is described as dense/hard to
  follow/difficult to read, or when documenting a procedure whose reader will be
  click-building one step at a time in another window. Covers the four techniques that do
  most of the work — lead with a structure tree, collapse N-way repeats into a table,
  extract every expression to its own block, name a repeated sub-expression once — plus how
  to prove a templated rewrite is lossless rather than hoping it is.
---

# Build recipes that can actually be followed

A build recipe is read **while building**, in a second window, one action at a time. That is
a different job from a design doc, and it fails in specific ways.

The reader needs, for each step: *what is this thing called, what type is it, what do I put in
it, and where does it sit.* Anything that makes them hold two places in their head at once —
prose that describes nesting, an expression buried mid-sentence, four near-identical actions
written out four times — costs them the thread.

## The four techniques

### 1. Lead with a structure tree

Before any detail, show the shape. Nesting and depth are the hardest things to recover from
prose, and the easiest to draw.

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

The right-hand column is the *why*, one clause. A reader who only reads the tree should be
able to explain the flow. Add a depth note when nesting approaches a platform limit.

### 2. Collapse N-way repeats into a table

The dominant pattern in click-built work is *the same three actions, four times, with
different values*. Written out longhand it is four near-identical paragraphs the reader has
to diff by eye to find what changes. Written as a table it is obvious:

| # | Filter array | Category value | Select | Compose | Heading |
|---|---|---|---|---|---|
| 1 | `Filter_A` | `Type-A` | `Select_ALis` | `Compose_ASec` | 🗺️ Section A |
| 2 | `Filter_B` | `Type-B` | `Select_BLis` | `Compose_BSec` | 👤 Section B |

Then state the shared part **once**: *"each Filter array is From `@{body('Filter_Rows')}`,
condition `@{item()?['Category']}` is equal to column 3."*

Say "build one and repeat it N times with different values" explicitly. That is the sentence
that tells the reader they are not reading N different things.

### 3. One expression per block, never inline

An expression inside a sentence cannot be copied cleanly and hides its own length. Give it its
own fenced block, with the sentence above it saying what it does in plain words:

> **c. The four Composes** — same template, omit the section when its filter is empty:
> ```
> @{if(empty(body('«FILTER»')),'',concat('<h3>«HEADING» (',length(body('«FILTER»')),')</h3><ul>',join(body('«SELECT»'),''),'</ul>'))}
> ```

Add a *reads as* line for anything non-obvious: *"reads as: first detected today → prefix the
badge; otherwise append — since MM/dd."*

### 4. Name a repeated sub-expression once

When the same fragment appears in several places, give it a bracketed name, write it out once,
and reference it thereafter. Make the substitution instruction explicit or someone will paste
the placeholder:

> …where **«NEW-TEST»** is pasted verbatim, both times:
> ```
> equals(convertFromUtc(coalesce(item()?['Date'],'1900-01-01T00:00:00Z'),'Eastern Standard Time','yyyy-MM-dd'), outputs('Compose_Today'))
> ```

Use a delimiter that cannot occur in the target language — `«…»` is safe in most expression
syntaxes; `{{…}}` and `${…}` often are not.

## Template + substitution table

Techniques 2–4 combine into the highest-leverage move: replace N near-identical expressions
with **one template plus a table of what varies**. Eight verbose expressions become one block
and eight short rows, and the *difference* between them becomes visible instead of buried.

Only the varying pieces go in the table. If two items differ in a fifth way you did not give a
column, the template is wrong — add the column rather than adding prose exceptions.

## Prove the rewrite is lossless

Templating is a refactor of content people will paste into a production system. Do not eyeball
it. Reconstruct every instance from the template + table and assert the result appears verbatim
in the original text — `scripts/verify_template_lossless.py` does exactly this.

Expect a small number of legitimate mismatches: places where the **original** used shorthand
("same as above but with X") and never wrote the expression out. Those are the cases where the
rewrite is strictly better — confirm each one by reading the original, and say so in the commit
message rather than quietly leaving them.

Report the count: *"11/11 reconstruct byte-for-byte; the 2 that don't were abbreviated in the
original and are now explicit."*

## Smaller rules that keep paying off

- **Warnings attach to the step they threaten.** A gotcha in a trailing section is read after
  the mistake. Put it inline, at the action it applies to.
- **Flag silent-failure branches loudly.** A condition whose No branch does nothing deserves a
  ⚠️ saying who does not get told, because nothing in the tool will ever surface it.
- **Record name drift.** When the as-built names differ from the doc (a prefix added, a suffix
  dropped), note it once near the top. Otherwise the next reader diffs names against the live
  artifact and concludes something is missing.
- **State each action's type.** "Filter array", "Select (text mode)", "Compose" — the reader is
  choosing from a menu of hundreds.
- **Keep a fixed order explicit.** If sections must appear in a set order, say **FIXED** and
  give the order; a table implies no ordering on its own.
- **Never abbreviate an expression.** "Same but with Y" forces reconstruction at exactly the
  moment the reader is context-switching into another window.

## Anti-patterns

| Smell | Why it hurts |
|---|---|
| "Four Filter arrays over X, condition …: `A` (a), `B` (b), `C` (c), `D` (d)" | Four actions crammed into one bullet; nothing is scannable at action granularity |
| Expression inline in a sentence | Cannot be copied cleanly; its length is disguised |
| Prose describing nesting ("inside the loop, within the condition…") | Makes the reader build the tree you could have drawn |
| Trailing "Gotchas" section | Read after the mistake it would have prevented |
| "same with `'Other-Value'`" | The reader reconstructs an expression mid-build |
