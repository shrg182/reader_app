import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from reader_app.extensions import db
from reader_app.models import Annotation, Book, BookChapter, ReaderPreference, VocabularyEntry
from tests.conftest import register


def make_epub(*, unsafe_member: bool = False, encrypted: bool = False) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/package.opf",
            '''<?xml version="1.0"?>
            <package xmlns="http://www.idpf.org/2007/opf" version="3.0">
              <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                <dc:title>多语言 EPUB</dc:title><dc:creator>Test Author</dc:creator>
                <dc:language>zh</dc:language><dc:identifier>test-id</dc:identifier>
              </metadata>
              <manifest>
                <item id="one" href="one.xhtml" media-type="application/xhtml+xml"/>
                <item id="two" href="two.xhtml" media-type="application/xhtml+xml"/>
                <item id="image" href="images/pixel.png" media-type="image/png"/>
                <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
              </manifest>
              <spine><itemref idref="one"/><itemref idref="two"/></spine>
            </package>''',
        )
        archive.writestr(
            "OPS/one.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>开始</title></head><body><h1>第一章</h1><p>你好 EPUB</p><img src="images/pixel.png" alt="pixel"/><a href="two.xhtml">Next</a><script>alert(1)</script></body></html>',
        )
        archive.writestr(
            "OPS/two.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Second</title></head><body><h1>Глава два</h1><p>Привет EPUB</p></body></html>',
        )
        archive.writestr(
            "OPS/nav.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><nav><ol><li><a href="one.xhtml">Start from navigation</a></li><li><a href="two.xhtml">Вторая глава</a></li></ol></nav></body></html>',
        )
        archive.writestr("OPS/images/pixel.png", b"\x89PNG\r\n\x1a\n")
        if unsafe_member:
            archive.writestr("../escape.txt", "unsafe")
        if encrypted:
            archive.writestr("META-INF/encryption.xml", "<encryption/>")
    return output.getvalue()


def test_library_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_registration_creates_private_library(client):
    response = register(client)
    assert response.status_code == 200
    assert b"My Library" in response.data


