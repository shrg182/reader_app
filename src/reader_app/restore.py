"""Validated, transactional restoration of user-isolated Reader backups."""

import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from secrets import token_urlsafe
from uuid import uuid4

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from reader_app.epub import InvalidEpub, normalize_chapter, parse_epub
from reader_app.extensions import db
from reader_app.models import (
    Annotation,
    Book,
    BookChapter,
    ReaderPreference,
    ReadingProgress,
    VocabularyEntry,
)

bp = Blueprint("restore", __name__, url_prefix="/restore")
MAX_MEMBERS = 10000
MAX_EXPANDED_SIZE = 250 * 1024 * 1024
REQUIRED_TABLES = {"book", "progress", "annotation", "vocabulary", "preference"}
REQUIRED_BOOK_COLUMNS = {
    "id", "title", "author", "language", "original_filename", "stored_filename", "file_type",
    "content_hash",
}


class InvalidBackup(ValueError):
    """Raised when a backup cannot be trusted or restored."""


def validate_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise InvalidBackup("The backup contains an unsafe archive path.")
    return str(path)


def archive_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS or sum(item.file_size for item in infos) > MAX_EXPANDED_SIZE:
        raise InvalidBackup("The backup expands beyond the supported safety limit.")
    return {validate_member_name(item.filename): item for item in infos if not item.is_dir()}


def extract_database(archive: zipfile.ZipFile, members: dict, directory: Path) -> Path:
    if "library.sqlite3" not in members:
        raise InvalidBackup("The backup does not contain library.sqlite3.")
    destination = directory / "library.sqlite3"
    with archive.open(members["library.sqlite3"]) as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target)
    return destination


def readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    connection.row_factory = sqlite3.Row
    return connection


