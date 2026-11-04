-- Target database: zava. Execute as postgres after 11_reader_privileges.sql.
-- Apply this file in one transaction so policy creation and RLS enablement commit together.
-- Missing or empty store context matches no rows; invalid integers raise an error.
-- The composite foreign key already enforces the parent order's store.
-- The server must authorize the store before setting transaction-local context.

CREATE POLICY order_items_reader_select
    ON retail.order_items
    FOR SELECT
    TO zava_mcp_reader
    USING (
        store_id = NULLIF(current_setting('app.current_store_id', true), '')::integer
    );

ALTER TABLE retail.order_items ENABLE ROW LEVEL SECURITY;
