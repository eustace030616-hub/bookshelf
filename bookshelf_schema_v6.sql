-- schema v6 — annotations: a mark, and later an underline or a note
--
-- The shelf never rewrites a file. `content` holds what a document says; this table holds
-- what a reader says about it, which is why the two are separate: a note survives a `u`,
-- and a re-walk of the folder cannot overwrite it.
--
-- One table for three features, because they are the same thing at different sizes: a mark
-- is a position, an underline is a range, a note is a range with words attached.
--
--	kind       mark | underline | note
--	anchor     the text the annotation is attached to, so it can be found again after the
--	           document is re-rendered -- a scroll row or a character offset alone does not
--	           survive an edit upstream
--	position   a scroll row for a mark, a character offset into the source otherwise
--	span       how many characters a range covers; 0 for a mark
--	note       what the reader typed; NULL for anything that is not a note
--
-- Marks are one per document and expire: `take_mark` reads and deletes in the same
-- transaction, so the jump happens once. The CHECK on `kind` is the only guard against a
-- typo becoming a fourth feature by accident.

BEGIN;

CREATE TABLE annotation (
    id         INTEGER PRIMARY KEY,
    book_id    INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    kind       TEXT    NOT NULL CHECK (kind IN ('mark', 'underline', 'note')),
    anchor     TEXT    NOT NULL,
    position   INTEGER NOT NULL,
    span       INTEGER NOT NULL DEFAULT 0,
    note       TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Every read is "this document's annotations of this kind", and a mark is taken by kind
CREATE INDEX annotation_book_kind ON annotation (book_id, kind);

COMMIT;
