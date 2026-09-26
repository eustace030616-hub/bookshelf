"""The document as a model, and the cursor over it — what `i` reads with.

The viewer draws Markdown as a tree of widgets, and a tree is a poor place to keep a position:
a paragraph's text is a `Content`, a bullet list is an empty string with item children, a
table is an empty string with cell widgets, and a fence keeps its code in a `Label` it
composes. So the tree is read once into a flat model — blocks, pieces, and one document
string — and every position after that is an offset into that string: the cursor, the
selection, what gets stored, what gets found again.

Drawing is a second pass. Each piece is re-derived from the text it had when it was read plus
the styles the model asks for, so painting the same document twice is the same as painting it
once: nothing accumulates, and removing a style means not asking for it.

Nothing here imports the app, the database or a screen. A cursor is arithmetic, and it is
tested as arithmetic.
"""
from dataclasses import dataclass, field
from typing import Any

from textual.color import Color
from textual.content import Content
from textual.style import Style

# The character under the cursor, and the range a reader has selected. Both are styles rather
# than widgets: a span is what a `Content` can carry, and the app already draws everything else
# that way.
#
# The selection is a highlight, not an underline. Underline is a Markdown thing -- a link, a
# run of emphasis -- so drawing it over a range tells a reader nothing about which lines are
# theirs, and it is close to invisible on serif text at this size. A warm wash behind the words
# reads as a marker, and it is what a marked-up page looks like.
#
# Measured on the wash: body ink 8.8:1, and the worst of the five code colours 3.9:1, against
# 4.8:1 on bare cream. The range is a selection rather than body text, so the drop is the price
# of being able to see it at all -- and it lasts as long as the selection is on screen.
CURSOR = Style(reverse=True)
# The colours are Color objects, not strings: Textual's Style keeps a string it was handed
# as a string, and combining that with the parsed styles a fence already carries raises
# `Color + str` deep inside its renderer. Color.parse is what makes the style fully parsed.
SELECTED = Style(background=Color.parse("#F0E2B8"))
BLOCK_SEPARATOR = "\n"
PIECE_SEPARATOR = " "


def draw(widget, content):
	"""Put styled text back into a widget, whichever way that widget takes it.

	Textual's own blocks are not uniform: a paragraph has `set_content`, while a table cell and
	the Label a fence composes only have `update`. Both end up holding the Content a reader
	sees, so both are asked the way they understand.
	"""
	if hasattr(widget, "set_content"):
		widget.set_content(content)
	else:
		widget.update(content)


@dataclass
class Piece:
	"""One widget's text, and where it sits in the document."""

	widget: Any
	original: Content
	text: str                  # verbatim, so a local offset is a real offset into `original`
	start: int                 # offset of this piece in the document text

	@property
	def end(self) -> int:
		return self.start + len(self.text)


@dataclass
class Block:
	"""A top-level block: one paragraph, one list, one table, one fence."""

	widget: Any                # the widget itself, whose position on the page is known
	pieces: list[Piece]
	text: str                  # the pieces joined by a space -- what the reader sees, in order
	start: int

	@property
	def end(self) -> int:
		return self.start + len(self.text)

	@property
	def length(self) -> int:
		return len(self.text)

	def holds(self, offset: int) -> bool:
		return self.start <= offset < self.end


class Document:
	"""A rendered Markdown widget, read as text with offsets that can be stored."""

	def __init__(self, markdown):
		self.blocks: list[Block] = []
		self.text = ""
		for child in markdown.children:
			pieces = []
			for node in child.walk_children(with_self=True):
				content = getattr(node, "content", None)
				if isinstance(content, Content) and content.plain.strip():
					pieces.append(Piece(widget=node, original=content, text=content.plain, start=0))
			if not pieces:
				continue                       # a rule, an empty list, a spacer: no text to sit on
			self.blocks.append(Block(
				widget=child,
				pieces=pieces,
				text=PIECE_SEPARATOR.join(piece.text for piece in pieces),
				start=0,
			))
		self.reflow()

	def reflow(self):
		"""Give every block and piece the offsets the document text actually has."""
		offset = 0
		for index, block in enumerate(self.blocks):
			if index:
				offset += len(BLOCK_SEPARATOR)
			block.start = offset
			piece_offset = offset
			for piece in block.pieces:
				piece.start = piece_offset
				piece_offset += len(piece.text) + len(PIECE_SEPARATOR)
			offset += len(block.text)
		self.text = BLOCK_SEPARATOR.join(block.text for block in self.blocks)

	# ------------------------------------------------------------------ looking things up

	def block_at(self, offset: int):
		"""The block an offset falls in, or the last one, or None for an empty document."""
		for block in self.blocks:
			if block.holds(offset):
				return block
		return self.blocks[-1] if self.blocks else None

	def piece_at(self, offset: int):
		"""The piece an offset falls in, or the closest one before it."""
		block = self.block_at(offset)
		if block is None:
			return None
		for piece in block.pieces:
			if piece.start <= offset < piece.end:
				return piece
		return block.pieces[-1] if block.pieces else None

	def find(self, needle: str) -> int:
		"""Where a remembered piece of text is now, or -1. How a stored range is re-found."""
		return self.text.find(needle) if needle else -1

	def spans(self, start: int, end: int) -> list[tuple[Piece, int, int]]:
		"""The pieces a range covers, as (piece, local start, local end) -- what to draw."""
		start, end = min(start, end), max(start, end)
		out = []
		for block in self.blocks:
			if block.end <= start or block.start >= end:
				continue
			for piece in block.pieces:
				first = max(start, piece.start) - piece.start
				last = min(end, piece.end) - piece.start
				if last > first:
					out.append((piece, first, last))
		return out

	# ------------------------------------------------------------------ moving

	def move_h(self, offset: int) -> int:
		block = self.block_at(offset)
		return max(offset - 1, block.start) if block else offset

	def move_l(self, offset: int) -> int:
		block = self.block_at(offset)
		return min(offset + 1, block.end - 1) if block else offset

	def move_k(self, offset: int) -> int:
		"""Up a block, keeping the column, as vim keeps it."""
		block = self.block_at(offset)
		index = self.blocks.index(block)
		if index == 0:
			return offset
		above = self.blocks[index - 1]
		return above.start + min(offset - block.start, max(above.length - 1, 0))

	def move_j(self, offset: int) -> int:
		"""Down a block, keeping the column."""
		block = self.block_at(offset)
		index = self.blocks.index(block)
		if index == len(self.blocks) - 1:
			return offset
		below = self.blocks[index + 1]
		return below.start + min(offset - block.start, max(below.length - 1, 0))

	# ------------------------------------------------------------------ drawing

	def paint(self, cursor: int | None = None, ranges=()):
		"""Draw the document again: the text it had, plus the styles asked for here.

		Every piece is re-derived, not updated, which is what makes this idempotent: a piece
		that was underlined and no longer should be is simply not asked for again.
		"""
		styles: dict[int, list[tuple[int, int, Style]]] = {}
		for start, end in ranges:
			for piece, first, last in self.spans(start, end):
				styles.setdefault(id(piece), []).append((first, last, SELECTED))
		if cursor is not None:
			for piece, first, last in self.spans(cursor, cursor + 1):
				styles.setdefault(id(piece), []).append((first, last, CURSOR))

		for block in self.blocks:
			for piece in block.pieces:
				content = piece.original
				for first, last, style in styles.get(id(piece), ()):
					content = content.stylize(style, first, last)
				draw(piece.widget, content)
