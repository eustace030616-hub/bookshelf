"""The dialogs and trees -- everything on screen except the list itself.

Split out of bookshelf_tui so that file holds the app: modes, reload, keys. A screen here
knows nothing about the database. It is handed rows that are already loaded and dismisses
with a value the app acts on, which is what keeps the app the only place that writes.

The four screens and the trees they use:

	Confirm          yes/no, one key. The mount and unmount guards both end here
	Preview          a .md as Markdown, code as one fenced block
	PickerScreen     a tree of rows, j/k, one key to take one -- the shared half
	MountScreen      a folder on disk, picked by walking to it
	UnmountScreen    a mounted root, picked by name
"""
from pathlib import Path

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Footer, MarkdownViewer, Static, Tree

# Rows a j/k press moves the preview. The arrow keys still move one row.
PREVIEW_SCROLL = 5

# j/k on every tree. Textual supplies the actions; this supplies the keys.
#
# Written once and handed to each class, rather than shared through a mixin. A mixin cannot
# work here: when Textual collects BINDINGS, COMPONENT_CLASSES and CSS it walks one chain of
# DOMNode bases, not every base. A plain mixin is not a DOMNode and its keys are dropped; a
# DOMNode mixin sends that walk down the mixin's own branch and cuts the Tree's components
# out of it, which breaks the tree's rendering. So the list is a value, not a base class.
VIM_KEYS = (Binding("j", "cursor_down", "down"), Binding("k", "cursor_up", "up"))


def iter_nodes(node):
	"""Depth-first over every node, including `node` itself."""
	yield node
	for child in node.children:
		yield from iter_nodes(child)


def find_node(root, predicate):
	return next((n for n in iter_nodes(root) if predicate(n)), None)


def force_line_rebuild(tree):
	"""Textual builds `Tree._tree_lines` lazily and `move_cursor` reads `node._line` out of
	that same cache. A tree filled by remove_children()/add_leaf() has an empty cache, so
	the cursor would be placed from a stale line number. Touching the property rebuilds it.
	"""
	len(tree._tree_lines)


class BookTree(Tree):
	"""The list of books."""

	BINDINGS = VIM_KEYS


class DirTree(DirectoryTree):
	"""The folder picker: folders only, dotfolders hidden."""

	BINDINGS = VIM_KEYS

	def filter_paths(self, paths):
		# A file cannot be a root, and offering one invites a silent failure.
		return [p for p in paths if p.is_dir() and not p.name.startswith(".")]


class Confirm(ModalScreen):
	"""A yes/no guard. Dismisses True, or None when cancelled."""

	# No BINDINGS, on purpose. on_key() on a Screen runs *before* the App's binding check,
	# so declaring bindings here would mean the App never saw the key. Every key that
	# arrives is handled in on_key(), and everything else is swallowed.
	# Two ways in, one way out. `enter` confirms any guard; the verb key -- the key that
	# opened the dialog -- confirms the one it opened; `q` is the only way to revoke, which is
	# the same key that leaves the preview and the pickers. `y` and `escape` used to work here
	# and no longer do: three yes-keys and two escapes is not a prompt, it is a menu.
	YES_KEYS = ("enter",)
	NO_KEYS = ("q",)

	def __init__(self, title, body, verb="confirm", yes_key=None):
		super().__init__()
		self.title_text = title
		self.body = body
		self.verb = verb
		self.yes_key = yes_key          # "m" in the mount guard -- the key that opened it

	@property
	def hint(self):
		"""The keys that work, and only those: one line, two verbs, three keys."""
		keys = "[enter]"
		if self.yes_key:
			keys += f" / [{self.yes_key}]"
		return f"{keys}  {self.verb}    [q] cancel"

	def compose(self) -> ComposeResult:
		with Vertical(id="confirm-box"):
			yield Static(self.title_text, id="confirm-title")
			yield Static(self.body, id="confirm-body")
			# Static parses its content as Rich markup, so [enter] would be read as a style
			# tag and vanish. Escaping the bracket is what makes the key names visible.
			yield Static(self.hint.replace("[", r"\["), id="confirm-hint")

	def on_mount(self) -> None:
		# Focus the box. With nothing focusable app.focused stays None and a key event has
		# no widget to start from, which is a bad position for a dialog to be in.
		box = self.query_one("#confirm-box", Vertical)
		box.can_focus = True
		box.focus()

	def on_key(self, event: events.Key) -> None:
		"""Every key the dialog sees, and nothing leaks to the list behind it.

		The verb key is also yes: the key that opened this dialog confirms it. Anything
		else is swallowed, so a stray t or s cannot act on a book while you are answering.
		"""
		event.stop()
		event.prevent_default()
		if event.key in self.YES_KEYS or event.key == self.yes_key:
			self.dismiss(True)
		elif event.key in self.NO_KEYS:
			self.dismiss(None)


