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
from bookshelf_html import to_markdown
from bookshelf_scan import MODES, row_name
from bookshelf_tree import children, plan

VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1">'

# The palette is bookshelf.tcss's, so a page served to a phone and the app on the desk look
# like the same shelf.
STYLE = """
:root { color-scheme: light dark; --ink:#3D3A31; --paper:#FDFAF1; --panel:#F4EDD9; --brand:#8A6A1B; }
body { margin:0 auto; max-width:44rem; padding:1.2rem 1.1rem 4rem; background:var(--paper);
       color:var(--ink); font:16px/1.6 Charter, Georgia, "Times New Roman", serif; }
h1,h2,h3 { line-height:1.25; } h1 { font-size:1.5rem; } h2 { font-size:1.15rem; }
a { color:var(--brand); text-decoration:none; } a:hover { text-decoration:underline; }
header { border-bottom:1px solid var(--panel); margin-bottom:1rem; padding-bottom:.6rem; }
nav a { margin-right:.9rem; font-weight:600; } nav a[aria-current] { text-decoration:underline; }
ul.tree { list-style:none; padding-left:.2rem; } ul.tree ul { padding-left:1.1rem; }
li.folder > span { color:var(--brand); font-weight:600; }
li.file { margin:.15rem 0; }
.star { color:#B8860B; }
pre { background:var(--panel); padding:.7rem .8rem; border-radius:4px; overflow-x:auto;
      font:13px/1.45 "JetBrains Mono", ui-monospace, Menlo, monospace; }
code { font-family:"JetBrains Mono", ui-monospace, Menlo, monospace; font-size:.92em; }
table { border-collapse:collapse; width:100%; font-size:.95rem; }
th,td { text-align:left; padding:.35rem .5rem; border-bottom:1px solid var(--panel); }
blockquote { margin:0; padding-left:.9rem; border-left:3px solid var(--brand); color:#5b574c; }
footer { margin-top:2rem; color:#6b6a64; font-size:.85rem; }
.meta { color:#6b6a64; font-size:.85rem; }
@media (prefers-color-scheme: dark) {
  :root { --ink:#e6e1d6; --paper:#191813; --panel:#242219; --brand:#d3ab52; }
  blockquote { color:#b9b3a5; } .meta, footer { color:#9a9488; }
}
"""

PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">{viewport}<title>{title}</title>
<style>{style}</style></head>
<body><header><nav>{nav}</nav></header>
{body}
<footer>{footer}</footer></body></html>
"""


def page(title, body, nav, footer=""):
	return PAGE.format(viewport=VIEWPORT, title=html.escape(title), style=STYLE, nav=nav, body=body, footer=footer)


def nav(mode, counts=None):
	"""The mode switch, as links. Counts are shown in the index, not on a document page."""
	parts = []
	for name, other in MODES.items():
		mark = ' aria-current="page"' if name == mode.name else ""
		label = f"{name} ({counts[name]})" if counts else name
		parts.append(f'<a href="/?mode={name}"{mark}>{label}</a>')
	return "".join(parts)


def with_viewport(body):
	"""Put a viewport tag into a stored document, or iOS lays it out at 980px and pinches.

	A converted document was built for paper and carries no viewport, so the one tag that
	makes it readable on a phone is added at the moment it is served -- not stored, because
	the stored body is the artifact, and this is about the screen it is going to.
	"""
	if "name=\"viewport\"" in body or "name='viewport'" in body:
		return body
	if "</head>" in body:
		return body.replace("</head>", VIEWPORT + "</head>", 1)
	if "<body" in body:
		return VIEWPORT + body
	return VIEWPORT + body




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
		mark = '<span class="star">&#9733;</span> ' if row["is_important"] else ""
		items.append(
			f'<li class="file"><a href="/doc/{row["id"]}">{mark}'
			f"{html.escape(row_name(row, mode))}</a></li>"
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
	return page(label, "".join(blocks), nav(mode, counts), footer)


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
		if row["kind"] == "html":
			# A stored HTML document is a whole page with its own design -- a converted
			# document keeps its parchment, its fonts and its page geometry. It goes out as
			# it is, with the viewport added, and nothing of this server's styling around it:
			# wrapping it in a template would nest two documents and lose the design.
			self.send(200, with_viewport(body))
			return
		mode = MODES["code"] if row["kind"] in MODES["code"].kinds.values() else MODES["book"]
		title = row_name(row, mode)
		back = f'<p class="meta"><a href="/?mode={mode.name}">&#8592; back to the shelf</a></p>'
		rendered = markdown_to_html(body) if row["kind"] == "md" else f"<pre><code>{html.escape(body)}</code></pre>"
		self.send(200, page(title, back + rendered, nav(mode), row["path"]))

	def raw(self, conn, path):
		row = self.row(conn, path, "raw")
		if row is None:
			return
		body = repo.content_of(conn, row["id"])
		if body is None:
			self.send(404, "not stored yet\n", "text/plain; charset=utf-8")
			return
		types = {"html": "text/html; charset=utf-8", "md": "text/markdown; charset=utf-8"}
		self.send(200, body, types.get(row["kind"], "text/plain; charset=utf-8"))

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
