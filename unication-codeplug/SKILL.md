---
name: unication-codeplug
description: >
  Read and edit Unication GxPPS `.unipps` codeplug files (G-series P25 pagers) outside the
  CPS, and write files the CPS still loads. Use this when asked to bulk-edit talkgroups,
  build or re-sort dial (knob) positions, add zones, restrict a zone to particular trunking
  sites, or diff two codeplugs — or when a hand-edited `.unipps` is silently rejected with
  no error. Covers the container format (60-byte header, two CRC-16/CCITT fields, a 32-bit
  length, a payload zip of SQLite 2.1 databases), why modern sqlite3 cannot open the
  databases, and the non-obvious traps: a timestamp coupled to a header CRC, a
  site-to-control-channel join on the wrong key, VACUUM after filtering a system, and a
  WACN that passes every checksum while making the pager look dead.
---

# Unication GxPPS `.unipps` codeplugs

A `.unipps` file is a 60-byte header followed by a plain zip of **SQLite 2.1** databases.
Everything a pager does — talkgroups, dial positions, zones, trunking systems — is rows in
those databases, so bulk edits are ordinary SQL. The CPS accepts a rewritten file provided
the derived header fields are recomputed.

`scripts/unipps.py` does the container work. No dependencies beyond the Python 3 standard
library.

```
python3 unipps.py unpack mycodeplug.unipps work
sqlite work/tree/<org>/<system>.db "UPDATE tabGroup_New SET GroupName='NEW' WHERE GroupNo='1';"
python3 unipps.py pack work edited.unipps
```

`unpack` prints `ok` / `BAD` for every derived field, so a broken file is caught before the
CPS sees it. `pack` recomputes them all.

## First: you need sqlite 2.x

⚠️ **`sqlite3` cannot open these databases.** They are SQLite **2.1**
(`** This file contains an SQLite 2.1 database **`, magic int `0xdae37528`), a different
on-disk format dropped long before sqlite3. Build 2.8.17:

```bash
curl -L -o sqlite2.tar.gz "https://sqlite.org/src/tarball/sqlite-2.8.17.tar.gz?r=version-2.8.17"
mkdir sq2 && tar xzf sqlite2.tar.gz -C sq2 --strip-components=1
cd sq2 && mkdir bld && cd bld
CFLAGS="-O1 -fcommon -w -std=gnu89" ../configure --disable-tcl --disable-shared
make sqlite
```

⚠️ SQLite 2 has no `CAST`. Sort numeric-valued text columns with `ORDER BY col+0`.

The schema is plaintext and carries the vendor's own comments, which document most enum
values — read `SELECT sql FROM sqlite_master` before guessing what a column means.

## Header

```
offset  size  encoding          meaning
0       4     FE FE FE FE       magic
4       6     constant          01 02 00 01 00 00
10      4     u32 big-endian    Unix epoch seconds, stamped when the file is written
14      2     constant          00 01
16      2     u16 big-endian    CRC(header[0..15]) ^ 0xBBBE
18      4     u32 big-endian    36 + len(payload)
22      2     u16 big-endian    CRC(GUID + payload)
24      36    ASCII             GUID, matches the main .db filename
60      ...                     payload: a plain zip of SQLite 2.1 databases
```

Both CRCs are the same function:

```
poly 0x1021 (CCITT), input bytes reflected, result reflected once at the end,
init 0x0000, xorout 0x0000
```

⚠️ **Bytes 16–17 are computed over the timestamp at 10–13, so the two move together.**
Changing the timestamp without recomputing that CRC produces a file the CPS silently
refuses. This is the most confusing failure in the format: the field looks unvalidated for
as long as every test happens to hold the timestamp constant.

⚠️ The timestamp should also stay close to the save time recorded *inside* the payload
(`tabOrganization_New`). Stamping "now" over an otherwise untouched payload is rejected.
`pack` therefore preserves the timestamp by default; `--restamp` moves the in-database
string and the header together via a same-length byte replace, needing no sqlite binary.

⚠️ A `.unipps` can carry **more than one organization** — the CPS's "save as new" leaves the
previous org's database in the zip. The header GUID names the active one, and that GUID is
what the payload CRC is computed over.

## Payload layout

```
<org>.db                    the codeplug: ~165 tables — zones, knobs, settings
<org>/<system>.db           a trunking system: sites, control channels, talkgroups
<org>/AlertToneTotal.db
<org>/VoicePromptTotal.db
```

Talkgroups live in the **system** database (`tabGroup_New`), not the codeplug database.

## Dial (knob) positions

```
tabP25TrunkingSystemKnob (ZoneID, KnobIndex, ChannelID, P25TrunkingID, ...)  PK (ZoneID, KnobIndex)
tabChannelGroup          (ChannelID, GroupID, ...)                          talkgroups on that position
tabReceivingMode_NewG4   (ZoneID, KnobIndex, CurrentMode, ChannelName, ...) PK (ZoneID, KnobIndex)
```

`KnobIndex` is the dial position. `ChannelID` ties it to a talkgroup list; each `GroupID`
refers to `tabGroup_New.GroupID` in the system database.

