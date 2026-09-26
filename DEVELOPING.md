# Developing bookshelf

How the shelf is built, and why. What it does, and which key does what, is in
[README.md](README.md).

## Layout

Nineteen files and 3,361 lines. Two views of one data layer -- the terminal app and the
web front end -- and nothing below them knows either exists.

```
bookshelf_tui.py         the app: modes, reload, keys          548
        │
        ├── bookshelf_screens.py     the dialogs and the trees             861
        ├── bookshelf_web.py         the shelf over HTTP, GET only         511
        ├── bookshelf_reading.py     the document as a model, and the      274
        │                            cursor over it
        ├── bookshelf_html.py        HTML read as Markdown                 220
        ├── bookshelf_main.py        the `bookshelf` command               51
        │
        ├── bookshelf_repo.py        the verbs, the re-walk, the           368
        │                            ingest
        ├── bookshelf_scan.py        the kinds, the modes, how a           95
        │                            row is named
        ├── bookshelf_tree.py        the shape a tree view needs           48
        │
        └── bookshelf_db.py          connections and revisions,            73
        │                            one of which cannot write
        │
        bookshelf_schema.sql     the contract, revision 1              33
        bookshelf_schema_v2.sql  the code kinds                        39
        bookshelf_schema_v3.sql  the html kind                         36
        bookshelf_schema_v4.sql  end of the pdf rows                   16
        bookshelf_schema_v5.sql  the documents themselves              38
        bookshelf_schema_v6.sql  a reader's annotations                38
        bookshelf_schema_v7.sql  a marked range is a highlight         39
        bookshelf.tcss           every rule the app draws with         34
        Dockerfile               the server, without a UI              39
                    │
                 shelf.db
```

```
│ repo holds no SQLite import   every function takes an open connection. The caller
│                               owns the transaction, so two writes commit together
│                               or neither does
│ repo holds no file policy     kinds and paths belong to scan -- one map per mode --
│                               and resolution and nesting belong to add_root. The one
│                               function in repo that reads the disk does it through
│                               scan, and it lives there so every front end re-walks
│                               the folders the same way
│ one choke point               connect() is the only place a connection is built,
│                               so row_factory and PRAGMA foreign_keys are set once
│                               and cannot be missed
│ the UI adds no SQL            the first version of the missing action is a function
│                               in bookshelf_repo, not a query in the TUI
│ screens hold no state         a screen is handed rows that are loaded, and dismisses
│                               with a value. bookshelf_tui is the only writer
│ the tree rules live once      directories before files, one entry per root, and
│                               when the root level is drawn all come from
│                               bookshelf_tree, which both renderers consume
│ Textual keeps a colour string as a string   `Style(background="#F0E2B8")` is not parsed, and
│                               combining it with the parsed styles a code fence already carries
│                               raises `Color + str` deep inside the renderer. Pass Color.parse
│                               and the style is fully parsed, which is what the highlight does
│ the note is a layer, not a line   the strip belongs to the preview screen and docks in a CSS
│                               layer of its own, so showing it costs nothing: measured with it
│                               hidden and shown, the viewer keeps its height, its scroll and
│                               its content size to the row. A note mounted into the document
│                               would take a row out of the page and shift everything below;
│                               writing the text into its line would move every character
│                               offset in the model, and the cursor with them
│ the composer saves on Enter   and leaves on Escape, not `q`: a text field belongs to its
│                               text, and a note beginning with "q" is unwritable if that
│                               letter also means leave. Measured, not assumed -- the first
│                               version ate the "q" and saved nothing
│ painting is incremental   a piece knows the styles it currently carries, and a paint writes
│                               only the pieces whose styles changed. Without that, one
│                               keystroke rewrote every piece in a 57 KB document -- 957
│                               content writes for a single `j` -- and Textual invalidates a
│                               widget's layout on every write, so each key paid for the whole
│                               document's layout. Now: 0 to 2 writes per key, and opening the
│                               document went from 957 writes to 1
│ what is left is Textual's   that same document is 246 Markdown blocks and 1,093 widgets to
│                               mount: about 1.5 s to open, and about 36 ms of event path per
│                               keypress before the app does anything. Two levers, if it comes
│                               to it: draw the cursor as a selection rather than rewriting
│                               content, or page the document so one section is mounted
│ the motions are arithmetic   every movement -- a character, a block, a word, the top, the
│                               middle, the end -- is a function over one string in
│                               bookshelf_reading, and the screen only binds keys to them. None
│                               of them need Textual, and all of them are tested without an app
│ the reading model is separate   a rendered document is a tree of widgets, and a tree is a
│                               poor place to keep a position. bookshelf_reading reads it once
│                               into blocks, pieces and one string, so every position after
│                               that is an offset -- the mark, the selection, what is stored.
│                               Drawing re-derives each piece from the text it had plus the
│                               styles asked for, which is what makes painting twice the same
│                               as painting once
│ one vocabulary for a row      the mode table, the row's name and its star mark live in
│                               bookshelf_scan, so the terminal and the browser cannot
│                               disagree about what a row is called or which colour its
│                               star is. The browser learned this the hard way: it had
│                               invented its own mark
```

