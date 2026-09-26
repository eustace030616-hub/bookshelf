-- schema v7 — the range a reader marks is a highlight, not an underline
--
-- Revision 6 called the second kind `underline`, after the way it was drawn. It is drawn as a
-- warm wash behind the words now, because underline is a Markdown thing -- a link, a run of
-- emphasis -- and drawing it over a range told a reader nothing about which lines were theirs.
-- The name in the table should say what the row means, not what it looked like in one version.
--
-- So: a table rebuild, the same procedure as revisions 2 and 3, because a CHECK constraint
-- cannot be altered in place. `id` and `book_id` are copied, the one existing kind is renamed
-- in the same statement, and nothing else changes.
--
-- Applied by db.bootstrap() once, when user_version is 6.

BEGIN;

CREATE TABLE annotation_v7 (
    id         INTEGER PRIMARY KEY,
    book_id    INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    kind       TEXT    NOT NULL CHECK (kind IN ('mark', 'highlight', 'note')),
    anchor     TEXT    NOT NULL,
    position   INTEGER NOT NULL,
    span       INTEGER NOT NULL DEFAULT 0,
    note       TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO annotation_v7 (id, book_id, kind, anchor, position, span, note, created_at)
     SELECT id, book_id,
            CASE kind WHEN 'underline' THEN 'highlight' ELSE kind END,
            anchor, position, span, note, created_at
       FROM annotation;

DROP TABLE annotation;

ALTER TABLE annotation_v7 RENAME TO annotation;

CREATE INDEX annotation_book_kind ON annotation (book_id, kind);

COMMIT;
