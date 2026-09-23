"""HTML to Markdown, for reading a web page inside the app.

The shelf holds HTML documents -- a converted PDF, a saved article -- and `i` shows them.
Textual has no HTML renderer and a grid of character cells cannot lay out a page, so the
markup is rewritten into the subset MarkdownViewer already draws: headings, paragraphs,
lists, tables, fenced code, quotes, bold and italic.

A code block keeps the language it declares -- `class="language-java"` becomes a ```java
fence -- so the app colours it with the same palette it uses for its own files. A block that
declares nothing becomes ```text, which is monochrome on purpose: an ASCII diagram wants no
lexer, and guessing at one is how a diagram ends up with a keyword in it.

What is deliberately dropped: the stylesheet, so no colour or font survives; the page
furniture, so no cover, running header or page number; anchors, as there is nothing to
click; and image contents, because a terminal cannot draw one. What a terminal can carry is
a document's structure, and `Enter` hands the file to the browser when the design itself is
what you want to see.

Not a general HTML engine. It is a reader for the documents this shelf holds, written
against the standard library, offline, with nothing to install.
"""
from html.parser import HTMLParser

# Elements whose *content* is not text: skipped, with everything inside them.
SKIP = {"style", "script", "head", "title"}
# Void elements have no end tag, so they must never raise the skip depth -- an unclosed
# <meta> would otherwise swallow the rest of the document.
VOID = {"meta", "link", "input", "source", "base"}
BLOCKS = {"p", "div", "section", "article", "header", "footer", "figure", "figcaption", "main", "body"}
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
INLINE = {"strong": "**", "b": "**", "em": "*", "i": "*"}
DEFAULT_FENCE = "text"


def fence_language(attrs):
	"""The language a code block declares, from `class="language-java"` or `lang`.

	Carrying it matters: a fence with a language is coloured by that language's lexer, and a
	fence without one is guessed at. `text` is a real answer -- it means monochrome, which is
	what an ASCII diagram wants -- so an undeclared block gets that rather than a guess.
	"""
	for name, value in attrs:
		if name == "class":
			for token in value.split():
				if token.startswith("language-"):
					return token[len("language-"):]
				if token.startswith("lang-"):
					return token[len("lang-"):]
		elif name in ("data-language", "lang") and value:
			return value
	return None


class Markdown(HTMLParser):
	"""One pass over the markup, emitting a line of Markdown as each block closes."""

	def __init__(self):
		super().__init__(convert_charrefs=True)
		self.lines = []            # finished lines
		self.text = ""             # inline text of the block being read
		self.skip = 0              # inside <style> or <head>
		self.pre = 0               # inside <pre>, where whitespace is the content
		self.quote = 0
		self.table = None          # [(cells, is_header)] while inside <table>
		self.row = None
		self.cell = None
		self.cell_header = False
		self.row_header = False

	# ------------------------------------------------------------------ emitting

	def emit(self, line=""):
		self.lines.append(line)

	def flush(self):
		"""Take the buffered text: into a table cell if one is open, otherwise as a line."""
		raw, self.text = self.text, ""
		if self.cell is not None:
			self.cell.append(" ".join(raw.split()))
			return
		if self.table is not None:
			return                 # text loose in a table, not in a cell: drop it
		clean = raw.strip("\n") if self.pre else " ".join(raw.split())
		if clean:
			self.emit(("> " * self.quote) + clean)

	def render_table(self):
		"""The finished table as Markdown rows, one separator under the header row."""
		rows = self.table or []
		width = max((len(cells) for cells, _ in rows), default=0)
		if not width:
			return
		for index, (cells, header) in enumerate(rows):
			padded = cells + [""] * (width - len(cells))
			self.emit("| " + " | ".join(padded) + " |")
			if header and index == 0:
				self.emit("|" + " --- |" * width)
		self.emit()

	# ------------------------------------------------------------------ the parser

	def handle_starttag(self, tag, attrs):
		if tag in SKIP:
			self.skip += 1
			return
		if self.skip or tag in VOID:
			return
		if tag == "pre":
			self.flush()
			self.pre += 1
			self.emit("```" + (fence_language(attrs) or DEFAULT_FENCE))
		elif tag == "code" and self.pre:
			# <pre><code class="language-java">: the language arrives on the inner tag, so
			# the fence line written a moment ago is corrected rather than rewritten
			language = fence_language(attrs)
			if language and self.lines and self.lines[-1].startswith("```"):
				self.lines[-1] = "```" + language
		elif tag == "br" and not self.pre:
			self.text += "\n"
		elif tag in HEADINGS:
			self.flush()
			self.text = "#" * HEADINGS[tag] + " "
		elif tag == "li":
			self.flush()
			self.text = "- "
		elif tag == "blockquote":
			self.flush()
			self.quote += 1
		elif tag == "hr":
			self.flush()
			self.emit("---")
		elif tag == "a":
			pass                                   # the text, not the target
		elif tag == "img":
			self.text += f"![{dict(attrs).get('alt', '')}]"
		elif tag == "table":
			self.flush()
			self.emit()
			self.table = []
		elif tag == "tr":
			self.flush()
			self.row = []
			self.row_header = False
		elif tag in ("td", "th"):
			self.flush()
			self.cell = []
			self.cell_header = tag == "th"
		elif tag == "code" and not self.pre:
			self.text += "`"
		elif tag in INLINE:
			self.text += INLINE[tag]
		elif tag in BLOCKS and not self.pre:
			self.flush()

	def handle_endtag(self, tag):
		if tag in SKIP:
			self.skip = max(0, self.skip - 1)
			return
		if self.skip:
			return
		if tag == "pre":
			self.flush()
			self.emit("```")
			self.emit()
			self.pre = max(0, self.pre - 1)
		elif tag in HEADINGS:
			self.flush()
			self.emit()
		elif tag in ("td", "th"):
			self.flush()
			if self.row is not None and self.cell is not None:
				self.row.append(" ".join("".join(self.cell).split()))
				if self.cell_header:
					self.row_header = True
			self.cell = None
		elif tag == "tr":
			self.flush()
			if self.table is not None and self.row:
				self.table.append((self.row, self.row_header))
			self.row = None
		elif tag == "table":
			self.flush()
			self.render_table()
			self.table = None
		elif tag == "blockquote":
			self.flush()
			self.quote = max(0, self.quote - 1)
			self.emit()
		elif tag == "code" and not self.pre:
			# rstrip first: `** Haoxi Peng **` renders with the spaces inside the bold run
			self.text = self.text.rstrip() + "` " 
		elif tag in INLINE:
			self.text = self.text.rstrip() + INLINE[tag] + " " 
		elif tag in BLOCKS and not self.pre:
			self.flush()
			self.emit()

	def handle_data(self, data):
		if self.skip:
			return
		self.text += data if self.pre else " ".join(data.split()) + " "

	def result(self):
		"""The finished Markdown, with runs of blank lines squeezed to one."""
		self.flush()
		out = []
		for line in self.lines:
			if line.strip() == "" and out and out[-1].strip() == "":
				continue
			out.append(line.rstrip())
		while out and out[-1].strip() == "":
			out.pop()
		return "\n".join(out) + "\n"


def to_markdown(html):
	"""Rewrite a document's markup as the Markdown the app's viewer draws."""
	parser = Markdown()
	parser.feed(html)
	return parser.result()
