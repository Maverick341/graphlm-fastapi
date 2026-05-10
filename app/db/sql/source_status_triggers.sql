-- =============================================================================
-- PostgreSQL LISTEN/NOTIFY Trigger Functions and Triggers
-- Channel: source_status_updates
--
-- Trigger 1: Fires AFTER UPDATE on sources when status changes.
-- Trigger 2: Fires AFTER UPDATE on source_indexes when vector_indexed,
--            graph_indexed, or error_message changes.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- FUNCTION: notify_source_status_update
-- Fires on sources.status change. Publishes overall source status.
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION notify_source_status_update()
RETURNS TRIGGER AS $$
DECLARE
    payload TEXT;
BEGIN
    payload := json_build_object(
        'event',          'source_status_changed',
        'source_id',      NEW.id,
        'overall_status', NEW.status,
        'title',          NEW.title,
        'type',           NEW.type
    )::text;

    PERFORM pg_notify('source_status_updates', payload);

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- -----------------------------------------------------------------------------
-- TRIGGER: source_status_trigger
-- AFTER UPDATE on sources — only when status actually changes.
-- -----------------------------------------------------------------------------

CREATE TRIGGER source_status_trigger
AFTER UPDATE ON sources
FOR EACH ROW
WHEN (
    OLD.status IS DISTINCT FROM NEW.status
)
EXECUTE FUNCTION notify_source_status_update();


-- -----------------------------------------------------------------------------
-- FUNCTION: notify_source_index_update
-- Fires on source_indexes changes. Publishes full index state.
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION notify_source_index_update()
RETURNS TRIGGER AS $$
DECLARE
    payload TEXT;
BEGIN
    payload := json_build_object(
        'event',             'source_index_changed',
        'source_id',         NEW.source_id,

        'vector_indexed',    NEW.vector_indexed,
        'vector_indexed_at', NEW.vector_indexed_at,

        'graph_indexed',     NEW.graph_indexed,
        'graph_indexed_at',  NEW.graph_indexed_at,

        'entity_count',      NEW.entity_count,
        'relation_count',    NEW.relation_count,

        'error_message',     NEW.error_message
    )::text;

    PERFORM pg_notify('source_status_updates', payload);

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- -----------------------------------------------------------------------------
-- TRIGGER: source_index_status_trigger
-- AFTER UPDATE on source_indexes — only when meaningful fields change.
-- -----------------------------------------------------------------------------

CREATE TRIGGER source_index_status_trigger
AFTER UPDATE ON source_indexes
FOR EACH ROW
WHEN (
    OLD.vector_indexed  IS DISTINCT FROM NEW.vector_indexed
    OR
    OLD.graph_indexed   IS DISTINCT FROM NEW.graph_indexed
    OR
    OLD.error_message   IS DISTINCT FROM NEW.error_message
)
EXECUTE FUNCTION notify_source_index_update();
