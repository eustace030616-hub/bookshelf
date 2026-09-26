# bookshelf

A terminal bookshelf over one or more folders of HTML and Markdown files — and, in
code mode, over Python and SQL.

A PDF is not indexed. A PDF is the format a document arrives in, not the format the shelf
reads: convert it to HTML first, and one document is one row instead of a row per
representation.

Nothing is moved, renamed or rewritten. A root is a folder the app watches; a
book is one file inside it. The database holds the shelf — the star — and the files
stay where they are.

```
python3 -m pip install textual
python3 bookshelf_main.py           # the app, on shelf.db next to the code
python3 bookshelf_main.py --db other.db
python3 bookshelf_main.py -h        # what it is and how to start it
```

Requires Python 3.13 and Textual 8. There is no `bookshelf` on your PATH until you
install or link one; the two commands above are the whole command line, and
`bookshelf_tui.py` also runs directly if you prefer the module.

## Keys

The list is the main screen. Every key below acts on the highlighted row.

| Key | Action |
|---|---|
| `j` / `k` | move down and up. Arrow keys do the same |
| `Enter` | open the file in the default application. On a folder, expand or collapse it |
| `i` | inspect in the app: Markdown as Markdown, code and HTML as what a terminal can draw |
| `m` | mount a folder — browse the disk and add it as a root |
| `n` | unmount a folder — pick a root and forget it |
| `t` | switch between book mode and code mode |
| `u` | update — re-walk every mounted folder and match the shelf to the disk |
| `f` | show or hide the star |
| `s` | star the highlighted book, or unstar it |
| `q` | quit |

`Escape` closes whatever screen is open.

## Modes

`t` switches the app between two modes, and the mode decides what the list shows and
what `n` is asked about.

| Mode | Shown in the tree |
|---|---|
| book (default) | `md` and `html` rows |
| code | `py` and `sql` rows |

What a folder *contributes* does not depend on the mode. Mounting records every file the
shelf can hold — `.md`, `.html`, `.py`, `.sql` — and `t` decides which of those you see.
One rule for what a folder is worth, so mounting in one mode and updating in the other
cannot disagree about what is on the shelf.

One database holds both libraries and they never mix on screen: the tree, the counts,
the unmount list and the status line only ever show the mode you are in. Switching
modes changes nothing on disk and nothing in the database — the other mode's rows stay
where they are, and come back when `t` does.

| Mode | File shown as | Why |
|---|---|---|
| book | `docker-guide` | the title, filename without its extension. A shelf is a reading list |
| code | `schema.sql` | the filename on disk. Two files in one folder may share a stem |

The difference is drawing only. `books.title` holds the stem in both modes, and the
name in the list is the only place the extension shows.

The mode is per process. The app starts in book mode every time.

## Roots

A root is a folder the app reads, registered by absolute path. Any number of
roots can be mounted; each book stores its path relative to its root, so moving
a folder means re-registering one root rather than rewriting every book.

Mounting walks the folder and records every file the shelf can hold under it, at any
depth — `.md`, `.html`, `.py`, `.sql` — whichever mode you are in. `t` is a view, not a
filter on what gets recorded.

| Key | In the folder picker |
|---|---|
| `j` / `k` | move |
| `Enter` | open a folder |
| `m` | mount the highlighted folder |
| `Escape` | cancel |

The picker opens at `~`, shows folders only, and hides dotfolders. A folder that is
already a root is marked `[already mounted]`.

`m` opens a guard naming the folder. `Escape` cancels; `Enter`, `y` and `m` accept.

The walk happens after the guard, not before it: saying yes puts the folder in the
database and the app indexes it on a worker thread, with `counting /path ...` in the
status line while it runs. Mounting is instant, the UI never blocks, and the tree fills
in when the count lands. `~/` takes about 36 seconds, which is what the status line is
for.

Two rules apply, and both live in `add_root`:

```
│ nesting      a root inside another root is refused, because the same file would
│              appear twice under two different relative paths
│ resolution   every path is resolved before it is stored or compared. On macOS
│              /tmp is a symlink to /private/tmp, so an unresolved path and its
│              resolved form are one folder that compares as two strings
```

