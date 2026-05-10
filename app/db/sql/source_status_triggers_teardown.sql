-- =============================================================================
-- Teardown: Drop triggers and trigger functions for source_status_updates
-- Used by Alembic downgrade.
-- =============================================================================

DROP TRIGGER IF EXISTS source_status_trigger ON sources;
DROP FUNCTION IF EXISTS notify_source_status_update();

DROP TRIGGER IF EXISTS source_index_status_trigger ON source_indexes;
DROP FUNCTION IF EXISTS notify_source_index_update();
