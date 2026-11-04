-- Target database: zava. Execute as postgres after 11_reader_privileges.sql.
-- Apply this file in one transaction so policy creation and RLS enablement commit together.
-- Missing or empty store context matches no rows; invalid integers raise an error.
-- Filter by store only: zero-stock rows must remain visible to that store.
-- The server must authorize the store before setting transaction-local context.

CREATE POLICY inventory_reader_select
    ON retail.inventory
    FOR SELECT
    TO zava_mcp_reader
    USING (
        store_id = NULLIF(current_setting('app.current_store_id', true), '')::integer
    );

ALTER TABLE retail.inventory ENABLE ROW LEVEL SECURITY;