## Unmounting

`n` lists the mounted roots that hold files of the current mode, with how many. A root
holding only the other mode's files is not listed. Choosing one asks for confirmation,
then deletes the root and its books from the database. A root is a folder, not a row per
mode: unmounting it forgets both modes' files, and the confirm says so when the folder
holds more of one than the other.

**The files on disk are never touched.** Unmounting forgets; it does not delete.
Mounting the folder again restores the books, without the star you had set.

## Staying in sync

Nothing watches the disk. The shelf is a snapshot of the last walk, so a file you add or
delete outside the app is invisible until something walks the root again. Two things do:

```
│ on start   every mounted folder is re-walked, in a worker, as soon as the app opens.
│            It scrolls nothing and says nothing unless it found something -- the tree
│            you see is already corrected by the time you look at it
│ `u`        the same walk, on demand. Always reports, including "update: no changes"
```

| What changed on disk | What `u` does |
|---|---|
| a file was added | a row is added, and title and kind are refreshed for every file |
| a file was deleted | its row is removed, so `i` cannot offer to read a file that is gone |
| a file was renamed | new path, new row; the old one goes |
| the whole folder moved or the drive is unplugged | **nothing is removed.** The root is reported as not on disk, and its rows are kept |

The last row is a deliberate refusal. Every file under a missing root looks deleted, and
forgetting a library because an external disk is not mounted is not a mistake worth being
able to make. `n` is how a root is forgotten.

The walk covers every kind the shelf can hold, not the mode you are in: the table keeps
both libraries, so a file is only gone when it is gone for all of them. That is why
mounting records all five extensions too — one rule for what a folder is worth, and `t`
only decides what you see.

## Star

`f` puts one mark in front of every book name.

| Row | Meaning |
|---|---|
| `○  docker-guide` | not starred |
| `●  docker-guide` | starred |

`○` is no and `●` in yellow is yes. `f` again and the mark is not drawn.

## Inspecting

`i` renders a text file in the app. Markdown is drawn as Markdown: headings, lists and
code, from the file on disk. A `.py` or `.sql` file is drawn as one highlighted code
block in the same viewer — the source is wrapped in a fence, so `# a comment` stays a
comment instead of turning into a heading. `j` and `k` scroll five rows, the arrow keys
scroll one. `Escape`, `q` or `i` closes it.

The fence is sized to the file: one backtick more than the longest backtick run inside
it, so a ``` in a Python docstring cannot end the block early.

`i` on an HTML file shows it in the app too. The markup is rewritten into Markdown first —
headings, paragraphs, lists, tables, fenced code — and that is what the viewer draws. There
is no layout engine and no stylesheet in a terminal, so what arrives is a document's
structure, not its design. `Enter` opens the same file in the browser when the design is
what you want to see; that is the only HTML renderer a cell grid can reach.

The rewrite is `bookshelf_html.py`: the standard library's HTML parser, one pass, offline,
nothing to install. It drops the stylesheet, the page furniture, anchors and image
contents, and keeps the shape. A code block keeps the language it declares, so a
`language-java` block is coloured exactly as a file of that language would be; a block that
declares nothing becomes `text`, which draws monochrome rather than letting a lexer guess at
a diagram.

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

## What it stores

Three tables: `bookshelf_schema.sql` for the first two, then one script per revision —
`v2` the code kinds, `v3` the html kind, `v4` the end of the pdf rows, `v5` the documents
themselves.

```
roots              one row per mounted folder. `path` is the only absolute path
                   in the schema
books              one row per file: root_id, relative path, title, kind,
                   star, added_at
