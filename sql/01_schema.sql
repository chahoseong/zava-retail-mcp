-- Target database: zava. Execute as postgres.
-- Create the schema only; an existing schema causes an error.
-- Business tables will be created in a later step:
--   retail.stores
--   retail.categories
--   retail.product_types
--   retail.products
--   retail.customers
--   retail.orders
--   retail.order_items
--   retail.inventory

CREATE SCHEMA retail AUTHORIZATION postgres;