def validate_database(connection: sqlite3.Connection) -> dict[str, set[str]]:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise InvalidBackup("The backup database failed its integrity check.")
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if not REQUIRED_TABLES <= tables:
        raise InvalidBackup("The backup database schema is incomplete.")
    columns = {
        table: {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        for table in REQUIRED_TABLES | ({"chapter"} if "chapter" in tables else set())
    }
    if not REQUIRED_BOOK_COLUMNS <= columns["book"]:
        raise InvalidBackup("The backup book schema is incompatible.")
    return columns


def inspect_backup(path: Path) -> dict:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as error:
        raise InvalidBackup("The selected file is not a valid Reader backup ZIP.") from error
    with archive, tempfile.TemporaryDirectory(prefix="reader-restore-inspect-") as temporary:
        members = archive_members(archive)
        if "manifest.json" not in members:
            raise InvalidBackup("The backup manifest is missing.")
        try:
            manifest = json.loads(archive.read(members["manifest.json"]))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise InvalidBackup("The backup manifest is invalid.") from error
        if manifest.get("format") != 1:
            raise InvalidBackup("This Reader backup format is not supported.")
        database = extract_database(archive, members, Path(temporary))
        connection = readonly_connection(database)
        columns = validate_database(connection)
        books = connection.execute(
            "SELECT id, title, author, file_type, content_hash FROM book ORDER BY title"
        ).fetchall()
        existing_hashes = set(
            db.session.scalars(
                db.select(Book.content_hash).where(
                    Book.user_id == current_user.id, Book.content_hash.is_not(None)
                )
            ).all()
        )
        result = {
            "manifest": manifest,
            "books": [dict(row) | {"duplicate": row["content_hash"] in existing_hashes} for row in books],
            "annotations": connection.execute("SELECT COUNT(*) FROM annotation").fetchone()[0],
            "vocabulary": connection.execute("SELECT COUNT(*) FROM vocabulary").fetchone()[0],
            "has_chapters": "chapter" in columns,
        }
        connection.close()
        return result


def source_member(members: dict[str, zipfile.ZipInfo], old_book_id: int) -> zipfile.ZipInfo:
    prefix = f"books/{old_book_id}-"
    matches = [item for name, item in members.items() if name.startswith(prefix)]
    if len(matches) != 1:
        raise InvalidBackup(f"The source file for backup book {old_book_id} is missing or ambiguous.")
    return matches[0]


def row_value(row: sqlite3.Row, columns: set[str], name: str, default=None):
    return row[name] if name in columns else default


def restore_backup(path: Path) -> tuple[int, int]:
    created_paths: list[Path] = []
    restored = 0
    skipped = 0
    try:
        with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(
            prefix="reader-restore-apply-"
        ) as temporary:
            members = archive_members(archive)
            database = extract_database(archive, members, Path(temporary))
            source = readonly_connection(database)
            columns = validate_database(source)
            existing_hashes = set(
                db.session.scalars(
                    db.select(Book.content_hash).where(
                        Book.user_id == current_user.id, Book.content_hash.is_not(None)
                    )
                ).all()
            )
            book_map = {}
            chapter_map = {}
            for old_book in source.execute("SELECT * FROM book ORDER BY id"):
                content_hash = old_book["content_hash"]
                extension = str(old_book["file_type"])
                title = str(old_book["title"] or "").strip()
                author = str(old_book["author"] or "").strip() or None
                language = str(old_book["language"] or "").strip() or None
                original_filename = str(old_book["original_filename"] or "").strip()
                if extension not in {"txt", "md", "markdown", "epub"}:
                    raise InvalidBackup("The backup contains an unsupported book format.")
                if not title or len(title) > 255 or len(author or "") > 255:
                    raise InvalidBackup("The backup contains invalid book metadata.")
                if len(language or "") > 32 or not original_filename or len(original_filename) > 255:
                    raise InvalidBackup("The backup contains invalid language or filename metadata.")
                if content_hash and not re.fullmatch(r"[0-9a-f]{64}", str(content_hash)):
                    raise InvalidBackup("The backup contains an invalid book content hash.")
                if content_hash and content_hash in existing_hashes:
                    skipped += 1
                    continue
                member = source_member(members, old_book["id"])
                file_data = archive.read(member)
                calculated_hash = hashlib.sha256(file_data).hexdigest()
                if content_hash and calculated_hash != content_hash:
                    raise InvalidBackup(f"The stored hash for “{old_book['title']}” does not match.")
                content_hash = content_hash or calculated_hash
                stored_filename = f"{uuid4().hex}.{extension}"
                destination = Path(current_app.config["BOOK_UPLOAD_FOLDER"]) / stored_filename
                destination.write_bytes(file_data)
                created_paths.append(destination)
                parsed = None
                if extension == "epub":
                    try:
                        parsed = parse_epub(file_data)
                    except InvalidEpub as error:
                        raise InvalidBackup(f"An EPUB in the backup is invalid: {error}") from error
                asset_root = uuid4().hex if parsed else None
                book = Book(
                    user_id=current_user.id,
                    title=title,
                    author=author,
                    language=language,
                    original_filename=original_filename,
                    stored_filename=stored_filename,
                    file_type=extension,
                    content_hash=content_hash,
                    asset_root=asset_root,
                )
                db.session.add(book)
                db.session.flush()
                book_map[old_book["id"]] = book
                if parsed:
                    chapter_paths = {
                        chapter.source_path: ordinal
                        for ordinal, chapter in enumerate(parsed.chapters, start=1)
                    }
                    new_chapters = []
                    for ordinal, chapter in enumerate(parsed.chapters, start=1):
                        new_chapter = BookChapter(
                            book_id=book.id,
                            ordinal=ordinal,
                            identifier=chapter.identifier,
                            title=chapter.title[:500],
                            source_path=chapter.source_path,
                            content_html=normalize_chapter(
                                chapter, book.id, chapter_paths, set(parsed.assets)
                            ),
                        )
                        db.session.add(new_chapter)
                        new_chapters.append(new_chapter)
                    db.session.flush()
                    if "chapter" in columns:
                        old_chapters = source.execute(
                            "SELECT id, ordinal FROM chapter WHERE book_id = ?", (old_book["id"],)
                        ).fetchall()
                        by_ordinal = {chapter.ordinal: chapter.id for chapter in new_chapters}
                        chapter_map.update(
                            {row["id"]: by_ordinal.get(row["ordinal"]) for row in old_chapters}
                        )
                    asset_directory = (
                        Path(current_app.config["BOOK_UPLOAD_FOLDER"]) / "assets" / asset_root
                    )
                    created_paths.append(asset_directory)
                    for relative_path, data in parsed.assets.items():
                        asset_path = asset_directory / relative_path
                        asset_path.parent.mkdir(parents=True, exist_ok=True)
                        asset_path.write_bytes(data)
                existing_hashes.add(content_hash)
                restored += 1
            for old_id, book in book_map.items():
                progress = source.execute(
                    "SELECT locator FROM progress WHERE book_id = ?", (old_id,)
                ).fetchone()
                if progress:
                    try:
                        locator = json.loads(progress["locator"])
                        progress_value = float(locator["progress"])
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                        raise InvalidBackup("The backup contains invalid reading progress.") from error
                    if not 0 <= progress_value <= 1:
                        raise InvalidBackup("The backup contains invalid reading progress.")
                    db.session.add(
                        ReadingProgress(
                            user_id=current_user.id, book_id=book.id, locator=json.dumps(locator)
                        )
                    )
            annotation_columns = columns["annotation"]
            for row in source.execute("SELECT * FROM annotation ORDER BY id"):
                book = book_map.get(row["book_id"])
                if book:
                    old_chapter = row_value(row, annotation_columns, "chapter_id")
                    if (
                        row["start_offset"] < 0
                        or row["end_offset"] <= row["start_offset"]
                        or row["end_offset"] - row["start_offset"] > 5000
                        or len(row["selected_text"]) > 5000
                        or len(row["note"]) > 10000
                        or row["color"] not in {"yellow", "green", "blue", "pink"}
                    ):
                        raise InvalidBackup("The backup contains an invalid annotation.")
                    db.session.add(
                        Annotation(
                            user_id=current_user.id,
                            book_id=book.id,
                            chapter_id=chapter_map.get(old_chapter),
                            start_offset=row["start_offset"],
                            end_offset=row["end_offset"],
                            selected_text=row["selected_text"],
                            note=row["note"],
                            color=row["color"],
                        )
                    )
            vocabulary_columns = columns["vocabulary"]
            for row in source.execute("SELECT * FROM vocabulary ORDER BY id"):
                book = book_map.get(row["book_id"])
                if book:
                    old_chapter = row_value(row, vocabulary_columns, "chapter_id")
                    if (
                        row["start_offset"] < 0
                        or row["end_offset"] <= row["start_offset"]
                        or len(row["term"]) > 500
                        or len(row["language"]) > 32
                        or len(row["definition"]) > 10000
                        or len(row["context"]) > 2000
                        or len(row["note"]) > 10000
                    ):
                        raise InvalidBackup("The backup contains an invalid vocabulary entry.")
                    db.session.add(
                        VocabularyEntry(
                            user_id=current_user.id,
                            book_id=book.id,
                            chapter_id=chapter_map.get(old_chapter),
                            start_offset=row["start_offset"],
                            end_offset=row["end_offset"],
                            term=row["term"],
                            language=row["language"],
                            definition=row["definition"],
                            context=row["context"],
                            note=row["note"],
                        )
                    )
            if current_user.preference is None:
                preference = source.execute("SELECT * FROM preference LIMIT 1").fetchone()
                if preference:
                    if (
                        preference["theme"] not in {"light", "sepia", "dark"}
                        or preference["font_family"] not in {"serif", "sans"}
                        or not 14 <= preference["font_size"] <= 30
                        or not 130 <= preference["line_height"] <= 240
                        or not 520 <= preference["column_width"] <= 1000
                    ):
                        raise InvalidBackup("The backup contains invalid reader preferences.")
                    db.session.add(
                        ReaderPreference(
                            user_id=current_user.id,
                            theme=preference["theme"],
                            font_family=preference["font_family"],
                            font_size=preference["font_size"],
                            line_height=preference["line_height"],
                            column_width=preference["column_width"],
                        )
                    )
            db.session.commit()
            source.close()
    except Exception:
        db.session.rollback()
        for created in reversed(created_paths):
            if created.is_dir():
                shutil.rmtree(created, ignore_errors=True)
            else:
                created.unlink(missing_ok=True)
        raise
    return restored, skipped


def staging_directory() -> Path:
    directory = Path(current_app.instance_path) / "restore-staging"
    directory.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - 24 * 60 * 60
    for staged in directory.glob("*.zip"):
        try:
            if staged.stat().st_mtime < cutoff:
                staged.unlink()
        except OSError:
            pass
    return directory


@bp.route("", methods=("GET", "POST"))
@login_required
def upload():
    if request.method == "POST":
        uploaded = request.files.get("backup")
        if uploaded is None or not uploaded.filename:
            flash("Choose a Reader backup ZIP.", "error")
            return render_template("restore/upload.html")
        token = token_urlsafe(24)
        old_token = session.get("restore_token")
        if old_token:
            (staging_directory() / f"{current_user.id}-{old_token}.zip").unlink(missing_ok=True)
        path = staging_directory() / f"{current_user.id}-{token}.zip"
        size = 0
        with path.open("wb") as destination:
            while chunk := uploaded.stream.read(1024 * 1024):
                size += len(chunk)
                if size > current_app.config["BACKUP_MAX_CONTENT_LENGTH"]:
                    destination.close()
                    path.unlink(missing_ok=True)
                    flash("Backups may not exceed 100 MB.", "error")
                    return render_template("restore/upload.html")
                destination.write(chunk)
        try:
            preview = inspect_backup(path)
        except InvalidBackup as error:
            path.unlink(missing_ok=True)
            flash(str(error), "error")
            return render_template("restore/upload.html")
        session["restore_token"] = token
        return render_template("restore/preview.html", preview=preview, token=token)
    return render_template("restore/upload.html")


@bp.post("/apply")
@login_required
def apply():
    token = request.form.get("token", "")
    if not token or token != session.get("restore_token"):
        flash("The restore preview has expired. Upload the backup again.", "error")
        return redirect(url_for("restore.upload"))
    path = staging_directory() / f"{current_user.id}-{token}.zip"
    if not path.is_file():
        flash("The staged backup is missing. Upload it again.", "error")
        return redirect(url_for("restore.upload"))
    try:
        inspect_backup(path)
        restored, skipped = restore_backup(path)
    except (
        InvalidBackup,
        OSError,
        SQLAlchemyError,
        TypeError,
        ValueError,
        sqlite3.DatabaseError,
        zipfile.BadZipFile,
    ) as error:
        flash(f"Nothing was restored: {error}", "error")
        return redirect(url_for("restore.upload"))
    finally:
        path.unlink(missing_ok=True)
        session.pop("restore_token", None)
    flash(f"Restored {restored} books; skipped {skipped} duplicates.", "success")
    return redirect(url_for("library.index"))