content            one row per file that has been read: the text itself, its size,
                   and the size and mtime of the file it came from
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
│ staleness     `source_size` and `source_mtime` are what make `u` cheap -- it reads
│               only the files that changed. A row with no body yet is read from
│               disk once by `i`, on the way through
│ revision      PRAGMA user_version holds the schema revision. bootstrap() applies
│               revision 1 to a fresh file and then migrates it like any other, so
│               there is one path through the code. A released revision is never
│               edited in place -- each one is its own script
```

## How it is built

Fifteen files and 2,185 lines. Two views of one data layer -- the terminal app and the
web front end -- and nothing below them knows either exists.

```
bookshelf_tui.py        the app: modes, reload, keys            521 lines
        │
        ├── bookshelf_screens.py the dialogs and the trees      347
        │
        ├── bookshelf_web.py     the shelf over HTTP, GET only  367
        ├── bookshelf_html.py    HTML read as Markdown          220
        ├── bookshelf_main.py    the `bookshelf` command        51
        │
        ├── bookshelf_repo.py    the verbs, the re-walk, the    262
        │                        ingest
        ├── bookshelf_scan.py    the kinds, the modes, how a    79
        │                        row is named
        ├── bookshelf_tree.py    the shape a tree view needs    48
        │
        └── bookshelf_db.py      connections and revisions,     71
                    │            one of which cannot write
        bookshelf_schema.sql     the contract, revision 1       33
        bookshelf_schema_v2.sql  the code kinds                 39
        bookshelf_schema_v3.sql  the html kind                  36
        bookshelf_schema_v4.sql  end of the pdf rows            16
        bookshelf_schema_v5.sql  the documents themselves       38
        bookshelf.tcss           every rule the app draws with  25
        Dockerfile               the server, without a UI       32
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
```

## Command line

One command and one flag. There are no subcommands, because there is nothing to do
outside the app: the shelf is a terminal UI, and mounting is a key in it.

```
bookshelf                       open the shelf
bookshelf --db other.db         open another database
bookshelf -h                    what the app is and how to start it
```

```
$ bookshelf -h
usage: bookshelf [-h] [--db DB]

a terminal bookshelf over folders of HTML, Markdown, Python and SQL.

This is a TUI. Run `bookshelf` and the shelf opens:

  m  mount a folder        t  books <-> code
  i  preview a file        q  leave

The footer lists the keys for whatever has focus.
```

`-h` prints that and exits; it never imports Textual, so it answers instantly even
before the UI dependencies are installed.

## Over HTTP

The terminal app is for the machine with the folders. A phone needs something else, so the
same data layer is served read-only by a second front end:

```
python3 bookshelf_web.py --db shelf.db                     # localhost:8080, the index
python3 bookshelf_web.py --db shelf.db --token SECRET       # required off loopback
```

| Route | What it returns |
|---|---|
| `GET /` | the index, one mode at a time: `?mode=code` |
| `GET /doc/<id>` | one document: HTML as it was stored, Markdown and code rendered here |
| `GET /raw/<id>` | the stored text, exactly as it is |
| `GET /health` | counts, bytes, and when the shelf was last walked |

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
│ when markdown-it is missing   the fallback renderer at the bottom of bookshelf_web.py
│             covers headings, fences, lists, quotes and inline spans. A container with
│             nothing installed loses polish, not the route
│ the container proves the split   the image has no Textual in it, so the import would fail
│             if the data layer had a UI dependency:
│             docker build -t bookshelf-web .
│             mkdir -p ~/shelf-sync && cp shelf.db ~/shelf-sync/
│             docker run --rm -p 127.0.0.1:8080:8080 -e BOOKSHELF_TOKEN=dev \
│               -v ~/shelf-sync:/data:ro bookshelf-web
│ the copy, never the original   the DB is copied in and mounted `:ro`; the Mac stays the
│             only writer, forever
```


## What it does not do

```
│ folders as notes     a folder holding images but no .md is not a book, so it does
│                      not appear at all. notes/guides/how to make a good science
│                      reaserch/ is one of these
│ no watching          the shelf is a snapshot. It re-walks on start and on `u`, and it
│                      does not watch the disk, so a change made while the app is open
│                      shows up when you ask for it
│ no index generation  the plan was a generated JSON summary per book, stored in a
│                      table. Not built
```

Migrations are the exception: the database moves forward rather than being rebuilt.
`bookshelf_db.py` holds one script per revision, `bootstrap()` runs the missing ones in
order, and a fresh file gets revision 1 and is then migrated like any other, so there is
one path through the code. Revision 2 rebuilt `books` to widen a CHECK constraint, which
SQLite cannot ALTER — the procedure sqlite.org documents, with `books.id` copied so the
stars stayed attached to the same files.
