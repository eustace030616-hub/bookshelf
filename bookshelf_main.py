"""The `bookshelf` command.

	bookshelf            open the shelf
	bookshelf --db PATH  use another database (default: shelf.db beside the code)
	bookshelf -h         this message

There are no subcommands, because there is nothing to do outside the app. The shelf is a
terminal UI: run `bookshelf`, and mount a folder from inside it with `m`. Everything the
app knows lives in one SQLite file next to the code, so the command line has one thing to
decide, which is which file that is.
"""
import sys
import argparse
from pathlib import Path

DB_FILE = Path(__file__).parent / "shelf.db"


def build_parser():
	parser = argparse.ArgumentParser(
		prog="bookshelf",
		description="a terminal bookshelf over folders of PDF, Markdown, Python and SQL.",
		epilog=(
			"This is a TUI. Run `bookshelf` and the shelf opens:\n"
			"\n"
			"  m  mount a folder        t  books <-> code\n"
			"  i  preview a file        q  leave\n"
			"\n"
			"The footer lists the keys for whatever has focus."
		),
		formatter_class=argparse.RawDescriptionHelpFormatter,
		allow_abbrev=False,
	)
	parser.add_argument(
		"--db", default=str(DB_FILE), help=f"the database to open (default: {DB_FILE})"
	)
	return parser


def main(argv=None):
	argv = sys.argv[1:] if argv is None else list(argv)
	args = build_parser().parse_args(argv)

	# Imported after parsing, so `bookshelf -h` never loads Textual and answers instantly.
	from bookshelf_tui import run

	return run(args.db)


if __name__ == "__main__":
	sys.exit(main())
