# Using Reader App

Reader App lets you keep a personal library of TXT, Markdown, and EPUB books,
resume reading, highlight passages, write notes, and collect vocabulary. It
supports multilingual text and filenames, including English, Chinese, and Russian.

## 1. Start the app

If someone has already hosted Reader for you, open their Reader address in your
browser and continue to [Create an account](#2-create-an-account).

### First-time local setup

You need Python 3.11 or newer. Open a terminal in the `reader_app` project folder.
On macOS or Linux, run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
reader-app
```

Open **http://127.0.0.1:5000** in your browser. Keep the terminal running while
you use the app. The startup command prepares or upgrades the database.

### Start it again later

From the same project folder:

```bash
source .venv/bin/activate
reader-app
```

Press **Ctrl+C** in the terminal to stop the server. Your saved library remains
available when you restart it.

If port 5000 is already occupied, use another port:

```bash
reader-app --port 8000
```

Then open **http://127.0.0.1:8000**. Use a consistent address and port for everyday
reading: pending positions in browser storage belong to that particular address.

The default address is accessible only on the computer running Reader. On a
phone, use the address of a hosted installation; `127.0.0.1` on the phone does
not point to your computer. Hosting requires additional server configuration;
see [README.md](README.md). The built-in server is intended for local development.

## 2. Create an account

1. On the login page, choose **Create an account**.
2. Enter a unique username of at least two characters, your email, and a password
   of at least eight characters.
3. Select **Register** to open your library.

On later visits, log in with your username or email and password. Each account
has its own books, study records, and appearance settings. Use **Log out** in the
top navigation when finished on a shared browser.

There is currently no self-service password reset screen.

## 3. Import a book

1. Open **Library** and select **Import book**.
2. Choose a file under **Book file**.
3. Optionally enter its **Title**, **Author**, and **Language**.
4. Select **Import and read**.

| Format | Preparation and behavior |
| --- | --- |
| TXT (`.txt`) | Save the text as UTF-8. Recognized chapter headings can generate a contents list. |
| Markdown (`.md`, `.markdown`) | Save as UTF-8. Headings generate contents navigation; supported formatting is rendered safely. |
| EPUB (`.epub`) | Use an unencrypted EPUB. Reader uses its metadata, chapter order, and supported images. |

Each book may be up to **10 MB**. EPUBs also have an expanded-size safety limit
of **50 MB**. PDF and DRM-protected or encrypted EPUB files are not supported.
EPUB presentation is simplified, so it may differ from the publisher's layout.

When you leave the title blank, Reader uses the filename for text/Markdown or
the EPUB's title metadata. EPUB author and language metadata are used when those
fields are left blank.

If the same file is already in your library, Reader displays a duplicate message.
To deliberately import another copy, reselect the file, check **Import another
copy intentionally**, and submit again. Each copy has separate study records.

## 4. Find and manage books

The library shows each book's reading percentage, highlight count, and vocabulary
count. Use **Search by title** to find a book. Choose **Recent activity**, **Title**,
**Author**, or **Progress**, then press **Search** to apply the sorting.

- **Continue reading →** opens the book at its saved position.
- **Manage** opens the book's metadata and export controls.
- Edit the title, author, or language and select **Save details** to update them.
- **Delete book** asks for confirmation and permanently removes the book and its
  progress, highlights, notes, and vocabulary. There is no trash or undo screen;
  create a backup first if you may need to recover it.

## 5. Read and adjust the view

Scroll through the text normally. Open **Contents** to jump to a recognized
heading or EPUB chapter. EPUBs also provide **Previous** and **Next** links.

Open **Appearance** to change:

- **Theme:** Light, Sepia, or Dark.
- **Font:** Serif or Sans serif.
- **Text size**, **Line spacing**, and **Column width**.

Appearance changes take effect immediately and are saved to your account while
connected. Narrow screens adapt the layout to the available width.

### Reading position and sync

Reading position saves automatically. The status beside the progress indicator
explains where the latest position is stored:

| Status | Meaning |
| --- | --- |
| **Position saved on this device; waiting to sync** | The position is in this browser's storage and is waiting to reach the server. |
| **Position synced** | The server has saved the position. |
| **Position not synced. Retrying…** | A request failed; Reader will retry. |
| **Device storage unavailable; keep this page open until synced** | The browser could not retain a local copy. Wait for server sync before closing. |

Pending positions survive closing a tab when browser storage is available. Reopen
the same book using the same browser, site address, and account to resume and
retry syncing. Clearing site data removes unsynced positions. Wait for **Position
synced** before moving to another device or making a backup of your latest progress.

Books still require a connection to the running Reader server to open. Local
position storage does not provide full offline reading, and it does not queue
unsaved notes or vocabulary.

For EPUBs, the overall percentage gives each chapter equal weight. It is an
estimate rather than an exact count of words or pages read. The position within
the current chapter is saved separately for reopening.

## 6. Highlight passages and write notes

1. Select text in the book:
   - **Mouse:** drag across the passage.
   - **Touch:** long-press text and adjust the selection handles.
   - **Keyboard:** focus the book text with Tab, then extend a selection with
     **Shift+Arrow** keys.
2. On a wide screen, use the editor in **Highlights & notes**. On a smaller screen,
   select **Add note or word** to open the editor over the reading view.
3. Choose a **Color**: Yellow, Green, Blue, or Pink.
4. Optionally enter a **Note**.
5. Select **Highlight**.

The highlight appears in the text and in the book's annotation list. Selections
may cross paragraphs or overlap earlier highlights. A highlight can cover up to
5,000 characters.

To change an existing annotation, edit its color or note in the annotation list
and select **Save**. Select **Delete** on that annotation to remove it. On smaller
screens, existing annotations appear below the reading area.

Use **Cancel**, or press **Escape** while focused in the new-annotation editor,
to dismiss an unfinished selection.

### Review notes across books

Choose **Notes** in the top navigation. Search highlighted text and notes, filter
by book or color, and press **Filter**. **Open source →** returns to the passage
in its book. To edit an annotation, open its source and use the reader's annotation
list; the Notes dashboard is for browsing and searching.

## 7. Collect and review vocabulary

1. Select a word or phrase while reading, using the same selection controls.
2. Open the editor if needed with **Add note or word**.
3. Optionally fill in **Language**, **Definition**, and **Note**.
4. Select **Save vocabulary**.

Reader captures the selected phrase and surrounding text as context. Definitions
are entered manually; there is no automatic dictionary lookup. A vocabulary
selection can contain up to 500 characters.

**Highlight** and **Save vocabulary** are separate actions. If you want both for
the same passage, save one, then select the passage again and save the other.

Choose **Vocabulary** in the top navigation to review your collection. Search
terms, definitions, or notes; filter by book or language; then select **Filter**.
Edit an entry's language, definition, or personal note and select **Save changes**.
Use **Open source →** to revisit its passage, or **Delete** to remove the entry.

## 8. Export study material

| What you want | Where to download it |
| --- | --- |
| All vocabulary as CSV | **Vocabulary → Export CSV** |
| All books' highlights, notes, and vocabulary as Markdown | **Notes → Export Markdown** |
| One book's highlights, notes, and vocabulary as Markdown | **Library → Manage → Download notes and vocabulary as Markdown** |

Exports include your account's data. Dashboard search and filter selections do
not restrict the all-books exports. CSV can be opened in spreadsheet software;
Markdown can be opened in a text editor or Markdown reader.

These study exports are for reading or reuse elsewhere. To restore a library into
Reader, use a **Backup** ZIP instead.

## 9. Back up and restore your library

### Download a backup

Select **Backup** in the top navigation. Your browser downloads
`reader-personal-backup.zip`, containing your books, study records, reading
positions, and saved reader preferences. Store this file somewhere you can find
it again. Passwords are not included.

Backups contain server-saved data. Save any annotation or vocabulary edits and
wait for reading-position sync before downloading one.

### Restore a backup

1. Log in to the account that should receive the books.
2. Select **Restore** in the top navigation.
3. Choose the Reader backup ZIP and select **Validate and preview**.
4. Review the book list and any **Already present — will skip** labels.
5. Select **Restore into my library** and confirm, or choose **Cancel**.

The restore adds books to your current account; it does not switch accounts or
replace your login. Existing books are retained. Matching book files are skipped,
including their backed-up study records: restore does **not** merge newer notes
into a book already present in your library. Existing appearance preferences are
kept; backup preferences are applied only if your account has none saved.

Restore accepts ZIP uploads up to **100 MB**, with up to **250 MB** of expanded
contents. Exporting a very large library can produce a backup beyond these restore
limits. A failed restore rolls back the attempted changes rather than leaving a
partially restored library.

## 10. Troubleshooting

| Problem | What to try |
| --- | --- |
| The page will not open | Make sure `reader-app` is still running and the browser address matches its port. |
| `reader-app` is not found | Activate `.venv` from the project folder and run `python -m pip install -e .` if needed. |
| Text contains replacement characters | Convert the original TXT/Markdown file to UTF-8 and import it again. |
| An EPUB is rejected | Check its size and that it is an unencrypted, valid EPUB. Not every EPUB variation is supported. |
| A text book has no contents list | Use Markdown headings such as `# Chapter 1`, or recognizable TXT headings such as `Chapter 1`, `第一章`, or `Глава 1`. |
| No annotation editor appears on a phone | Select actual book text, then tap **Add note or word**. |
| Progress will not sync | Check the connection to the server. If your session expired, log in again and reopen the book in the same browser. |
| A save reports an error | Keep the editor open, restore the connection or session, and save again. Notes and vocabulary are not saved merely by typing. |
| A restore preview has expired | Upload the ZIP again and review the new preview before confirming. |

### Where local data lives

With the editable setup above, this project uses **`src/instance/`** for runtime
data, including `reader.sqlite3` and the `books/` directory. Other installation
methods or custom configuration can use a different location. Stopping the server
does not delete these files; deleting them can remove your library. Use the app's
backup and restore controls to move your personal library.

For development checks and hosting configuration, see [README.md](README.md).