## What it stores

Four tables: `bookshelf_schema.sql` for the first two, then one script per revision --
`v2` the code kinds, `v3` the html kind, `v4` the end of the pdf rows, `v5` the documents
themselves, `v6` what a reader says about them, `v7` the range a reader marks.

```
roots              one row per mounted folder. `path` is the only absolute path
                   in the schema
books              one row per file: root_id, relative path, title, kind,
                   star, added_at
content            one row per file that has been read: the text itself, its size,
                   and the size and mtime of the file it came from
annotation         one row per thing a reader says about a document: a mark, a
                   highlighted range, and later a note. kind, anchor, position,
                   span, note
```

| Column | Values |
|---|---|
| `kind` | `md`, `html`, `py`, `sql` (`pdf` is reserved: revision 3 admits it, nothing writes it) |
| `is_important` | `0` or `1` |

```
│ identity      a book is addressed by (root_id, path), never by title. Two files
│               may share a title; no two share a path
│ derived       title comes from the filename and the tree view comes from the
│               paths. Neither is stored
│ content       the body is the file verbatim, in its own table so `SELECT b.*` on
│               books stays cheap: one document is read at a time, and a vanished
│               file takes its body with it (ON DELETE CASCADE)
│ annotations are not content   a note survives a `u` because it is not in the file: the
│               folder is re-walked, `content` is rewritten, and `annotation` is untouched
│ one table, three features   a mark is a position, a highlighted range is a range, a note
│               is a range with words. `a` covers two of the three verbs on the same key: it
│               starts a range, and pressing it inside a range a reader already made removes
│               it -- pointing at your own mark means "not this", and no separate key was
│               worth adding for it `anchor` holds the text it is attached to, so it can be
│               found again after a re-render -- a row or an offset alone does not survive
│               an edit upstream
│ staleness     `source_size` and `source_mtime` are what make `u` cheap -- it reads
│               only the files that changed. A row with no body yet is read from
│               disk once by `i`, on the way through
│ revision      PRAGMA user_version holds the schema revision. bootstrap() applies
│               revision 1 to a fresh file and then migrates it like any other, so
│               there is one path through the code. A released revision is never
│               edited in place -- each one is its own script
```

Migrations are the exception: the database moves forward rather than being rebuilt.
`bookshelf_db.py` holds one script per revision, `bootstrap()` runs the missing ones in
order, and a fresh file gets revision 1 and is then migrated like any other, so there is
one path through the code. Revision 2 rebuilt `books` to widen a CHECK constraint, which
SQLite cannot ALTER — the procedure sqlite.org documents, with `books.id` copied so the
stars stayed attached to the same files.

## Appearance

The app draws itself in a light warm palette, registered as a Textual theme named
`parchment` in `bookshelf_tui.py`, and every rule it draws with is in `bookshelf.tcss`.
One sheet, loaded through `CSS_PATH`, rather than a `CSS` string on each of five screens:
the same selectors have to work for a ModalScreen stacked over the list, and the sheet is
where a colour is changed.

