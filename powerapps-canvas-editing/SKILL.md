---
name: powerapps-canvas-editing
description: >
  Edit Microsoft Power Apps canvas apps as source (.fx.yaml / .pa.yaml) and ship them
  as importable solution .zip files, entirely offline with the pac CLI — no tenant
  connection. Use this when asked to fix or add screens/controls/Power Fx in a Power
  Platform canvas app, repackage a solution, or debug why a re-imported app "didn't
  change" or shows blank/empty screens in Studio, or why a SharePoint choice column keeps
  reverting to its default after a Patch/save, or why a Power Automate flow errors "The workflow
  parameter ... is not found" when referencing an environment variable. Covers the non-obvious
  traps: three-stamp version bumping, gallery Layout, searchable ComboBox SearchItems, %RESERVED%
  enum tokens, the ConnectionReferences import gate, required columns blocking an Update item, SharePoint choice-column default
  revert-on-Patch, and environment-variable references in flows.
---

# Editing Power Apps Canvas Solutions (offline, pac CLI)

This skill is for editing a Power Apps **canvas** app by hand-editing its source YAML and
re-packing it into an importable **solution `.zip`** — without ever touching the live
tenant. The maker (a person) imports the resulting `.zip` in the Power Platform maker
portal. You produce the artifact; you do not deploy it.

