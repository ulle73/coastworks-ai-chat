-- Generated columns also backfill the existing active index. Both branches are
-- tenant/version scoped by retrieval; GIN is only a candidate lookup accelerator.
ALTER TABLE chunks ADD COLUMN search_text tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('swedish'::regconfig, coalesce(title,'')), 'A') ||
    setweight(to_tsvector('swedish'::regconfig, content), 'B') ||
    to_tsvector('simple'::regconfig, coalesce(title,'') || ' ' || content)
) STORED;
CREATE INDEX chunks_search_gin ON chunks USING gin(search_text);
