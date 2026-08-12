#!/usr/bin/env python3
"""Bump the three canvas-app version stamps and re-zip a solution working dir.

Power Platform dedups a canvas app inside a solution by the APP's version, not the
solution <Version>. A re-import that bumps only solution.xml <Version> succeeds but
Studio silently keeps the old screens. You must bump all three, every build:

  1. solution.xml       <Version>
  2. customizations.xml <AppVersion>   (new ISO  YYYY-MM-DDThh:mm:ssZ)
  3. customizations.xml sienaVersion   (YYYYMMDDThhmmssZ-<clientver>, keep the suffix)

This script does all three off "now" in LOCAL time (not UTC), preserving the existing
sienaVersion client-version suffix, then re-zips with the correct FLAT structure (no
parent folder, Workflows/ included when present).

WHY LOCAL, NOT UTC: Power Apps Studio stamps <AppVersion> with the user's *local*
wall-clock time but appends a literal `Z` (it is NOT actually UTC), and the maker-portal
solution dashboard displays the stamp at face value with no timezone conversion. If you
stamp genuine UTC here, the value is hours ahead of local and the dashboard shows the app
"updated in the future" on import. Stamping local-now (with the `Z` suffix) matches Studio
and reads correctly. Run the build on a machine set to the tenant/user's timezone.

MULTI-APP SOLUTIONS: each canvas app dedups independently by ITS OWN AppVersion, so the
two customizations.xml stamps must be scoped to one <CanvasApp> block. Pass --app <name>.
With 2+ apps present and no --app, this script REFUSES to run and lists the names rather
than bumping the first block — block order is export order, not the order you care about,
so "the first one" is a coin flip. Bumping the wrong block is silent in both directions:
the app you edited keeps its old version (import succeeds, Studio shows the old screens),
and the app you did not edit gets republished over whatever is live in the tenant.

Usage:
  python3 bump_and_repack.py <work_dir> --version 0.0.0.18 --out dist/App_0_0_0_18.zip
  python3 bump_and_repack.py <work_dir> --version 0.0.0.19 --app adminapp --out out.zip
  python3 bump_and_repack.py <work_dir> --version 0.0.0.18 --out out.zip --dry-run

<work_dir> is the unzipped solution root containing [Content_Types].xml, solution.xml,
customizations.xml, CanvasApps/ (and optionally Workflows/).

Requires the `zip` CLI for packaging (uses -X with an explicit member list).
"""

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path


def now_stamps():
    # LOCAL time + literal "Z" — matches Studio's stamp convention so the maker-portal
    # dashboard doesn't show the app "updated in the future". See module docstring.
    now = dt.datetime.now().replace(microsecond=0)
    app_version = now.strftime("%Y-%m-%dT%H:%M:%SZ")        # 2026-05-30T03:00:00Z (local, Z suffix)
    siena_ts = now.strftime("%Y%m%dT%H%M%SZ")               # 20260530T030000Z
    return app_version, siena_ts


def bump_solution_xml(path: Path, version: str, dry: bool) -> None:
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(r"(<Version>)[^<]*(</Version>)",
                     rf"\g<1>{version}\g<2>", text, count=1)
    if n == 0:
        sys.exit(f"ERROR: no <Version> element found in {path}")
    print(f"  solution.xml      <Version> → {version}")
    if not dry:
        path.write_text(new, encoding="utf-8")


# Non-spanning: a lazy <CanvasApp>.*?</CanvasApp> silently runs into the NEXT block and
# edits the wrong app. The tempered pattern below cannot cross a closing tag.
CANVAS_APP_RE = re.compile(r"<CanvasApp>(?:(?!</CanvasApp>).)*?</CanvasApp>", re.S)
NAME_RE = re.compile(r"<Name>([^<]*)</Name>")

# sienaVersion appears in <Tags> as: ...sienaVersion=20260530T030000Z-3.26052.14.0...
# Keep everything after the first '-' (the client-version suffix); replace only the ts.
SIENA_RE = re.compile(
    r'(?P<pre>sienaVersion["\'=:>\s]*?)'
    r'\d{8}T\d{6}Z'
    r'(?P<suffix>-[0-9.]+)'
)


def block_name(block: str) -> str:
    m = NAME_RE.search(block)
    return m.group(1) if m else "<unnamed>"


