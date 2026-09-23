"""The shape a tree view needs, built from a flat list of book rows.

Shared by the TUI and by the command line, so the grouping rules live in one place:
one entry per mounted root, directories before files, and nothing stored that the
relative paths already say.
"""

FILES = "__files__"


def build_tree(rows):
	"""Nest rows by their relative paths. A directory is a dict; FILES holds its books."""
	tree = {}
	for row in rows:
		node = tree
		*dirs, _name = row["path"].split("/")
		for name in dirs:
			node = node.setdefault(name, {})
		node.setdefault(FILES, []).append(row)
	return tree


def forest(rows):
	"""[(root label, tree), ...] -- one entry per mounted root, in the order rows arrive."""
	groups = {}
	for row in rows:
		groups.setdefault(row["root_label"], []).append(row)
	return [(label, build_tree(group)) for label, group in groups.items()]


def plan(rows):
	"""What a tree widget draws for these rows: (label, draw_roots, entries).

	One root: name the tree after it and skip its level. Several: name the tree
	"bookshelf" and show which root each group came from. The label and the level go
	together, which is why one function decides both and no renderer does.
	"""
	entries = forest(rows)
	multi = len(entries) > 1
	return ("bookshelf" if multi or not entries else entries[0][0]), multi, entries


def children(subtree):
	"""Yield (name, value, is_directory) for one level -- directories first, then files."""
	for name in sorted(key for key in subtree if key != FILES):
		yield name, subtree[name], True
	for row in sorted(subtree.get(FILES, ()), key=lambda r: r["title"].casefold()):
		yield row["title"], row, False
