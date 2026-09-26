# bookshelf

A terminal bookshelf over folders of Markdown, Python and SQL files. Nothing is moved,
renamed or rewritten: a root is a folder the shelf points at, a book is one file inside it,
and the database holds the shelf — the star and the reader's marks.

```
python3 -m pip install textual
python3 bookshelf_main.py             # the app, on shelf.db next to the code
python3 bookshelf_main.py --db other.db
python3 bookshelf_main.py -h
```

Requires Python 3.13 and Textual 8. `bookshelf_tui.py` runs directly too. How it is built,
and the two non-terminal ways to read it, are in [DEVELOPING.md](DEVELOPING.md).

## Home

The list is the main page. Every key acts on the highlighted row.

| Key | |
|---|---|
| `j` `k` | down / up a row. Arrows do the same |
| `i` | open the row in the preview page |
| `Enter` | open the file in the default application; on a folder, expand or collapse it |
| `t` | book rows <-> code rows |
| `m` `n` | mount / unmount a folder |
| `s` | star the row, or unstar it |
| `u` | re-walk every mounted folder and match the shelf to the disk |
| `q` | quit |

`○` is unstarred, `●` (warm yellow) is starred.

## Preview

One file, rendered. `q` closes it; Escape deliberately does not.

| Key | |
|---|---|
| `j` `k` | down / up a block |
| `h` `l` | left / right a character |
| `J` `K` | down / up one drawn line (shift+`j`, shift+`k`) |
| `w` `b` | next / previous word |
| `gg` `G` | top / last block of the file |
| `ctrl+g` | the middle block |
| `ctrl-d` `ctrl-u` | half a page |
| `ctrl-f` `ctrl-b` | a page |
| `/` | search this document; `<` `>` step the matches |
| `a` | start a range, move with `h j k l`, `a` again marks it |
| `m` | leave a mark; opening the file again jumps to it, once |
| `N` | write a note on this line |
| `C` | edit the note on this line |
| `n` | the next line with a note, wrapping |
| `q` | close the page |

Notes: the cursor is on from the moment the file opens. `a` inside a range you already made
takes that range away, and `q` drops a range you are still choosing. The note is a box above
its own line, and that line wears the same wash as a highlight.

## Note composer

| Key | |
|---|---|
| `Enter` | save |
| `tab` | indent to the next tab stop |
| `shift+enter` | new line, same indentation |
| `Escape` | leave without saving |
| `ctrl+q` | discard what is typed |

Not `q`: this is a text field, and a note may begin with "q".

## Folder picker

Opened by `m` (mount) or `n` (unmount). `m` browses the disk from `~`; `n` lists the mounted
roots that hold files of the current mode.

| Key | |
|---|---|
| `j` `k` | down / up |
| `Enter` | open a folder (mount picker only) |
| `m` `n` | take the highlighted folder |
| `Escape` `q` | cancel |

## Guard

Every mount and unmount asks first. `Enter` or the key that opened it confirms — `m` for a
mount, `n` for an unmount — and `q` cancels.

## Modes

`t` decides which rows the list shows; it does not change what is on disk or in the database.

| Mode | Rows | Shown as |
|---|---|---|
| book (default) | `.md` | the title, without its extension — `docker-guide` |
| code | `.py`, `.sql` | the filename on disk — `schema.sql` |

Mounting and updating record every kind either way, so both libraries live in one database
and only one is ever on screen.

## On disk

Only `.md`, `.py` and `.sql` are read; everything else is left alone. A root is registered by
absolute path and each book stores its path relative to it, so moving a folder means
re-registering the root, not rewriting its books.

The files are never touched. Unmounting forgets a root, it does not delete it, and `u` drops
the row of a file that is gone. A root whose folder is missing — an unplugged disk — is
reported and never emptied. Mounting the folder again restores the rows, without the stars.

The shelf is a snapshot, not a watcher: it re-walks every root when the app opens, and `u`
does the same on demand. A file changed outside the app appears in the list at the next walk.
