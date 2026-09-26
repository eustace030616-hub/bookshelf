"""Which files count as books, how to find them, and which mode shows what.

One map per mode, and nothing else: adding a format is one line in one of these, and no
other file changes. The mode table lives here rather than in the app because the mode is not
a screen idea -- the browser front end needs the same table, and it cannot import Textual.

A PDF and an HTML page are formats a document arrives in, not the formats this shelf
keeps: a converted document is Markdown by the time it lands here, so one document is one
row. Adding a format is this dictionary and a schema revision for the kind.
"""
from dataclasses import dataclass
from pathlib import Path

KINDS = {
	".md": "md",
}

CODE_KINDS = {
	".py": "py",
	".sql": "sql",
}

# Everything the shelf can hold. The database keeps both libraries at once, so a re-walk of
# the disk has to look for all of them: a file is only gone when it is gone for every mode.
EVERY_KIND = {**KINDS, **CODE_KINDS}


@dataclass(frozen=True)
class Mode:
	"""One mode: its name, the extensions it indexes, and what a row in it is called."""

	name: str
	kinds: dict
	noun: str

	@property
	def extensions(self):
		"""The extensions it takes, for the status line and a view's title."""
		return " ".join(sorted(self.kinds))

	@property
	def plural(self):
		"""What several rows are called, for counts and confirmations."""
		return self.noun + "s"


MODES = {
	"book": Mode("book", KINDS, "book"),
	"code": Mode("code", CODE_KINDS, "code file"),
}


# The star mark, and its two colours. They live here rather than in a front end because both
# front ends draw the same mark: a filled circle in dark gold for starred, an empty ring in
# muted warm grey for not. The ring is drawn rather than left blank so a column of unstarred
# rows still lines up, and so "not yet" is visible instead of implied.
RING = "\u25cb"
FILL = "\u25cf"
ON_COLOUR = "#B8860B"
OFF_COLOUR = "#A89F85"


def star_mark(row):
	"""One row's star as (glyph, colour). The same answer in the terminal and the browser."""
	on = bool(row["is_important"])
	return (FILL, ON_COLOUR) if on else (RING, OFF_COLOUR)


def row_name(row, mode):
	"""One row as a name, the way a reader of that mode expects to see it.

	Book mode shows the title, which is the filename without its extension: a shelf is a
	reading list, and `docker-guide` reads better than `docker-guide.md`. Code mode shows the
	filename as it is on disk, because there the extension is the information -- `schema.sql`
	and `schema.py` are different files to a reader, not two names for one thing.

	This is a drawing rule and nothing else: `books.title` holds the stem in both modes. It
	lives here, next to the modes, because the terminal app and the browser have to agree.
	"""
	return Path(row["path"]).name if mode.name == "code" else row["title"]


def scan(root, kinds):
	"""Yield (path relative to root, title, kind) for every supported file under root.

	`kinds` is required, not defaulted: the caller knows which mode it is filling, and a
	silent default would be a second answer to "what counts as a book".
	"""
	root = Path(root)
	for file in sorted(root.rglob("*")):
		kind = kinds.get(file.suffix.lower())
		if kind and file.is_file():
			yield str(file.relative_to(root)), file.stem, kind
