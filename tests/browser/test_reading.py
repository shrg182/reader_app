import io
import os
import struct
import threading
import zipfile
import zlib
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from reader_app import create_app
from reader_app.cli import prepare_database
from tests.test_app import make_epub


@pytest.fixture()
def live_url(tmp_path):
    app = create_app({
        'SECRET_KEY': 'browser-tests-only',
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{tmp_path / "browser.sqlite3"}',
        'BOOK_UPLOAD_FOLDER': str(tmp_path / 'books'),
    })
    prepare_database(app)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    thread.join()


@pytest.fixture(params=['desktop', 'mobile'])
def browser_page(request, live_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        channel = os.environ.get('READER_TEST_BROWSER_CHANNEL')
        browser = playwright.chromium.launch(channel=channel)
        mobile = request.param == 'mobile'
        context = browser.new_context(
            viewport={'width': 390 if mobile else 1440, 'height': 844 if mobile else 1000},
            is_mobile=mobile, has_touch=mobile,
        )
        errors = []
        context.on('page', lambda page: page.on('pageerror',
                                               lambda error: errors.append(str(error))))
        page = context.new_page()
        page.goto(f'{live_url}/auth/register')
        page.locator('[name=username]').fill('browserreader')
        page.locator('[name=email]').fill('browser@example.com')
        page.locator('[name=password]').fill('test-password-123')
        page.locator('button[type=submit]').click()
        page.wait_for_url(live_url + '/')
        yield page, mobile
        assert errors == []
        context.close()
        browser.close()


def import_book(page, name, content):
    page.get_by_role('link', name='Import book').click()
    page.locator('[name=book]').set_input_files({'name': name, 'mimeType':
                                              'application/octet-stream', 'buffer': content})
    page.get_by_role('button', name='Import and read').click()
    page.wait_for_selector('#prose')
    page.wait_for_function('window.ReaderProgressQueue !== undefined')


def open_editor(page, mobile):
    if mobile:
        page.locator('#selectionAction').click()
    page.locator('#newNote').fill('A multilingual note')
    screenshot = os.environ.get('READER_TEST_SCREENSHOTS')
    if screenshot:
        Path(screenshot).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f'{screenshot}/{"mobile" if mobile else "desktop"}-editor.png')
    page.locator('#saveAnnotation').click()


def test_selection_overlap_and_reopen(browser_page):
    from playwright.sync_api import expect

    page, mobile = browser_page
    import_book(page, '阅读.md', '# 第一章\n\nHello 中文 Привет.\n\nSecond paragraph 第二段.\n'.encode())
    original = page.locator('#prose').text_content()
    # Real keyboard selection: no mouseup event is emitted.
    page.locator('#prose').focus()
    page.keyboard.press('Control+Home')
    page.evaluate('''() => {
      const selection = getSelection();
      selection.collapse(document.querySelector('#prose p').firstChild, 0);
    }''')
    page.keyboard.down('Shift')
    for _ in range(5):
        page.keyboard.press('ArrowRight')
    page.keyboard.up('Shift')
    expect(page.locator('#selectionPreview')).to_contain_text('Hello')
    open_editor(page, mobile)
    expect(page.locator('.annotation-item')).to_have_count(1)
    # selectionchange also captures touch-handle changes and cross-block selections.
    page.evaluate('''() => {
      const prose = document.querySelector('#prose');
      const ps = prose.querySelectorAll('p');
      const r = document.createRange();
      r.setStart(ps[0], 0); r.setEnd(ps[1].firstChild, 6);
      getSelection().removeAllRanges(); getSelection().addRange(r);
    }''')
    expect(page.locator('#selectionPreview')).to_contain_text('Second')
    open_editor(page, mobile)
    expect(page.locator('.annotation-item')).to_have_count(2)
    assert page.locator('#prose').text_content() == original
    expect(page.locator('#prose p')).to_have_count(2)
    page.reload()
    expect(page.locator('.annotation-item')).to_have_count(2)
    assert page.locator('#prose').text_content() == original
    page.locator('.annotation-item [data-action=delete]').first.click()
    expect(page.locator('.annotation-item')).to_have_count(1)
    assert page.locator('#prose').text_content() == original
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    screenshot = os.environ.get('READER_TEST_SCREENSHOTS')
    if screenshot:
        page.evaluate('scrollTo(0, 0)')
        page.screenshot(path=f'{screenshot}/{"mobile" if mobile else "desktop"}-reader.png')


def test_offline_position_survives_page_close(browser_page):
    from playwright.sync_api import expect

    page, _mobile = browser_page
    import_book(page, 'Война.txt', ('Hello 中文 Привет\n' * 500).encode())
    page.route('**/progress', lambda route: route.abort())
    page.evaluate('scrollTo(0, document.documentElement.scrollHeight * .55)')
    page.wait_for_function('Object.keys(localStorage).some(k => k.startsWith("reader-position:"))')
    record = page.evaluate('JSON.parse(localStorage.getItem(Object.keys(localStorage)[0]))')
    url = page.url
    context = page.context
    page.close()
    reopened = context.new_page()
    reopened.goto(url)
    expect(reopened.locator('#progressSaveStatus')).to_have_text('Position synced')
    response = reopened.request.get(url)
    assert f'data-progress="{record["progress"]}"' in response.text()
    reopened.close()


def test_epub_chapter_navigation(browser_page):
    from playwright.sync_api import expect

    page, _mobile = browser_page
    import_book(page, '多语言.epub', make_epub())
    expect(page.locator('#prose')).to_contain_text('你好 EPUB')
    page.locator('.chapter-navigation a').filter(has_text='Next').first.click()
    expect(page.locator('#prose')).to_contain_text('Привет EPUB')
    page.locator('#prose').focus()
    page.keyboard.press('End')
    page.evaluate('scrollTo(0, document.documentElement.scrollHeight)')
    expect(page.locator('#progressSaveStatus')).to_have_text('Position synced')
    page.reload()
    expect(page.locator('#prose')).to_contain_text('Привет EPUB')
    expect(page.locator('#progressLabel')).to_have_text('100% read')


def test_image_epub_restores_after_images_load(browser_page):
    from playwright.sync_api import expect

    page, _mobile = browser_page

    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data
                + struct.pack('>I', zlib.crc32(kind + data)))

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', 320, 240, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress((b'\x00' + b'\x80\xa0\xc0' * 320) * 240))
           + chunk(b'IEND', b''))
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(make_epub())) as source, zipfile.ZipFile(output, 'w') as target:
        for name in source.namelist():
            data = source.read(name)
            if name.endswith('pixel.png'):
                data = png
            if name.endswith('one.xhtml'):
                data = data.replace(b'</body>', (b'<p>Hello \xe4\xb8\xad\xe6\x96\x87</p>'
                                                b'<img src="images/pixel.png"/>' * 30) + b'</body>')
            target.writestr(name, data)
    import_book(page, 'Images.epub', output.getvalue())
    page.wait_for_function('Array.from(document.querySelectorAll("#prose img"))'
                           '.every(img => img.complete && img.naturalWidth === 320)')
    page.evaluate('scrollTo(0, document.documentElement.scrollHeight * .5)')
    expect(page.locator('#progressSaveStatus')).to_have_text('Position synced')
    before = page.evaluate('scrollY')
    page.reload(wait_until='load')
    page.wait_for_function('(before) => Math.abs(scrollY - before) < 8', arg=before)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