def block_text(block):
	"""A block's text, its subtree included, whitespace collapsed to single spaces.

	The text is never where you would first look. Prose holds Content; a bullet list is an
	empty string with item children; a table is an empty string with cell widgets that hold
	it; a fence is an empty string too, and its code lives in a Label it composes. So every
	descendant is asked, whatever kind of widget it is, and a mark remembers what was on
	screen rather than what a block class happens to expose.
	"""
	parts = []
	for node in block.walk_children(with_self=True):
		content = getattr(node, "content", None)
		if isinstance(content, str):
			text = content
		else:
			text = getattr(content, "plain", "") or ""
		if text.strip():
			parts.append(" ".join(text.split()))
	return " ".join(parts)


class Preview(ModalScreen):
	"""A text file rendered inside the TUI. `q` closes it, and nothing else does.

	Escape deliberately does not leave: this screen is a reading surface, the footer names
	the one key that exits, and the app's other dialogs still answer to Escape as they should.

	Markdown arrives as itself; code arrives already wrapped in a fence by the app, which
	is what keeps `# a comment` a comment instead of a heading.
	"""

	BINDINGS = [
		Binding("q", "close_preview", "close"),
		Binding("m", "mark", "mark"),
		Binding("j", "preview_down", "down", show=False),
		Binding("k", "preview_up", "up", show=False),
	]

	class Marked(Message):
		"""`m` was pressed: here is where the reader is. The app owns the database, so a
		screen reports the position and does not store it itself."""

		def __init__(self, book_id, anchor, position):
			super().__init__()
			self.book_id = book_id
			self.anchor = anchor
			self.position = position

	def __init__(self, heading, body, book_id=None, jump=None):
		super().__init__()
		self.heading = heading
		self.body = body
		self.book_id = book_id
		self.jump = jump          # a mark to open at: (anchor, position) or None

	def compose(self) -> ComposeResult:
		yield Static(self.heading, id="preview-title")
		yield MarkdownViewer(self.body, show_table_of_contents=False)
		yield Footer()

	def on_mount(self) -> None:
		viewer = self.query_one(MarkdownViewer)
		viewer.focus()
		if self.jump:
			# Not here: a screen's on_mount runs before its children have built, so the blocks
			# a jump needs do not exist yet. Wait for them.
			self.call_after_refresh(self.try_jump)

	def blocks(self):
		"""The top-level blocks that carry text, in reading order.

		Top-level, because a position in this view is measured against the document: a nested
		block's coordinates are relative to its parent, and only these sit on the container's
		own axis. Text, because a mark wants the words on screen.
		"""
		markdown = next(iter(self.query("Markdown")), None)
		if markdown is None:
			return []
		return [child for child in markdown.children if block_text(child)]

	def try_jump(self, tries=0):
		"""Jump once the document has blocks, waiting a refresh at a time until it does.

		Retrying on the refresh is deterministic where a timer is: the jump happens on the
		first layout that produced a document. A document that renders nothing gives up
		after twenty tries rather than looping.
		"""
		if not self.jump:
			return
		if not self.blocks() and tries < 20:
			self.call_after_refresh(self.try_jump, tries + 1)
			return
		anchor, position = self.jump
		self.jump = None
		self.open_at(anchor, position)

	def anchor_at_top(self):
		"""The text of the block at the top of the view, and the row it sits on.

		Stored together so a mark survives a re-render: the row is right until the document
		changes, the text is right as long as those words are still there, and the text is
		what is looked up first.
		"""
		viewer = self.query_one(MarkdownViewer)
		top = viewer.scroll_offset.y
		for block in self.blocks():
			# virtual_region, not region: a block scrolled off the top has a negative screen
			# row, and the scroll offset this is compared against lives in content space
			y, height = block.virtual_region.y, block.virtual_region.height
			if y + height > top:
				return block_text(block)[:80], int(top)
		return "", int(top)

	def open_at(self, anchor, position):
		"""Scroll to a remembered mark: by its text when that text is still there."""
		viewer = self.query_one(MarkdownViewer)
		if anchor:
			for block in self.blocks():
				if anchor[:40] in block_text(block):
					viewer.scroll_to(y=block.virtual_region.y, animate=False)
					return
		viewer.scroll_to(y=position, animate=False)

	def action_mark(self) -> None:
		"""`m`: leave a mark here. One per document, and it expires when it is used."""
		anchor, position = self.anchor_at_top()
		self.post_message(self.Marked(self.book_id, anchor, position))

	def action_close_preview(self) -> None:
		self.dismiss()

	# MarkdownViewer scrolls one row with the arrow keys; j/k jump PREVIEW_SCROLL rows.
	# scroll_relative measures y in rows, and animate=False keeps the jump instant.
	def action_preview_down(self) -> None:
		self.query_one(MarkdownViewer).scroll_relative(y=PREVIEW_SCROLL, animate=False)

	def action_preview_up(self) -> None:
		self.query_one(MarkdownViewer).scroll_relative(y=-PREVIEW_SCROLL, animate=False)


