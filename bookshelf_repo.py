"""Data access layer. Every function takes an open connection.

This module does not import sqlite3 and never calls connect(). The caller owns
the connection, and therefore owns the transaction boundary:

	with contextlib.closing(db.connect(path)) as conn, conn:
		root_id = repo.add_root(conn, "/Users/me/Desktop/NOTES")
		repo.add_book(conn, root_id, "guides/vim.md", "vim-guide", "md")

Both statements commit together or neither does.

Books are addressed by `id`, not by path. The TUI has a row in hand after the
user selects it; the importer has a path. Look the path up once, then use ids.
"""

from pathlib import Path


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