It encodes a set of traps that each cost real debugging time. Read "Critical traps" before
shipping anything — most of them fail **silently** (the import succeeds, the app just
doesn't change or renders blank).

## What you need

- **`pac` CLI** (Power Platform CLI). Verify with `pac help`. Version pinned in our
  environment is **1.34.4**. No login is required for `pac canvas pack` / `unpack` —
  they are pure local file operations.

  ⚠️ **Why 1.34.4, and why it matters to this skill.** The pin used to be recorded
  as "later Linux builds shipped a broken nupkg". That is **false** — measured
  against real containers 2026-08-04. pac 1.45+ targets .NET 9 and 2.0+ targets
  .NET 10; an image with only the .NET 8 SDK reports the missing framework asset as
  `Settings file 'DotnetToolSettings.xml' was not found in the package`, which names
  the packaging instead of the framework floor. Given a newer SDK, 2.10.1 installs
  and runs fine.

  The **real** reason to hold is this skill itself. Newer pac deprecates the
  `Experimental` source layout in favour of `SourceCode`, which makes **`*.pa.yaml`
  the primary source** — the exact inverse of the rule the section below is built
  on. Upgrading therefore invalidates every trap documented here until each is
  retested against the new packer, including the `#`/`PA3003` bug in §7 (which an
  upgrade plausibly fixes). Treat a pac upgrade as a scoped migration of this
  skill, not a version bump.
- **`python3` + `pyyaml`** if you use the bundled `pa_to_fx.py` converter.
- **`zip`** for repackaging (or use the bundled `bump_and_repack.py`).

## The two source formats — know which one you're editing

| Format | File | What it is | Who reads it |
|---|---|---|---|
| **Modern** | `*.fx.yaml` | The format `pac canvas pack` consumes directly | `pac canvas pack` |
| **Old / source-control** | `*.pa.yaml` | Human-friendlier; **NOT** consumed by pack as-is | conversion step only |

`*.pa.yaml` files that live *inside* an `.msapp` (under `Other/Src/`) are **source-control
artifacts only** — Studio ignores them. If a screen exists only as `.pa.yaml` and never gets
converted+packed, **Studio shows a blank app with no screens.** Studio actually renders from
`Controls\*.json` inside the msapp, which `pac canvas pack` generates from `Src/*.fx.yaml`.

**Decide before editing:** if a screen has a `Src/<Screen>.fx.yaml`, edit that directly. If it
only has `Other/Src/<Screen>.pa.yaml`, edit the `.pa.yaml` then run the converter
(`scripts/pa_to_fx.py`) to (re)generate the `.fx.yaml`. Don't mix — pick the one that drives
the pack.

## The pipeline

```
edit Src/*.fx.yaml            (or edit Other/Src/*.pa.yaml → pa_to_fx.py → Src/*.fx.yaml)
   → pac canvas pack          (writes a fresh .msapp; Controls\*.json = what Studio shows)
   → swap .msapp into the solution wrapper (CanvasApps/)
   → bump ALL THREE version stamps  (see Critical trap #1)
   → re-zip preserving structure (no parent folder)
   → maker imports the .zip via Solutions → Import
```

A canvas app distributed as a **solution** is a `.zip` with this shape (flat at the root —
**no wrapping parent folder**):

```
[Content_Types].xml
solution.xml
customizations.xml
CanvasApps/<AppName>_DocumentUri.msapp   ← the packed app
Workflows/<flow>.json                    ← present only if the solution has flows
```

## Workflow

1. **Unpack to inspect (optional).** `pac canvas unpack --msapp app.msapp --sources ./_unpacked`
   gives you `Src/*.fx.yaml` + `Connections/`, `DataSources/`, `pkgs/`, etc. ⚠️ unpack is
   **lossy** — see trap #3 (it silently strips `IsSearchable`/`SearchItems`). Prefer editing a
   git-tracked source tree over round-tripping through unpack.
2. **Edit the `.fx.yaml`** (or `.pa.yaml` + convert). Keep control declarations as
   `Name As <type>:` with `Properties` as `Key: =Formula` lines. Each control needs a `ZIndex`.
3. **Pack:** `pac canvas pack --msapp out.msapp --sources ./_unpacked`. Exit 0 with only a
   checksum-mismatch warning is normal. Any `PA****` error is a real Power Fx / structure
   problem — fix it before proceeding.
4. **Repackage the solution zip** and **bump all three stamps** —
   use `scripts/bump_and_repack.py` (does both) or do it by hand per trap #1.
5. **Hand off.** Tell the maker the exact filename and that it imports via
   **Solutions → Import** (unmanaged). You never import it yourself.

## Critical traps (each fails silently — read before shipping)

### 1. A re-import "does nothing" unless you bump THREE stamps
Power Platform dedups the canvas app by version. Bumping the solution `<Version>` alone makes
the **solution** version tick up while Studio **silently keeps the old app**. You must bump
**all three**, every build:

1. `solution.xml` → `<Version>` (e.g. `0.0.0.18`)
2. `customizations.xml` → `<AppVersion>` → a **new** ISO timestamp `YYYY-MM-DDThh:mm:ssZ`
3. `customizations.xml` → `sienaVersion` inside `<Tags>` → `YYYYMMDDThhmmssZ-<clientver>`
   (keep the existing `-<clientver>` suffix; only change the timestamp)

The `.msapp` bytes and its internal `Header.json` DocVersion are **not** the import gate.
`bump_and_repack.py` handles all three.

### 2. Galleries must set `Layout: =Layout.Vertical`
`pac canvas pack` defaults an absent gallery `Layout` to `Layout.Horizontal` (+ `WrapCount: 1`),
even for a `BrowseLayout_Vertical_*` variant. A horizontal gallery sizes each item
`TemplateSize`-px **wide** / full-height — the list renders as a tall narrow strip and any
template control positioned past `TemplateSize` (e.g. a label at `X:103`) is **clipped**. It
looks like an empty-data or binding bug but is purely the wrong layout. **Always set
`Layout: =Layout.Vertical` explicitly** on every gallery. (`pa_to_fx.py` injects it
automatically.) Verify: each gallery rule in `Controls\*.json` reads `Layout=Layout.Vertical`.

### 3. A searchable classic ComboBox needs a `SearchItems` rule — and unpack strips it
A classic `ComboBox@2.4.0` with `IsSearchable: =true` populates its dropdown from
**`SearchItems`**, NOT `Items`. With `SearchItems` absent, the dropdown shows **no options**.
Worse: **`pac canvas unpack` silently drops both `IsSearchable` AND `SearchItems`** from the
regenerated YAML — so a working control and a broken one look identical in source, and any
unpack→pack round-trip silently re-breaks it. `pac pack` *does* honor both when present.

Author all of these on every searchable combo:
```yaml
IsSearchable: =true
SearchFields: =["Col"]
DisplayFields: =["Col"]
SearchItems: =Search(Sort(<Source>, <Col>), <SelfName>.SearchText, <Col>)
```
For a custom-query picker (e.g. an Office365Users people picker), set `SearchItems` to the
**same expression as `Items`**. After **any** `pac unpack`, re-add these to every searchable combo.

**Two ComboBox template defaults that error/mislead in a real app — set them explicitly:**
- `DefaultSelectedItems` template default is **`First(ComboBoxSample)`**, referencing a sample data
  source that doesn't exist in your app, so an unset combo shows a red error in Studio. Set it
  explicitly to **`=Blank()`** for "no default selection" (it's an Array/table-typed property —
  `""` would itself raise a type error). Use `=LookUp(<Source>, <key> = <var>.<key>)` to pre-select
  on edit.
- `InputTextPlaceholder` template default is a localized "find items" hint. For a **filter** combo,
  set it to the category it filters (e.g. `="Departments"`) so the empty control reads as a labeled
  filter instead of generic placeholder text. Apply this convention to every filter dropdown.

### 4. Never write `%Enum.RESERVED%` tokens in an instance formula
`%DisplayMode.RESERVED%.Edit`, `%DateTimeZone.RESERVED%.Local`,
`%DateTimeFormat.RESERVED%.ShortDate`, `%StartOfWeek.RESERVED%.Sunday` etc. are **control-
template default placeholders** — valid only inside `pkgs/*.xml` and `Src/Themes.json`. In a
control instance's property they are **not** valid Power Fx. `pac pack` passes them through
unvalidated, then Studio raises `Expected operator…` and **refuses to Publish**. Use the plain
enum: `DisplayMode.Edit`, `DateTimeZone.Local`, etc.
Guard before packing:
```
grep -rE "%[A-Za-z]+\.RESERVED%" _unpacked/Src   # must be empty
```
(Hits in `pkgs/` and `Themes.json` are expected — leave those alone.)

### 5. `<ConnectionReferences>` is the import-time connection-binding gate
On import, Power Platform binds connections **only** for the data sources listed in the
solution `customizations.xml` `<ConnectionReferences>` JSON. Studio's export writes only the
data sources that existed at the app's *original* creation — anything added later (and service
connectors like Office 365 Users) is **omitted**, so it imports as "Not connected" even though
the msapp's `Connections.json` maps it correctly. Re-adding it in Studio does not survive the
next export.

