"""Data access layer. Every function takes an open connection.

This module does not import sqlite3 and never calls connect(). The caller owns
the connection, and therefore owns the transaction boundary:

	with db.session(path) as conn:
		root_id = repo.add_root(conn, "/Users/me/Desktop/NOTES")
		repo.add_book(conn, root_id, "guides/vim.md", "vim-guide", "md")

Both statements commit together or neither does.

Two functions here read the disk, and both go through bookshelf_scan -- which stays the only
place that decides which files count. `sync_root` walks a root and reconciles the rows;
`ingest` stores one file's text beside its row, which is what makes the shelf readable from
a machine that does not have the files.

Books are addressed by `id`, not by path. The TUI has a row in hand after the
user selects it; a front end without the files has only the id. Look the path up
once, then use ids.
"""

from pathlib import Path

from bookshelf_scan import scan


# --------------------------------------------------------------------- roots

def add_root(conn, path, label=None):
	"""Get-or-create a library root. Re-adding never overwrites an existing label.

	Refuses a path that nests inside -- or contains -- an existing root. Otherwise the same
	file gets indexed twice under two different relative paths and appears twice in the list.

	Paths are resolved first. On macOS /tmp is a symlink to /private/tmp, so an unresolved
	"/tmp/x" and a resolved "/private/tmp/x" are the same folder comparing as different
	strings -- which would let one directory in twice and defeat the check below.
	"""
	path = Path(path).expanduser().resolve()
	if not path.is_dir():
		raise ValueError(f"{path} is not a folder")
	path = str(path)
	for r in list_roots(conn):
		existing = str(Path(r["path"]).expanduser().resolve())
		if path.startswith(existing + "/") or existing.startswith(path + "/"):
			raise ValueError(f"{path} nests inside existing root {existing!r}; register one or the other")

	conn.execute(
		"INSERT INTO roots (path, label) VALUES (?, ?) ON CONFLICT (path) DO NOTHING",
		(path, label or Path(path).name or path),
	)
	return conn.execute("SELECT id FROM roots WHERE path = ?", (path,)).fetchone()["id"]


def get_root(conn, root_id):
	return conn.execute("SELECT * FROM roots WHERE id = ?", (root_id,)).fetchone()


def list_roots(conn, kinds=None):
	"""Every root with how many books it holds.

	`kinds` narrows both the join and the count, so a root that holds only Markdown reports
	n = 0 while the shelf is in code mode. Pass None for every root, which is what the
	nesting check in add_root needs: it must see all of them, not one mode's worth.
	"""
	join = "LEFT JOIN books b ON b.root_id = r.id"
	params = ()
	if kinds is not None:
		holes = ", ".join("?" * len(kinds))
		join += f" AND b.kind IN ({holes})"
		params = tuple(kinds)
	return conn.execute(
		f"""
		SELECT r.*, count(b.id) AS n
		  FROM roots r
		  {join}
		 GROUP BY r.id
		 ORDER BY r.label COLLATE NOCASE
		""",
		params,
	).fetchall()


def remove_root(conn, root_id):
	"""Deletes the root and every book in it (CASCADE). Returns True if it existed."""
	return conn.execute("DELETE FROM roots WHERE id = ?", (root_id,)).rowcount == 1


# --------------------------------------------------------------------- books

def add_book(conn, root_id, path, title, kind):
	"""Insert, or refresh title/kind if this (root, path) is already known.

	Idempotent: importing the same library twice leaves the same number of rows.
	"""
	row = conn.execute(
		"""
		INSERT INTO books (root_id, path, title, kind) VALUES (?, ?, ?, ?)
		ON CONFLICT (root_id, path) DO UPDATE
		   SET title = excluded.title, kind = excluded.kind
		RETURNING id
		""",
		(root_id, path, title, kind),
	).fetchone()
	return row["id"]


# Every book query needs the root's path and label to build an absolute path, so the
# projection is written once here instead of in two SELECTs that have to stay identical.
BOOK_SELECT = """
	SELECT b.*, r.path AS root_path, r.label AS root_label
	  FROM books b JOIN roots r ON r.id = b.root_id
"""


def remove_book(conn, book_id):
	"""Returns True if a row was deleted. Category links go with it (CASCADE)."""
	return conn.execute("DELETE FROM books WHERE id = ?", (book_id,)).rowcount == 1


