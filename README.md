# Reader App

For setup and everyday reading instructions, see [USAGE.md](USAGE.md).

A private, multilingual browser-based reader. The current first milestone supports:

- account registration, login, and isolated personal libraries;
- safe import of TXT and Markdown files up to 10 MB;
- Unicode reading content, including English, Chinese, and Russian;
- sanitized Markdown rendering; and
- automatic reading-progress restoration;
- durable highlights with colors and optional notes; and
- annotation editing, deletion, and restoration after reopening a book;
- vocabulary capture with language, definition, context, and personal notes; and
- searchable all-books vocabulary and annotation dashboards with source links.
- persistent font, spacing, width, and light/sepia/dark appearance settings;
- generated contents navigation for Markdown and multilingual TXT chapter headings; and
- versioned Alembic database migrations applied automatically at startup.
- editable book metadata, progress and study counts, and library sorting;
- SHA-256 duplicate detection and guarded book deletion;
- multilingual CSV and Markdown exports; and
- user-isolated ZIP backups containing books, study data, and a portable SQLite database.
- validated EPUB import with metadata, reading-order, navigation, and image extraction;
- sanitized chapter-based EPUB reading with protected assets; and
- chapter-aware progress, highlights, vocabulary, and source links.
- validated backup preview and account-bound restore confirmation;
- transactional ID-remapped restoration with duplicate detection; and
- rollback cleanup for corrupt archives, hash failures, and database errors.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
reader-app
```

Then open <http://127.0.0.1:5000>. Runtime data is stored under the ignored `instance/`
directory. To use another address, run `reader-app --host 0.0.0.0 --port 8000`.

Do not expose the development server publicly. Before production deployment, supply a
strong secret key, use a production WSGI server, and apply database migrations before
starting workers.

Production mode refuses to start without an explicit secret key:

```bash
export READER_ENV=production
export READER_SECRET_KEY='generate-a-long-random-secret'
export READER_TRUSTED_HOSTS='reader.example.com'
reader-app --host 127.0.0.1 --port 8000
```

Production mode enables secure, HTTP-only, SameSite session cookies. Run Reader behind
an HTTPS reverse proxy and a production WSGI server; the built-in server is for local
development only.

## Development

Application code lives under `src/reader_app/` and tests live under `tests/`.

```bash
ruff check .
pytest
reader-app --version
```

The progress-save regression tests also require Node.js:

```bash
node --test tests/js/progress.test.cjs
```

Browser regressions use a temporary database, a local server, and Chromium:

```bash
python -m pip install -e '.[dev,browser]'
python -m playwright install chromium
pytest tests/browser --run-browser
```

To use an installed Chrome, set `READER_TEST_BROWSER_CHANNEL=chrome`. Set
`READER_TEST_SCREENSHOTS=/tmp/reader-screenshots` to capture desktop and mobile layouts.
The regular `pytest` run includes fresh-install and legacy database-upgrade checks;
browser tests run only with `--run-browser`. GitHub Actions runs both suites plus lint
and JavaScript checks on Python 3.11 and 3.14.

## Reliability

Unicode filenames are preserved for display; uploaded files use generated storage names.
Failed imports roll back database changes and clean up their files. Reading-position saves
are written to browser storage immediately, then synced to the server. Pending positions
survive closing a tab and retry when that book is reopened in the same browser and account.
The status distinguishes device storage from server sync. This requires available browser
storage; clearing site data removes pending positions. Books themselves still require a
connection to open.

Select text with a mouse or touch handles to annotate it. Keyboard users can focus the
book text and extend a selection with Shift+Arrow keys. On smaller screens, “Add note
or word” opens the editor over the reading view; Escape or Cancel dismisses it.

EPUB completion uses equally weighted chapters; the saved position within a chapter is
kept separately for restoration. This is an estimate, not a page- or word-weighted measure.

Database upgrades run automatically through `reader-app`. For a WSGI deployment from
this checkout, run `flask --app reader_app:create_app db upgrade` from the project root
before starting workers. Back up existing runtime data before upgrading.

The next planned milestone is EPUB cover display, EPUB 2 NCX refinements, and library
collections. PDF support will follow because stable PDF selection and annotation anchoring
require a separate model.
