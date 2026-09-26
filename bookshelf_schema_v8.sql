-- schema v8 — the shelf reads Markdown and code, and nothing else
--
-- Revisions 1 to 3 widened `kind` for pdf, then py/sql, then html. This one narrows it back
-- to the three the shelf still reads: Markdown, Python and SQL. A PDF and an HTML page are
-- both the format a document arrives in, not the format this shelf keeps -- a converted
-- document is Markdown by the time it lands here, so one document is one row.
--
-- The rows for the dropped kinds are unreachable now -- nothing walks for an html file any
-- more, so the next re-walk would treat every one of them as deleted -- and they go here, in
-- one auditable copy rather than as a side effect of a sync. `.pdf` was already emptied by
-- revision 4; its kind leaves the CHECK with this rebuild.
--
-- A CHECK constraint cannot be altered, so the table is rebuilt, the same procedure as
-- revisions 2 and 3. `books.id` is copied, not renumbered, so the star and the added_at date
-- stay attached to the same file, and UNIQUE (root_id, path) is re-created with the table.
--
-- Unlike revisions 2 and 3, this rebuild runs while `content` and `annotation` exist and
-- reference `books`. Their foreign keys would cascade on DROP TABLE, so foreign keys are
-- turned off for the rebuild and back on after it: with them off, dropping `books` removes
-- the table and nothing else, and the child rows for the surviving books are untouched. The
-- children of a dropped html or pdf row are orphaned by the same copy, so they go explicitly.
--
-- Applied by db.bootstrap() once, when user_version is 7.

PRAGMA foreign_keys = OFF;

BEGIN;

CREATE TABLE books_v8 (
    id           INTEGER PRIMARY KEY,
    root_id      INTEGER NOT NULL REFERENCES roots(id) ON DELETE CASCADE,
    path         TEXT    NOT NULL,              -- relative to roots.path
    title        TEXT    NOT NULL,
    kind         TEXT    NOT NULL CHECK (kind IN ('md', 'py', 'sql')),
    is_important INTEGER NOT NULL DEFAULT 0 CHECK (is_important IN (0, 1)),
    added_at     TEXT    NOT NULL DEFAULT (datetime('now')),

    UNIQUE (root_id, path)
);

INSERT INTO books_v8 (id, root_id, path, title, kind, is_important, added_at)
     SELECT id, root_id, path, title, kind, is_important, added_at
       FROM books
      WHERE kind IN ('md', 'py', 'sql');

DROP TABLE books;

ALTER TABLE books_v8 RENAME TO books;

DELETE FROM content    WHERE book_id NOT IN (SELECT id FROM books);
DELETE FROM annotation WHERE book_id NOT IN (SELECT id FROM books);

COMMIT;

PRAGMA foreign_keys = ON;