def select_app_block(text: str, path: Path, app: str | None):
    """Return the (match, name) of the single <CanvasApp> block to bump.

    A multi-app solution dedups each app independently by ITS OWN AppVersion, so bumping
    the wrong block leaves the app you changed on its old version — the import "succeeds"
    and Studio silently keeps the old screens. Worse, the app you did NOT change gets
    republished, which can clobber in-tenant edits. So: with 2+ blocks, --app is REQUIRED.
    """
    blocks = list(CANVAS_APP_RE.finditer(text))
    if not blocks:
        sys.exit(f"ERROR: no <CanvasApp> block found in {path}")

    names = [block_name(b.group(0)) for b in blocks]
    if len(blocks) == 1:
        if app and app.lower() not in names[0].lower():
            sys.exit(f"ERROR: --app {app!r} does not match the only app present: {names[0]}")
        return blocks[0], names[0]

    if not app:
        sys.exit(
            f"ERROR: {len(blocks)} <CanvasApp> blocks in {path.name} — pass --app to say which one:\n"
            + "".join(f"    --app {n}\n" for n in names)
            + "  (Bumping 'the first one' is never safe: block order is export order, not yours.)"
        )

    hits = [(b, n) for b, n in zip(blocks, names) if app.lower() in n.lower()]
    if not hits:
        sys.exit(f"ERROR: --app {app!r} matched none of: {', '.join(names)}")
    if len(hits) > 1:
        sys.exit(f"ERROR: --app {app!r} is ambiguous — matched: {', '.join(n for _, n in hits)}")
    return hits[0]


def bump_customizations_xml(path: Path, app_version: str, siena_ts: str, dry: bool,
                            app: str | None = None) -> None:
    text = path.read_text(encoding="utf-8")
    match, name = select_app_block(text, path, app)
    block = match.group(0)
    print(f"  customizations.xml target app → {name}")

    new_block, n_app = re.subn(r"(<AppVersion>)[^<]*(</AppVersion>)",
                               rf"\g<1>{app_version}\g<2>", block, count=1)
    if n_app == 0:
        sys.exit(f"ERROR: no <AppVersion> element inside the {name} <CanvasApp> block")
    print(f"  customizations.xml <AppVersion> → {app_version}")

    new_block, n_siena = SIENA_RE.subn(
        lambda m: f'{m.group("pre")}{siena_ts}{m.group("suffix")}', new_block, count=1)
    if n_siena == 0:
        # Fallback: bare sienaVersion timestamp with no -clientver suffix.
        new_block, n_siena = re.subn(
            r'(sienaVersion["\'=:>\s]*?)\d{8}T\d{6}Z',
            rf'\g<1>{siena_ts}', new_block, count=1)
        if n_siena == 0:
            sys.exit(f"ERROR: no sienaVersion timestamp inside the {name} <CanvasApp> block")
        print(f"  customizations.xml sienaVersion → {siena_ts} (no clientver suffix found)")
    else:
        m = SIENA_RE.search(block)
        print(f"  customizations.xml sienaVersion → {siena_ts}{m.group('suffix')}")

    # Splice the edited block back in place — everything outside it is byte-identical.
    new_text = text[:match.start()] + new_block + text[match.end():]

    untouched = [n for n in (block_name(b.group(0)) for b in CANVAS_APP_RE.finditer(text))
                 if n != name]
    if untouched:
        print(f"  untouched app(s): {', '.join(untouched)}")

    if not dry:
        path.write_text(new_text, encoding="utf-8")


def repack(work: Path, out: Path, dry: bool) -> None:
    members = ["[Content_Types].xml", "solution.xml", "customizations.xml", "CanvasApps"]
    if (work / "Workflows").is_dir():
        members.append("Workflows")
    else:
        print("  (no Workflows/ — packing canvas-only)")

    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not dry:
        out.unlink()

    cmd = ["zip", "-X", "-r", str(out), *members]
    print(f"  zip → {out}")
    print(f"       {' '.join(cmd)}  (cwd={work})")
    if not dry:
        r = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"ERROR: zip failed:\n{r.stdout}\n{r.stderr}")
        print(f"  wrote {out}  ({out.stat().st_size} bytes)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work_dir", help="Unzipped solution root")
    ap.add_argument("--version", required=True, help="New solution version, e.g. 0.0.0.18")
    ap.add_argument("--out", required=True, help="Output .zip path")
    ap.add_argument("--app", default=None,
                    help="Which <CanvasApp> to bump (substring of its <Name>). "
                         "REQUIRED when the solution holds more than one app — the script "
                         "refuses to guess, and lists the available names.")
    ap.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = ap.parse_args()

    work = Path(args.work_dir).resolve()
    sol = work / "solution.xml"
    cust = work / "customizations.xml"
    for required in (sol, cust, work / "[Content_Types].xml", work / "CanvasApps"):
        if not required.exists():
            sys.exit(f"ERROR: {required} not found — is {work} a solution root?")

    app_version, siena_ts = now_stamps()
    print(f"Bumping stamps in {work}{'  (dry run)' if args.dry_run else ''}:")
    bump_solution_xml(sol, args.version, args.dry_run)
    bump_customizations_xml(cust, app_version, siena_ts, args.dry_run, args.app)
    repack(work, Path(args.out), args.dry_run)
    print("Done." if not args.dry_run else "Dry run complete — nothing written.")


if __name__ == "__main__":
    main()
