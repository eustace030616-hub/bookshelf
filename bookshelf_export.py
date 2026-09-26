"""The shelf as static files: a reader with no server, no process, no machine kept awake.

GitHub Pages, Netlify, any bucket. The terminal app stays the writer; this renders the last
state of the database into a folder of HTML that a phone can read with the Mac off, and that
never costs anything to keep. The pages are the server's own shell -- the open document panel,
the note and shelf dropdowns, the annotations -- with the links pointing at files instead of
routes and the freshness watcher left out, because there is no server to ask.

Why this and not the running server, for a public shelf: a static host has no process to
attack, no token to leak, and no uptime to keep. It is also the one shape that survives the
machine that made it.

	python3 bookshelf_export.py --db shelf.db site/
"""

from __future__ import annotations

import argparse
import html
from pathlib import Path

import bookshelf_db as db
import bookshelf_repo as repo
import bookshelf_web as web
from bookshelf_annotate import annotate
from bookshelf_scan import MODES, row_name
from bookshelf_tree import plan


def page_href(row):
	"""A row's page as a file beside this one, so the site works under any URL prefix."""
	return f"doc-{row['id']}.html"


def mode_of(row):
	"""The mode a row belongs to, from its kind. The same test the server uses."""
	return MODES["code"] if row["kind"] in MODES["code"].kinds.values() else MODES["book"]


def document(conn, row):
	"""One document page with its annotations baked in, or None when it has no stored text."""
	body = repo.content_of(conn, row["id"])
	if body is None:
		return None
	mode = mode_of(row)
	rendered = (web.markdown_to_html(body) if row["kind"] == "md"
				else web.code_html(row["kind"], body))
	rendered = annotate(rendered, repo.highlights_for(conn, row["id"]),
						repo.notes_for(conn, row["id"]))
	placed = rendered.count('<aside class="note"')
	back = '<p class="meta"><a href="index.html">&#8592; back to the shelf</a></p>'
	panel = ('<div id="panel">' + web.notes_nav(placed)
			 + web.shelf_picker(conn, href=page_href)
			 + '<span class="grip" aria-hidden="true"></span></div>'
			 + (web.NOTE_SCRIPT if placed else "") + web.SHELF_SCRIPT + web.PANEL_SCRIPT)
	return web.page(row_name(row, mode), back + rendered, "", row["path"],
					header=False, panel=panel, reload_href="index.html")


def index(conn):
	"""One page for the whole shelf, both modes: a static site has no query string to switch."""
	blocks = ["<h1>bookshelf</h1>"]
	for name, mode in MODES.items():
		rows = repo.list_books(conn, order="path", kinds=mode.kinds.values())
		if not rows:
			continue
		blocks.append(f"<h2>{html.escape(mode.plural.title())}</h2>")
		_label, multi, entries = plan(rows)
		for root_label, subtree in entries:
			heading = f"<h3>{html.escape(root_label)}/</h3>" if multi else ""
			blocks.append(heading + f'<ul class="tree">{web.tree_html(subtree, mode, page_href)}</ul>')
	return web.page("bookshelf", "".join(blocks), "", "a static copy of the shelf",
					header=False, reload_href="index.html")


def export(db_path, out_dir):
	"""Render every document and the index into `out_dir`. Returns the page count."""
	out = Path(out_dir)
	out.mkdir(parents=True, exist_ok=True)
	# Pages runs Jekyll unless told not to, and Jekyll ignores files it does not understand.
	(out / ".nojekyll").write_text("", encoding="utf-8")
	conn = db.connect_readonly(db_path)
	written = 0
	for row in repo.list_books(conn):
		page = document(conn, row)
		if page is None:
			continue
		(out / page_href(row)).write_text(page, encoding="utf-8")
		written += 1
	(out / "index.html").write_text(index(conn), encoding="utf-8")
	return written + 1


def main(argv=None):
	parser = argparse.ArgumentParser(
		prog="bookshelf-export",
		description="render the shelf as static HTML for GitHub Pages or any host",
	)
	parser.add_argument("--db", default=str(Path(__file__).parent / "shelf.db"))
	parser.add_argument("out", help="directory to write the site into")
	args = parser.parse_args(argv)
	print(f"wrote {export(args.db, args.out)} page(s) to {args.out}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
