-- schema v5 — the documents themselves, beside their rows
--
-- Until now the database held paths and stars: the shelf was a view of your folders and the
-- bytes stayed where they were. This table is what makes the shelf readable from somewhere
-- that does not have the folders — a phone, a container, a VPS — because the server has
-- nothing else to read from.
--
-- A separate table, not a column on books. `list_books` does `SELECT b.*` and every tree node
-- carries `dict(row)`, so content on `books` would drag the whole library through every
-- reload. One document is read at a time, so 1:1 is the right shape, and ON DELETE CASCADE
-- means a file that vanished takes its body with it.
--
-- `source_size` and `source_mtime` are what make `u` cheap: the walk compares them and reads
-- only the files that changed. Without them every update would re-read the entire library.
--
-- The migration can create the table but cannot fill it -- backfilling needs the files -- so
-- the first `u` after upgrading is what populates it, and the app has to run once on the
-- machine that has the folders. `i` heals a single row on the way through, for rows that
-- predate this revision.
--
-- Search is deliberately not here. An FTS index over `body` is revision 6, once the ingest
-- this table introduces has been proven.

BEGIN;

CREATE TABLE content (
    book_id      INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    body         TEXT    NOT NULL,          -- the file, verbatim: rendering is the reader's job
    bytes        INTEGER NOT NULL,          -- utf-8 length, for a status line and for the phone
    source_size  INTEGER NOT NULL,          -- stat() of the file this came from
    source_mtime TEXT    NOT NULL,
    ingested_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- "which rows have no body yet": the heal-on-read path and the freshness line both ask this
CREATE INDEX content_ingested_at ON content (ingested_at);

COMMIT;
