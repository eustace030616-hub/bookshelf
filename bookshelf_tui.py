"""The bookshelf app: one list, two modes, over one database.

	j / k      move down / up             (arrows work too)
	Enter      open the file, or expand a folder
	i          inspect -- Markdown and code render in-app, a PDF opens in Quick Look
	m          mount a folder -- browse the disk, confirm, add it as a library
	n          unmount a folder -- pick one, confirm, forget its books
	t          book mode  <->  code mode
	s          selected book: starred (important) on / off
	f          show / hide the star
	q          quit

`t` picks the mode, and the mode picks what `m` and `n` accept: `.pdf` and `.md` in book
mode, `.py` and `.sql` in code mode. Both libraries share one database and never mix on
screen -- the tree, the counts and the status line only ever show the mode you are in.

The dialogs and trees are in bookshelf_screens, the rules for both are in README.md, and
every colour and rule the app draws with is in bookshelf.tcss.

Unmounting only forgets books. It never deletes a file from disk.

Run:  bookshelf            (the command line)  or  python3 bookshelf_tui.py
"""
import sys
import subprocess
from dataclasses import dataclass
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
from bookshelf_scan import CODE_KINDS, KINDS, scan
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


@dataclass(frozen=True)
class Mode:
	"""One mode: its name, the extensions it indexes, and what a row in it is called."""

	name: str
	kinds: dict
	noun: str

	@property
	def extensions(self):
		"""The extensions it takes, for the status line and the picker title."""
		return " ".join(sorted(self.kinds))

	@property
	def plural(self):
		"""What several rows are called, for counts and confirmations."""
		return self.noun + "s"


MODES = {
	"book": Mode("book", KINDS, "book"),
	"code": Mode("code", CODE_KINDS, "code file"),
}

RING = "○"      # no
FILL = "●"      # yes

# On cream, Rich's "yellow" disappears. Both star styles are named explicitly: a dark
# gold for yes, a muted warm grey for no.
ON_STYLE = "#B8860B"
OFF_STYLE = "#A89F85"

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


def open_path(path):
	"""Hand the file to the OS default application.

	On macOS /usr/bin/open returns immediately for GUI apps, so the TUI keeps running.
	For a terminal editor you would need to suspend the app first.
	"""
	subprocess.run(["open", str(path)], check=False)


def quicklook(path):
	"""Finder's space bar, from the command line: /usr/bin/qlmanage -p.

	Launched, not waited on, and its output is discarded -- qlmanage writes progress text
	to stdout that would otherwise land in the middle of the TUI.
	"""
	subprocess.Popen(
		["qlmanage", "-p", str(path)],
		stdout=subprocess.DEVNULL,
		stderr=subprocess.DEVNULL,
	)


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
		Binding("f", "toggle_stars", "star"),
		Binding("s", "toggle_important", "starred"),
		Binding("q", "quit", "quit"),
	]

	def __init__(self, db_path):
		super().__init__()
		self.db_path = str(db_path)
		self.mode = MODES["book"]
		self.stars_on = False
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

	def check_action(self, action, parameters):
		# A dialog owns the keyboard. Without this, t/f/s/i would still act on the list
		# behind it, because App bindings stay live while a screen is stacked.
		return len(self.screen_stack) == 1

	def name_of(self, row):
		"""One file as the current mode draws it: `schema.sql` in code mode, the stem in book
		mode. A drawing rule only -- `books.title` holds the stem in both modes."""
		return row["path"].rsplit("/", 1)[-1] if self.mode.name == "code" else row["title"]

	def row_text(self, row):
		"""One row as the list draws it, prefixed by the star sphere when `f` is on."""
		name = self.name_of(row)
		if not self.stars_on:
			return Text(name)
		on = bool(row["is_important"])
		return Text.assemble((FILL if on else RING, ON_STYLE if on else OFF_STYLE), " ", name)

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
		selected = self.name_of(node.data) if node and node.data else "-"
		self.say(
			f"{len(self.rows)} {self.mode.plural}  |  mode: {self.mode.name} ({self.mode.extensions})"
			f"  |  stars: {'on' if self.stars_on else 'off'}  |  {selected}"
		)

	def say(self, text) -> None:
		"""Replace the status line. Used while a mount is counting, before there are rows."""
		self.query_one("#status", Static).update(text)

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

	def action_toggle_stars(self) -> None:
		self.stars_on = not self.stars_on
		self.reload()

	def action_inspect(self) -> None:
		"""`i`: render text in the app, hand a PDF to Quick Look."""
		row = self.selected()
		if row is None:
			return
		path = Path(row["root_path"]) / row["path"]
		if row["kind"] == "pdf":
			# A terminal cannot render a PDF page, so use the thing that can.
			quicklook(path)
			return
		try:
			body = path.read_text(encoding="utf-8")
		except (OSError, UnicodeDecodeError) as error:
			self.notify(f"cannot read: {error}", severity="error")
			return
		if row["kind"] != "md":
			# Code goes to the same viewer as Markdown, wrapped in one fence: inside a fence
			# `#` stays a comment instead of becoming a heading, and the fence carries the
			# language that colours it.
			body = fenced(body, LANGUAGES.get(row["kind"], row["kind"]))
		self.push_screen(Preview(f"{row['root_label']} / {row['path']}", body))

	def action_toggle_important(self) -> None:
		"""Toggle the star on the selected row."""
		row = self.selected()
		if row is None:
			return
		want = 0 if row["is_important"] else 1
		with db.session(self.db_path) as conn:
			repo.set_important(conn, row["id"], want)
		self.notify(f"{self.name_of(row)} -> {'starred' if want else 'unstarred'}")
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
		count lands. `mode` is captured here: `t` may be pressed while the walk runs, and the
		walk has to stay the one that was started.
		"""
		if chosen is None:
			return
		mode = self.mode
		self.say(f"counting {chosen} for {mode.extensions} ...")
		self.index(chosen, mode)

	@work(thread=True)
	def index(self, chosen, mode) -> None:
		"""Walk the folder and record it, in a thread. Reports back on the UI thread."""
		found = list(scan(chosen, mode.kinds))
		with db.session(self.db_path) as conn:
			try:
				root_id = repo.add_root(conn, str(chosen))
			except ValueError as error:
				self.call_from_thread(self.notify, str(error), severity="error")
				return
			for path, title, kind in found:
				repo.add_book(conn, root_id, path, title, kind)
		self.call_from_thread(self.indexed, chosen, mode, len(found))

	def indexed(self, chosen, mode, count) -> None:
		"""Back on the UI thread: the folder is in the database, so redraw."""
		self.reload()
		self.notify(f"mounted {chosen.name} -- {count} {mode.plural}")

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