Fix: regenerate `<ConnectionReferences>` from the app's own `Connections/Connections.json` —
one entry per connection (`id`/`displayName`/`iconUri`), the full `dataSources[]` array, and
`dataSets:{<siteUrl>:{dataSources:{<name>:{tableName}}}}` for SharePoint (`dataSets:{}` for
service connectors). The complete msapp `DataSources.json` is necessary but **not** sufficient —
the solution wrapper is the gate.

### 6. The datepicker can't be re-nulled, and defaults to Today()
A classic `datepicker_2.6.0` ships `DefaultDate="Today()"`, so an "optional" end-date control
is **never blank** and always writes a value. Worse, once a user picks a date the classic
control offers **no way to clear it back to null**. Standard workaround for an optional date:
- Drive `DefaultDate` off a context flag: `=If(locCleared, Blank(), If(IsBlank(varEditing), Blank(), varEditing.SomeDate))`
- Add a small clear icon: `OnSelect: =UpdateContext({ locCleared: true }); Reset(dpControl)`
- Read it as `dpControl.SelectedDate` (blank = unset).
- **Also set `InputTextPlaceholder: =""`.** The template default is
  `If(IsBlank(Self.SelectedDate), Text(Date(2001,12,31), Self.Format, Self.Language))`, which
  renders a misleading **`12/31/2001`** in the box when no date is selected — making an empty
  optional date look populated. `""` makes the empty box actually look empty.

### 7. `#` in formulas breaks `pac` 1.34.4
`pac` 1.34.4 throws `PA3003` on **any** `#` in a formula — even inside a string literal
(`"#Microsoft.Azure…"`, `"i:0#.f|membership|"`). Replace `"#foo"` with `Char(35) & "foo"`.
(The `pa_to_fx.py` converter also rewrites leading-`#` YAML comment lines to Power Fx `//`.)

### 8. A blank/new app has NO control templates — `pac pack` fails with `PA3001`
A canvas app created **blank** (`AppCreationSource: AppFromScratch`) and exported before any
real controls were added registers only `screen`/`Host`/`groupContainer` in
`ControlTemplates.json`, with no control `*.xml` under `pkgs/`. Author screens that use
`gallery`/`label`/`button`/`combobox`/… and `pac canvas pack` dies with
`PA3001 Internal error. Object reference not set…` in `GalleryTemplateTransform.BeforeWrite`
(gallery trips first; every unregistered control is affected). **Fix:** port the templates
from a sibling app in the **same tenant + same source-format version** — merge the missing
keys from its `ControlTemplates.json` and copy its `pkgs/*.xml` into the new app's `_unpacked/`.
Guard before packing: `ControlTemplates.json` keys must include every control type you use.