| Token | Colour | Where it lands |
|---|---|---|
| `background` | `#FDFAF1` | the screen, under everything |
| `surface` | `#FAF4E6` | the tree area, dialogs, code blocks, the preview |
| `panel` | `#F4EDD9` | header, footer, status bar |
| `foreground` | `#3D3A31` | text |
| `primary` | `#8A6A1B` | headings, tree guides, the footer's key names |
| `accent` | `#B8860B` | the filled star |

The empty ring is `#A89F85`. Rich's named `yellow` is not used anywhere: on pale cream
it is invisible, so both star styles are named by hex.

`surface`, not `background`, is the colour you actually see. Textual's Tree paints
itself `$surface` and tints it 5% toward `$foreground` (`textual/widgets/_tree.py`),
and the tree fills the screen. Changing `background` alone shifts nothing visible, and
lightening `surface` by 20% lightens the screen by less than 20%, because the tint is a
fixed 5% of the gap and so grows as the surface approaches white. The values above are
solved against the rendered result rather than against the tint itself.

| Rendered area | Colour |
|---|---|
| the tree, which is most of the screen | `#F0EADC` |
| header, footer, status bar | `#F4EDD9` |

### The code palette

Textual's stock palette is built for a dark UI: it draws operators bold, `self` italic
and function names underlined, and maps every token onto one of the theme's five accent
hues. On cream those hues land between 3.0:1 and 4.8:1 of the background, so the file
reads as noise rather than as code.

`CODE_STYLES` in `bookshelf_tui.py` names five literal colours instead, each measured
against `#FDFAF1`, and turns every text-style off.

| Token | Colour | Contrast |
|---|---|---|
| everything else — the bulk of a file | `#3D3A31` | 10.9:1 |
| keyword | `#8C3A24` | 7.3:1 |
| string, docstring | `#4E6425` | 6.3:1 |
| comment | `#6F6A5C` | 5.2:1 |
| number, decorator | `#8A6A1B` | 4.8:1 |

A token the table does not name is plain foreground. `CodeHighlight` deliberately does
not inherit Textual's `STYLES`: a map that kept them would keep the loud colours for
the tokens it still covered.

Tabs are expanded to eight columns before highlighting. Pygments tokenises
`text.expandtabs(tabsize)` while Textual styles the string it was handed, tabs and all,
so in a tab-indented file every character after the first tab takes the token belonging
eight columns later — a `#` mid-line turns brown, one identifier in three changes colour,
and a word gets a stray underline. Expanding first makes the tokenised text and the
styled text the same string.

`CodeFence` reaches fenced blocks inside a Markdown file as well: `Markdown` looks the
widget up in `Markdown.BLOCKS`, and the app swaps in its own before any file is opened.

## Two front ends, one data layer

