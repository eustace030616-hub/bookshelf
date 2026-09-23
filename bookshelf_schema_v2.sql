-- schema v2 — widen books.kind so the shelf can hold code as well as books
--
-- Revision 1 constrained `kind` to ('pdf','md'). SQLite cannot ALTER a CHECK
-- constraint: the constraint lives in the table definition, and the only way to
-- replace a table definition is to rebuild the table. So: create the new shape,
-- copy every row, drop the old table, rename. This is the procedure sqlite.org
-- documents under "Making Other Kinds Of Table Schema Changes".
--
-- `books.id` is copied, not renumbered, so is_important and every id the user has
-- already seen stay attached to the same file. Revision 1's UNIQUE (root_id, path)
-- is re-created with the table, and still supplies the index for "everything in
-- root N", so no separate index on root_id is needed.
--
-- Applied by db.bootstrap() once, when user_version is 1. A fresh database gets
-- revision 1 first and then this file, so there is a single code path.

BEGIN;

CREATE TABLE books_v2 (
    id           INTEGER PRIMARY KEY,
    root_id      INTEGER NOT NULL REFERENCES roots(id) ON DELETE CASCADE,
    path         TEXT    NOT NULL,              -- relative to roots.path
    title        TEXT    NOT NULL,
    kind         TEXT    NOT NULL CHECK (kind IN ('pdf', 'md', 'py', 'sql')),
    is_important INTEGER NOT NULL DEFAULT 0 CHECK (is_important IN (0, 1)),
    added_at     TEXT    NOT NULL DEFAULT (datetime('now')),

    UNIQUE (root_id, path)
);

INSERT INTO books_v2 (id, root_id, path, title, kind, is_important, added_at)
     SELECT id, root_id, path, title, kind, is_important, added_at
       FROM books;

DROP TABLE books;

ALTER TABLE books_v2 RENAME TO books;

COMMIT;
