#!/usr/bin/env python3
"""Bump the three canvas-app version stamps and re-zip a solution working dir.

Power Platform dedups a canvas app inside a solution by the APP's version, not the
solution <Version>. A re-import that bumps only solution.xml <Version> succeeds but
Studio silently keeps the old screens. You must bump all three, every build:

  1. solution.xml       <Version>
  2. customizations.xml <AppVersion>   (new ISO  YYYY-MM-DDThh:mm:ssZ)
  3. customizations.xml sienaVersion   (YYYYMMDDThhmmssZ-<clientver>, keep the suffix)

This script does all three off "now" (UTC), preserving the existing sienaVersion
client-version suffix, then re-zips with the correct FLAT structure (no parent folder,
Workflows/ included when present).

Usage:
  python3 bump_and_repack.py <work_dir> --version 0.0.0.18 --out dist/App_0_0_0_18.zip
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
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    app_version = now.strftime("%Y-%m-%dT%H:%M:%SZ")        # 2026-05-30T03:00:00Z
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


def bump_customizations_xml(path: Path, app_version: str, siena_ts: str, dry: bool) -> None:
    text = path.read_text(encoding="utf-8")

    new, n_app = re.subn(r"(<AppVersion>)[^<]*(</AppVersion>)",
                         rf"\g<1>{app_version}\g<2>", text, count=1)
    if n_app == 0:
        sys.exit(f"ERROR: no <AppVersion> element found in {path}")
    print(f"  customizations.xml <AppVersion> → {app_version}")

    # sienaVersion appears in <Tags> as: ...sienaVersion=20260530T030000Z-3.26052.14.0...
    # Keep everything after the first '-' (the client-version suffix); replace only the ts.
    def repl_siena(m):
        suffix = m.group("suffix")
        return f'{m.group("pre")}{siena_ts}{suffix}'

    siena_pat = re.compile(
        r'(?P<pre>sienaVersion["\'=:>\s]*?)'
        r'\d{8}T\d{6}Z'
        r'(?P<suffix>-[0-9.]+)'
    )
    new2, n_siena = siena_pat.subn(repl_siena, new, count=1)
    if n_siena == 0:
        # Fallback: bare sienaVersion timestamp with no -clientver suffix.
        new2, n_siena = re.subn(
            r'(sienaVersion["\'=:>\s]*?)\d{8}T\d{6}Z',
            rf'\g<1>{siena_ts}', new, count=1)
        if n_siena == 0:
            sys.exit(f"ERROR: no sienaVersion timestamp found in {path}")
        print(f"  customizations.xml sienaVersion → {siena_ts} (no clientver suffix found)")
    else:
        m = siena_pat.search(text)
        print(f"  customizations.xml sienaVersion → {siena_ts}{m.group('suffix')}")

    if not dry:
        path.write_text(new2, encoding="utf-8")


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
    bump_customizations_xml(cust, app_version, siena_ts, args.dry_run)
    repack(work, Path(args.out), args.dry_run)
    print("Done." if not args.dry_run else "Dry run complete — nothing written.")


if __name__ == "__main__":
    main()
