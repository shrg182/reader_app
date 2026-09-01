"""Ownership-scoped annotation API."""

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

from reader_app.extensions import db
from reader_app.library import owned_book_or_404
from reader_app.models import Annotation, BookChapter

bp = Blueprint("annotations", __name__, url_prefix="/reader")
COLORS = {"yellow", "green", "blue", "pink"}


def serialize(annotation: Annotation) -> dict:
    return {
        "id": annotation.id,
        "start_offset": annotation.start_offset,
        "end_offset": annotation.end_offset,
        "chapter_id": annotation.chapter_id,
        "selected_text": annotation.selected_text,
        "note": annotation.note,
        "color": annotation.color,
    }


def annotation_or_404(book_id: int, annotation_id: int) -> Annotation:
    annotation = db.session.scalar(
        db.select(Annotation).where(
            Annotation.id == annotation_id,
            Annotation.book_id == book_id,
            Annotation.user_id == current_user.id,
        )
    )
    if annotation is None:
        abort(404)
    return annotation


@bp.post("/<int:book_id>/annotations")
@login_required
def create(book_id: int):
    owned_book_or_404(book_id)
    payload = request.get_json(silent=True) or {}
    try:
        start = int(payload["start_offset"])
        end = int(payload["end_offset"])
    except (KeyError, TypeError, ValueError):
        return jsonify(error="Annotation offsets must be integers."), 400
    text = str(payload.get("selected_text", "")).strip()
    note = str(payload.get("note", "")).strip()
    color = str(payload.get("color", "yellow"))
    if start < 0 or end <= start or end - start > 5000 or not text:
        return jsonify(error="Select between 1 and 5,000 characters."), 400
    if len(text) > 5000 or len(note) > 10000:
        return jsonify(error="The selected text or note is too long."), 400
    if color not in COLORS:
        return jsonify(error="Unsupported highlight color."), 400
    chapter_id = payload.get("chapter_id")
    if chapter_id is not None:
        chapter = db.session.scalar(
            db.select(BookChapter).where(BookChapter.id == chapter_id, BookChapter.book_id == book_id)
        )
        if chapter is None:
            return jsonify(error="The selected EPUB chapter does not exist."), 400
    annotation = Annotation(
        user_id=current_user.id,
        book_id=book_id,
        start_offset=start,
        end_offset=end,
        selected_text=text,
        note=note,
        color=color,
        chapter_id=chapter_id,
    )
    db.session.add(annotation)
    db.session.commit()
    return jsonify(serialize(annotation)), 201


@bp.patch("/<int:book_id>/annotations/<int:annotation_id>")
@login_required
def update(book_id: int, annotation_id: int):
    owned_book_or_404(book_id)
    annotation = annotation_or_404(book_id, annotation_id)
    payload = request.get_json(silent=True) or {}
    note = str(payload.get("note", annotation.note)).strip()
    color = str(payload.get("color", annotation.color))
    if len(note) > 10000:
        return jsonify(error="The note is too long."), 400
    if color not in COLORS:
        return jsonify(error="Unsupported highlight color."), 400
    annotation.note = note
    annotation.color = color
    db.session.commit()
    return jsonify(serialize(annotation))


@bp.delete("/<int:book_id>/annotations/<int:annotation_id>")
@login_required
def delete(book_id: int, annotation_id: int):
    owned_book_or_404(book_id)
    annotation = annotation_or_404(book_id, annotation_id)
    db.session.delete(annotation)
    db.session.commit()
    return "", 204
