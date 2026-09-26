"""The bookshelf app: one list, two modes, over one database.

	j / k      move down / up             (arrows work too)
	Enter      open the file, or expand a folder
	i          inspect -- Markdown and code render in-app; Enter opens a file outside
	m          mount a folder -- browse the disk, confirm, add it as a library
	n          unmount a folder -- pick one, confirm, forget its books
	t          book mode  <->  code mode
	u          update -- re-walk the mounted folders and match the shelf to the disk
	s          selected book: starred (important) on / off
	q          quit

`t` picks the mode, and the mode picks what the list shows: `.md` in book mode, `.py` and
`.sql` in code mode. Only what the shelf can draw is indexed -- a converted document is
Markdown by the time it lands here -- so one document is one row. Both libraries share one
database and never mix on screen: the tree, the counts and the status line only ever show
the mode you are in.

The dialogs and trees are in bookshelf_screens, the rules for both are in README.md, and
every colour and rule the app draws with is in bookshelf.tcss.

Unmounting only forgets books. It never deletes a file from disk.
Run:  bookshelf            (the command line)  or  python3 bookshelf_tui.py
"""
import sys
import subprocess
from pathlib import Path

from rich.text import Text
from pygments.token import Token
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.highlight import HighlightTheme, highlight
from textual.theme import Theme
from textual.widgets import Footer, Header, Markdown, Static
from textual.widgets._markdown import MarkdownFence

import bookshelf_db as db
import bookshelf_repo as repo
from bookshelf_scan import EVERY_KIND, MODES, row_name, star_mark
from bookshelf_screens import BookTree, MountScreen, Preview, UnmountScreen, find_node, force_line_rebuild
from bookshelf_tree import children, plan

DB_FILE = Path(__file__).parent / "shelf.db"

# Light warm yellow. `dark=False` is what makes every widget in Textual pick light-mode
# defaults for anything this palette does not name.
THEME = Theme(
	name="parchment",
	dark=False,
	background="#FDFAF1",
	surface="#FAF4E6",
	panel="#F4EDD9",
	foreground="#3D3A31",
	primary="#8A6A1B",
	secondary="#B08C3A",
	accent="#B8860B",
	warning="#B8860B",
	error="#A33A2A",
	success="#5F7A2E",
)


# Must equal the `tab_size` handed to highlight() in CodeFence.highlight.
TAB_SIZE = 8

# Textual's default code palette is built for a dark UI: it maps tokens onto the theme's
# five accent hues and draws operators bold, `self` italic and function names underlined.
# On cream those hues sit between 3.0:1 and 4.8:1 of the background, so a file reads as
# noise -- a stray letter looks stressed, one identifier in three looks a different
# colour. The palette below is named in literal hex instead, each colour measured against
# #FDFAF1, with every text-style off. Anything not listed is plain foreground at 10.9:1,
# which is what carries most of a file.
CODE_STYLES = {
	Token.Comment: "#6F6A5C",          # 5.2:1
	Token.Keyword: "#8C3A24",          # 7.3:1
	Token.Literal.String: "#4E6425",   # 6.3:1
	Token.Literal.Number: "#8A6A1B",   # 4.8:1
	Token.Name.Decorator: "#8A6A1B",   # 4.8:1
}


class CodeHighlight(HighlightTheme):
	"""The five colours above and nothing else -- no bold, no italic, no underline.

	The default palette is not inherited on purpose: it is the decorations and the six
	accent hues that made code unreadable here, so a token it styles must fall back to
	plain text rather than keep its mapping.
	"""

	STYLES = CODE_STYLES


class CodeFence(MarkdownFence):
	"""A fenced code block drawn in CodeHighlight instead of Textual's default palette.

	`highlight` is the only method the base builds its content with -- once in __init__
	and again when the theme changes -- so overriding it is the whole change.
	"""

	@classmethod
	def highlight(cls, code, language, ansi=False, dark=False):
		# Tabs are expanded before highlighting, and that is the point of the override.
		# Pygments tokenises `text.expandtabs(tabsize)`, Textual then styles the string it
		# was handed -- tabs and all. So in a tab-indented file every character after the
		# first tab is styled with the token that belongs eight columns later: a `#` mid-line
		# goes brown, one identifier in three changes colour. Expanding here makes the
		# tokenised text and the styled text the same string.
		# ansi and dark are dropped on purpose: this palette is one set of hex colours solved
		# against the app background, and the app is light-mode only.
		code = code.expandtabs(TAB_SIZE)
		return highlight(code, language=language or None, theme=CodeHighlight, tab_size=TAB_SIZE)


