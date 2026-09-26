"""Put a reader's own marks back into a document the server is about to send.

The app keeps a highlight and a note as offsets into the document's plain text -- the same
text the terminal draws, built from the rendered blocks. The server has only HTML, and its
tags sit where that plain text had none, so an offset means nothing here. What survives is
the anchor: the exact words a reader marked. This finds each anchor in the rendered page and
puts the mark back on those words, wherever they are now.

A highlight is wrapped where it is found. A note is set ahead of the block it was written on,
which is what the terminal's "just above the line" becomes when the line is a paragraph, a
heading, a list item or a fence. An anchor whose words are gone is dropped rather than painted
somewhere else -- the rule the terminal already uses, because a mark in the wrong place is
worse than no mark.

Not a second HTML engine: it reads the HTML this server just produced, so it runs the same
whether markdown-it is installed or the small fallback renderer wrote the page.

The words are matched with whitespace collapsed. The terminal and the browser write the same
text with different whitespace: a soft line break is a space there and a newline here, and a
table row is spaces there and a newline between its cells here. Collapsing both sides is what
lets an anchor survive the trip; the hit is then mapped back to the range it really covered.
"""

from html import escape
from html.parser import HTMLParser

# The elements a note can hang off: the block the note is written on. A note goes before the
# nearest one of these that holds its anchor.
BLOCK = {"p", "li", "blockquote", "pre", "td", "th",
         "h1", "h2", "h3", "h4", "h5", "h6", "div", "section", "article"}
# Void elements never open a block, so they must not go on the stack: an unclosed <br> would
# otherwise hold the stack open to the end of the page.
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
        "source", "track", "wbr"}


class Page(HTMLParser):
	"""The served HTML as parts, with its text joined so an anchor can be found in it.

	`parts` is the document in order, one entry per tag and one per run of text. `text` is
	every text part run together, and `start_of` says where each part begins in it -- so a
	position found in `text` can be traced back to the part that holds it, and to the block
	that part sits in.
	"""

	def __init__(self):
		super().__init__(convert_charrefs=True)
		self.parts = []          # ("tag", raw) | ("text", decoded)
		self.owner = []          # per part: part index of the enclosing block's start tag
		self.start_of = {}       # text part index -> where it begins in `text`
		self.stack = []          # (tag, part index) still open
		self.text = ""           # every text part joined

	def handle_starttag(self, tag, attrs):
		index = len(self.parts)
		self.parts.append(("tag", self.get_starttag_text()))
		self.owner.append(self.block_owner())
		if tag not in VOID:
			self.stack.append((tag, index))

	def handle_startendtag(self, tag, attrs):
		self.parts.append(("tag", self.get_starttag_text()))
		self.owner.append(self.block_owner())

	def handle_endtag(self, tag):
		self.parts.append(("tag", f"</{tag}>"))
		self.owner.append(self.block_owner())
		for index in range(len(self.stack) - 1, -1, -1):
			if self.stack[index][0] == tag:
				del self.stack[index:]
				break

	def handle_data(self, data):
		index = len(self.parts)
		self.parts.append(("text", data))
		self.owner.append(self.block_owner())
		self.start_of[index] = len(self.text)
		self.text += data

	def block_owner(self):
		"""The part index of the nearest open block's start tag, or None outside every block."""
		for tag, index in reversed(self.stack):
			if tag in BLOCK:
				return index
		return None

	def part_at(self, position):
		"""The text part holding a position in the joined text, or None."""
		for index, (kind, value) in enumerate(self.parts):
			if kind != "text":
				continue
			start = self.start_of[index]
			if start <= position < start + len(value):
				return index
		return None


def normalized(text):
	"""`text` with each run of whitespace collapsed to one space, plus the index maps.

	`starts[i]` and `ends[i]` say which stretch of the original produced the character at
	position `i`, so a match in the collapsed text maps back to a real range in `text`.
	"""
	out, starts, ends = [], [], []
	index, size = 0, len(text)
	while index < size:
		if text[index].isspace():
			stop = index
			while stop < size and text[stop].isspace():
				stop += 1
			out.append(" ")
			starts.append(index)
			ends.append(stop)
			index = stop
		else:
			out.append(text[index])
			starts.append(index)
			ends.append(index + 1)
			index += 1
	return "".join(out), starts, ends


def find_anchors(text, anchors):
	"""Where each anchor's words are now, as (start, end) in `text`, in reading order.

	Both sides are whitespace-collapsed before the search, and each hit is mapped back to the
	range it covered. Searching from where the last one ended keeps two anchors that hold the
	same words from both landing on the first copy of them.
	"""
	flat, starts, ends = normalized(text)
	found, cursor = [], 0
	for anchor in anchors:
		needle = " ".join(anchor.split())
		if not needle:
			continue
		at = flat.find(needle, cursor)
		if at < 0:
			at = flat.find(needle)
		if at < 0:
			continue
		cursor = at + len(needle)
		found.append((starts[at], ends[at + len(needle) - 1]))
	return found


def merge(ranges):
	"""Overlapping and touching ranges as one: two highlights that meet are one wash."""
	out = []
	for start, end in sorted(ranges):
		if out and start <= out[-1][1]:
			out[-1] = (out[-1][0], max(out[-1][1], end))
		else:
			out.append((start, end))
	return out


def text_html(page, index, data, marks):
	"""One text part, escaped, with each highlight range inside it wrapped in a `<mark>`."""
	start = page.start_of[index]
	out, cursor = [], 0
	for first, last in marks:
		low, high = max(first, start) - start, min(last, start + len(data)) - start
		if high <= low:
			continue
		if low > cursor:
			out.append(escape(data[cursor:low]))
		out.append('<mark class="mark">' + escape(data[low:high]) + "</mark>")
		cursor = high
	if cursor < len(data):
		out.append(escape(data[cursor:]))
	return "".join(out)


def note_html(note, number):
	"""One note as a callout, numbered so a link can reach it.

	`white-space: pre-wrap` in the sheet keeps its line breaks. The number is the id the note
	button's plain-link fallback points at; the script upgrades that to stepping through them.
	"""
	return (f'<aside class="note" id="note-{number}">'
	        '<span class="note-label">note</span>' + escape(note) + "</aside>")


def annotate(body, highlights=(), notes=()):
	"""`body` with each highlight wrapped and each note set above the block it was written on."""
	if not highlights and not notes:
		return body
	page = Page()
	page.feed(body)
	page.close()

	marks = merge(find_anchors(page.text, [anchor for _, _, anchor in highlights]))
	callouts = {}            # part index of a block start tag -> [note, ...]
	trailing = []            # a note whose block cannot be placed: shown at the end instead
	for _, anchor, note in notes:
		if not anchor or not note:
			continue
		at = find_anchors(page.text, [anchor])
		if not at:
			continue
		part = page.part_at(at[0][0])
		owner = page.owner[part] if part is not None else None
		if owner is None:
			trailing.append(note)
		else:
			callouts.setdefault(owner, []).append(note)

	out = []
	placed = 0
	for index, (kind, value) in enumerate(page.parts):
		if kind == "tag":
			for note in callouts.get(index, ()):
				placed += 1
				out.append(note_html(note, placed))
			out.append(value)
		else:
			out.append(text_html(page, index, value, marks))
	for note in trailing:
		placed += 1
		out.append(note_html(note, placed))
	return "".join(out)
