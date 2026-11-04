-- Target database: zava. Execute as postgres after 12_orders_rls.sql.
-- Apply this file in one transaction so policy creation and RLS enablement commit together.
-- A customer is visible through their primary store or an order at the current store.
-- The orders policy must not reference customers, preventing a policy dependency cycle.
-- Missing or empty store context matches no rows; invalid integers raise an error.
-- The server must authorize the store before setting transaction-local context.

CREATE POLICY customers_reader_select
    ON retail.customers
    FOR SELECT
    TO zava_mcp_reader
    USING (
        primary_store_id = NULLIF(current_setting('app.current_store_id', true), '')::integer
        OR EXISTS (
            SELECT 1
            FROM retail.orders AS o
            WHERE o.customer_id = customers.customer_id
              AND o.store_id = NULLIF(current_setting('app.current_store_id', true), '')::integer
        )
    );

ALTER TABLE retail.customers ENABLE ROW LEVEL SECURITY;
