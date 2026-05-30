# Power Fx YAML authoring + layout self-QA (offline)

Authoring and layout knowledge distilled from Microsoft's official
[`power-platform-skills`](https://github.com/microsoft/power-platform-skills) `canvas-apps`
plugin (`references/TechnicalGuide.md`, `references/QAChecks.md`).

**Scope / caveat.** That plugin authors `.pa.yaml` for the *live Canvas Authoring service*
(`compile_canvas` over an MCP coauthoring session — connection-required, which we never use).
This file keeps only the **toolchain-independent** parts: Power Fx syntax, YAML-escaping traps,
and layout anti-patterns. They apply equally to the `.fx.yaml` we pack offline with `pac canvas
pack`. Validation here is **by reading the YAML**, not by any compiler.

> Filename collision warning: this repo and that plugin both say "`.pa.yaml`" but mean different
> things. Ours is a source-control artifact Studio ignores (convert → `.fx.yaml` → pack). Theirs
> is the format their service compiles. The *syntax* below is shared; the *toolchain* is not.

---

## YAML / Power Fx syntax traps

- **Multi-line formulas use the `|-` block scalar.** The `=` goes on the first *content* line,
  not on the `|-` line:
  ```yaml
  OnSelect: |-
    =Set(x, 1);
    Set(y, 2)
  ```
- **Inline record literals must be quoted.** `Default: ={Value:"Tab1"}` *silently fails* — YAML
  parses `Value:` as a mapping key before Power Fx sees it. Quote the whole value:
  ```yaml
  Default: '={Value:"Tab1"}'        # single quotes — no inner escaping needed
  Default: "={Value: ""Tab1""}"     # or double, with doubled inner quotes
  ```
  Bites `ModernTabList.Default`, `Selected`, hardcoded `Items`, etc.
- **Any plain string containing `: ` (colon-space) must be quoted** for the same reason:
  `HintText: ="Label: enter a value"`.
- **Escape enum/option-set names** with `'...'` when they contain spaces/specials or start with a
  digit: `'Account Status'.Active`, `'Status (Assignments)'.Active`, `DecimalPrecision.'2'`,
  `'ButtonCanvas.Appearance'.Transparent`.
- **Date/time format specifiers are lowercase**: `Text(Now(), "hh:mm:ss")`, `"dddd, mmmm d, yyyy"`
  (`mm` = month, not `MM`).
- **Strip `@version` from `Control:` values** — `Control: Text`, never `Control: Text@2.0.0`.
- **Mock external data offline** with `ClearCollect(...)` in `App.OnStart`; reusable
  constants/UDFs go in `App.Formulas`.

## Control-selection notes

- **`GroupContainer` has no `OnSelect` — it cannot be clicked.** For a clickable card use
  `ModernCard`; for any other clickable area overlay a transparent `Button`/`Rectangle`
  (`Fill: =RGBA(0,0,0,0)`, `BorderThickness: =0`).
- Don't reinvent high-level controls with primitives: `Avatar`, `Badge`, `Progress`,
  `ModernTabList`, `ModernCard` exist. (Their plugin learns these via `list_controls`/
  `describe_control` — connection-gated. Offline: rely on this list and **flag, don't invent**,
  any property you're unsure of.)
- Default to **AutoLayout** (responsive); use ManualLayout only for pixel-perfect/fixed-size
  desktop. Never mix ManualLayout inside an AutoLayout container, and don't nest scrollbars.

## Layout self-QA — 10 checks the compiler can't catch

Run these by reading the YAML and fixing inline. They tighten layout intent; none deletes
semantic content.

1. **GroupContainer min-size.** PA defaults `LayoutMinWidth=250`, `LayoutMinHeight=100` and
   silently clips siblings → set both `=0` on *every* `GroupContainer`.
2. **AutoLayout child cross-axis.** Any child of a container that sets `LayoutDirection` needs
   `AlignInContainer` → default `.Stretch` (use `.Center` for an intentionally smaller child).
3. **AutoLayout child `FillPortions`.** Always set it explicitly: `=0` = keep fixed size, `=1` =
   fill remaining space.
4. **Scroll trap.** A direct child with `FillPortions: =1` inside a
   `LayoutOverflowY: =LayoutOverflow.Scroll` container pins to the viewport and clips instead of
   scrolling → change to `=0`.
5. **Single-line labels** (`Label`/`ModernText` used as nav item, tab, header, badge, KPI,
   breadcrumb) wrap by default → add `Wrap: =false`. (Leave body/paragraph text wrapping.)
6. **No-height trap.** AutoLayout child with `FillPortions: =0` (or absent) and no explicit
   `Height` defaults to **200px** → add an explicit `Height` (sum of child heights + gaps +
   padding, or a safe static value).
7. **Text padding.** `Label`/`ModernText` default all four paddings to **5** → set
   `PaddingTop/Bottom/Left/Right: =0` (or the intended value) so the 5 can't creep in.
8. **FillPortions+Height conflict** (vertical AutoLayout): if `FillPortions > 0` *and* an explicit
   `Height`, remove the `Height` — PA computes it.
9. **FillPortions+Width conflict** (horizontal AutoLayout): same, remove the explicit `Width`.
10. **Control version suffix:** strip any `@…` from `Control:` (see syntax traps).

Useful sizing idioms: dynamic gallery height
`Height: =CountRows(Self.AllItems) * Self.TemplateHeight`; center horizontally
`X: =(Parent.Width - Self.Width) / 2`; `AutoHeight: =true` on most text labels.
