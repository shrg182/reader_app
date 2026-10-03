# Handoff: 随身书房 · Personal Reader

Last updated: 2026-10-02

## Purpose

Personal, multilingual reading library with accounts, TXT/Markdown/EPUB import,
reading-position restoration, annotations, vocabulary, export, and backup.

## Current state

- The committed application supports personal libraries, EPUB reading,
  annotations, vocabulary, progress synchronization, and backup/restore.
- The documented next product milestone is EPUB cover display, EPUB 2 NCX
  refinements, and library collections. PDF support is planned afterward.
- The current local worktree contains an unfinished home-Wi-Fi hosting change:
  `reader-app --home`, Waitress integration, a macOS login-service helper,
  documentation, and CLI tests. Preserve and finish this work before starting
  the EPUB milestone.
- The visible product name is **随身书房 · Personal Reader**. The repository and
  Python package names remain unchanged.

## Run and verify

```bash
source .venv/bin/activate
python -m pip install -e '.[dev,browser]'
ruff check .
pytest
node --test tests/js/progress.test.cjs
pytest tests/browser --run-browser
```

For the pending home-server work, also verify `reader-app --home` on the trusted
home network and run the install, status, restart, and stop paths in
`tools/home_server.py` on macOS.

## Important files

- `src/reader_app/` — application code.
- `tests/` and `tests/browser/` — automated verification.
- `USAGE.md` — everyday use and home-network instructions.
- `tools/home_server.py` — pending macOS home-service helper.
- `instance/` or `src/instance/` — ignored runtime data; back it up before
  migration or service changes.

## Known constraints

- The built-in development server is not suitable for public hosting.
- Home mode uses HTTP and is restricted to a trusted home network.
- Pending reading positions depend on browser storage until server sync succeeds.
- PDF annotation requires a separate anchoring model and is not part of the next
  milestone.

## Latest verification

- Focused CLI and home-mode tests: `3 passed` on 2026-10-02.
- The wider Python, JavaScript, and browser suites must be rerun after the
  pending home-server work is complete.

## Next three tasks

1. Complete, test, and commit the existing home-Wi-Fi hosting work without
   discarding the current uncommitted files.
2. Implement EPUB cover display and improve EPUB 2 NCX navigation, with import
   and browser regression coverage.
3. Add library collections while preserving account isolation, sorting, export,
   backup, and restore behavior.
