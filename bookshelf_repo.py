"""Data access layer. Every function takes an open connection.

This module does not import sqlite3 and never calls connect(). The caller owns
the connection, and therefore owns the transaction boundary:

	with db.session(path) as conn:
		root_id = repo.add_root(conn, "/Users/me/Desktop/NOTES")
		repo.add_book(conn, root_id, "guides/vim.md", "vim-guide", "md")

Both statements commit together or neither does.

The one function here that reads the disk is sync_root, and it reads it through
bookshelf_scan -- which stays the only place that decides which files count. It lives here
rather than in a screen so that every front end gets the same re-walk.

Books are addressed by `id`, not by path. The TUI has a row in hand after the
user selects it; the importer has a path. Look the path up once, then use ids.
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


def find_root(conn, path):
	return conn.execute("SELECT * FROM roots WHERE path = ?", (str(path),)).fetchone()


def list_roots(conn, kinds=None):
	"""Every root with how many books it holds.

	`kinds` narrows both the join and the count, so a root that holds only PDFs reports
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


def get_book(conn, book_id):
	"""One book, with its root joined on so you can build an absolute path."""
	return conn.execute(BOOK_SELECT + " WHERE b.id = ?", (book_id,)).fetchone()


def find_book(conn, root_id, path):
	row = conn.execute(
		"SELECT id FROM books WHERE root_id = ? AND path = ?", (root_id, path)
	).fetchone()
	return row["id"] if row else None


def remove_book(conn, book_id):
	"""Returns True if a row was deleted. Category links go with it (CASCADE)."""
	return conn.execute("DELETE FROM books WHERE id = ?", (book_id,)).rowcount == 1


def set_important(conn, book_id, flag):
	return conn.execute(
		"UPDATE books SET is_important = ? WHERE id = ?",
		(1 if flag else 0, book_id),
	).rowcount == 1


# ---------------------------------------------------------------------- sync

def sync_root(conn, root_id, kinds):
	"""Bring one root in line with the disk. Returns (added, removed, folder_missing).

	Files are not watched. The shelf is a snapshot, so a file added or deleted since the
	last walk is invisible until something re-walks the root -- that is this.

	A root whose folder is not there any more -- an unplugged drive, a folder that moved --
	is reported, not emptied. Every file would look gone, and forgetting a whole library
	because a volume is not mounted is not a mistake worth being able to make.

	`kinds` is the union of every mode's map, not the current mode's: the table holds both
	libraries, so a file is only gone when it is gone for all of them.
	"""
	root = get_root(conn, root_id)
	if root is None or not Path(root["path"]).is_dir():
		return 0, 0, True

	found = list(scan(root["path"], kinds))
	known = {
		row["path"]: row["id"]
		for row in conn.execute("SELECT id, path FROM books WHERE root_id = ?", (root_id,))
	}
	on_disk = {path for path, _, _ in found}

	# Every file found is upserted, not just the ones that are new: add_book refreshes title
	# and kind on conflict, so a file whose name or extension changed lands too. The star
	# survives -- add_book touches neither is_important nor added_at.
	for path, title, kind in found:
		add_book(conn, root_id, path, title, kind)

	for path, book_id in known.items():
		if path not in on_disk:
			remove_book(conn, book_id)

	return len(on_disk - known.keys()), len(known.keys() - on_disk), False


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


def list_books(conn, root_id=None, important_only=False, order="id"):
	"""All filters optional. Values are always bound; only literal clauses are concatenated."""
	if order not in ORDERINGS:
		raise ValueError(f"unknown order {order!r}; choose from {', '.join(ORDERINGS)}")

	select = [BOOK_SELECT]
	where, params = [], []

	if root_id is not None:
		where.append("b.root_id = ?")
		params.append(root_id)
	if important_only:
		where.append("b.is_important = 1")

	if where:
		select.append("WHERE " + " AND ".join(where))
	select.append("ORDER BY " + ORDERINGS[order])
	return conn.execute(" ".join(select), params).fetchall()