Nothing below the two front ends knows either exists. The image that serves the web one has
no Textual in it, so a router that accidentally imported the UI would fail at import rather
than in production.
```

```
│ read-only by construction   every route is a GET, the connection is `mode=ro` so SQLite
│             itself refuses a write, and there is no POST anywhere. Mount, unmount, `u` and
│             the star stay in the terminal app, on the machine with the files
│ ids, not paths   a request names a row, never a file, so there is nothing to traverse
│ no path traversal is not a policy here, it is the absence of a feature
│ two renderings   a stored HTML document is served as the page it is -- its own design,
│             its own fonts -- with a viewport tag added, because iOS otherwise lays a
│             paper-shaped page out at 980px. Markdown and code are wrapped in this
│             server's own page, using the app's palette
│ the image installs two libraries   `markdown-it-py`, which is the renderer the terminal
│             app already uses through Textual, and `pygments` for code. Same engine, same
│             output: a document now reads the same on the phone and in the terminal
│ fallbacks kept   with neither installed, bookshelf_web still renders headings, fences,
│             lists, quotes, inline spans and pipe tables as monospace. That path is the
│             last resort, not the default -- one paragraph per source line was the reason
│             a phone page looked broken before those two lines went into the image
│ the container proves the split   the image has no Textual in it, so the import would fail
│             if the data layer had a UI dependency:
│             docker build -t bookshelf-web .
│             mkdir -p ~/shelf-sync && cp shelf.db ~/shelf-sync/
│             docker run --rm -p 127.0.0.1:8080:8080 -e BOOKSHELF_TOKEN=dev \
│               -v ~/shelf-sync:/data:ro bookshelf-web
│ the copy, never the original   the DB is copied in and mounted `:ro`; the Mac stays the
│             only writer, forever
│ freshness is a stamp, not a push   a page is rendered with the shelf's stamp -- rows,
│             documents, bytes, newest ingest -- and polls `/health` (or `/stamp/<id>`) for
│             the current one. Different stamp, a bar appears; the page never reloads
│             itself, because a reader halfway down a document loses their place. A push
│             (SSE) would be a long-lived connection per client and a thread to feed it,
│             which one reader does not justify
│ what the stamp cannot see   the server reads a copy. A change on the Mac is invisible
│             until the copy is synced -- one `cp`, or a timer, or serve the live file
│             directly, where no copy exists to keep in step
│ the star is the same mark in both   one glyph and two colours come from `star_mark` in
│             bookshelf_scan: filled dark gold for starred, an empty ring in muted warm grey
│             for not. The browser gets the colours as CSS variables injected from those
│             constants, so the two front ends cannot drift apart on what a row looks like
``````

## Verifying a change

The checks that caught the bugs worth catching, cheapest first:

```
python3 -m py_compile *.py                      syntax, always

# a migration, on a copy of the shelf rather than on the shelf
cp shelf.db /tmp/check.db && python3 -c "
import bookshelf_db as db, sqlite3
db.bootstrap('/tmp/check.db')
c = sqlite3.connect('/tmp/check.db')
print(c.execute('PRAGMA user_version').fetchone()[0],
      c.execute('SELECT count(*) FROM books').fetchone()[0])"

# ingest is idempotent: the second walk must read nothing
python3 -c "
import bookshelf_db as db, bookshelf_repo as repo
from bookshelf_scan import EVERY_KIND
with db.session('shelf.db') as conn:
    for root in repo.list_roots(conn):
        print(repo.sync_root(conn, root['id'], EVERY_KIND))   # added, removed, read, missing"

# the server, in the shape the phone sees it
python3 bookshelf_web.py --db /tmp/check.db --port 8080 &
curl -s localhost:8080/health | python3 -m json.tool
curl -s localhost:8080/ | grep -c 'class="dot'

# and inside the image that will run on a VPS: no Textual, no extra packages
docker build -t bookshelf-web . && docker run --rm --entrypoint python3 bookshelf-web \
  -c "import bookshelf_web, bookshelf_repo, bookshelf_tree, bookshelf_html"

# the read-only guarantee is a refusal, not a promise
python3 -c "
import bookshelf_db as db, sqlite3
try: db.connect_readonly('/tmp/check.db').execute('DELETE FROM books')
except sqlite3.OperationalError as e: print('refused:', e)"
```

The line counts in the layout tree are checked against the files rather than remembered,
and every one of them has matched since the tree was written.

## Deferred

```
│ search          an FTS5 index over `content.body` -- revision 6. It is the phone's best
│                 feature and the reason the text is stored at all, but the ingest has to be
│                 proven first
│ binary kinds    everything in KINDS is text today. A PDF or an image would want a BLOB,
│                 and Python's sqlite3 reads a BLOB whole into memory -- a decision to make
│                 with the file size in hand, not before
│ the pickers' Escape   the guards are `Enter` or the verb key, `q` to cancel; the two
│                 pickers still accept Escape as well. Unifying them is one binding
│ no CLI reader   `bookshelf_tree.plan` is consumed by a screen and a page; there is no
│                 `bookshelf list` and no second renderer to keep in step