def set_important(conn, book_id, flag):
	return conn.execute(
		"UPDATE books SET is_important = ? WHERE id = ?",
		(1 if flag else 0, book_id),
	).rowcount == 1


# ---------------------------------------------------------------------- ingest

def ingest(conn, book_id, path):
	"""Store one file's text beside its row, if the file changed since the last time.

	Returns True when a body was written. Size and mtime decide: re-reading a whole library on
	every `u` is the difference between 11 MB and 10 GB of I/O for an answer that has not
	changed. A file that cannot be read as text -- gone, or not UTF-8 -- leaves whatever is
	stored alone rather than emptying the row, so one unreadable file cannot blank a document.
	"""
	path = Path(path)
	try:
		stat = path.stat()
		body = path.read_text(encoding="utf-8")
	except (OSError, UnicodeDecodeError):
		return False

	known = conn.execute(
		"SELECT source_size, source_mtime FROM content WHERE book_id = ?", (book_id,)
	).fetchone()
	if known and known["source_size"] == stat.st_size and known["source_mtime"] == str(stat.st_mtime):
		return False

	conn.execute(
		"""
		INSERT INTO content (book_id, body, bytes, source_size, source_mtime)
		VALUES (?, ?, ?, ?, ?)
		ON CONFLICT (book_id) DO UPDATE
		   SET body = excluded.body,
		       bytes = excluded.bytes,
		       source_size = excluded.source_size,
		       source_mtime = excluded.source_mtime,
		       ingested_at = datetime('now')
		""",
		(book_id, body, len(body.encode("utf-8")), stat.st_size, str(stat.st_mtime)),
	)
	return True


def content_of(conn, book_id):
	"""The stored text of one document, or None if this row has no body yet."""
	row = conn.execute("SELECT body FROM content WHERE book_id = ?", (book_id,)).fetchone()
	return row["body"] if row else None


def stored_totals(conn):
	"""(documents, bytes) held in the database: what a front end without the files has."""
	row = conn.execute("SELECT count(*), coalesce(sum(bytes), 0) FROM content").fetchone()
	return row[0], row[1]


# ---------------------------------------------------------------------- sync

def sync_root(conn, root_id, kinds):
	"""Bring one root in line with the disk.

	Returns (added, removed, ingested, folder_missing). Files are not watched. The shelf is a
	snapshot, so a file added, changed or deleted since the last walk is invisible until
	something re-walks the root -- that is this. `ingested` counts the files whose text was
	read: the walk compares size and mtime, so an unchanged library costs one stat per file
	and no reads at all.

	A root whose folder is not there any more -- an unplugged drive, a folder that moved --
	is reported, not emptied. Every file would look gone, and forgetting a whole library
	because a volume is not mounted is not a mistake worth being able to make.

	`kinds` is the union of every mode's map, not the current mode's: the table holds both
	libraries, so a file is only gone when it is gone for all of them.
	"""
	root = get_root(conn, root_id)
	if root is None or not Path(root["path"]).is_dir():
		return 0, 0, 0, True

	found = list(scan(root["path"], kinds))
	known = {
		row["path"]: row["id"]
		for row in conn.execute("SELECT id, path FROM books WHERE root_id = ?", (root_id,))
	}
	on_disk = {path for path, _, _ in found}

	# Every file found is upserted, not just the ones that are new: add_book refreshes title
	# and kind on conflict, so a file whose name or extension changed lands too. The star
	# survives -- add_book touches neither is_important nor added_at.
	ingested = 0
	for path, title, kind in found:
		book_id = add_book(conn, root_id, path, title, kind)
		if ingest(conn, book_id, Path(root["path"]) / path):
			ingested += 1

	for path, book_id in known.items():
		if path not in on_disk:
			remove_book(conn, book_id)

	return len(on_disk - known.keys()), len(known.keys() - on_disk), ingested, False


# ----------------------------------------------------------------- marks

def set_mark(conn, book_id, anchor, position):
	"""Remember where a reader stopped, replacing whatever was there.

	One mark per document: the new one erases the old, because a reader has one place they
	put the book down, not a history of them. The anchor is the text at the top of the view,
	stored beside the row so the mark can be found again after the document is re-rendered.
	"""
	conn.execute("DELETE FROM annotation WHERE book_id = ? AND kind = 'mark'", (book_id,))
	conn.execute(
		"INSERT INTO annotation (book_id, kind, anchor, position) VALUES (?, 'mark', ?, ?)",
		(book_id, anchor, position),
	)


