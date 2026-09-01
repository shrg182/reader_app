"""Reading view and progress persistence."""

import json
import re
from html import unescape
from pathlib import Path

import bleach
import markdown
from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from flask_login import current_user, login_required
from markupsafe import Markup, escape

from reader_app.annotations import serialize
from reader_app.extensions import db
from reader_app.library import owned_book_or_404
from reader_app.models import (
    Annotation,
    BookChapter,
    ReaderPreference,
    ReadingProgress,
    VocabularyEntry,
)

bp = Blueprint("reader", __name__, url_prefix="/reader")

ALLOWED_TAGS = {
    "p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "code",
    "em", "strong", "ul", "ol", "li", "hr", "a",
}
CHAPTER_PATTERN = re.compile(
    r"^\s*(?:chapter|part|book|глава|часть)\s+[\w\divxlcdm]+|^\s*第.{1,12}[章节部卷篇]",
    re.IGNORECASE,
)
PREFERENCE_DEFAULTS = {
    "theme": "sepia",
    "font_family": "serif",
    "font_size": 18,
    "line_height": 185,
    "column_width": 760,
}


def render_markdown(text: str) -> tuple[Markup, list[dict]]:
    rendered = markdown.markdown(text, extensions=["fenced_code", "sane_lists", "toc"])
    chapters = []
    for level, identifier, title_html in re.findall(
        r'<h([1-6]) id="([^"]+)">(.*?)</h\1>', rendered, flags=re.DOTALL
    ):
        title = unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
        chapters.append({"level": int(level), "id": identifier, "title": title})
    cleaned = bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes={"a": ["href"], "h1": ["id"], "h2": ["id"], "h3": ["id"],
                    "h4": ["id"], "h5": ["id"], "h6": ["id"]},
    )
    return Markup(cleaned), chapters


def render_plain_text(text: str) -> tuple[Markup, list[dict]]:
    chapters = []
    output = []
    for line in text.splitlines(keepends=True):
        title = line.strip()
        if title and CHAPTER_PATTERN.match(title):
            identifier = f"chapter-{len(chapters) + 1}"
            chapters.append({"level": 2, "id": identifier, "title": title})
            output.append(f'<h2 id="{identifier}">{escape(title)}</h2>')
            if line.endswith(("\n", "\r")):
                output.append("\n")
        else:
            output.append(str(escape(line)))
    return Markup("".join(output)), chapters


def preference_data(preference: ReaderPreference | None) -> dict:
    if preference is None:
        return PREFERENCE_DEFAULTS.copy()
    return {key: getattr(preference, key) for key in PREFERENCE_DEFAULTS}


@bp.get("/<int:book_id>")
@login_required
def read(book_id: int):
    book = owned_book_or_404(book_id)
    locator = json.loads(book.progress.locator) if book.progress else {"progress": 0}
    jump_offset = None
    target_chapter_id = None
    annotation_id = request.args.get("annotation", type=int)
    vocabulary_id = request.args.get("vocabulary", type=int)
    if annotation_id:
        target = db.session.scalar(
            db.select(Annotation).where(
                Annotation.id == annotation_id,
                Annotation.book_id == book.id,
                Annotation.user_id == current_user.id,
            )
        )
        if target:
            jump_offset, target_chapter_id = target.start_offset, target.chapter_id
    elif vocabulary_id:
        target = db.session.scalar(
            db.select(VocabularyEntry).where(
                VocabularyEntry.id == vocabulary_id,
                VocabularyEntry.book_id == book.id,
                VocabularyEntry.user_id == current_user.id,
            )
        )
        if target:
            jump_offset, target_chapter_id = target.start_offset, target.chapter_id
    active_chapter = None
    if book.file_type == "epub":
        requested_ordinal = request.args.get("chapter", type=int)
        if target_chapter_id:
            active_chapter = db.session.scalar(
                db.select(BookChapter).where(
                    BookChapter.id == target_chapter_id, BookChapter.book_id == book.id
                )
            )
        if active_chapter is None:
            requested_ordinal = requested_ordinal or locator.get("chapter", 1)
            active_chapter = db.session.scalar(
                db.select(BookChapter).where(
                    BookChapter.book_id == book.id, BookChapter.ordinal == requested_ordinal
                )
            )
        if active_chapter is None:
            abort(404)
        content = Markup(active_chapter.content_html)
        chapters = [
            {"title": chapter.title, "ordinal": chapter.ordinal, "level": 1}
            for chapter in book.chapters
        ]
        progress = locator.get("progress", 0) if locator.get("chapter") == active_chapter.ordinal else 0
        annotations = [
            serialize(item)
            for item in sorted(book.annotations, key=lambda item: item.id)
            if item.chapter_id == active_chapter.id
        ]
        is_markdown = True
    else:
        path = Path(current_app.config["BOOK_UPLOAD_FOLDER"]) / book.stored_filename
        text = path.read_text(encoding="utf-8", errors="replace")
        if book.file_type in {"md", "markdown"}:
            content, chapters = render_markdown(text)
            is_markdown = True
        else:
            content, chapters = render_plain_text(text)
            is_markdown = False
        progress = locator.get("progress", 0)
        annotations = [serialize(item) for item in sorted(book.annotations, key=lambda item: item.id)]
    return render_template(
        "reader/read.html",
        book=book,
        content=content,
        is_markdown=is_markdown,
        progress=progress,
        annotations=annotations,
        jump_offset=jump_offset,
        chapters=chapters,
        preferences=preference_data(current_user.preference),
        active_chapter=active_chapter,
    )