class PickerScreen(ModalScreen):
	"""A tree of rows: j/k to move, one key to take the highlighted one, Escape to leave.

	MountScreen and UnmountScreen differ in what they list and in what their guard says.
	The tree, the title line, the cursor and the confirm round trip are identical, so they
	are here, and a subclass supplies four small things: make_tree, summary, guard, taken.
	"""

	BINDINGS = [Binding("escape,q", "cancel", "cancel")]

	# Both pickers end their title line the same way, because both behave the same way:
	# Escape leaves, j/k move. The key that acts on a row is the one thing that differs.
	TAIL = "j/k move · esc cancel"

	def __init__(self, rows=()):
		super().__init__()
		self.rows = list(rows)

	# ------------------------------------------------------------ what a subclass fills in

	def make_tree(self):
		"""The tree widget. Every subclass builds its own: the unmount list from its rows,
		the folder picker from a path."""
		raise NotImplementedError

	def summary(self, row):
		"""The title line under the tree for one row."""
		raise NotImplementedError

	def guard(self, row):
		"""Keyword arguments for the Confirm that a choice opens."""
		raise NotImplementedError

	def taken(self, row):
		"""What this screen dismisses with when a row is taken."""
		raise NotImplementedError

	# ------------------------------------------------------------------ the shared half

	def tree(self):
		return self.query_one("#picker", Tree)

	def current(self):
		"""The row under the cursor, or the first row if the cursor is nowhere."""
		node = self.tree().cursor_node
		return node.data if node is not None and node.data else self.rows[0]

	def compose(self) -> ComposeResult:
		yield Static("", id="picker-title")
		yield self.make_tree()
		yield Footer()

	def on_mount(self) -> None:
		tree = self.tree()
		self.fill(tree)
		tree.focus()
		self.show_current()

	def fill(self, tree) -> None:
		"""One leaf per row, cursor on the first.

		A DirectoryTree loads itself and overrides this with a no-op.
		"""
		root = tree.root
		root.remove_children()
		root.expand()
		for row in self.rows:
			root.add_leaf(self.leaf_text(row), data=row)
		if self.rows:
			force_line_rebuild(tree)
			tree.move_cursor(root.children[0])

	def leaf_text(self, row):
		"""One row as the tree draws it."""
		raise NotImplementedError

	def on_tree_node_highlighted(self, event) -> None:
		self.show_current()

	def show_current(self) -> None:
		self.query_one("#picker-title", Static).update(self.summary(self.current()))

	def action_choose(self) -> None:
		row = self.current()

		def answered(ok):
			if ok:
				self.dismiss(self.taken(row))

		self.app.push_screen(Confirm(**self.guard(row)), answered)

	def action_cancel(self) -> None:
		self.dismiss(None)