def take_mark(conn, book_id):
	"""The mark for one document, and it is used up by being read.

	Read and delete in one transaction on purpose: a mark that survives its own jump would
	take the reader to the same place twice, and the second time it would be wrong.
	"""
	row = conn.execute(
		"SELECT anchor, position FROM annotation WHERE book_id = ? AND kind = 'mark'", (book_id,)
	).fetchone()
	if row is not None:
		conn.execute("DELETE FROM annotation WHERE book_id = ? AND kind = 'mark'", (book_id,))
	return row


def add_highlight(conn, book_id, position, span, anchor):
	"""Mark a range: where it starts, how long it is, and the words it covers.

	Many per document, unlike a mark, so there is no delete first. The anchor is the text
	under the wash, which is what puts it back on the right sentence after the file is re-read.
	"""
	conn.execute(
		"INSERT INTO annotation (book_id, kind, anchor, position, span) "
		"VALUES (?, 'highlight', ?, ?, ?)",
		(book_id, anchor, position, span),
	)


def set_note(conn, book_id, position, anchor, note):
	"""Write a note on one line, replacing whatever was on that line.

	One note per line, for the same reason there is one mark per document: a reader writing on
	a line is saying something about that line, not adding to a pile.
	"""
	conn.execute(
		"DELETE FROM annotation WHERE book_id = ? AND kind = 'note' AND position = ?",
		(book_id, position),
	)
	conn.execute(
		"INSERT INTO annotation (book_id, kind, anchor, position, note) "
		"VALUES (?, 'note', ?, ?, ?)",
		(book_id, anchor, position, note),
	)


def notes_for(conn, book_id):
	"""Every note on one document, in reading order: (position, anchor, note)."""
	return [
		(row["position"], row["anchor"], row["note"])
		for row in conn.execute(
			"SELECT position, anchor, note FROM annotation "
			"WHERE book_id = ? AND kind = 'note' ORDER BY position",
			(book_id,),
		)
	]


def remove_highlight(conn, book_id, position, span):
	"""Forget one marked range. Returns True if a row went.

	Position and span are the key as well as the address: a reader pressing `a` inside a range
	is pointing at that range, and two ranges that start and end in the same place are the same
	mark to them.
	"""
	return conn.execute(
		"DELETE FROM annotation WHERE book_id = ? AND kind = 'highlight' "
		"AND position = ? AND span = ?",
		(book_id, position, span),
	).rowcount == 1


def highlights_for(conn, book_id):
	"""Every marked range on one document, in reading order: (position, span, anchor)."""
	return [
		(row["position"], row["span"], row["anchor"])
		for row in conn.execute(
			"SELECT position, span, anchor FROM annotation "
			"WHERE book_id = ? AND kind = 'highlight' ORDER BY position",
			(book_id,),
		)
	]


# ---------------------------------------------------------------------- list

# ORDER BY cannot take a ? placeholder: a placeholder substitutes a *value*, and a column
# name is not a value. So the allowed orderings are kept here as literal SQL and looked up
# by name. Anything not in this dict is rejected before it reaches the database.
ORDERINGS = {
	"id": "b.id",
	"title": "b.title COLLATE NOCASE",
	"path": "b.path COLLATE NOCASE",
	"added": "b.added_at",
}


def list_books(conn, root_id=None, important_only=False, order="id", kinds=None):
	"""All filters optional. Values are always bound; only literal clauses are concatenated.

	`kinds` is a mode's map values -- `mode.kinds.values()` -- so a front end can ask for one
	mode's rows without holding a mode object.
	"""
	if order not in ORDERINGS:
		raise ValueError(f"unknown order {order!r}; choose from {', '.join(ORDERINGS)}")

	select = [BOOK_SELECT]
	where, params = [], []

	if root_id is not None:
		where.append("b.root_id = ?")
		params.append(root_id)
	if important_only:
		where.append("b.is_important = 1")
	if kinds is not None:
		kinds = list(kinds)
		where.append(f"b.kind IN ({', '.join('?' * len(kinds))})")
		params.extend(kinds)

	if where:
		select.append("WHERE " + " AND ".join(where))
	select.append("ORDER BY " + ORDERINGS[order])
	return conn.execute(" ".join(select), params).fetchall()