**Companion trap (same from-blank context): stale `Entropy/` → `ErrOpeningDocument`.** Hand-editing
source (deleting the placeholder `Screen1`, adding screens) does **not** refresh `Entropy/Entropy.json`
+ `Entropy/checksum.json` — they stay keyed to the old controls. The msapp **packs and imports fine
but won't open for edit in Studio** (`ErrOpeningDocument_UnknownError`). **Fix:** clean round-trip
before shipping — `pac canvas pack` → `pac canvas unpack` (regenerates Entropy to match real
controls) → **re-add `IsSearchable`+`SearchItems`** (unpack strips them, trap #3) → `pac canvas pack`.
Guard: `grep -o Screen1 Entropy/Entropy.json` empty; your real screen names present.

### 9. Multi-app solution — bump only the changed app's stamps
When a solution holds two+ `<CanvasApp>` blocks, import dedups each app independently by its
`AppVersion`+`sienaVersion`. To update one app and leave the other (e.g. a live, verified app)
untouched: bump the solution `<Version>` + **only the target app's** `AppVersion`/`sienaVersion`,
and keep the other app's msapp **byte-identical** (verify with md5). Isolate the target
`<CanvasApp>` block with a **non-spanning** regex `<CanvasApp>(?:(?!</CanvasApp>).)*?</CanvasApp>`
— a lazy `<CanvasApp>.*?Name.*?</CanvasApp>` silently spans into the next block and edits the
wrong app.

### 10. Layout: design for the device + anchor to `App.Width`/`App.Height`
Pick the canvas size for the **target device** up front (`CanvasManifest.json`
`DocumentLayoutWidth/Height`; desktop apps → `1920×1080`). Changing it later means rebasing
every right-anchored control, so:
- **Right-edge elements use `App.Width`** (`X: =App.Width - <offset>`, full-height panels
  `Height: =App.Height`), never hard pixels tied to the old right edge — those float to the
  middle on any other canvas size. Left-anchored content and full-screen forms stay put.
- **A control's `Width` must fit its longest text** or it wraps/clips: a `toggleSwitch` wraps
  `TrueText`/`FalseText` over its pill when too narrow (give ~240px + explicit `Height`); a
  `dropdown`/`combobox` clips its selected item below the longest option width and must sit
  clear of its own field label.
- **Guard with a static geometry audit** (resolve each top-level control's
  `X/Y/Width/Height`, flag `x+w>canvasW`, `y+h>canvasH`, foreground overlaps) before import —
  the only pre-render check. It can't see `Visible`-gated overlaps, gallery-internal relative
  layout, or in-control text wrapping; those still need a Studio/Preview eyeball.

### 11. A SharePoint choice column's configured default silently reverts unwritten Patches
A SharePoint list **Choice** column that has a **configured default value** re-applies that
default on **every** `Patch` that doesn't explicitly write the column — including an update to a
record that already holds a *different* choice. So an item set to `"B"` snaps back to the default
`"A"` the next time you `Patch` it for any **other** field, with no error. It reads like a binding
or state bug but is the list column's default doing exactly what it's configured to do.

**Before calling any partial write a trap-#11 defect, check whether the column actually has a
default.** The trap needs a *configured* default; a Choice column without one is left untouched by
an omitted write, and a partial `Patch`/`Update item` against it is correct as authored. A flow or
formula alone cannot tell you which — the **list schema is the deciding evidence**, and a mature
project usually records it (look for a schema reference doc before opening SharePoint). Well-designed
lists often carry **no** Choice defaults precisely so partial updates stay safe — reading that as an
oversight and "fixing" it is a real and easy mistake, and it manufactures work that changes nothing.

Two rules, in order of preference:

1. **Prefer setting the default in the app/flow, not on the list column.** Author the default in
   your `Patch`/`Defaults()`/form `DefaultMode`, or in the Power Automate flow, and leave the
   SharePoint column with **no configured default**. A column default is not a free "initial
   value" — it is an "always-on unless overridden on every write" value, so only configure one
   when that revert-on-every-write behavior is **specifically** what the column is meant to do.
2. **If the column must keep a configured default,** every `Patch` to that item must **explicitly
   set the choice** — to its *existing* value when unchanged, not only on the writes that change
   it. Read-modify-write the choice (e.g. include `'Status': {Value: gblExisting.Status.Value}`)
   on **every** write path; omit it and the unwritten column reverts to the default.

### 12. An environment variable in a Power Automate flow must be inserted via the picker — its parameter name is `Display Name (schema_name)`

When a solution flow needs a **solution environment variable's** value (e.g. an API key in an HTTP
action header), insert it by **selecting it from _Add dynamic content → Environment variables →
\<Display Name\>_** — never by hand-typing a `parameters(...)` expression. Selecting it does two
things a typed expression does not: it **registers the variable as a workflow parameter** in the
flow's `definition.parameters` (which otherwise holds only `$authentication` + `$connections`), and
it writes the correct reference token for you.

