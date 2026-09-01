"""User-isolated study exports and personal backups."""

import csv
import io
import json
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from flask import Blueprint, current_app, send_file
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from reader_app.extensions import db
from reader_app.library import owned_book_or_404
from reader_app.models import Book, VocabularyEntry

bp = Blueprint("exports", __name__, url_prefix="/exports")


def markdown_for_book(book: Book) -> str:
    lines = [f"# {book.title}", "", f"Author: {book.author or 'Unknown'}", ""]
    lines.extend(["## Highlights and notes", ""])
    for item in sorted(book.annotations, key=lambda value: value.created_at):
        quote = "\n> ".join(item.selected_text.splitlines())
        lines.extend([f"> {quote}", ""])
        if item.note:
            lines.extend([item.note, ""])
    lines.extend(["## Vocabulary", ""])
    for entry in sorted(book.vocabulary, key=lambda value: value.created_at):
        lines.extend([f"### {entry.term}", ""])
        if entry.language:
            lines.extend([f"Language: {entry.language}", ""])
        if entry.definition:
            lines.extend([entry.definition, ""])
        if entry.context:
            lines.extend([f"> {entry.context}", ""])
        if entry.note:
            lines.extend([f"Note: {entry.note}", ""])
    return "\n".join(lines)


@bp.get("/vocabulary.csv")
@login_required
def vocabulary_csv():
    entries = db.session.scalars(
        db.select(VocabularyEntry)
        .where(VocabularyEntry.user_id == current_user.id)
        .order_by(VocabularyEntry.created_at)
    ).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["term", "language", "definition", "context", "note", "book"])
    for entry in entries:
        writer.writerow(
            [entry.term, entry.language, entry.definition, entry.context, entry.note, entry.book.title]
        )
    payload = io.BytesIO(("\ufeff" + output.getvalue()).encode("utf-8"))
    return send_file(payload, mimetype="text/csv; charset=utf-8", as_attachment=True,
                     download_name="reader-vocabulary.csv")


@bp.get("/notes.md")
@login_required
def notes_markdown():
    books = db.session.scalars(
        db.select(Book).where(Book.user_id == current_user.id).order_by(Book.title)
    ).all()
    text = "# Reader notes and vocabulary\n\n" + "\n\n---\n\n".join(
        markdown_for_book(book) for book in books
    )
    return send_file(io.BytesIO(text.encode()), mimetype="text/markdown; charset=utf-8",
                     as_attachment=True, download_name="reader-notes.md")


@bp.get("/books/<int:book_id>.md")
@login_required
def book_markdown(book_id: int):
    book = owned_book_or_404(book_id)
    filename = secure_filename(book.title) or f"book-{book.id}"
    return send_file(io.BytesIO(markdown_for_book(book).encode()),
                     mimetype="text/markdown; charset=utf-8", as_attachment=True,
                     download_name=f"{filename}-study.md")


def build_backup_database(path: Path, books: list[Book]) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE book (id INTEGER PRIMARY KEY, title TEXT, author TEXT, language TEXT,
          original_filename TEXT, stored_filename TEXT, file_type TEXT, content_hash TEXT,
          asset_root TEXT);
        CREATE TABLE chapter (id INTEGER PRIMARY KEY, book_id INTEGER, ordinal INTEGER,
          identifier TEXT, title TEXT, source_path TEXT, content_html TEXT);
        CREATE TABLE progress (book_id INTEGER PRIMARY KEY, locator TEXT, updated_at TEXT);
        CREATE TABLE annotation (id INTEGER PRIMARY KEY, book_id INTEGER, chapter_id INTEGER,
          start_offset INTEGER, end_offset INTEGER, selected_text TEXT, note TEXT, color TEXT,
          created_at TEXT);
        CREATE TABLE vocabulary (id INTEGER PRIMARY KEY, book_id INTEGER, chapter_id INTEGER,
          start_offset INTEGER, end_offset INTEGER, term TEXT, language TEXT, definition TEXT,
          context TEXT, note TEXT, created_at TEXT);
        CREATE TABLE preference (theme TEXT, font_family TEXT, font_size INTEGER,
          line_height INTEGER, column_width INTEGER);
        """
    )
    for book in books:
        connection.execute(
            "INSERT INTO book VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (book.id, book.title, book.author, book.language, book.original_filename,
             book.stored_filename, book.file_type, book.content_hash, book.asset_root),
        )
        connection.executemany(
            "INSERT INTO chapter VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(chapter.id, book.id, chapter.ordinal, chapter.identifier, chapter.title,
              chapter.source_path, chapter.content_html) for chapter in book.chapters],
        )
        if book.progress:
            connection.execute(
                "INSERT INTO progress VALUES (?, ?, ?)",
                (book.id, book.progress.locator, book.progress.updated_at.isoformat()),
            )
        connection.executemany(
            "INSERT INTO annotation VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(item.id, book.id, item.chapter_id, item.start_offset, item.end_offset,
              item.selected_text, item.note, item.color, item.created_at.isoformat())
             for item in book.annotations],
        )
        connection.executemany(
            "INSERT INTO vocabulary VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(entry.id, book.id, entry.chapter_id, entry.start_offset, entry.end_offset, entry.term,
              entry.language, entry.definition, entry.context, entry.note,
              entry.created_at.isoformat())
             for entry in book.vocabulary],
        )
    if current_user.preference:
        preference = current_user.preference
        connection.execute(
            "INSERT INTO preference VALUES (?, ?, ?, ?, ?)",
            (preference.theme, preference.font_family, preference.font_size,
             preference.line_height, preference.column_width),
        )
    connection.commit()
    connection.close()


@bp.get("/backup.zip")
@login_required
def backup_zip():
    books = list(db.session.scalars(db.select(Book).where(Book.user_id == current_user.id)).all())
    output = io.BytesIO()
    with tempfile.TemporaryDirectory(prefix="reader-backup-") as temporary:
        database_path = Path(temporary) / "library.sqlite3"
        build_backup_database(database_path, books)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(database_path, "library.sqlite3")
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {"format": 1, "created_at": datetime.now(UTC).isoformat(),
                     "username": current_user.username, "book_count": len(books)},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            archive.writestr("study/notes.md", "\n\n---\n\n".join(
                markdown_for_book(book) for book in books
            ))
            for book in books:
                source = Path(current_app.config["BOOK_UPLOAD_FOLDER"]) / book.stored_filename
                if source.is_file():
                    archive.write(source, f"books/{book.id}-{secure_filename(book.original_filename)}")
    output.seek(0)
    return send_file(output, mimetype="application/zip", as_attachment=True,
                     download_name="reader-personal-backup.zip")
