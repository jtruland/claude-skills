# claude-skills

Portable [Claude Code](https://claude.com/claude-code) skills, shareable across machines and colleagues.

Each subdirectory is a self-contained skill (a `SKILL.md` plus optional `scripts/` and
`reference/` material). Claude Code discovers personal skills under `~/.claude/skills/`, so
this repo is intended to **be** that directory (or be symlinked into it).

## Skills

| Skill | What it does |
|---|---|
| [`powerapps-canvas-editing`](powerapps-canvas-editing/) | Edit Microsoft Power Apps **canvas** apps as source (`.fx.yaml` / `.pa.yaml`) and ship them as importable solution `.zip` files, entirely offline with the `pac` CLI — no tenant connection. Covers the non-obvious traps: three-stamp version bumping, gallery Layout, searchable ComboBox `SearchItems`, `%RESERVED%` enum tokens, and the `ConnectionReferences` import gate. |
| [`build-recipe-format`](build-recipe-format/) | Write or restructure a **step-by-step build recipe** for something assembled by hand in a GUI (a Power Automate flow, a canvas screen, a list schema). Four techniques do most of the work — lead with a structure tree, collapse N-way repeats into a table, extract every expression to its own block, name a repeated sub-expression once — plus a script that proves a templated rewrite is lossless instead of assuming it. |

## Install

Clone into your Claude Code skills directory:

```bash
git clone git@github.com:jtruland/claude-skills.git ~/.claude/skills
```

Then **enable the secret-scan hook** (see below). Hooks are not cloned by git, so this is
a required one-time step on each machine.

## Secret-scan pre-commit hook

This repo ships a `pre-commit` hook in [`.githooks/`](.githooks/) that blocks commits
containing private IPs, GitHub tokens, private keys, and other high-confidence secret
patterns — a safety net so internal infrastructure details don't leak into this public repo.

Enable it after cloning:

```bash
git -C ~/.claude/skills config core.hooksPath .githooks
```

To bypass it for a commit you've verified is clean: `git commit --no-verify`.