@bp.post("/<int:book_id>/progress")
@login_required
def save_progress(book_id: int):
    book = owned_book_or_404(book_id)
    payload = request.get_json(silent=True) or {}
    try:
        progress_value = max(0.0, min(1.0, float(payload["progress"])))
    except (KeyError, TypeError, ValueError):
        return jsonify(error="Progress must be a number between 0 and 1."), 400
    progress = book.progress or ReadingProgress(user_id=current_user.id, book_id=book.id)
    locator = {"progress": progress_value}
    if book.file_type == "epub":
        try:
            chapter_id = int(payload["chapter_id"])
        except (KeyError, TypeError, ValueError):
            return jsonify(error="EPUB progress requires a chapter identifier."), 400
        chapter = db.session.scalar(
            db.select(BookChapter).where(BookChapter.id == chapter_id, BookChapter.book_id == book.id)
        )
        if chapter is None:
            return jsonify(error="The EPUB chapter does not exist."), 400
        locator["chapter"] = chapter.ordinal
    progress.locator = json.dumps(locator)
    db.session.add(progress)
    db.session.commit()
    return jsonify(progress=progress_value)


@bp.get("/<int:book_id>/assets/<path:asset_path>")
@login_required
def epub_asset(book_id: int, asset_path: str):
    book = owned_book_or_404(book_id)
    if book.file_type != "epub" or not book.asset_root:
        abort(404)
    directory = Path(current_app.config["BOOK_UPLOAD_FOLDER"]) / "assets" / book.asset_root
    return send_from_directory(directory, asset_path, conditional=True)


@bp.post("/preferences")
@login_required
def save_preferences():
    payload = request.get_json(silent=True) or {}
    theme = str(payload.get("theme", ""))
    font_family = str(payload.get("font_family", ""))
    try:
        font_size = int(payload.get("font_size"))
        line_height = int(payload.get("line_height"))
        column_width = int(payload.get("column_width"))
    except (TypeError, ValueError):
        return jsonify(error="Reader dimensions must be integers."), 400
    if theme not in {"light", "sepia", "dark"} or font_family not in {"serif", "sans"}:
        return jsonify(error="Unsupported reader theme or font."), 400
    if not 14 <= font_size <= 30 or not 130 <= line_height <= 240 or not 520 <= column_width <= 1000:
        return jsonify(error="One or more reader settings are outside the supported range."), 400
    preference = current_user.preference or ReaderPreference(user_id=current_user.id)
    preference.theme = theme
    preference.font_family = font_family
    preference.font_size = font_size
    preference.line_height = line_height
    preference.column_width = column_width
    db.session.add(preference)
    db.session.commit()
    return jsonify(preference_data(preference))
