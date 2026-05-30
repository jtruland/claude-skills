# Power Apps Canvas Solution — Packaging Reference (long form)

This is the full-explanation companion to `SKILL.md`. Read the SKILL first for the workflow and
the checklist version of these traps. This file is the "why" for when a checklist line isn't enough.

---

## Solution `.zip` anatomy

A canvas app shipped as an unmanaged solution is a flat zip — **no wrapping parent folder**:

```
[Content_Types].xml                         describes the part content types
solution.xml                                solution identity + <Version>
customizations.xml                          app metadata: <AppVersion>, sienaVersion, <ConnectionReferences>
CanvasApps/
   <AppName>_<id>_DocumentUri.msapp         the packed app (Studio reads Controls\*.json inside)
Workflows/                                  present ONLY if the solution carries Power Automate flows
   <flow-name>_<id>.json
```

Re-zip command that preserves this structure (run from inside the working dir):

```bash
zip -X -r ../out.zip '[Content_Types].xml' solution.xml customizations.xml CanvasApps Workflows
```

`-X` drops extra file attributes; the explicit member list (not `zip -r out.zip .`) avoids
capturing a `./` parent or stray dotfiles. **Omit `Workflows` from the member list and you drop
every flow from the solution** — a common silent regression when copying the "canvas-only" zip
command.

---

## Trap 1 (full): the three version stamps

Power Platform treats the **canvas app** inside the solution as an independently versioned
artifact, keyed off the app's own version metadata — **not** the solution `<Version>`. So:

- Bump only `solution.xml` `<Version>`: import succeeds, the *solution* version increments, and
  Studio **keeps the old app screens**. This is the most common "I imported and nothing changed."
- Bump the app's `<AppVersion>` + `sienaVersion` too: Studio sees a newer app and overwrites.

The three, all in the wrapper (no msapp edit needed for the bump itself):

1. `solution.xml` → `<Version>0.0.0.N</Version>`
2. `customizations.xml` → `<AppVersion>YYYY-MM-DDThh:mm:ssZ</AppVersion>` (strictly newer ISO)
3. `customizations.xml` → `sienaVersion` inside `<Tags>`: `YYYYMMDDThhmmssZ-<clientver>`
   — keep the existing `-<clientver>` suffix exactly; only move the timestamp forward.

The `.msapp`'s internal `Header.json` `DocVersion` is **not** the gate; you do not need to touch
it to make a new build import.

`bump_and_repack.py` finds and rewrites all three, deriving the timestamps from "now" (UTC) and
preserving the existing `sienaVersion` client-version suffix.

---

## Trap 2 (full): gallery Layout defaults to Horizontal

`pac canvas pack` writes `Layout: Layout.Horizontal` + `WrapCount: 1` for any gallery whose
source omits `Layout` — even when the gallery's variant name is `BrowseLayout_Vertical_…`. A
horizontal gallery lays items out left-to-right: each item is `TemplateSize` pixels **wide** and
the gallery's full height. The visible result is a tall, ~`TemplateSize`-px-wide vertical strip,
and any template control whose `X` exceeds `TemplateSize` (e.g. a name label at `X:103` in a
50px template) is clipped off-canvas. You typically see only the leftmost control (often an image
placeholder) and conclude the data didn't load or the template is misbound. It's neither —
it's the layout.

Always author `Layout: =Layout.Vertical` on every gallery. After packing, confirm each gallery
rule in `Controls\*.json` reads `Layout=Layout.Vertical`.

---

## Trap 3 (full): searchable ComboBox + the lossy unpack

A classic `ComboBox@2.4.0` with `IsSearchable: =true` does **not** filter its `Items`. When
searchable, the dropdown is populated from a separate **`SearchItems`** rule. Studio
auto-generates `SearchItems` when you configure the control's fields in the designer; a
hand-authored YAML control never has it, so the dropdown is empty — looking exactly like an
empty data source.

