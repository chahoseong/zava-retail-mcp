-- Target database: zava. Execute as postgres after 10_reader_role.sql.
-- This PUBLIC revoke affects every ordinary role connected to zava.
-- Grant temporary-table privileges separately if another role needs them.
REVOKE TEMPORARY ON DATABASE zava FROM PUBLIC;

GRANT CONNECT ON DATABASE zava TO zava_mcp_reader;
GRANT USAGE ON SCHEMA retail TO zava_mcp_reader;

-- Enumerate the current business tables; future tables are not auto-granted.
-- No grant option or sequence privileges are granted.
GRANT SELECT ON TABLE
    retail.stores,
    retail.categories,
    retail.product_types,
    retail.products,
    retail.customers,
    retail.orders,
    retail.order_items,
    retail.inventory
TO zava_mcp_reader;

-- Row-level policies will be configured separately in the following steps.
