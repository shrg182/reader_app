"""Vocabulary capture and cross-book study dashboards."""

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from reader_app.extensions import db
from reader_app.library import owned_book_or_404
from reader_app.models import Annotation, Book, BookChapter, VocabularyEntry

bp = Blueprint("study", __name__)


def vocabulary_or_404(entry_id: int) -> VocabularyEntry:
    entry = db.session.scalar(
        db.select(VocabularyEntry).where(
            VocabularyEntry.id == entry_id, VocabularyEntry.user_id == current_user.id
        )
    )
    if entry is None:
        abort(404)
    return entry


def serialize_vocabulary(entry: VocabularyEntry) -> dict:
    return {
        "id": entry.id,
        "book_id": entry.book_id,
        "start_offset": entry.start_offset,
        "end_offset": entry.end_offset,
        "chapter_id": entry.chapter_id,
        "term": entry.term,
        "language": entry.language,
        "definition": entry.definition,
        "context": entry.context,
        "note": entry.note,
    }


@bp.post("/reader/<int:book_id>/vocabulary")
@login_required
def create_vocabulary(book_id: int):
    owned_book_or_404(book_id)
    payload = request.get_json(silent=True) or {}
    try:
        start = int(payload["start_offset"])
        end = int(payload["end_offset"])
    except (KeyError, TypeError, ValueError):
        return jsonify(error="Vocabulary offsets must be integers."), 400
    term = str(payload.get("term", "")).strip()
    language = str(payload.get("language", "")).strip()
    definition = str(payload.get("definition", "")).strip()
    context = str(payload.get("context", "")).strip()
    note = str(payload.get("note", "")).strip()
    if start < 0 or end <= start or not term or len(term) > 500:
        return jsonify(error="Select a word or phrase up to 500 characters."), 400
    if end - start > 500 or len(context) > 2000 or len(definition) > 10000 or len(note) > 10000:
        return jsonify(error="The vocabulary entry is too long."), 400
    if len(language) > 32:
        return jsonify(error="The language label is too long."), 400
    chapter_id = payload.get("chapter_id")
    if chapter_id is not None:
        chapter = db.session.scalar(
            db.select(BookChapter).where(BookChapter.id == chapter_id, BookChapter.book_id == book_id)
        )
        if chapter is None:
            return jsonify(error="The selected EPUB chapter does not exist."), 400
    entry = VocabularyEntry(
        user_id=current_user.id,
        book_id=book_id,
        start_offset=start,
        end_offset=end,
        term=term,
        language=language,
        definition=definition,
        context=context,
        note=note,
        chapter_id=chapter_id,
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify(serialize_vocabulary(entry)), 201


@bp.get("/vocabulary")
@login_required
def vocabulary():
    query = request.args.get("q", "").strip()
    language = request.args.get("language", "").strip()
    book_id = request.args.get("book_id", type=int)
    statement = db.select(VocabularyEntry).where(VocabularyEntry.user_id == current_user.id)
    if query:
        statement = statement.where(
            or_(
                VocabularyEntry.term.ilike(f"%{query}%"),
                VocabularyEntry.definition.ilike(f"%{query}%"),
                VocabularyEntry.note.ilike(f"%{query}%"),
            )
        )
    if language:
        statement = statement.where(VocabularyEntry.language == language)
    if book_id:
        statement = statement.where(VocabularyEntry.book_id == book_id)
    entries = db.session.scalars(statement.order_by(VocabularyEntry.created_at.desc())).all()
    books = db.session.scalars(
        db.select(Book).where(Book.user_id == current_user.id).order_by(Book.title)
    ).all()
    languages = db.session.scalars(
        db.select(VocabularyEntry.language)
        .where(VocabularyEntry.user_id == current_user.id, VocabularyEntry.language != "")
        .distinct()
        .order_by(VocabularyEntry.language)
    ).all()
    return render_template(
        "study/vocabulary.html",
        entries=entries,
        books=books,
        languages=languages,
        query=query,
        selected_language=language,
        selected_book=book_id,
    )


@bp.post("/vocabulary/<int:entry_id>/update")
@login_required
def update_vocabulary(entry_id: int):
    entry = vocabulary_or_404(entry_id)
    values = {
        "language": request.form.get("language", "").strip(),
        "definition": request.form.get("definition", "").strip(),
        "note": request.form.get("note", "").strip(),
    }
    if len(values["language"]) > 32 or any(len(values[key]) > 10000 for key in ("definition", "note")):
        flash("One or more vocabulary fields are too long.", "error")
    else:
        entry.language, entry.definition, entry.note = values.values()
        db.session.commit()
        flash(f"Updated “{entry.term}”.", "success")
    return redirect(url_for("study.vocabulary"))


@bp.post("/vocabulary/<int:entry_id>/delete")
@login_required
def delete_vocabulary(entry_id: int):
    entry = vocabulary_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    flash("Vocabulary entry deleted.", "success")
    return redirect(url_for("study.vocabulary"))


@bp.get("/notes")
@login_required
def notes():
    query = request.args.get("q", "").strip()
    color = request.args.get("color", "").strip()
    book_id = request.args.get("book_id", type=int)
    statement = db.select(Annotation).where(Annotation.user_id == current_user.id)
    if query:
        statement = statement.where(
            or_(Annotation.selected_text.ilike(f"%{query}%"), Annotation.note.ilike(f"%{query}%"))
        )
    if color:
        statement = statement.where(Annotation.color == color)
    if book_id:
        statement = statement.where(Annotation.book_id == book_id)
    annotations = db.session.scalars(statement.order_by(Annotation.created_at.desc())).all()
    books = db.session.scalars(
        db.select(Book).where(Book.user_id == current_user.id).order_by(Book.title)
    ).all()
    return render_template(
        "study/notes.html",
        annotations=annotations,
        books=books,
        query=query,
        selected_color=color,
        selected_book=book_id,
    )
