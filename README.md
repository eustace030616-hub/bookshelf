# bookshelf

A terminal bookshelf over one or more folders of HTML and Markdown files — and, in
code mode, over Python and SQL.

A PDF is not indexed. A PDF is the format a document arrives in, not the format the shelf
reads: convert it to HTML first, and one document is one row instead of a row per
representation.

Nothing is moved, renamed or rewritten. A root is a folder the shelf points at; a
book is one file inside it. The database holds the shelf — the star — and the files
stay where they are.

```
python3 -m pip install textual
python3 bookshelf_main.py           # the app, on shelf.db next to the code
python3 bookshelf_main.py --db other.db
python3 bookshelf_main.py -h        # what it is and how to start it
```

Requires Python 3.13 and Textual 8. There is no `bookshelf` on your PATH until you
install or link one; the commands above are the whole command line, and `bookshelf_tui.py`
also runs directly if you prefer the module. How it is built, and why, is in
[DEVELOPING.md](DEVELOPING.md).

## Keys

The list is the main screen. Every key below acts on the highlighted row.

| Key | Action |
|---|---|
| `j` / `k` | move down and up. Arrow keys do the same |
| `Enter` | open the file in the default application. On a folder, expand or collapse it |
| `i` | inspect in the app: Markdown as Markdown, code as a fence. A converted page says to press `Enter` |
| `m` | mount a folder — browse the disk and add it as a root |
| `n` | unmount a folder — pick a root and forget it |
| `t` | switch between book mode and code mode |
| `u` | update — re-walk every mounted folder and match the shelf to the disk |
| `s` | star the highlighted book, or unstar it |
| `q` | quit |

`q` cancels the guards and closes the preview; the folder picker also takes `Escape`. A
guard confirms with `Enter` or with the key that opened it -- `m` for a mount, `n` for an
unmount -- so one line of hint names every key that works.

The preview answers to its own keys: `j`/`k` by block and `J`/`K` by drawn line, `h`/`l`,
`w`/`b`, `gg`/`G` and `ctrl-g`
move the cursor, `ctrl-d`/`ctrl-u` and `ctrl-f`/`ctrl-b` move the view, `/` searches the
document and `<`/`>` step the matches, `m` marks a place,
`a` marks a range, `N` writes a note, `C` edits one and `n` finds them, `q` closes. `m` there
is a mark, not a mount -- below the list, a key means what the screen needs it to mean.

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
| `Escape`, `q` | cancel |

The picker opens at `~`, shows folders only, and hides dotfolders. A folder that is
already a root is marked `[already mounted]`.

`m` opens a guard naming the folder. `Enter` or `m` accepts; `q` cancels. The guard names
both keys on its own hint line, and nothing else answers to it.

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

Every row carries its mark, always: `s` sets it, nothing hides it.

| Row | Meaning |
|---|---|
| `○  docker-guide` | not starred |
| `●  docker-guide` | starred |

`○` is no and `●` in yellow is yes. The ring for no is a muted warm grey rather than an
absence, so a list of unstarred rows still lines up in one column.

## Inspecting

`i` renders a text file in the app. Markdown is drawn as Markdown: headings, lists and
code, from the file on disk. A `.py` or `.sql` file is drawn as one highlighted code
block in the same viewer — the source is wrapped in a fence, so `# a comment` stays a
comment instead of turning into a heading. `q` closes it -- Escape is left out on purpose, so
the footer names the one key that leaves and a reader cannot lose the page with a stray
keystroke.

`m` leaves a mark where you are. The next time you open that document it opens on the
block you marked, and the mark is spent by being used — one jump, then it is gone. Pressing
`m` again replaces it, because a reader has one place they put the book down, not a history
of them. The mark is found by the text it was set on, so it survives the document being
re-read; the row it was on is only a fallback.

The cursor is on from the moment a document opens, at the middle of the screen -- not the
top, which you have already read past. `j`/`k` move it a block at a time, keeping the column,
and the view follows by the least it can, so a line at a time reads as a line at a time
instead of jumping the page on every press. `h`/`l` move it a character at a time, crossing
into the block above or below at the edges. `w` and `b` move by word -- a word being a run of
characters between spaces, so a filename counts as one word. `gg` goes to the top of the
file, `G` to its last block, and `ctrl-g` to the middle; a stray key between the two `g`
presses forgets the first, so there is no mode to leave.