def test_import_and_read_unicode_text(client, app):
    register(client)
    response = client.post(
        "/books/import",
        data={
            "title": "Three Languages",
            "language": "Multilingual",
            "book": (io.BytesIO("Hello 中文 Привет".encode()), "sample.txt"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Hello 中文 Привет".encode() in response.data

    with app.app_context():
        book = db.session.scalar(db.select(Book))
        book_id = book.id
    saved = client.post(f"/reader/{book_id}/progress", json={"progress": 0.42})
    assert saved.get_json() == {"progress": 0.42}
    with app.app_context():
        book = db.session.get(Book, book_id)
        assert json.loads(book.progress.locator)["progress"] == 0.42


def test_user_cannot_read_another_users_book(client, app):
    register(client, "first", "first@example.com")
    client.post(
        "/books/import",
        data={"book": (io.BytesIO(b"private"), "private.txt")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        book_id = db.session.scalar(db.select(Book.id))
    client.post("/auth/logout")
    register(client, "second", "second@example.com")
    assert client.get(f"/reader/{book_id}").status_code == 404
    assert client.post(f"/reader/{book_id}/progress", json={"progress": 1}).status_code == 404


def test_markdown_is_sanitized(client):
    register(client)
    response = client.post(
        "/books/import",
        data={"book": (io.BytesIO(b"# Safe\n\n<script>alert(1)</script>"), "book.md")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b'<h1 id="safe">Safe</h1>' in response.data
    assert b"<script>" not in response.data


def test_annotation_lifecycle_and_restoration(client, app):
    register(client)
    client.post(
        "/books/import",
        data={"book": (io.BytesIO(b"A durable selected passage."), "anchors.txt")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        book_id = db.session.scalar(db.select(Book.id))
    created = client.post(
        f"/reader/{book_id}/annotations",
        json={
            "start_offset": 2,
            "end_offset": 9,
            "selected_text": "durable",
            "note": "Remember this",
            "color": "green",
        },
    )
    assert created.status_code == 201
    annotation_id = created.get_json()["id"]
    page = client.get(f"/reader/{book_id}")
    assert b"Remember this" in page.data
    assert b'"start_offset": 2' in page.data
    updated = client.patch(
        f"/reader/{book_id}/annotations/{annotation_id}",
        json={"note": "Updated", "color": "blue"},
    )
    assert updated.get_json()["note"] == "Updated"
    assert client.delete(f"/reader/{book_id}/annotations/{annotation_id}").status_code == 204
    with app.app_context():
        assert db.session.get(Annotation, annotation_id) is None


def test_user_cannot_change_another_users_annotation(client, app):
    register(client, "owner", "owner@example.com")
    client.post(
        "/books/import",
        data={"book": (io.BytesIO(b"private note"), "private.txt")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        book_id = db.session.scalar(db.select(Book.id))
    created = client.post(
        f"/reader/{book_id}/annotations",
        json={"start_offset": 0, "end_offset": 7, "selected_text": "private"},
    )
    annotation_id = created.get_json()["id"]
    client.post("/auth/logout")
    register(client, "intruder", "intruder@example.com")
    url = f"/reader/{book_id}/annotations/{annotation_id}"
    assert client.patch(url, json={"note": "stolen"}).status_code == 404
    assert client.delete(url).status_code == 404


def test_vocabulary_capture_dashboard_edit_and_source_jump(client, app):
    register(client)
    client.post(
        "/books/import",
        data={"title": "Russian", "book": (io.BytesIO("Привет мир".encode()), "words.txt")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        book_id = db.session.scalar(db.select(Book.id))
    created = client.post(
        f"/reader/{book_id}/vocabulary",
        json={
            "start_offset": 0,
            "end_offset": 6,
            "term": "Привет",
            "language": "Russian",
            "definition": "Hello",
            "context": "Привет мир",
            "note": "Greeting",
        },
    )
    assert created.status_code == 201
    entry_id = created.get_json()["id"]
    dashboard = client.get("/vocabulary?q=Привет&language=Russian")
    assert "Привет".encode() in dashboard.data
    assert b"Hello" in dashboard.data
    updated = client.post(
        f"/vocabulary/{entry_id}/update",
        data={"language": "Russian", "definition": "Hi", "note": "Informal greeting"},
        follow_redirects=True,
    )
    assert b"Informal greeting" in updated.data
    source = client.get(f"/reader/{book_id}?vocabulary={entry_id}")
    assert b'data-jump-offset="0"' in source.data
    assert client.post(f"/vocabulary/{entry_id}/delete").status_code == 302
    with app.app_context():
        assert db.session.get(VocabularyEntry, entry_id) is None


def test_vocabulary_and_notes_dashboards_are_private(client, app):
    register(client, "collector", "collector@example.com")
    client.post(
        "/books/import",
        data={"book": (io.BytesIO(b"private word and note"), "study.txt")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        book_id = db.session.scalar(db.select(Book.id))
    vocab = client.post(
        f"/reader/{book_id}/vocabulary",
        json={"start_offset": 0, "end_offset": 7, "term": "private"},
    ).get_json()
    client.post(
        f"/reader/{book_id}/annotations",
        json={"start_offset": 17, "end_offset": 21, "selected_text": "note", "note": "secret"},
    )
    client.post("/auth/logout")
    register(client, "visitor", "visitor@example.com")
    assert b"private" not in client.get("/vocabulary").data
    assert b"secret" not in client.get("/notes").data
    assert client.post(f"/vocabulary/{vocab['id']}/delete").status_code == 404


def test_reader_preferences_are_saved_per_user(client, app):
    register(client)
    response = client.post(
        "/reader/preferences",
        json={
            "theme": "dark",
            "font_family": "sans",
            "font_size": 22,
            "line_height": 200,
            "column_width": 840,
        },
    )
    assert response.status_code == 200
    assert response.get_json()["theme"] == "dark"
    with app.app_context():
        preference = db.session.scalar(db.select(ReaderPreference))
        assert preference.font_size == 22


def test_markdown_and_multilingual_text_chapters_create_contents(client):
    register(client)
    markdown_response = client.post(
        "/books/import",
        data={"book": (io.BytesIO(b"# Beginning\n\n## Second Part\n"), "chapters.md")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b'href="#beginning"' in markdown_response.data
    assert b'href="#second-part"' in markdown_response.data
    text_response = client.post(
        "/books/import",
        data={"book": (io.BytesIO("第一章 开端\n内容\nГлава 2\nТекст".encode()), "chapters.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b'href="#chapter-1"' in text_response.data
    assert b'href="#chapter-2"' in text_response.data


def test_duplicate_detection_edit_and_safe_delete(client, app):
    register(client)
    payload = b"same book content"
    client.post(
        "/books/import",
        data={"title": "Original", "book": (io.BytesIO(payload), "same.txt")},
        content_type="multipart/form-data",
    )
    duplicate = client.post(
        "/books/import",
        data={"title": "Copy", "book": (io.BytesIO(payload), "same.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"already exists" in duplicate.data
    with app.app_context():
        assert len(db.session.scalars(db.select(Book)).all()) == 1
        book = db.session.scalar(db.select(Book))
        book_id, stored_filename = book.id, book.stored_filename
    edited = client.post(
        f"/books/{book_id}/edit",
        data={"title": "Renamed", "author": "Author", "language": "English"},
        follow_redirects=True,
    )
    assert b"Renamed" in edited.data
    deleted = client.post(f"/books/{book_id}/delete", follow_redirects=True)
    assert b"Deleted" in deleted.data
    with app.app_context():
        assert db.session.get(Book, book_id) is None
    assert not (Path(app.config["BOOK_UPLOAD_FOLDER"]) / stored_filename).exists()


def test_exports_and_backup_are_user_isolated(client, app):
    register(client, "firstexport", "firstexport@example.com")
    client.post(
        "/books/import",
        data={"title": "First Book", "book": (io.BytesIO("你好".encode()), "first.txt")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        first_book_id = db.session.scalar(db.select(Book.id))
    client.post(
        f"/reader/{first_book_id}/vocabulary",
        json={"start_offset": 0, "end_offset": 2, "term": "你好", "definition": "hello"},
    )
    client.post("/auth/logout")
    register(client, "secondexport", "secondexport@example.com")
    client.post(
        "/books/import",
        data={"title": "Second Book", "book": (io.BytesIO(b"second"), "second.txt")},
        content_type="multipart/form-data",
    )
    csv_response = client.get("/exports/vocabulary.csv")
    assert "你好".encode() not in csv_response.data
    backup = client.get("/exports/backup.zip")
    with zipfile.ZipFile(io.BytesIO(backup.data)) as archive:
        names = archive.namelist()
        assert any(name.endswith("second.txt") for name in names)
        assert not any(name.endswith("first.txt") for name in names)
        with archive.open("library.sqlite3") as source:
            backup_db = io.BytesIO(source.read())
    temporary_path = Path(app.config["BOOK_UPLOAD_FOLDER"]) / "backup-check.sqlite3"
    with temporary_path.open("wb") as destination:
        destination.write(backup_db.getvalue())
    connection = sqlite3.connect(temporary_path)
    assert connection.execute("SELECT title FROM book").fetchall() == [("Second Book",)]
    connection.close()


def test_book_management_is_private(client, app):
    register(client, "bookowner", "bookowner@example.com")
    client.post(
        "/books/import",
        data={"book": (io.BytesIO(b"owned"), "owned.txt")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        book_id = db.session.scalar(db.select(Book.id))
    client.post("/auth/logout")
    register(client, "notowner", "notowner@example.com")
    assert client.get(f"/books/{book_id}/edit").status_code == 404
    assert client.post(f"/books/{book_id}/delete").status_code == 404
    assert client.get(f"/exports/books/{book_id}.md").status_code == 404


def test_epub_import_navigation_assets_and_chapter_anchors(client, app):
    register(client)
    response = client.post(
        "/books/import",
        data={"book": (io.BytesIO(make_epub()), "multilingual.epub")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "多语言 EPUB".encode() in response.data
    assert "你好 EPUB".encode() in response.data
    assert b"Start from navigation" in response.data
    assert b"<script>" not in response.data
    with app.app_context():
        book = db.session.scalar(db.select(Book))
        chapters = db.session.scalars(
            db.select(BookChapter).where(BookChapter.book_id == book.id).order_by(BookChapter.ordinal)
        ).all()
        book_id, first_id, second_id = book.id, chapters[0].id, chapters[1].id
    asset = client.get(f"/reader/{book_id}/assets/OPS/images/pixel.png")
    assert asset.status_code == 200
    assert asset.data.startswith(b"\x89PNG")
    second = client.get(f"/reader/{book_id}?chapter=2")
    assert "Привет EPUB".encode() in second.data
    assert f'data-chapter-id="{second_id}"'.encode() in second.data
    progress = client.post(
        f"/reader/{book_id}/progress", json={"progress": 0.4, "chapter_id": second_id}
    )
    assert progress.status_code == 200
    annotation = client.post(
        f"/reader/{book_id}/annotations",
        json={
            "chapter_id": second_id,
            "start_offset": 0,
            "end_offset": 5,
            "selected_text": "Глава",
        },
    ).get_json()
    source = client.get(f"/reader/{book_id}?annotation={annotation['id']}")
    assert f'data-chapter-id="{second_id}"'.encode() in source.data
    assert f'data-chapter-id="{first_id}"'.encode() not in source.data


def test_unsafe_and_encrypted_epubs_are_rejected(client, app):
    register(client)
    for content in (make_epub(unsafe_member=True), make_epub(encrypted=True)):
        response = client.post(
            "/books/import",
            data={"book": (io.BytesIO(content), "unsafe.epub")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"unsafe archive path" in response.data or b"Encrypted" in response.data
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Book.id))) == 0


def test_epub_assets_are_private(client, app):
    register(client, "epubowner", "epubowner@example.com")
    client.post(
        "/books/import",
        data={"book": (io.BytesIO(make_epub()), "private.epub")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        book_id = db.session.scalar(db.select(Book.id))
    client.post("/auth/logout")
    register(client, "epubvisitor", "epubvisitor@example.com")
    assert client.get(f"/reader/{book_id}/assets/OPS/images/pixel.png").status_code == 404


def test_backup_restore_reassigns_ownership_and_skips_duplicates(client, app):
    register(client, "backupsource", "backupsource@example.com")
    client.post(
        "/books/import",
        data={"title": "Restorable", "book": (io.BytesIO("restore 中文".encode()), "restore.txt")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        original_book = db.session.scalar(db.select(Book))
        original_id, original_user_id = original_book.id, original_book.user_id
    client.post(
        f"/reader/{original_id}/annotations",
        json={"start_offset": 0, "end_offset": 7, "selected_text": "restore", "note": "kept"},
    )
    backup = client.get("/exports/backup.zip").data
    client.post("/auth/logout")
    register(client, "backupdestination", "backupdestination@example.com")
    preview = client.post(
        "/restore",
        data={"backup": (io.BytesIO(backup), "reader-backup.zip")},
        content_type="multipart/form-data",
    )
    assert b"Restore preview" in preview.data
    assert b"Restorable" in preview.data
    with client.session_transaction() as browser_session:
        token = browser_session["restore_token"]
    restored = client.post("/restore/apply", data={"token": token}, follow_redirects=True)
    assert b"Restored 1 books" in restored.data
    with app.app_context():
        restored_book = db.session.scalar(
            db.select(Book).where(Book.user_id != original_user_id)
        )
        assert restored_book.id != original_id
        assert restored_book.annotations[0].note == "kept"

    duplicate_preview = client.post(
        "/restore",
        data={"backup": (io.BytesIO(backup), "reader-backup.zip")},
        content_type="multipart/form-data",
    )
    assert b"will skip" in duplicate_preview.data
    with client.session_transaction() as browser_session:
        duplicate_token = browser_session["restore_token"]
    duplicate = client.post(
        "/restore/apply", data={"token": duplicate_token}, follow_redirects=True
    )
    assert b"skipped 1 duplicates" in duplicate.data


def test_epub_backup_restores_chapters_and_assets(client, app):
    register(client, "epubsource", "epubsource@example.com")
    client.post(
        "/books/import",
        data={"book": (io.BytesIO(make_epub()), "source.epub")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        source_book_id = db.session.scalar(db.select(Book.id))
    backup = client.get("/exports/backup.zip").data
    client.post("/auth/logout")
    register(client, "epubrestore", "epubrestore@example.com")
    client.post(
        "/restore",
        data={"backup": (io.BytesIO(backup), "epub-backup.zip")},
        content_type="multipart/form-data",
    )
    with client.session_transaction() as browser_session:
        token = browser_session["restore_token"]
    client.post("/restore/apply", data={"token": token})
    with app.app_context():
        restored_book = db.session.scalar(
            db.select(Book).where(Book.id != source_book_id, Book.file_type == "epub")
        )
        restored_id = restored_book.id
        assert len(restored_book.chapters) == 2
    assert client.get(f"/reader/{restored_id}?chapter=2").status_code == 200
    assert client.get(f"/reader/{restored_id}/assets/OPS/images/pixel.png").status_code == 200


def test_restore_rejects_unsafe_archive_and_incomplete_schema(client):
    register(client)
    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../manifest.json", '{"format": 1}')
    response = client.post(
        "/restore",
        data={"backup": (io.BytesIO(unsafe.getvalue()), "unsafe.zip")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"unsafe archive path" in response.data

    connection = sqlite3.connect(":memory:")
    incomplete_database = connection.serialize()
    connection.close()
    incomplete = io.BytesIO()
    with zipfile.ZipFile(incomplete, "w") as archive:
        archive.writestr("manifest.json", '{"format": 1}')
        archive.writestr("library.sqlite3", incomplete_database)
    response = client.post(
        "/restore",
        data={"backup": (io.BytesIO(incomplete.getvalue()), "incomplete.zip")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"schema is incomplete" in response.data


def test_restore_rolls_back_records_and_files_on_hash_failure(client, app):
    register(client, "rollbacksource", "rollbacksource@example.com")
    for title, content in (("First", b"valid first"), ("Second", b"valid second")):
        client.post(
            "/books/import",
            data={"title": title, "book": (io.BytesIO(content), f"{title}.txt")},
            content_type="multipart/form-data",
        )
    original = client.get("/exports/backup.zip").data
    tampered = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(tampered, "w") as target:
        book_members = sorted(name for name in source.namelist() if name.startswith("books/"))
        for item in source.infolist():
            data = b"tampered" if item.filename == book_members[-1] else source.read(item.filename)
            target.writestr(item, data)
    client.post("/auth/logout")
    register(client, "rollbacktarget", "rollbacktarget@example.com")
    client.post(
        "/restore",
        data={"backup": (io.BytesIO(tampered.getvalue()), "tampered.zip")},
        content_type="multipart/form-data",
    )
    with client.session_transaction() as browser_session:
        token = browser_session["restore_token"]
    before_files = set(Path(app.config["BOOK_UPLOAD_FOLDER"]).glob("*.txt"))
    response = client.post("/restore/apply", data={"token": token}, follow_redirects=True)
    assert b"Nothing was restored" in response.data
    with app.app_context():
        target_books = db.session.scalars(
            db.select(Book).where(Book.user_id == 2)
        ).all()
        assert target_books == []
    assert set(Path(app.config["BOOK_UPLOAD_FOLDER"]).glob("*.txt")) == before_files


def test_production_requires_secret_key(monkeypatch):
    from reader_app import create_app

    monkeypatch.setenv("READER_ENV", "production")
    monkeypatch.delenv("READER_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="READER_SECRET_KEY"):
        create_app()


def test_production_cookie_and_host_security(monkeypatch, tmp_path):
    from reader_app import create_app

    monkeypatch.setenv("READER_ENV", "production")
    monkeypatch.setenv("READER_SECRET_KEY", "a-production-secret-with-sufficient-entropy")
    monkeypatch.setenv("READER_TRUSTED_HOSTS", "reader.example.com,localhost")
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "BOOK_UPLOAD_FOLDER": str(tmp_path / "books"),
        }
    )
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["TRUSTED_HOSTS"] == ["reader.example.com", "localhost"]


def test_safe_error_pages(client):
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert b"Page not found" in response.data
    assert b"Traceback" not in response.data
