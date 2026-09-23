"""Which files count as books, and how to find them.

One map per mode, and nothing else: adding a format is one line in one of these, and no
other file changes. The TUI's mode table picks the map; the app passes it to scan().
"""
from pathlib import Path

KINDS = {
	".pdf": "pdf",
	".md": "md",
}

CODE_KINDS = {
	".py": "py",
	".sql": "sql",
}

# Everything the shelf can hold. The database keeps both libraries at once, so a re-walk of
# the disk has to look for all of them: a file is only gone when it is gone for every mode.
EVERY_KIND = {**KINDS, **CODE_KINDS}


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