The view has its own keys: `ctrl-d`/`ctrl-u` half a page, `ctrl-f`/`ctrl-b` a page, the arrows
a row. Scrolling never leaves the cursor behind -- it comes along if it would fall off the
screen.

`a` marks a range with a warm wash behind the words: it anchors at the cursor, and a second
`a` marks everything between the two ends. Pressing `a` with the cursor inside a mark you
already made takes that mark away. `q` drops a selection you have changed your mind about, and
only closes the document when there is none.

`N` writes a note on the line the cursor is on, and `n` jumps to the next line that has one,
wrapping round at the end of the file -- which is how you find notes you wrote months ago. One
note per line: `N` on a noted line offers to delete it, and asks first. `C` on a noted line
opens the composer on that note, and saving replaces it.

The note is a box on the line above its own, centred across the view, and it is only there
while the cursor is on its line. It lies in a layer of its own, over the document rather than
in it, so showing and hiding it moves nothing: the page keeps its height, its scroll position
and its line breaks, and the text you are reading does not jump. A note written into its line
would take a row out of the page and shift every line below it. The line the note belongs to
wears the same wash as a highlight, so the noted lines are visible at a glance.

The composer takes more than one line: `tab` indents to the next tab stop, and `shift-enter`
starts the next line at the indentation of the line it came from. `Enter` saves and `Escape`
leaves (or `ctrl-q`, which discards what you have typed). `Enter` on an empty line leaves
nothing behind. Tab is not the focus key here -- the box is the only thing to focus, and
`Escape` is the way out. It is not a `q` to leave, because it is a text field: a note that
begins with "q" is a note somebody will write, and a letter that both types and leaves is a
letter the field eats.

The range is stored with the text it covers, so it comes back on the same sentence after the
file is re-read; a range whose words are gone is dropped rather than drawn in the wrong place.
It is a highlight rather than an underline because underline is a Markdown thing -- links and
emphasis -- and a reader needs to see at a glance which lines are theirs.

The fence is sized to the file: one backtick more than the longest backtick run inside
it, so a ``` in a Python docstring cannot end the block early.

A converted page is not drawn in the app. It is HTML with its own design, and a terminal has no
layout engine and no stylesheet; a second renderer that lifted the structure out of the markup
was one more thing to keep in step. So `i` says the row is a converted page and points at
`Enter`, which hands the file to the browser — that is where a page is read.

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
| `GET /health` | counts, bytes, when the shelf was last walked, and a stamp of it |
| `GET /stamp/<id>` | that stamp for one document, which is what a page watches |

The token can be given once as `?k=SECRET`, and the page remembers it in a cookie so the
links work; without it, nothing but a loopback address is served at all.

A page does not refresh itself. It remembers the stamp it was rendered from, asks the
server for the current one every ten seconds, and when they differ it offers a bar at the
bottom: *the shelf changed · reload*. Nothing moves under your eyes — you reload when you
are ready — and `reload` in the top right does the same thing on demand.

The database is copied in, never shared live: the copy the server reads is mounted
read-only, and the machine with the folders stays the only writer.

## Two front ends

The same shelf is a terminal app and a web page. The terminal is where the shelf is managed
-- mounting, updating, starring -- and the browser is where it is read, which is why the
server has no write route at all.

The page carries the reader's own marks: a highlight is a wash behind the words it covered, and
a note is a callout above the block it was written on. Neither is written from the browser --
the rows are read and drawn, which is the whole point of the read-only server. A document's own
navigation is a `note` button that steps through its notes, a `find` box that highlights on the
page and steps with Enter, and the `reload` every page keeps; the book/code switch lives on the
shelf, because a document is already one mode's row.

| | Terminal (this machine) | Browser (anywhere) |
|---|---|---|
| modes | `t`, per switch | shelf page only: `?mode=book` or `?mode=code` |
| star | on every row; `s` sets it | on every row; read-only |
| reading | `i` opens the viewer, `q` closes it | one page per document |
| your marks | highlights and notes, drawn in the viewer | the same highlights and notes on the page, read-only |
| writing | mount, unmount, `u`, `s` | nothing |
| gestures | the key tables above | links, scroll, back-swipe |

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
