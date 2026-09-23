import sqlite3, contextlib
from pathlib import Path

HERE = Path(__file__).parent
SCHEMA_VERSION = 4
SCHEMA_FILE = HERE / "bookshelf_schema.sql"

# One script per revision, keyed by the revision it produces. Revision 1 is the whole
# database and lives in SCHEMA_FILE. Later revisions are separate files, because a
# released revision is never edited in place: someone's shelf.db already ran it.
MIGRATIONS = {
	2: HERE / "bookshelf_schema_v2.sql",
	3: HERE / "bookshelf_schema_v3.sql",
	4: HERE / "bookshelf_schema_v4.sql",
}

def connect(db_path: str) -> sqlite3.Connection:
	conn = sqlite3.connect(db_path)
	conn.row_factory = sqlite3.Row
	conn.execute("PRAGMA foreign_keys = ON")
	return conn


@contextlib.contextmanager
def session(db_path: str):
	"""One connection, one transaction: commits on a clean exit, rolls back on an error.

	The caller owns the transaction boundary, so two writes in one `with` block commit
together or not at all. Every write in the app goes through here.
	"""
	with contextlib.closing(connect(db_path)) as conn, conn:
		yield conn

def bootstrap(db_path: str) -> None:
	"""Bring the database up to SCHEMA_VERSION. Safe to call on every start.

	A brand new file gets revision 1 and is then migrated like any other, so a fresh
	shelf and an old one take the same path through the code.
	"""
	with contextlib.closing(connect(db_path)) as conn:
		current = conn.execute("PRAGMA user_version").fetchone()[0]
		if current > SCHEMA_VERSION:
			raise RuntimeError(f"DB is at revision {current}, code knows {SCHEMA_VERSION}")

		if current == 0:
			conn.executescript(SCHEMA_FILE.read_text())
			conn.execute("PRAGMA user_version = 1")
			current = 1

		while current < SCHEMA_VERSION:
			# Each script opens its own transaction, so a failure leaves the revision
			# counter and the tables in agreement -- either both moved or neither did.
			conn.executescript(MIGRATIONS[current + 1].read_text())
			conn.execute(f"PRAGMA user_version = {current + 1}")
			conn.commit()
			current += 1
