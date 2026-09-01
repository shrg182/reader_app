# Reader App

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
strong secret key, use a production WSGI server, and introduce database migrations.

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

The next planned milestone is EPUB cover display, EPUB 2 NCX refinements, and library
collections. PDF support will follow because stable PDF selection and annotation anchoring
require a separate model.
