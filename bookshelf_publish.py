"""Publish the static shelf after a sync.

The static host holds a snapshot, so `u` alone cannot move it: this is the other half, run
after the walk has written the database. It renders the shelf into the site clone and pushes
it. Deliberately small and deliberately removable -- when the shelf is served from a machine
that is always on, publishing stops being a step at all and this file goes.

Where the clone lives: `$BOOKSHELF_SITE`, or `~/workspace/bookshelf-site` otherwise. A missing
clone or a dead network is reported, never raised, because a reader pressing `u` should still
get their local shelf updated.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import bookshelf_export as export

SITE = Path(os.environ.get("BOOKSHELF_SITE", str(Path.home() / "workspace" / "bookshelf-site")))
COMMIT = "shelf: update from the terminal"


def last_line(result, fallback):
	"""The one line of a failed git command worth showing, or a fallback."""
	text = (result.stderr or result.stdout or "").strip()
	return text.splitlines()[-1][:120] if text else fallback


def publish(db_path, site=None):
	"""Export the shelf into its site clone and push it. Returns (ok, message)."""
	site = Path(site or SITE)
	if not (site / ".git").is_dir():
		return False, f"no site clone at {site}"
	try:
		pages = export.export(db_path, site)
		add = subprocess.run(["git", "add", "-A"], cwd=site, capture_output=True, text=True)
		if add.returncode:
			return False, last_line(add, "git add failed")
		commit = subprocess.run(["git", "commit", "-m", COMMIT], cwd=site,
								capture_output=True, text=True)
		if commit.returncode not in (0, 1):      # 1 is git's "nothing to commit"
			return False, last_line(commit, "git commit failed")
		push = subprocess.run(["git", "push"], cwd=site, capture_output=True, text=True)
		if push.returncode:
			return False, last_line(push, "git push failed")
	except (OSError, subprocess.SubprocessError) as error:
		return False, str(error)[:120]
	return True, f"{pages} page(s) published"