# Textual picks the widget for a fenced block out of Markdown.BLOCKS, which is private. The
# getattr keeps a Textual that renames it from taking the app down: without this line code
# falls back to Textual's own palette and nothing else changes.
if (blocks := getattr(Markdown, "BLOCKS", None)) is not None:
	blocks["fence"] = CodeFence
	blocks["code_block"] = CodeFence


# kind -> Pygments lexer name, for the fence code is wrapped in before Preview renders it.
# A kind that is not here is passed through as its own name: Pygments and markdown-it both
# fall back to plain text rather than raising, so an unmapped kind shows uncoloured code.
LANGUAGES = {
	"py": "python",
	"sql": "sql",
}

# Where the `m` folder browser opens. Change to Path("/") to reach every volume.
PICKER_ROOT = Path.home()

# Re-walk every mounted folder when the app opens. Files are not watched, so the shelf is
# only ever as fresh as its last walk; this is what makes the first thing you see true.
# The walk runs in a worker either way, so turning it off costs freshness, never latency.
SYNC_ON_START = True


def open_path(path):
	"""Hand the file to the OS default application.

	On macOS /usr/bin/open returns immediately for GUI apps, so the TUI keeps running.
	For a terminal editor you would need to suspend the app first.
	"""
	subprocess.run(["open", str(path)], check=False)


def fenced(code, language):
	"""Wrap code in a fence that no backtick run inside it can close.

	CommonMark closes a fence with a run at least as long as the one that opened it, so one
	backtick more than the longest run in the file is always enough. Without that, a ```
	inside a Python docstring would end the block and the rest would render as prose.
	"""
	run = longest = 0
	for char in code:
		run = run + 1 if char == "`" else 0
		longest = max(longest, run)
	bar = "`" * max(3, longest + 1)
	return f"{bar}{language}\n{code.rstrip(chr(10))}\n{bar}"


