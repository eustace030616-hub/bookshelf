# bookshelf

A terminal bookshelf over one or more folders of PDF and Markdown files — and, in
code mode, over Python and SQL.

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
| `i` | inspect. Markdown and code render in the app; a PDF opens in Quick Look |
| `m` | mount a folder — browse the disk and add it as a root |
| `n` | unmount a folder — pick a root and forget it |
| `t` | switch between book mode and code mode |
| `f` | show or hide the star |
| `s` | star the highlighted book, or unstar it |
| `q` | quit |

`Escape` closes whatever screen is open.

## Modes

`t` switches the app between two modes, and the mode decides what `m` and `n`
accept.

| Mode | Files `m` indexes | Shown in the tree |
|---|---|---|
| book (default) | `.pdf`, `.md` | only `pdf` and `md` rows |
| code | `.py`, `.sql` | only `py` and `sql` rows |

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

A root is a folder the app watches, registered by absolute path. Any number of
roots can be mounted; each book stores its path relative to its root, so moving
a folder means re-registering one root rather than rewriting every book.

Mounting walks the folder and indexes every file under it, at any depth, that the
current mode accepts: `.pdf` and `.md` in book mode, `.py` and `.sql` in code mode.
The picker title names the mode and its extensions, so what `m` will take is visible
before you press it.

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
database and the app indexes it on a worker thread, with
`counting /path for .md .pdf ...` in the status line while it runs. Mounting is
instant, the UI never blocks, and the tree fills in when the count lands. `~/` takes
about 36 seconds, which is what the status line is for.

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

`i` on a PDF runs `qlmanage -p`, the same Quick Look that Finder's space bar
opens, because a terminal cannot render a PDF page.

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

Two tables, defined in `bookshelf_schema.sql` and widened by
`bookshelf_schema_v2.sql`.

```
roots              one row per mounted folder. `path` is the only absolute path
                   in the schema
books              one row per file: root_id, relative path, title, kind,
                   star, added_at
```

| Column | Values |
|---|---|
| `kind` | `pdf`, `md`, `py`, `sql` |
| `is_important` | `0` or `1` |

```
│ identity      a book is addressed by (root_id, path), never by title. Two files
│               may share a title; no two share a path
│ derived       title comes from the filename and the tree view comes from the
│               paths. Neither is stored
│ revision      PRAGMA user_version holds the schema revision. bootstrap() applies
│               revision 1 to a fresh file and then migrates it like any other, so
│               there is one path through the code. A released revision is never
│               edited in place -- revision 2 is its own script
```

## How it is built

Ten files and 1,269 lines, of which the TUI is two: the app and the screens. Each layer
knows only the one below it.

```
bookshelf_tui.py        the app: modes, reload, keys            480 lines
        │
        ├── bookshelf_screens.py the dialogs and the trees      344
        │
        ├── bookshelf_main.py    the `bookshelf` command          51
        │
        ├── bookshelf_repo.py    the verbs, over a connection   166
        ├── bookshelf_scan.py    which files count, one map      29
        │                        per mode
        ├── bookshelf_tree.py    the shape a tree view needs     48
        │
        └── bookshelf_db.py      one connection, one revision   54
                    │
        bookshelf_schema.sql     the contract, revision 1       33
        bookshelf_schema_v2.sql  the code-mode kinds            39
        bookshelf.tcss           every rule the app draws with  25
                    │
                 shelf.db
```

```
│ repo holds no SQLite import   every function takes an open connection. The caller
│                               owns the transaction, so two writes commit together
│                               or neither does
│ repo holds no policy          kinds and paths belong to scan -- one map per mode,
│                               and the mode picks the map; resolution and nesting
│                               belong to add_root
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

a terminal bookshelf over folders of PDF, Markdown, Python and SQL.

This is a TUI. Run `bookshelf` and the shelf opens:

  m  mount a folder        t  books <-> code
  i  preview a file        q  leave

The footer lists the keys for whatever has focus.
```

`-h` prints that and exits; it never imports Textual, so it answers instantly even
before the UI dependencies are installed.

## What it does not do

```
│ folders as notes     a folder holding images but no .md is not a book, so it does
│                      not appear at all. notes/guides/how to make a good science
│                      reaserch/ is one of these
│ no index generation  the plan was a generated JSON summary per book, stored in a
│                      table. Not built
```

Migrations are the exception: the database moves forward rather than being rebuilt.
`bookshelf_db.py` holds one script per revision, `bootstrap()` runs the missing ones in
order, and a fresh file gets revision 1 and is then migrated like any other, so there is
one path through the code. Revision 2 rebuilt `books` to widen a CHECK constraint, which
SQLite cannot ALTER — the procedure sqlite.org documents, with `books.id` copied so the
stars stayed attached to the same files.
