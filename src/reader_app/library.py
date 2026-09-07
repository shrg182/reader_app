"""Personal library and book import routes."""

import hashlib
import json
import shutil
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from reader_app.epub import InvalidEpub, normalize_chapter, parse_epub
from reader_app.extensions import db
from reader_app.models import Book, BookChapter, ReadingProgress

bp = Blueprint("library", __name__)
ALLOWED_EXTENSIONS = {"txt", "md", "markdown", "epub"}


def overall_progress(book: Book) -> float:
    """Estimate EPUB completion with equal weight for each chapter."""
    locator = json.loads(book.progress.locator) if book.progress else {}
    progress = locator.get("progress", 0)
    if book.file_type == "epub" and book.chapters:
        ordinal = locator.get("chapter", 1)
        progress = (ordinal - 1 + progress) / len(book.chapters)
    return max(0, min(1, progress))


@bp.get("/")
@login_required
def index():
    query = request.args.get("q", "").strip()
    sort = request.args.get("sort", "recent")
    statement = db.select(Book).where(Book.user_id == current_user.id)
    if query:
        statement = statement.where(Book.title.ilike(f"%{query}%"))
    books = list(db.session.scalars(statement).all())
    progress_values = {book.id: overall_progress(book) for book in books}
    if sort == "title":
        books.sort(key=lambda book: book.title.casefold())
    elif sort == "author":
        books.sort(key=lambda book: (book.author or "").casefold())
    elif sort == "progress":
        books.sort(key=lambda book: progress_values[book.id], reverse=True)
    else:
        sort = "recent"
        books.sort(
            key=lambda book: book.progress.updated_at if book.progress else book.created_at,
            reverse=True,
        )
    return render_template(
        "library/index.html", books=books, query=query, sort=sort, progress_values=progress_values
    )


@bp.route("/books/import", methods=("GET", "POST"))
@login_required
def import_book():
    if request.method == "POST":
        uploaded = request.files.get("book")
        title = request.form.get("title", "").strip()
        if uploaded is None or not uploaded.filename:
            flash("Choose a TXT, Markdown, or EPUB file.", "error")
            return render_template("library/import.html")
        safe_name = uploaded.filename.replace("\\", "/").rsplit("/", 1)[-1]
        extension = Path(safe_name).suffix.lower().lstrip(".")
        if extension not in ALLOWED_EXTENSIONS:
            flash("Only TXT, Markdown, and EPUB files are supported.", "error")
            return render_template("library/import.html")
        digest = hashlib.sha256()
        uploaded_size = 0
        while chunk := uploaded.stream.read(1024 * 1024):
            uploaded_size += len(chunk)
            if uploaded_size > current_app.config["BOOK_MAX_CONTENT_LENGTH"]:
                flash("Books may not exceed 10 MB.", "error")
                return render_template("library/import.html")
            digest.update(chunk)
        content_hash = digest.hexdigest()
        uploaded.stream.seek(0)
        duplicate = db.session.scalar(
            db.select(Book).where(
                Book.user_id == current_user.id, Book.content_hash == content_hash
            )
        )
        if duplicate and request.form.get("allow_duplicate") != "yes":
            flash(f"This file already exists as “{duplicate.title}”.", "error")
            return render_template("library/import.html", duplicate=duplicate)
        parsed_epub = None
        if extension == "epub":
            try:
                parsed_epub = parse_epub(uploaded.stream.read())
            except InvalidEpub as error:
                flash(str(error), "error")
                return render_template("library/import.html")
            finally:
                uploaded.stream.seek(0)
        stored_name = f"{uuid4().hex}.{extension}"
        stored_path = Path(current_app.config["BOOK_UPLOAD_FOLDER"]) / stored_name
        created_paths = [stored_path]
        try:
            uploaded.save(stored_path)
            asset_root = uuid4().hex if parsed_epub else None
            book = Book(
                user_id=current_user.id,
                title=title or (parsed_epub.title if parsed_epub else Path(safe_name).stem),
                author=request.form.get("author", "").strip()
                or (parsed_epub.author if parsed_epub else None),
                language=request.form.get("language", "").strip()
                or (parsed_epub.language if parsed_epub else None),
                original_filename=safe_name,
                stored_filename=stored_name,
                file_type=extension,
                content_hash=content_hash,
                asset_root=asset_root,
            )
            db.session.add(book)
            db.session.flush()
            if parsed_epub:
                chapter_paths = {
                    chapter.source_path: ordinal
                    for ordinal, chapter in enumerate(parsed_epub.chapters, start=1)
                }
                for ordinal, chapter in enumerate(parsed_epub.chapters, start=1):
                    db.session.add(
                        BookChapter(
                            book_id=book.id,
                            ordinal=ordinal,
                            identifier=chapter.identifier,
                            title=chapter.title[:500],
                            source_path=chapter.source_path,
                            content_html=normalize_chapter(
                                chapter, book.id, chapter_paths, set(parsed_epub.assets)
                            ),
                        )
                    )
                asset_directory = Path(current_app.config["BOOK_UPLOAD_FOLDER"]) / "assets" / asset_root
                created_paths.append(asset_directory)
                for relative_path, data in parsed_epub.assets.items():
                    destination = asset_directory / relative_path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
            db.session.add(ReadingProgress(user_id=current_user.id, book_id=book.id))
            db.session.commit()
        except Exception:
            db.session.rollback()
            for path in reversed(created_paths):
                try:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink(missing_ok=True)
                except OSError:
                    current_app.logger.exception("Could not clean up failed import: %s", path)
            raise
        return redirect(url_for("reader.read", book_id=book.id))
    return render_template("library/import.html")


@bp.route("/books/<int:book_id>/edit", methods=("GET", "POST"))
@login_required
def edit_book(book_id: int):
    book = owned_book_or_404(book_id)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title or len(title) > 255:
            flash("A title between 1 and 255 characters is required.", "error")
        else:
            book.title = title
            book.author = request.form.get("author", "").strip()[:255] or None
            book.language = request.form.get("language", "").strip()[:32] or None
            db.session.commit()
            flash("Book details updated.", "success")
            return redirect(url_for("library.index"))
    return render_template("library/edit.html", book=book)


@bp.post("/books/<int:book_id>/delete")
@login_required
def delete_book(book_id: int):
    book = owned_book_or_404(book_id)
    stored_filename = book.stored_filename
    asset_root = book.asset_root
    title = book.title
    db.session.delete(book)
    db.session.commit()
    remaining = db.session.scalar(db.select(Book.id).where(Book.stored_filename == stored_filename))
    if remaining is None:
        path = Path(current_app.config["BOOK_UPLOAD_FOLDER"]) / stored_filename
        try:
            path.unlink(missing_ok=True)
        except OSError:
            flash("The library record was deleted, but its stored file could not be removed.", "error")
            return redirect(url_for("library.index"))
    if asset_root:
        asset_directory = Path(current_app.config["BOOK_UPLOAD_FOLDER"]) / "assets" / asset_root
        try:
            shutil.rmtree(asset_directory, ignore_errors=False)
        except FileNotFoundError:
            pass
        except OSError:
            flash("The book was deleted, but some extracted EPUB assets remain.", "error")
            return redirect(url_for("library.index"))
    flash(f"Deleted “{title}” and its study records.", "success")
    return redirect(url_for("library.index"))


def owned_book_or_404(book_id: int) -> Book:
    book = db.session.scalar(
        db.select(Book).where(Book.id == book_id, Book.user_id == current_user.id)
    )
    if book is None:
        abort(404)
    return book