Compounding it: **`pac canvas unpack` drops both `IsSearchable` and `SearchItems`** from the
regenerated source. So:
- A known-good app, unpacked, yields source missing both — identical to a broken control.
- Any unpack → edit → pack cycle silently re-breaks every searchable combo.

`pac pack` *does* honor both when present. The fix is to author the full set and never trust
unpack to round-trip it:

```yaml
IsSearchable: =true
SearchFields: =["Department_Name"]
DisplayFields: =["Department_Name"]
SearchItems: =Search(Sort(CERTDB_Departments, Department_Name), Self.SearchText, "Department_Name")
```

`Self` here is the combo itself — substitute the control's own name. For a custom-query picker
(people picker over `Office365Users.SearchUserV2`), set `SearchItems` to the **same expression**
as `Items` so typing re-runs the query.

Rule of thumb: **after any `pac unpack`, re-add `IsSearchable` + `SearchItems` to every
searchable combo before you pack.**

Two more ComboBox template defaults that bite if you leave them unset:

- **`DefaultSelectedItems` defaults to `First(ComboBoxSample)`** — a reference to a non-existent
  sample data source. An unset combo therefore shows a red error in Studio's App Checker. Set it
  explicitly: `=Blank()` for no default selection, or `=LookUp(<Source>, <key> = <var>.<key>)` to
  pre-select a record in edit mode. It is an **Array/table-typed** property, so `=""` (a string)
  raises its own type-mismatch error — use `Blank()`, not `""`.
- **`InputTextPlaceholder` defaults to a localized "find items" hint.** For a **filter** combo,
  override it with the category being filtered (e.g. `="Departments"`) so the empty control reads
  as a labeled filter rather than generic placeholder text. Make this a project-wide convention so
  every filter dropdown labels itself consistently.

(Note the parallel with the datepicker's `InputTextPlaceholder` 12/31/2001 default in Trap 6 —
classic-control template defaults are frequently sample/placeholder formulas that are wrong in a
real app. When a property shows an error or odd default in Studio, check the `pkgs/*.xml` template
`defaultValue` and set the property explicitly.)

---

## Trap 4 (full): `%…RESERVED%` enum tokens

Inside `pkgs/*.xml` (control templates) and `Src/Themes.json`, default property values appear as
tokens like `%DisplayMode.RESERVED%.Edit`, `%DateTimeZone.RESERVED%.Local`,
`%DateTimeFormat.RESERVED%.ShortDate`, `%StartOfWeek.RESERVED%.Sunday`. These are a template
placeholder syntax — valid **only** in those template/theme files.

If one of these tokens ends up in an actual control **instance** property (easy to do by copying
a default out of a `pkgs` file), `pac canvas pack` does not validate it and packs cleanly — then
Power Apps Studio raises `Expected operator. We expect an operator like + at this point…` and
**refuses to Publish** the app. Use the plain enum in instances: `DisplayMode.Edit`,
`DateTimeZone.Local`, `DateTimeFormat.ShortDate`, `StartOfWeek.Sunday`.

Pre-pack guard (must return nothing for instance sources):

```bash
grep -rE "%[A-Za-z]+\.RESERVED%" _unpacked/Src
```

Expect — and ignore — hits under `_unpacked/pkgs/` and in `Themes.json`.

---

## Trap 5 (full): `<ConnectionReferences>` is the import binding gate

