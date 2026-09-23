-- schema v3 — widen books.kind again, for HTML documents
--
-- Revision 2 admitted py and sql. This one adds html, for a document that was converted
-- or just saved as a web page. Same procedure, for the same reason: a CHECK constraint
-- cannot be altered, so the table is rebuilt. sqlite.org documents this under "Making
-- Other Kinds Of Table Schema Changes".
--
-- `books.id` is copied rather than renumbered, so is_important and every id the shelf has
-- already shown stay attached to the same file. UNIQUE (root_id, path) is re-created with
-- the table and still supplies the index for "everything in root N".
--
-- Applied by db.bootstrap() once, when user_version is 2.

BEGIN;

CREATE TABLE books_v3 (
    id           INTEGER PRIMARY KEY,
    root_id      INTEGER NOT NULL REFERENCES roots(id) ON DELETE CASCADE,
    path         TEXT    NOT NULL,              -- relative to roots.path
    title        TEXT    NOT NULL,
    kind         TEXT    NOT NULL CHECK (kind IN ('pdf', 'md', 'html', 'py', 'sql')),
    is_important INTEGER NOT NULL DEFAULT 0 CHECK (is_important IN (0, 1)),
    added_at     TEXT    NOT NULL DEFAULT (datetime('now')),

    UNIQUE (root_id, path)
);

INSERT INTO books_v3 (id, root_id, path, title, kind, is_important, added_at)
     SELECT id, root_id, path, title, kind, is_important, added_at
       FROM books;

DROP TABLE books;

ALTER TABLE books_v3 RENAME TO books;

COMMIT;
