-- schema.sql — library metadata store, revision 1
--
-- Applied exactly once, by db.bootstrap(). Do not edit a released revision in
-- place: add revision 2 as a new script and bump db.SCHEMA_VERSION. Rows in
-- this DB are metadata only; the PDF/MD bytes live on disk.

-- A library directory. You have more than one, so this is a table, not a
-- key/value row. `roots.path` is the ONLY absolute path in this schema --
-- everything under it is relative, so a library folder can be moved and
-- re-registered without rewriting every book.
CREATE TABLE roots (
    id       INTEGER PRIMARY KEY,
    path     TEXT NOT NULL UNIQUE,
    label    TEXT NOT NULL,
    added_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per file on disk, belonging to exactly one root.
CREATE TABLE books (
    id           INTEGER PRIMARY KEY,
    root_id      INTEGER NOT NULL REFERENCES roots(id) ON DELETE CASCADE,
    path         TEXT    NOT NULL,              -- relative to roots.path
    title        TEXT    NOT NULL,
    kind         TEXT    NOT NULL CHECK (kind IN ('pdf', 'md')),
    is_important INTEGER NOT NULL DEFAULT 0 CHECK (is_important IN (0, 1)),
    added_at     TEXT    NOT NULL DEFAULT (datetime('now')),

    -- Not UNIQUE(path): two libraries may each contain guides/docker-guide.md.
    -- This composite also creates the index used for "everything in root N",
    -- so no separate index on root_id is needed.
    UNIQUE (root_id, path)
);