To add a position: one `tabP25TrunkingSystemKnob` row (copy an existing one wholesale,
changing only `KnobIndex` and a **fresh `ChannelID` GUID**), one `tabChannelGroup` row per
talkgroup, and one `tabP25TCallAlertSUID` row as `(ChannelID, '', 30, 30)`.

⚠️ **That is not enough — the position stays dark.** `tabReceivingMode_NewG4` ships with
eight rows, one per knob, and `CurrentMode = 0` means *off*. Enabling needs:

```
CurrentMode  16              -- Trunking TG-Scan. The schema comment lists the rest:
                             -- 1 Selective Call, 33 Monitor, 4 Normal Scan, 36 Priority
                             -- Scan, 68 Silent Scan, 8 Free Scan, 129 Advanced Channel
ChannelName  'Local'         -- what the position is called
AlertToneID  8
```

Overlap between positions is allowed — the same talkgroup can sit on several.

## Zones

A zone is a `tabZone_New` row `(ID, ZoneNo, Name, Note, ModifyByDevice)`. Duplicating the
knob layout into a new zone means: the zone row, a `tabP25TrunkingSystemKnob` row per
position with a fresh `ChannelID`, its `tabChannelGroup` rows, a `tabP25TCallAlertSUID` row
per `ChannelID`, and **all eight** `tabReceivingMode_NewG4` rows (`CurrentMode = 16` for the
live positions, `0` for the rest).

### Restricting a zone to particular sites

⚠️ **There is no per-zone site table** — the codeplug database's entire schema contains the
string `site` once, as a count.

Sites belong to the **system** definition, so a restricted zone needs its own duplicated
system. `tabP25TrunkingSecurity` is keyed by `P25TrunkingID` and carries a `DBFileName`;
each system lives in its own `<P25TrunkingID>.db` beside the codeplug database. Copy the
system, filter it, register it, and point that zone's knob rows at it:

```sql
DELETE FROM tabP25TrunkingSite          WHERE ID NOT IN (<site row ids>);
DELETE FROM tabP25TrunkingSiteControlCH WHERE SiteID NOT IN (<site row ids>);
DELETE FROM tabP25TrunkingControlCH     WHERE ID NOT IN (SELECT ControlChannelID FROM tabP25TrunkingSiteControlCH);
UPDATE tabP25TrunkingSystem SET ID='<new guid>', Name='<zone name>';
VACUUM;
```

then, in the codeplug database, insert a `tabP25TrunkingSecurity` row for the new
`P25TrunkingID` and run
`UPDATE tabP25TrunkingSystemKnob SET P25TrunkingID='<new guid>' WHERE ZoneID='<zone>'`.
Add the new `.db` to the zip.

⚠️ **`tabP25TrunkingSiteControlCH.SiteID` joins on the site's row `ID`, not its `SiteID`
column.** Those are different numbers in the same table. Using the wrong one silently builds
a zone pointing at the wrong towers, and every count and checksum still validates. Confirm
the join by reading `tabP25TrunkingControlCH.Note`, which names the site in prose.

⚠️ **`VACUUM` after filtering.** Deleting rows leaves the pages behind, so a filtered system
stays at its original size until vacuumed — which matters because the payload is zipped and
the header carries its length.

⚠️ **Read `WacnID`, `SystemID` and `TGIDCount` from the system you are filtering.**
Hardcoding them lets a duplicated system disagree with the original — invisible to row
counts, the length field and both CRCs.

## The WACN

Stored in exactly two places, which must agree: `tabP25TrunkingSecurity.WacnID` in the
codeplug database, and `tabP25TrunkingSystem.WacnID` in **each** system database.

⚠️ A wrong WACN stops the pager affiliating with the system at all, and presents as a dead
radio rather than a configuration error. Nothing in the file format catches it — every
checksum still validates. Check it whenever a pager mysteriously hears nothing.

## Method: working on a file the CPS rejects

The CPS rejects a bad codeplug **silently**, with no indication of which field is wrong, so
guessing is expensive. What works:

1. **Get a byte-identical control to load first.** Copy a file the CPS itself wrote, rename
   it, confirm it opens. Until that passes, nothing else is interpretable — a rejection
   could be the download, the filename, or Windows' Mark-of-the-Web rather than your edit.
2. **Change exactly one thing per test file**, and prove it by byte-diffing against the last
   file known to load. A test that changes three things and fails identifies nothing.
3. **Ask the CPS for a reference.** When a structure has never been observed — a second
   zone, a restricted site list — have someone build one small example in the CPS and diff
   it against yours. That settles in one round trip what inference will not.
4. **Trust `unpack`'s validation over loading the file.** It agrees with the CPS on every
   file whose fate is known, so it catches mistakes without a round trip.

## Field widths worth knowing

| Column | Width |
|---|---|
| `tabGroup_New.GroupName` | `VARCHAR(14)` — why talkgroup names look truncated |
| `tabZone_New.Name` | `VARCHAR(30)` |
| `tabReceivingMode_NewG4.ChannelName` | `VARCHAR(30)` |

⚠️ Storage width is not display width. How much of a 30-character name a given pager model
actually shows is not established here.