The token you cannot guess: the picker registers the parameter under the **combined
`\<Display Name\> (\<schema_name\>)`** label — space and parentheses included. So an env var with
display name `My_API_Key` and schema name `prefix_My_API_Key` is referenced as
**`@{parameters('My_API_Key (prefix_My_API_Key)')}`** — *not* `parameters('My_API_Key')` and *not*
`parameters('prefix_My_API_Key')`. Both bare forms fail at **run time** (the offline pack/import is
clean — this only shows when the flow runs):

> Unable to process template language expressions … **The workflow parameter '\<name\>' is not found.**

The error is identical whether you typed the display name or the prefixed schema name — the real
cause is the **missing parameter declaration** plus the non-obvious combined name.

**Fix:** delete the typed expression and re-insert the env var from the dynamic-content picker; it
overwrites the bad token with the correct combined-label one. **Fallback** if the env var doesn't
surface in dynamic content for that field: add an **Initialize variable** (String), set its *Value*
by picking the env var from dynamic content (which registers it), then reference `@{variables('…')}`
everywhere you need the value.

### 13. A required column blocks the action until you give it a value — write the existing one back

A SharePoint column marked **Required** is mandatory in the connector's **Create item** *and*
**Update item** forms. An `Update item` that means to change one field still cannot be saved until
every required column has a value, so a "touch one column" write is rarely as small as it looks.

The value for a column you are not changing is **the row's own current value, read back from the
loop item or lookup you already have**:

```
Exception_Key   @{items('ForEach_StampNotified')?['Exception_Key']}
Last_Notified   @{utcNow()}
```

Two consequences worth knowing:

- **Don't mistake it for sloppiness.** An `Update item` carrying fields it plainly doesn't change is
  usually satisfying required columns, not writing carelessly. Read it as the minimum the connector
  permits before "simplifying" it.
- **A recipe must state a value for every required field.** Otherwise the builder reaches a
  mandatory box the document never mentions, and invents something — see the `build-recipe-format`
  skill, which makes this an authoring rule.

⚠️ Distinct from trap #11, and they pull in opposite directions: #11 is about columns you may omit
but must not (a *configured default* silently re-applies), #13 is about columns you **cannot** omit
at all. Neither implies the other — a required column need not have a default, and a defaulted
column need not be required.

## Bundled helpers (`scripts/`)

- **`pa_to_fx.py`** — converts `Other/Src/*.pa.yaml` → `Src/*.fx.yaml`. Handles the flow-dict
  expansion, `#`→`//` comment rewrite, single-line-formula quoting, injects
  `Layout: =Layout.Vertical` into every gallery, and picks a `BrowseLayout_Vertical_*` variant
  so template children land inside the gallery slot.
  `python3 scripts/pa_to_fx.py <in_pa_dir> <out_fx_dir>`
- **`bump_and_repack.py`** — bumps all three version stamps and re-zips a solution working dir
  into an importable `.zip` with the correct flat structure. `python3 scripts/bump_and_repack.py --help`

## Reference

`reference/packaging-gotchas.md` — the same traps in long form plus the solution-zip anatomy,
for when you need the full explanation rather than the checklist.

`reference/authoring-and-layout-qa.md` — Power Fx YAML syntax traps (record-literal/colon
quoting, enum escaping, lowercase date formats) and 10 layout self-QA checks the compiler can't
catch (GroupContainer min-size, FillPortions, scroll/no-height traps, label wrap/padding).
Distilled from Microsoft's official `power-platform-skills` canvas-apps plugin; toolchain-
independent, so it applies to the `.fx.yaml` we author offline.

## Hand-off discipline

You author and pack; **the maker imports**. State clearly: the exact `.zip` filename, that it
imports **unmanaged** via **Solutions → Import**, and a short verification checklist (App Checker
clean, galleries vertical, combos populate, the specific screens you changed behave as intended).