class BookshelfApp(App):
	TITLE = "bookshelf"
	CSS_PATH = "bookshelf.tcss"

	BINDINGS = [
		Binding("t", "toggle_mode", "book/code"),
		Binding("i", "inspect", "inspect"),
		Binding("m", "mount", "mount"),
		Binding("n", "unmount", "unmount"),
		Binding("u", "sync", "update"),
		Binding("s", "toggle_important", "starred"),
		Binding("q", "quit", "quit"),
	]

	def __init__(self, db_path):
		super().__init__()
		self.db_path = str(db_path)
		self.mode = MODES["book"]
		self.syncing = False         # a walk is running; set and cleared on the UI thread
		self.rows = []
		self.selected_id = None        # survives across reloads

	# ------------------------------------------------------------- the list

	def compose(self) -> ComposeResult:
		yield Header()
		yield BookTree("library", id="books")
		yield Static("", id="status")
		yield Footer()

	def on_mount(self) -> None:
		self.register_theme(THEME)
		self.theme = THEME.name
		self.reload()
		if SYNC_ON_START:
			self.start_sync()

	def check_action(self, action, parameters):
		# A dialog owns the keyboard. Without this, t/f/s/i would still act on the list
		# behind it, because App bindings stay live while a screen is stacked.
		return len(self.screen_stack) == 1


	def row_text(self, row):
		"""One row as the list draws it, with its star in front -- filled, or an empty ring.

		The mark is always drawn: it answers "have I read this", and a view that has to be
		switched on to show it is a view you have to remember to switch on.
		"""
		glyph, colour = star_mark(row)
		return Text.assemble((glyph, colour), " ", row_name(row, self.mode))

	def reload(self) -> None:
		"""Re-query and rebuild the tree for the current mode. The library is tiny.

		Only this mode's kinds are loaded, so the tree, the counts and the status line
		describe one library. The other mode's rows stay in the database, untouched.
		"""
		wanted = set(self.mode.kinds.values())
		with db.session(self.db_path) as conn:
			rows = repo.list_books(conn, order="path")
		self.rows = [row for row in rows if row["kind"] in wanted]

		tree = self.query_one("#books", BookTree)
		root = tree.root
		root.remove_children()
		root.expand()

		label, multi, entries = plan(self.rows)
		root.set_label(label)
		for name, subtree in entries:
			parent = root.add(f"{name}/") if multi else root
			if multi:
				parent.expand()
			self.add_subtree(parent, subtree)
		if not self.rows:
			root.add_leaf("(empty)")

		# Put the cursor back where it was, or on the first real row. Without this the
		# cursor keeps a stale line number across a reload and lands on a folder.
		target = None
		if self.selected_id is not None:
			target = find_node(root, lambda n: n.data and n.data["id"] == self.selected_id)
		if target is None:
			target = find_node(root, lambda n: n.data is not None)
		if target is not None:
			force_line_rebuild(tree)
			tree.move_cursor(target)

		self.update_status()

	def add_subtree(self, node, subtree) -> None:
		"""One level of the shared tree shape, as Textual nodes."""
		for name, value, is_dir in children(subtree):
			if not is_dir:
				node.add_leaf(self.row_text(value), data=dict(value))
				continue
			branch = node.add(f"{name}/")
			branch.expand()
			self.add_subtree(branch, value)

	def update_status(self) -> None:
		node = self.query_one("#books", BookTree).cursor_node
		selected = row_name(node.data, self.mode) if node and node.data else "-"
		self.say(
			f"{len(self.rows)} {self.mode.plural}  |  mode: {self.mode.name} ({self.mode.extensions})"
			f"  |  {selected}"
		)

	def say(self, text) -> None:
		"""Replace the status line. Used while a mount is counting, before there are rows."""
		self.query_one("#status", Static).update(text)

	# ------------------------------------------------------------- update

	def action_sync(self) -> None:
		"""`u`: re-walk every mounted folder and match the shelf to the disk."""
		self.start_sync(quiet=False)

	def start_sync(self, quiet=True) -> None:
		"""Walk every root in a worker. `quiet` is the startup walk: it says nothing unless
		it found something, because a shelf that has not changed should not interrupt you."""
		if self.syncing:
			self.notify("already scanning the folders")
			return
		with db.session(self.db_path) as conn:
			roots = len(repo.list_roots(conn))
		if not roots:
			if not quiet:
				self.notify("nothing is mounted yet")
			return
		self.syncing = True
		self.say(f"scanning {roots} mounted folder(s) ...")
		self.walk_roots(quiet)

	@work(thread=True)
	def walk_roots(self, quiet) -> None:
		"""The walk, off the UI thread: a root can be an entire home directory."""
		added = removed = ingested = missing = 0
		stored = 0
		with db.session(self.db_path) as conn:
			for root in repo.list_roots(conn):
				a, r, read, gone = repo.sync_root(conn, root["id"], EVERY_KIND)
				added, removed, ingested, missing = added + a, removed + r, ingested + read, missing + gone
			stored = repo.stored_totals(conn)[1]
		self.call_from_thread(self.synced, added, removed, ingested, stored, missing, quiet)

	def synced(self, added, removed, ingested, stored, missing, quiet) -> None:
		"""Back on the UI thread: the table matches the disk, so redraw."""
		self.syncing = False
		self.reload()
		if quiet and not (added or removed or ingested or missing):
			return
		change = [
			f"{added} new" if added else "",
			f"{removed} gone" if removed else "",
			f"{ingested} file(s) read" if ingested else "",
		]
		note = ", ".join(part for part in change if part) or "no changes"
		note += f"  |  {stored / 1e6:.1f} MB stored" if stored else ""
		if missing:
			self.notify(f"update: {note}  |  {missing} root(s) not on disk", severity="warning")
		else:
			self.notify(f"update: {note}")

	# ------------------------------------------------------------- actions

	def selected(self):
		"""The dict of the highlighted row, or None if a folder is highlighted."""
		node = self.query_one("#books", BookTree).cursor_node
		if node is None or node.data is None:
			self.notify(f"select a {self.mode.noun} first", severity="warning")
			return None
		return node.data

	def action_toggle_mode(self) -> None:
		"""`t`: book mode <-> code mode.

		The selection is dropped: it is an id from the other mode's rows, and carrying it
		over would just make reload() search the tree for something that is not there.
		"""
		self.mode = MODES["code" if self.mode.name == "book" else "book"]
		self.selected_id = None
		self.reload()
		self.notify(f"{self.mode.name} mode -- m and n now take {self.mode.extensions}")

	def action_inspect(self) -> None:
		"""`i`: render the document, from the database.

		The body comes from the content table -- the same bytes a server without the files will
		read -- so the app and the phone render one source, not two. A row the walk has not
		ingested yet (added before revision 5) is read from disk once and stored on the way
		through, so the next `i` is a query and the next `u` costs nothing for it.

		Markdown and code are text, so they are drawn as they are.
		"""
		row = self.selected()
		if row is None:
			return
		with db.session(self.db_path) as conn:
			body = repo.content_of(conn, row["id"])
			if body is None:
				body = self.read_and_store(conn, row)
			# Taken, not read: a mark is spent by opening the document, so the jump happens
			# once. Reading it here and passing it down keeps the database in the app.
			mark = repo.take_mark(conn, row["id"])
			highlights = repo.highlights_for(conn, row["id"])
			notes = repo.notes_for(conn, row["id"])
		if body is None:
			return
		if row["kind"] != "md":
			# Code goes to the same viewer as Markdown, wrapped in one fence: inside a fence
			# `#` stays a comment instead of becoming a heading, and the fence carries the
			# language that colours it.
			body = fenced(body, LANGUAGES.get(row["kind"], row["kind"]))
		self.push_screen(
			Preview(f"{row['root_label']} / {row['path']}", body, book_id=row["id"],
					jump=tuple(mark) if mark else None, highlights=highlights,
					notes=notes)
		)
		if mark:
			self.notify("opened at your mark -- it has now expired")

	def on_preview_marked(self, message: Preview.Marked) -> None:
		"""The reader pressed `m` in the preview: remember the place, and only that place."""
		with db.session(self.db_path) as conn:
			repo.set_mark(conn, message.book_id, message.anchor, message.position)
		where = message.anchor[:40] or f"row {message.position}"
		self.notify(f"marked at {where!r} -- one jump, then it expires")

	def on_preview_highlighted(self, message: Preview.Highlighted) -> None:
		"""The reader marked a range: keep it, anchored to the words it covers."""
		with db.session(self.db_path) as conn:
			repo.add_highlight(conn, message.book_id, message.position, message.span, message.anchor)
		self.notify(f"marked {len(message.anchor)} character(s)")

	def on_preview_note_saved(self, message: Preview.NoteSaved) -> None:
		"""The reader wrote on a line: keep the note against that line's text."""
		with db.session(self.db_path) as conn:
			repo.set_note(conn, message.book_id, message.position, message.anchor, message.note)
		self.notify(f"note: {message.note[:40]}")

	def on_preview_note_removed(self, message: Preview.NoteRemoved) -> None:
		"""The reader deleted a note, after the guard."""
		with db.session(self.db_path) as conn:
			repo.remove_note(conn, message.book_id, message.position)
		self.notify("note deleted")

	def on_preview_highlight_removed(self, message: Preview.HighlightRemoved) -> None:
		"""The reader pressed `a` inside a marked range: that range goes."""
		with db.session(self.db_path) as conn:
			repo.remove_highlight(conn, message.book_id, message.position, message.span)

	def read_and_store(self, conn, row):
		"""Read one row's file and store it, for a row that predates the content table."""
		path = Path(row["root_path"]) / row["path"]
		if not repo.ingest(conn, row["id"], path):
			self.notify(f"cannot read {row['path']} -- `u` will retry it", severity="error")
			return None
		return repo.content_of(conn, row["id"])

	def action_toggle_important(self) -> None:
		"""Toggle the star on the selected row."""
		row = self.selected()
		if row is None:
			return
		want = 0 if row["is_important"] else 1
		with db.session(self.db_path) as conn:
			repo.set_important(conn, row["id"], want)
		self.notify(f"{row_name(row, self.mode)} -> {'starred' if want else 'unstarred'}")
		self.reload()

	# ------------------------------------------------------- mount/unmount

	def action_mount(self) -> None:
		"""Open the folder browser; `mounted` runs when it closes with a folder."""
		with db.session(self.db_path) as conn:
			already = [r["path"] for r in repo.list_roots(conn)]
		self.push_screen(MountScreen(PICKER_ROOT, already, self.mode), self.mounted)

	def mounted(self, chosen) -> None:
		"""A folder was chosen: index it, off the UI thread.

		The walk is unbounded -- ~/ takes about 36 seconds -- so it cannot run on the UI
		thread. The status line says a count is happening, and the tree is redrawn when the
		count lands.
		"""
		if chosen is None:
			return
		self.say(f"counting {chosen} ...")
		self.index(chosen)

	@work(thread=True)
	def index(self, chosen) -> None:
		"""Walk the folder and record it, in a thread. Reports back on the UI thread.

		This is the same call `u` makes, with the same map. A mounted folder contributes
		every file the shelf can hold and `t` decides which of them you see, because the two
		rules used to differ: mount indexed one mode's kinds, a re-walk found all of them, and
		the first `u` after a mount changed the shelf by itself.
		"""
		with db.session(self.db_path) as conn:
			try:
				root_id = repo.add_root(conn, str(chosen))
			except ValueError as error:
				self.call_from_thread(self.notify, str(error), severity="error")
				return
			added, _, ingested, _ = repo.sync_root(conn, root_id, EVERY_KIND)
		self.call_from_thread(self.indexed, chosen, added, ingested)

	def indexed(self, chosen, added, ingested) -> None:
		"""Back on the UI thread: the folder is in the database, so redraw."""
		self.reload()
		self.notify(f"mounted {chosen.name} -- {added} new file(s), {ingested} read")

	def action_unmount(self) -> None:
		"""Pick a mounted folder to forget. Only folders holding this mode's files are listed."""
		with db.session(self.db_path) as conn:
			totals = {r["id"]: r["n"] for r in repo.list_roots(conn)}
			roots = repo.list_roots(conn, self.mode.kinds.values())
		# A root is a folder, not a row per mode: unmounting it forgets everything under it,
		# so the guard wants both numbers -- this mode's files, and the folder's total.
		roots = [dict(r, total=totals[r["id"]]) for r in roots if r["n"]]
		if not roots:
			self.notify(f"nothing is mounted with {self.mode.extensions} in it")
			return
		self.push_screen(UnmountScreen(roots, self.mode), self.unmounted)

	def unmounted(self, root_id) -> None:
		if root_id is None:
			return
		with db.session(self.db_path) as conn:
			label = repo.get_root(conn, root_id)["label"]
			repo.remove_root(conn, root_id)
		self.selected_id = None
		self.reload()
		self.notify(f"unmounted {label} -- files untouched")

	# ------------------------------------------------------------ messages

	def on_tree_node_selected(self, event) -> None:
		"""Enter: a folder toggles, a file opens.

		NodeSelected bubbles up from *any* Tree -- the folder picker, the unmount list --
		whose nodes carry a DirEntry or a roots row, not a book row. Everything below this
		line assumes a book row, so filter on the sender first.
		"""
		if event.control is not self.query_one("#books", BookTree):
			return
		node = event.node
		if node.data is None:
			node.toggle()
			return
		open_path(Path(node.data["root_path"]) / node.data["path"])

	def on_tree_node_highlighted(self, event) -> None:
		if event.control is not self.query_one("#books", BookTree):
			return
		if event.node.data is not None:
			self.selected_id = event.node.data["id"]
		self.update_status()


def run(db_path) -> int:
	"""Bootstrap the database and open the shelf. The `bookshelf` command calls this."""
	db.bootstrap(db_path)
	BookshelfApp(db_path).run()
	return 0


def main(argv=None):
	"""Run the app without the command line: python3 bookshelf_tui.py [database]."""
	argv = sys.argv[1:] if argv is None else list(argv)
	return run(argv[0] if argv else str(DB_FILE))


if __name__ == "__main__":
	sys.exit(main())