class MountScreen(PickerScreen):
	"""Browse the disk and pick a folder to mount.

	The path is never typed: you walk to it, which is the whole point of doing this in the
	terminal instead of asking for a Finder drag. Nothing is counted here -- the app walks
	the folder after the guard, off the UI thread, and says so in the status line.
	"""

	BINDINGS = [Binding("m", "choose", "mount")]

	def __init__(self, start, already, mode):
		super().__init__()
		self.start = Path(start).expanduser().resolve()
		self.already = {str(Path(p)).rstrip("/") for p in already}
		self.mode = mode

	def make_tree(self):
		return DirTree(self.start, id="picker")

	def fill(self, tree) -> None:
		"""Nothing to fill: DirectoryTree walks the disk itself, one folder at a time."""

	def current(self):
		"""The highlighted folder, resolved -- see the note in repo.add_root about /tmp."""
		node = self.tree().cursor_node
		base = node.data.path if node is not None and node.data else self.start
		return Path(base).expanduser().resolve()

	def summary(self, path):
		flag = "  [already mounted]" if str(path) in self.already else ""
		return (
			f"{path}{flag}     [{self.mode.name}: {self.mode.extensions}]"
			f"  m mount · enter open folder · {self.TAIL}"
		)

	def guard(self, path):
		return dict(
			title="Mount this folder?",
			body=(
				f"{path}\n\n"
				"Every supported file under it is recorded -- .md .html .py .sql.\n"
				"`t` switches which of those the list shows."
			),
			verb="mount",
			yes_key="m",
		)

	def taken(self, path):
		return path


class UnmountScreen(PickerScreen):
	"""Pick which mounted folder to forget. The files themselves are never touched.

	Only roots holding the current mode's files are listed, and `n` beside each is that
	mode's count. The app decides which roots those are -- see BookshelfApp.action_unmount.
	"""

	BINDINGS = [Binding("n", "choose", "unmount")]

	def __init__(self, rows, mode):
		super().__init__(rows)
		self.mode = mode

	def make_tree(self):
		return Tree("mounted folders", id="picker")

	def leaf_text(self, row):
		return f"{row['label']}   ({row['n']} {self.mode.plural})"

	def summary(self, row):
		return f"{row['path']}     [{self.mode.name}]  n unmount · {self.TAIL}"

	def guard(self, row):
		body = [row["path"], "", f"{row['n']} {self.mode.plural} would leave the shelf."]
		other = row["total"] - row["n"]
		if other:
			body.append(
				f"That folder also holds {other} file(s) of the other mode; "
				f"unmounting forgets those too."
			)
		body.append("The files on disk are NOT touched -- they stay exactly where they are.")
		return dict(
			title=f"Unmount {row['label']}?",
			body="\n".join(body),
			verb="unmount",
			yes_key="n",
		)

	def taken(self, row):
		return row["id"]
