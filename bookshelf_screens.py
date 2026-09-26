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
from bookshelf_reading import Document
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


class Preview(ModalScreen):
	"""A text file rendered inside the TUI. `q` closes it, and nothing else does.

	Escape deliberately does not leave: this screen is a reading surface, the footer names
	the one key that exits, and the app's other dialogs still answer to Escape as they should.

	Three things live here beyond drawing the page. A mark (`m`) leaves one place to come back
	to. A selection (`a`, then h/l by character and j/k by block) underlines a range. Both are
	positions in `bookshelf_reading.Document`, and neither is stored here -- the screen reports
	them and the app writes them, because the app owns the database.

	Markdown arrives as itself; code arrives already wrapped in a fence by the app, which
	is what keeps `# a comment` a comment instead of a heading.
	"""

	BINDINGS = [
		Binding("q", "close_preview", "close"),
		Binding("m", "mark", "mark"),
		Binding("a", "select", "select"),
		Binding("h", "cursor_left", "left", show=False),
		Binding("l", "cursor_right", "right", show=False),
		Binding("j", "cursor_down", "down", show=False),
		Binding("k", "cursor_up", "up", show=False),
		Binding("w", "word_forward", "word", show=False),
		Binding("b", "word_back", "back", show=False),
		Binding("e", "word_end", "word end", show=False),
		Binding("g", "prefix_g", "top", show=False),
		Binding("G", "file_end", "end of file", show=False),
		Binding("ctrl+g", "file_middle", "middle", show=False),
		Binding("ctrl+d", "scroll_half_down", "half page", show=False),
		Binding("ctrl+u", "scroll_half_up", "half page", show=False),
		Binding("ctrl+f", "scroll_page_down", "page", show=False),
		Binding("ctrl+b", "scroll_page_up", "page", show=False),
	]

	class Marked(Message):
		"""`m` was pressed: here is where the reader is. The app owns the database, so a
		screen reports the position and does not store it itself."""

		def __init__(self, book_id, anchor, position):
			super().__init__()
			self.book_id = book_id
			self.anchor = anchor
			self.position = position

	class HighlightRemoved(Message):
		"""`a` was pressed inside a marked range: forget that one."""

		def __init__(self, book_id, position, span):
			super().__init__()
			self.book_id = book_id
			self.position = position
			self.span = span

	class Highlighted(Message):
		"""`a` was pressed twice: mark this range, and remember it."""

		def __init__(self, book_id, position, span, anchor):
			super().__init__()
			self.book_id = book_id
			self.position = position
			self.span = span
			self.anchor = anchor

	def __init__(self, heading, body, book_id=None, jump=None, highlights=()):
		super().__init__()
		self.heading = heading
		self.body = body
		self.book_id = book_id
		self.jump = jump                      # a mark to open at: (anchor, position) or None
		self.stored = list(highlights)        # (position, span, anchor) rows from the database
		self.document = None                  # built once the blocks have been laid out
		self.selecting = False
		self.pending_g = False               # `g` waits for its second key
		self.anchor_offset = 0
		self.cursor_offset = 0
		self.highlights = []                  # what to draw: (start, span, anchor)

	def compose(self) -> ComposeResult:
		yield Static(self.heading, id="preview-title")
		yield MarkdownViewer(self.body, show_table_of_contents=False)
		yield Footer()

	def on_mount(self) -> None:
		self.query_one(MarkdownViewer).focus()
		# Not here: a screen's on_mount runs before its children have built, so neither the
		# document nor the block a jump needs exists yet. Wait for them.
		self.call_after_refresh(self.build)

	# ------------------------------------------------------------------ the model

	def build(self, tries=0):
		"""Read the rendered tree into a document, draw it, and take a jump if there is one.

		Retrying on the refresh is deterministic where a timer is: it happens on the first
		layout that produced blocks. A document that renders nothing gives up after twenty
		tries rather than looping.
		"""
		markdown = next(iter(self.query("Markdown")), None)
		if (markdown is None or not markdown.children) and tries < 20:
			self.call_after_refresh(self.build, tries + 1)
			return
		if markdown is None:
			return
		self.document = Document(markdown)
		self.resolve_highlights()
		if not self.selecting:
			# The cursor is on from the moment the document opens, at the middle of the view:
			# a reader has to be able to see where a selection would start before starting one.
			self.cursor_offset = self.centre_offset()
		self.paint()
		if self.jump:
			anchor, position = self.jump
			self.jump = None
			self.open_at(anchor, position)

	def resolve_highlights(self):
		"""Put stored ranges back where they belong, by the text they covered.

		The offsets are a snapshot of the document text; if the file has been re-read since and
		the words moved, the anchor is what puts the underline back on the sentence a reader
		marked. A range whose text is gone is dropped rather than drawn in the wrong place.
		"""
		self.highlights = []
		for position, span, anchor in self.stored:
			if self.document.text[position:position + span] == anchor:
				self.highlights.append((position, span, anchor))
				continue
			found = self.document.find(anchor)
			if found >= 0:
				self.highlights.append((found, span, anchor))

	def paint(self):
		"""Draw the document with the cursor and the selection it currently has."""
		if self.document is None:
			return
		ranges = [(start, start + span) for start, span, _ in self.highlights]
		if self.selecting:
			ranges.append((self.anchor_offset, self.cursor_offset))
		self.document.paint(cursor=self.cursor_offset, ranges=ranges)

	def top_offset(self):
		"""The offset of the first block on screen."""
		return self.visible_offset(self.query_one(MarkdownViewer).scroll_offset.y)

	def centre_offset(self):
		"""The offset of the block nearest the middle of the screen: where the eye is.

		Not the top of the view. A reader scrolls until the passage they want is in front of
		them, and the top of the screen is by then something they have already read past --
		so a selection that starts there starts in the wrong place.
		"""
		viewer = self.query_one(MarkdownViewer)
		return self.visible_offset(viewer.scroll_offset.y + viewer.size.height // 2)

	def visible_offset(self, row):
		"""The first block at or below a row, in content-space rows."""
		if not self.document or not self.document.blocks:
			return 0
		for block in self.document.blocks:
			# virtual_region, not region: a block scrolled off the top has a negative screen
			# row, and the scroll offset this is compared against lives in content space
			region = block.widget.virtual_region
			if region.y + region.height > row:
				return block.start
		return self.document.blocks[-1].start

	def anchor_at_top(self):
		"""The text of the block at the top of the view, and the row it sits on.

		Stored together so a mark survives a re-render: the row is right until the document
		changes, the text is right as long as those words are still there, and the text is
		what is looked up first.
		"""
		offset = self.top_offset()
		block = self.document.block_at(offset) if self.document else None
		return (block.text[:80] if block else ""), int(self.query_one(MarkdownViewer).scroll_offset.y)

	def open_at(self, anchor, position):
		"""Scroll to a remembered mark: by its text when that text is still there."""
		viewer = self.query_one(MarkdownViewer)
		if self.document and anchor:
			for block in self.document.blocks:
				if anchor[:40] in block.text:
					viewer.scroll_to(y=block.widget.virtual_region.y, animate=False)
					return
		viewer.scroll_to(y=position, animate=False)

	# ------------------------------------------------------------------ the keys

	def action_mark(self) -> None:
		"""`m`: leave a mark here. One per document, and it expires when it is used."""
		self.pending_g = False
		anchor, position = self.anchor_at_top()
		self.post_message(self.Marked(self.book_id, anchor, position))

	def covering(self, offset):
		"""The marked range the cursor is inside, or None. What a second `a` takes away."""
		for start, span, anchor in self.highlights:
			if start <= offset < start + span:
				return (start, span, anchor)
		return None

	def action_select(self) -> None:
		"""`a`: mark a range, or take the mark away.

		Three cases, in the order a reader meets them. Inside a range that is already marked:
		the mark goes. Otherwise: a selection starts at the cursor, the movement keys take
		over, and the next `a` hands the range to the app.
		"""
		if self.document is None:
			return
		self.pending_g = False
		marked = self.covering(self.cursor_offset)
		if not self.selecting and marked:
			self.highlights.remove(marked)
			self.paint()
			self.post_message(self.HighlightRemoved(self.book_id, marked[0], marked[1]))
			self.notify("mark removed")
			return
		if not self.selecting:
			self.selecting = True
			self.cursor_offset = self.centre_offset()
			self.anchor_offset = self.cursor_offset
			self.paint()
			self.notify("selecting: h/l by character, j/k by block, a to mark it, q to drop it")
			return
		start, end = sorted((self.anchor_offset, self.cursor_offset))
		if end - start < 1:
			self.notify("nothing to mark yet -- move the cursor first", severity="warning")
			return
		text = self.document.text[start:end]
		self.selecting = False
		self.highlights.append((start, end - start, text))
		self.paint()
		self.post_message(self.Highlighted(self.book_id, start, end - start, text))

	def move_cursor(self, offset) -> None:
		"""Move the cursor, and take the view with it: the cursor is never off screen."""
		self.pending_g = False
		self.cursor_offset = offset
		self.follow_cursor()
		self.paint()

	def follow_cursor(self) -> None:
		"""Scroll the least that keeps the cursor visible, rather than centring it.

		Scrolling the cursor's block to the top on every `j` would jump the page under the
		reader's eyes on each press. Only the amount that brings it back into view is moved,
		so a line at a time reads as a line at a time.
		"""
		if self.document is None:
			return
		block = self.document.block_at(self.cursor_offset)
		if block is None:
			return
		viewer = self.query_one(MarkdownViewer)
		region = block.widget.virtual_region
		top = viewer.scroll_offset.y
		height = viewer.size.height
		if region.y < top:
			viewer.scroll_to(y=region.y, animate=False)
		elif region.y + region.height > top + height:
			viewer.scroll_to(y=region.y + region.height - height, animate=False)

	def action_cursor_left(self) -> None:
		"""`h`: back a character. The cursor is there to be placed, not only to select with."""
		if self.document:
			self.move_cursor(self.document.move_h(self.cursor_offset))

	def action_cursor_right(self) -> None:
		"""`l`: on a character."""
		if self.document:
			self.move_cursor(self.document.move_l(self.cursor_offset))

	def action_close_preview(self) -> None:
		"""`q`: drop a selection if one is open, otherwise leave.

		The same key backs out of both, so a reader is never stuck holding a selection they
		cannot put down without closing the document.
		"""
		self.pending_g = False
		if self.selecting:
			self.selecting = False
			self.paint()
			self.notify("selection dropped")
			return
		self.dismiss()

	# MarkdownViewer scrolls one row with the arrow keys; j/k jump PREVIEW_SCROLL rows -- or
	# move the cursor a block at a time while a selection is open, which is what the same key
	# means in the mode it is in.
	def action_word_forward(self) -> None:
		"""`w`: the next word. A word is a run of characters between spaces, so a filename and
		a word are the same thing to a reader."""
		if self.document:
			self.move_cursor(self.document.move_w(self.cursor_offset))

	def action_word_back(self) -> None:
		"""`b`: the previous word."""
		if self.document:
			self.move_cursor(self.document.move_b(self.cursor_offset))

	def action_word_end(self) -> None:
		"""`e`: the end of this word, or of the next one from a space."""
		if self.document:
			self.move_cursor(self.document.move_e(self.cursor_offset))

	def action_prefix_g(self) -> None:
		"""`g`: the first half of `gg`. A second `g` goes to the top; anything else forgets it.

		A two-key motion in a one-key reader needs a way out, and the way out here is any
		other key: no timer, no mode to leave, nothing to notice.
		"""
		if not self.document:
			return
		if self.pending_g:
			self.move_cursor(self.document.move_top())
			return
		self.pending_g = True
		self.notify("g -- press g again for the top of the file")

	def action_file_end(self) -> None:
		"""`G`: the last block of the file."""
		if self.document:
			self.move_cursor(self.document.move_bottom())

	def action_file_middle(self) -> None:
		"""`ctrl-g`: the middle block, the way a reader means the middle."""
		if self.document:
			self.move_cursor(self.document.move_middle())

	def action_cursor_down(self) -> None:
		"""`j`: the cursor down a block; the view follows only as far as it must."""
		if self.document:
			self.move_cursor(self.document.move_j(self.cursor_offset))

	def action_cursor_up(self) -> None:
		"""`k`: the cursor up a block."""
		if self.document:
			self.move_cursor(self.document.move_k(self.cursor_offset))

	def scroll_view(self, rows) -> None:
		"""Move the view, and bring the cursor back on screen if it fell off."""
		self.pending_g = False
		self.query_one(MarkdownViewer).scroll_relative(y=rows, animate=False)
		self.clamp_cursor()

	def action_scroll_half_down(self) -> None:
		"""`ctrl-d`: half a page of text, the cursor only if it would be left behind."""
		self.scroll_view(self.query_one(MarkdownViewer).size.height // 2)

	def action_scroll_half_up(self) -> None:
		"""`ctrl-u`: half a page up."""
		self.scroll_view(-self.query_one(MarkdownViewer).size.height // 2)

	def action_scroll_page_down(self) -> None:
		"""`ctrl-f`: a page."""
		self.scroll_view(self.query_one(MarkdownViewer).size.height - 2)

	def action_scroll_page_up(self) -> None:
		"""`ctrl-b`: a page up."""
		self.scroll_view(-(self.query_one(MarkdownViewer).size.height - 2))

	def clamp_cursor(self) -> None:
		"""Keep the cursor on screen after a scroll: a cursor nobody can see is no cursor."""
		if self.document is None or not self.document.blocks:
			return
		viewer = self.query_one(MarkdownViewer)
		top = self.visible_offset(viewer.scroll_offset.y)
		bottom = self.visible_offset(viewer.scroll_offset.y + viewer.size.height - 1)
		if self.cursor_offset < top:
			self.cursor_offset = top
		elif self.cursor_offset > bottom:
			self.cursor_offset = bottom
		self.paint()


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