At import time, Power Platform binds the app's connections strictly from the
`<ConnectionReferences>` JSON in `customizations.xml`. The msapp's own `Connections/
Connections.json` and `DataSources.json` describe the runtime wiring correctly, but they are
**not** what the importer reads to set up bindings.

Studio's export only writes `<ConnectionReferences>` for the data sources present when the app
was **first created**. Anything added later — extra SharePoint lists, and especially service
connectors like Office 365 Users — is omitted. Those import showing **"Not connected"** in the
Data pane. Re-adding them in Studio fixes the running app but does **not** survive the next
export, so the bug returns on every rebuild.

Fix: regenerate `<ConnectionReferences>` from the app's own `Connections/Connections.json`:
- one object per connection: `id`, `displayName`, `iconUri`
- the full `dataSources[]` array
- for SharePoint: `dataSets: { "<siteUrl>": { dataSources: { "<ListName>": { tableName: "<guid>" } } } }`
- for a service connector (e.g. Office365Users): `dataSets: {}`

Then bump the version stamps and re-zip. **No msapp change is required** — only the solution
wrapper is wrong.

---

## Trap 6 (full): optional dates with the classic datepicker

`datepicker_2.6.0` defaults `DefaultDate` to `Today()`, and once a user selects a date the
classic control gives no UI to clear it back to blank. An "optional end date" therefore always
carries a value and always writes one on Patch.

Pattern for a truly-optional, clearable date:

```yaml
# datepicker
DefaultDate: =If(locEndCleared, Blank(), If(IsBlank(varEditing), Blank(), varEditing.End_Date))
# clear icon next to it
OnSelect: =UpdateContext({ locEndCleared: true }); Reset(dpEnd)
```

- `locEndCleared` (a screen context var) forces `DefaultDate` to `Blank()`.
- `Reset(dpEnd)` snaps `SelectedDate` back to that blank default.
- Picking a new date afterward still works.
- Read the value as `dpEnd.SelectedDate`; treat `IsBlank(...)` as "no end / ongoing".

One more, easy to miss: the classic datepicker's `InputTextPlaceholder` **template default** is
`If(IsBlank(Self.SelectedDate), Text(Date(2001,12,31), Self.Format, Self.Language))`. So an
*empty* optional date doesn't show a blank box — it shows a formatted **`12/31/2001`** as
placeholder text, which reads as if a date is already set. Override it with
`InputTextPlaceholder: =""` (or a real hint like `"mm/dd/yyyy"`) so an unset date looks unset.

---

## Trap 7 (full): `#` and `pac` 1.34.4

`pac` 1.34.4 raises `PA3003` on any `#` character in a formula, including inside string literals.
This bites SharePoint/Graph payload strings such as `"#Microsoft.Azure.Connectors…"` and the
people-field claim prefix `"i:0#.f|membership|…"`. Replace the literal `#` using `Char(35)`:

```
"i:0#.f|membership|..."   →   "i:0" & Char(35) & ".f|membership|..."
```

The `pa_to_fx.py` converter separately rewrites YAML comment lines that begin with `#` into
Power Fx `//` comments (PyYAML would otherwise preserve them as literal text that `pac` rejects),
but it does **not** rewrite `#` inside string literals — fix those in source.

---

## Why Studio shows screens at all: `Controls\*.json`

Power Apps Studio renders an app from the `Controls\*.json` parts inside the `.msapp` (note the
**backslash** path separators in the zip entries — grep the whole extracted tree, not a forward-
slash path). `pac canvas pack` generates those from `Src/*.fx.yaml`. The `Src/*.pa.yaml` /
`Other/Src/*.pa.yaml` files inside an msapp are source-control artifacts that Studio **ignores**.
If a screen only ever exists as `.pa.yaml` and is never converted+packed into `Controls\*.json`,
Studio opens a blank app with no screens. This is why the pipeline always ends in a `pac pack`
and why you verify by grepping the packed msapp's `Controls\*.json`, not the source YAML.

---

## Verification checklist (give this to the maker)

After import in the maker portal:

- **App Checker** shows no new errors; Publish succeeds (catches stray `%…RESERVED%`).
- Every gallery renders as a vertical list (catches trap 2).
- Every searchable combo's dropdown populates and filters as you type (catches trap 3).
- Connections added after original creation show **Connected**, not "Not connected" (trap 5).
- Optional dates start blank and can be cleared after entry (trap 6).
- The specific screens/controls you changed behave as intended.
