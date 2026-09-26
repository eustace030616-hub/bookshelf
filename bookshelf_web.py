"""The shelf over HTTP, for a browser that is not on the machine with the folders.

Read-only, and read-only by construction rather than by promise: every route is a GET, the
database is opened with `mode=ro` so SQLite itself refuses a write, and there is no POST,
DELETE or PUT anywhere in this file. Mounting, unmounting, updating and starring live in the
terminal app, on the machine that has the files; a phone is a viewer.

	python3 bookshelf_web.py --db shelf.db                    # localhost only
	python3 bookshelf_web.py --db shelf.db --host 0.0.0.0 --token SECRET

	GET /              the index, one mode at a time: `?mode=code`
	GET /doc/<id>      one document, rendered for a browser
	GET /raw/<id>      the stored text, exactly as it is
	GET /health        counts, bytes, and when the shelf was last walked

Two things it does not need. Textual, because nothing here touches the terminal: the image
that runs this can leave the UI library out, and then the import itself is the proof. And
markdown-it, because a container built from `python:3.13-slim` has nothing installed -- when
the library is absent, the small renderer at the bottom of this file takes over.

The routes address rows by id, never by path, so there is no path for a request to traverse.
"""

import os
import re
import json
import html
import sqlite3
import argparse
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import bookshelf_db as db
import bookshelf_repo as repo
from bookshelf_annotate import annotate
from bookshelf_scan import MODES, OFF_COLOUR, ON_COLOUR, row_name, star_mark
from bookshelf_tree import children, plan

VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1">'

# The palette is bookshelf.tcss's, so a page served to a phone and the app on the desk look
# like the same shelf.
STYLE = """
:root { color-scheme: light dark; --ink:#3D3A31; --paper:#FDFAF1; --panel:#F4EDD9;
        --brand:#8A6A1B; --star-on:{star_on}; --star-off:{star_off}; }
body { margin:0 auto; max-width:44rem; padding:0 1.6rem 4rem; background:var(--paper);
       color:var(--ink); font:16px/1.6 Charter, Georgia, "Times New Roman", serif; }
h1,h2,h3 { line-height:1.25; } h1 { font-size:1.5rem; } h2 { font-size:1.15rem; }
a { color:var(--brand); text-decoration:none; } a:hover { text-decoration:underline; }
header { position:sticky; top:0; z-index:10; background:var(--paper);
         border-bottom:1px solid var(--panel); margin-bottom:1rem; padding:.5rem 0; }
header::after { content:""; display:block; clear:both; }
nav a { margin-right:.9rem; font-weight:600; } nav a[aria-current] { text-decoration:underline; }
ul.tree { list-style:none; padding-left:.2rem; } ul.tree ul { padding-left:1.1rem; }
li.folder > span { color:var(--brand); font-weight:600; }
li.file { margin:.15rem 0; }
.dot { font-size:.9em; } .dot.on { color:var(--star-on); } .dot.off { color:var(--star-off); }
pre { background:var(--panel); padding:.7rem .8rem; border-radius:4px; overflow-x:auto;
      font:13px/1.45 "JetBrains Mono", ui-monospace, Menlo, monospace; }
code { font-family:"JetBrains Mono", ui-monospace, Menlo, monospace; font-size:.92em; }
table { border-collapse:collapse; width:100%; font-size:.95rem; }
th,td { text-align:left; padding:.35rem .5rem; border-bottom:1px solid var(--panel); }
img { max-width:100%; height:auto; }
/* The app's own code palette, so a .py page in the browser and in the terminal match:
   comment grey, keyword brick, string olive, number and decorator gold, rest ink. */
pre.code { border:1px solid var(--panel); }
.c, .c1, .cm { color:#6F6A5C; font-style:italic; }
.k, .kn, .kd, .kc { color:#8C3A24; }
.s, .s1, .s2, .sd, .sb { color:#4E6425; }
.m, .mi, .mf, .mh { color:#8A6A1B; }
.nd { color:#8A6A1B; }
.nf, .nc { color:var(--ink); font-weight:600; }
@media (max-width: 44rem) {
  body { padding:0 1.4rem 3.5rem; font-size:17px; }
  nav input[type=search] { width:6.5rem; }
  table { display:block; overflow-x:auto; }
  h1 { font-size:1.35rem; }
}
blockquote { margin:0; padding-left:.9rem; border-left:3px solid var(--brand); color:#5b574c; }
/* the reader's own marks, the same in the browser as in the terminal: a warm wash behind the
   words they highlighted, and a note set above the block it was written on */
mark.mark { background:#F0E2B8; color:inherit; padding:0 .08em; border-radius:2px; }
.note { background:var(--panel); border-left:3px solid var(--brand); border-radius:4px;
        padding:.45rem .7rem; margin:.6rem 0; white-space:pre-wrap; font-size:.95rem;
        scroll-margin-top:3.5rem; }
.note-label { display:block; font-size:.72rem; letter-spacing:.08em; text-transform:uppercase;
              color:var(--brand); font-weight:700; }
/* find-on-page, in the nav beside `note`. Its hits are a cool wash so they never read as the
   reader's own warm highlights, and the current hit is the darker of the two. */
nav input[type=search] { width:9rem; font:inherit; font-size:.9rem; padding:.05rem .4rem;
                         color:var(--ink); background:var(--paper);
                         border:1px solid var(--panel); border-radius:4px; }
.hit { background:#DCE6F0; color:inherit; border-radius:2px; }
.hit-current { background:#A9C9DE; }
footer { margin-top:2rem; color:#6b6a64; font-size:.85rem; }
#changed { position:sticky; bottom:0; margin-top:1rem; text-align:center; }
#changed a { display:inline-block; padding:.45rem .9rem; border-radius:999px; font-size:.9rem;
            background:var(--brand); color:var(--paper); text-decoration:none; }
nav a[title] { float:right; margin-right:0; font-weight:400; font-size:.9rem; }
.meta { color:#6b6a64; font-size:.85rem; }
@media (prefers-color-scheme: dark) {
  :root { --ink:#e6e1d6; --paper:#191813; --panel:#242219; --brand:#d3ab52; }
  blockquote { color:#b9b3a5; } .meta, footer { color:#9a9488; }
  mark.mark { background:#5c4d22; }
  .hit { background:#33506a; } .hit-current { background:#4c7195; }
}
"""

PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">{viewport}<title>{title}</title>
<style>{style}</style></head>
<body><header><nav>{nav}{reload_link}</nav></header>
<main>{body}</main>
<div id="changed" hidden><a href="{reload_href}">the shelf changed &middot; reload</a></div>
<footer>{footer}</footer>{watcher}</body></html>
"""

# Polling, not pushing. A page says which stamp it was rendered from; a few seconds later it
# asks the server for the current one and, if it differs, reveals a bar offering a reload. It
# never reloads by itself: a reader halfway down a document loses their place, and the whole
# point of the button is that they decide. `.md` rendering and the stamp both come from the
# database, so a change in the file on the Mac reaches a phone only after the copy is synced
# -- this notices what the server's own copy did.
WATCHER = """<script>
(function () {
  var here = %(stamp)s, url = %(url)s, bar = document.getElementById("changed");
  setInterval(function () {
    fetch(url, {cache: "no-store"}).then(function (r) { return r.json(); }).then(function (now) {
      if (now.stamp !== here) { bar.hidden = false; }
    }).catch(function () {});
  }, %(every)d);
})();
</script>"""


def page(title, body, nav, footer="", stamp=None, watch_url="/health", reload_href="", every=10):
	"""One page. Given a stamp, the page also watches the server for a newer one."""
	watcher = ""
	if stamp is not None:
		watcher = WATCHER % {"stamp": json.dumps(stamp), "url": json.dumps(watch_url), "every": every * 1000}
	return PAGE.format(
		viewport=VIEWPORT,
		title=html.escape(title),
		style=STYLE.replace("{star_on}", ON_COLOUR).replace("{star_off}", OFF_COLOUR),
		nav=nav,
		reload_link=f'<a href="{reload_href or "/"}" title="pull the database again">reload</a>',
		reload_href=reload_href or "/",
		body=body,
		footer=footer,
		watcher=watcher,
	)


def nav(mode, counts=None):
	"""The mode switch, as links. Counts are shown in the index, not on a document page."""
	parts = []
	for name, other in MODES.items():
		mark = ' aria-current="page"' if name == mode.name else ""
		label = f"{name} ({counts[name]})" if counts else name
		parts.append(f'<a href="/?mode={name}"{mark}>{label}</a>')
	return "".join(parts)


# The document page's own navigation. The book/code buttons belong to the shelf, not here: a
# document is already one mode's row, and the mode is the shelf's choice. What a document has
# to move around is its own notes -- a click steps to the next one in reading order, wrapping
# -- and the script hooks that onto the button. Without the script the button is still a plain
# link to the first note, because every callout carries the id the anchor points at.
NOTE_SCRIPT = """<script>
(function () {
  var notes = document.querySelectorAll(".note");
  var button = document.getElementById("note-next");
  if (!button || !notes.length) { return; }
  var at = -1, plain = button.textContent;
  function label() { button.textContent = plain + " " + (at + 1) + "/" + notes.length; }
  button.addEventListener("click", function (event) {
    event.preventDefault();
    at = (at + 1) % notes.length;
    notes[at].scrollIntoView({behavior: "smooth", block: "center"});
    label();
  });
  button.textContent = plain + " " + notes.length;
})();
</script>"""


def notes_nav(count):
	"""The note button for a document page, or nothing when the page has no notes."""
	if not count:
		return ""
	return '<a href="#note-1" id="note-next" aria-label="jump to the next note">note</a>'


# Find on the page, beside the note button. Client-side, because the page is already here: no
# route, no index, and it works on a document the server rendered from an anchor it could only
# guess at. It wraps its hits in its own span, so the server's <mark> highlights survive it.
FIND_BOX = ('<input id="find" type="search" placeholder="find" aria-label="find on this page" '
            'autocomplete="off" spellcheck="false">')

FIND_SCRIPT = """<script>
(function () {
  var box = document.getElementById("find");
  var main = document.querySelector("main");
  if (!box || !main) { return; }
  var hits = [], at = -1;
  function clear() {
    var wrapped = main.querySelectorAll("span.hit");
    for (var i = 0; i < wrapped.length; i++) {
      wrapped[i].replaceWith(document.createTextNode(wrapped[i].textContent));
    }
    main.normalize();
    hits = []; at = -1;
  }
  function textNodes() {
    var walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        if (!node.nodeValue || !node.nodeValue.trim()) { return NodeFilter.FILTER_REJECT; }
        for (var p = node.parentNode; p && p !== main; p = p.parentNode) {
          if (p.nodeName === "SCRIPT" || p.nodeName === "STYLE") { return NodeFilter.FILTER_REJECT; }
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var out = [], node;
    while ((node = walker.nextNode())) { out.push(node); }
    return out;
  }
  function mark(query) {
    clear();
    var needle = query.toLowerCase();
    if (!needle) { return; }
    var list = textNodes();
    for (var i = 0; i < list.length; i++) {
      var node = list[i], text = node.nodeValue, lower = text.toLowerCase();
      if (lower.indexOf(needle) === -1) { continue; }
      var frag = document.createDocumentFragment(), last = 0, found;
      while ((found = lower.indexOf(needle, last)) !== -1) {
        frag.appendChild(document.createTextNode(text.slice(last, found)));
        var span = document.createElement("span");
        span.className = "hit";
        span.textContent = text.slice(found, found + needle.length);
        frag.appendChild(span);
        hits.push(span);
        last = found + needle.length;
      }
      frag.appendChild(document.createTextNode(text.slice(last)));
      node.parentNode.replaceChild(frag, node);
    }
  }
  function show() {
    for (var i = 0; i < hits.length; i++) { hits[i].classList.remove("hit-current"); }
    if (hits.length && hits[at]) {
      hits[at].classList.add("hit-current");
      hits[at].scrollIntoView({behavior: "smooth", block: "center"});
      box.placeholder = (at + 1) + "/" + hits.length;
    } else {
      box.placeholder = "find";
    }
  }
  function step(delta) {
    if (!hits.length) { return; }
    at = (at + delta + hits.length) % hits.length;
    show();
  }
  box.addEventListener("input", function () {
    mark(box.value);
    at = hits.length ? 0 : -1;
    show();
  });
  box.addEventListener("keydown", function (event) {
    if (event.key === "Enter") { event.preventDefault(); step(event.shiftKey ? -1 : 1); }
    if (event.key === "Escape") { box.value = ""; clear(); box.placeholder = "find"; }
  });
})();
</script>"""


def tree_html(subtree, mode):
	"""The shared tree shape as a nested list -- the same order the terminal app draws."""
	items = []
	for name, value, is_dir in children(subtree):
		if is_dir:
			items.append(
				f'<li class="folder"><span>{html.escape(name)}/</span>'
				f"<ul>{tree_html(value, mode)}</ul></li>"
			)
			continue
		row = value
		glyph, _ = star_mark(row)
		state = "on" if row["is_important"] else "off"
		items.append(
			f'<li class="file"><a href="/doc/{row["id"]}">'
			f'<span class="dot {state}">{glyph}</span> {html.escape(row_name(row, mode))}</a></li>'
		)
	return "".join(items)


def index_page(conn, mode):
	rows = repo.list_books(conn, order="path", kinds=mode.kinds.values())
	every = repo.list_books(conn)
	counts = {name: sum(1 for row in every if row["kind"] in m.kinds.values()) for name, m in MODES.items()}
	label, multi, entries = plan(rows)
	documents, size = repo.stored_totals(conn)
	last = conn.execute("SELECT max(ingested_at) FROM content").fetchone()[0] or "never"

	blocks = []
	for name, subtree in entries:
		heading = f"<h2>{html.escape(name)}/</h2>" if multi else ""
		blocks.append(heading + f'<ul class="tree">{tree_html(subtree, mode)}</ul>')
	if not rows:
		blocks.append("<p>Nothing here yet. Mount a folder in the terminal app and press "
					  "<code>u</code>.</p>")

	footer = (f"{len(rows)} {mode.plural} in view &middot; {documents} documents stored "
			  f"({size / 1e6:.1f} MB) &middot; last walked {html.escape(str(last))}")
	return page(label, "".join(blocks), nav(mode, counts), footer,
				stamp=shelf_stamp(conn), watch_url="/health", reload_href=f"/?mode={mode.name}")


def shelf_stamp(conn):
	"""What the shelf looks like right now, as one string a page can compare against.

	Counts, bytes and the newest ingest together: a document added, removed or re-read all
	change it, and seconds matter less than the fact that the answer differs.
	"""
	documents, size = repo.stored_totals(conn)
	last = conn.execute("SELECT max(ingested_at) FROM content").fetchone()[0] or "never"
	rows = len(repo.list_books(conn))
	return f"{rows}:{documents}:{size}:{last}"


def document_stamp(conn, book_id):
	"""The same idea for one document: its ingest time, its size, and the file's mtime."""
	row = conn.execute(
		"SELECT ingested_at, bytes, source_mtime FROM content WHERE book_id = ?", (book_id,)
	).fetchone()
	if row is None:
		return "missing"
	return f"{row['ingested_at']}:{row['bytes']}:{row['source_mtime']}"


def code_html(kind, body):
	"""A code document as highlighted HTML, or as monospace text when Pygments is absent.

	The colours come out as the same five classes the stylesheet names, which are the app's
	palette -- a `.py` page should not look like a different program in a browser.
	"""
	try:
		from pygments import highlight
		from pygments.formatters import HtmlFormatter
		from pygments.lexers import get_lexer_by_name
	except ImportError:
		return f"<pre><code>{html.escape(body)}</code></pre>"
	lexer = {"py": "python", "sql": "sql"}.get(kind, kind)
	try:
		lexer = get_lexer_by_name(lexer)
	except Exception:
		return f"<pre><code>{html.escape(body)}</code></pre>"
	formatter = HtmlFormatter(nowrap=True, cssclass="code")
	return '<pre class="code"><code>' + highlight(body, lexer, formatter) + "</code></pre>"


def markdown_to_html(text):
	"""Markdown as HTML: markdown-it when it is installed, the small renderer when not."""
	try:
		from markdown_it import MarkdownIt
	except ImportError:
		return simple_markdown(text)
	return MarkdownIt("commonmark").enable("table").render(text)


def simple_markdown(text):
	"""Headings, fences, lists, quotes, paragraphs and inline spans -- no dependencies.

	Enough for the guides this shelf holds, and it exists because the server may run in a
	container with nothing installed: a missing Markdown library should cost polish, not the
	whole route. Markers are stripped from the raw line before escaping, never after --
	`html.escape("> quoted")` is `&gt; quoted`, and slicing that loses the wrong characters.
	"""
	out, fence, listed = [], False, False
	for line in text.split("\n"):
		if line.startswith("```"):
			if listed:
				out.append("</ul>")
				listed = False
			out.append("</code></pre>" if fence else "<pre><code>")
			fence = not fence
			continue
		if fence:
			out.append(html.escape(line))
			continue

		stripped = line.strip()
		is_item = stripped.startswith(("- ", "* "))
		is_quote = stripped.startswith("> ")
		heading = len(stripped) - len(stripped.lstrip("#")) if stripped.startswith("#") else 0
		content = stripped[2:] if (is_item or is_quote) else stripped.lstrip("#").strip()
		escaped = html.escape(content)
		for pattern, tag in ((r"\*\*(.+?)\*\*", "strong"), (r"`(.+?)`", "code"), (r"\*(.+?)\*", "em")):
			escaped = re.sub(pattern, lambda match, tag=tag: f"<{tag}>{match.group(1)}</{tag}>", escaped)

		is_row = stripped.startswith("|")
		if listed and not is_item:
			out.append("</ul>")
			listed = False
		if not stripped:
			out.append("")
		elif is_item:
			if not listed:
				out.append("<ul>")
				listed = True
			out.append(f"<li>{escaped}</li>")
		elif heading:
			level = min(heading, 6)
			out.append(f"<h{level}>{escaped}</h{level}>")
		elif is_quote:
			out.append(f"<blockquote>{escaped}</blockquote>")
		elif is_row:
			# A table without a table engine: monospace keeps the columns lined up, which is
			# more honest than one paragraph per row of pipes.
			out.append(f'<pre class="code"><code>{stripped}</code></pre>')
		else:
			out.append(f"<p>{escaped}</p>")
	if listed:
		out.append("</ul>")
	return "\n".join(out)


class Handler(BaseHTTPRequestHandler):
	server_version = "bookshelf"
	db_path = None
	token = None
	remember = False      # set when the token arrived in the URL, so it can be remembered

	# ------------------------------------------------------------------ plumbing

	def send(self, status, body, content_type="text/html; charset=utf-8"):
		payload = body.encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", content_type)
		self.send_header("Content-Length", str(len(payload)))
		self.send_header("Cache-Control", "no-store")
		if self.remember:
			# The token came in the URL, and a click on any link would drop it. A cookie is
			# what makes the rest of the shelf reachable: HttpOnly, Lax, this path, and no
			# expiry beyond the browser session.
			self.send_header(
				"Set-Cookie", f"bookshelf={self.token}; Path=/; HttpOnly; SameSite=Lax"
			)
		self.end_headers()
		self.wfile.write(payload)

	def token_from_cookie(self):
		for part in self.headers.get("Cookie", "").split(";"):
			name, _, value = part.strip().partition("=")
			if name == "bookshelf":
				return value
		return None

	def authorise(self, query):
		"""One static token: in the URL, as a bearer, or in the cookie a first visit leaves.

		Nothing here changes the shelf, so there is no session to keep -- the cookie exists
		because a click cannot carry a query string, and without it every link past the first
		page would ask for the token again.
		"""
		if not self.token:
			return True
		supplied = query.get("k", [None])[0]
		if supplied is None:
			header = self.headers.get("Authorization", "")
			supplied = header[7:] if header.startswith("Bearer ") else None
		if supplied is None:
			supplied = self.token_from_cookie()
		if supplied == self.token:
			self.remember = query.get("k", [None])[0] == self.token
			return True
		self.send(401, page("not authorised", "<p>A token is required.</p>", ""))
		return False

	def log_message(self, fmt, *args):
		print(f"  {self.address_string()} {fmt % args}", flush=True)

	# ------------------------------------------------------------------ routes

	def do_GET(self):
		parsed = urlparse(self.path)
		query = parse_qs(parsed.query)
		if not self.authorise(query):
			return
		try:
			# One connection per request, closed with it: sqlite connections are not for
			# sharing across threads, and a shelf this size costs nothing to open.
			with contextlib.closing(db.connect_readonly(self.db_path)) as conn:
				if parsed.path == "/":
					self.index(conn, query)
				elif parsed.path == "/health":
					self.health(conn)
				elif parsed.path.startswith("/doc/"):
					self.document(conn, parsed.path)
				elif parsed.path.startswith("/raw/"):
					self.raw(conn, parsed.path)
				elif parsed.path.startswith("/stamp"):
					self.stamp(conn, parsed.path)
				else:
					self.send(404, page("not found", "<p>No such page.</p>", ""))
		except (OSError, sqlite3.Error) as error:
			self.send(500, page("cannot open the shelf", f"<p>{html.escape(str(error))}</p>", ""))

	def index(self, conn, query):
		name = query.get("mode", ["book"])[0]
		if name not in MODES:
			self.send(404, page("unknown mode", f"<p>{html.escape(name)} is not a mode.</p>", ""))
			return
		self.send(200, index_page(conn, MODES[name]))

	def document(self, conn, path):
		row = self.row(conn, path, "doc")
		if row is None:
			return
		body = repo.content_of(conn, row["id"])
		if body is None:
			self.send(404, page(row["title"], "<p>This row has no stored text yet. Run "
											   "<code>u</code> in the terminal app.</p>", nav(MODES["book"])))
			return
		mode = MODES["code"] if row["kind"] in MODES["code"].kinds.values() else MODES["book"]
		title = row_name(row, mode)
		back = f'<p class="meta"><a href="/?mode={mode.name}">&#8592; back to the shelf</a></p>'
		rendered = markdown_to_html(body) if row["kind"] == "md" else code_html(row["kind"], body)
		# The reader's own marks go back on the page: a highlight where those words are now, a
		# note above its block. Read-only like everything else -- the rows are read, not written.
		rendered = annotate(rendered, repo.highlights_for(conn, row["id"]),
							repo.notes_for(conn, row["id"]))
		# The mode buttons stay on the shelf; a document navigates its own notes instead, and
		# keeps the reload every page has.
		placed = rendered.count('<aside class="note"')
		body = back + rendered + (NOTE_SCRIPT if placed else "") + FIND_SCRIPT
		self.send(200, page(title, body, notes_nav(placed) + FIND_BOX, row["path"],
							stamp=document_stamp(conn, row["id"]),
							watch_url=f"/stamp/{row['id']}",
							reload_href=f"/doc/{row['id']}"))

	def raw(self, conn, path):
		row = self.row(conn, path, "raw")
		if row is None:
			return
		body = repo.content_of(conn, row["id"])
		if body is None:
			self.send(404, "not stored yet\n", "text/plain; charset=utf-8")
			return
		types = {"md": "text/markdown; charset=utf-8"}
		self.send(200, body, types.get(row["kind"], "text/plain; charset=utf-8"))

	def stamp(self, conn, path):
		"""The stamp a page polls for: the whole shelf, or one document."""
		tail = path[len("/stamp"):].strip("/")
		if not tail:
			self.send(200, json.dumps({"stamp": shelf_stamp(conn)}) + "\n", "application/json")
			return
		try:
			book_id = int(tail)
		except ValueError:
			self.send(404, json.dumps({"error": "not an id"}) + "\n", "application/json")
			return
		self.send(200, json.dumps({"stamp": document_stamp(conn, book_id)}) + "\n", "application/json")

	def health(self, conn):
		documents, size = repo.stored_totals(conn)
		payload = {
			"revision": conn.execute("PRAGMA user_version").fetchone()[0],
			"roots": len(repo.list_roots(conn)),
			"rows": len(repo.list_books(conn)),
			"documents": documents,
			"bytes": size,
			"last_walked": conn.execute("SELECT max(ingested_at) FROM content").fetchone()[0],
			"modes": {name: len(repo.list_books(conn, kinds=m.kinds.values())) for name, m in MODES.items()},
			"stamp": shelf_stamp(conn),
		}
		self.send(200, json.dumps(payload, indent=1) + "\n", "application/json")

	def row(self, conn, path, prefix):
		"""One row by id, or a 404. Ids keep the request from naming a file at all."""
		try:
			book_id = int(path[len(prefix) + 2:])
		except ValueError:
			self.send(404, page("not found", "<p>That is not an id.</p>", ""))
			return None
		row = conn.execute(
			"SELECT b.*, r.path AS root_path, r.label AS root_label FROM books b "
			"JOIN roots r ON r.id = b.root_id WHERE b.id = ?",
			(book_id,),
		).fetchone()
		if row is None:
			self.send(404, page("not found", "<p>No document with that id.</p>", ""))
		return row


def main(argv=None):
	parser = argparse.ArgumentParser(
		prog="bookshelf-web",
		description="serve the shelf read-only over HTTP, for a browser that is not this machine",
	)
	parser.add_argument("--db", default=str(Path(__file__).parent / "shelf.db"))
	parser.add_argument("--host", default="127.0.0.1", help="loopback unless you mean otherwise")
	parser.add_argument("--port", type=int, default=8080)
	parser.add_argument(
		"--token",
		default=os.environ.get("BOOKSHELF_TOKEN"),
		help="required when the host is not loopback; also read from $BOOKSHELF_TOKEN",
	)
	args = parser.parse_args(argv)

	if args.host not in ("127.0.0.1", "localhost", "::1") and not args.token:
		print("refusing to listen on a public address without --token: this is your whole shelf")
		return 2

	Handler.db_path = args.db
	Handler.token = args.token
	with ThreadingHTTPServer((args.host, args.port), Handler) as httpd:
		print(f"shelf on http://{args.host}:{args.port}  (db {args.db}, read-only)")
		httpd.serve_forever()
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
