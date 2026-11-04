-- Target database: zava. Execute as postgres after 07_orders.sql.
-- Create the table only; an existing table causes an error.
-- Preserve source IDs and amounts without generated values or defaults.
-- Keep historical sales independent of current inventory rows.
-- Preserve total_amount; do not enforce a recalculated transaction amount.

CREATE TABLE retail.order_items (
    order_item_id integer NOT NULL,
    order_id integer NOT NULL,
    store_id integer NOT NULL,
    product_id integer NOT NULL,
    quantity integer NOT NULL,
    unit_price numeric(10,2) NOT NULL,
    discount_percent integer NOT NULL,
    discount_amount numeric(10,2) NOT NULL,
    total_amount numeric(10,2) NOT NULL,

    CONSTRAINT order_items_pkey PRIMARY KEY (order_item_id),
    CONSTRAINT order_items_order_id_store_id_fkey
        FOREIGN KEY (order_id, store_id)
        REFERENCES retail.orders (order_id, store_id)
        ON DELETE NO ACTION ON UPDATE NO ACTION,
    CONSTRAINT order_items_product_id_fkey
        FOREIGN KEY (product_id) REFERENCES retail.products (product_id)
        ON DELETE NO ACTION ON UPDATE NO ACTION,
    CONSTRAINT order_items_quantity_check CHECK (quantity > 0),
    CONSTRAINT order_items_unit_price_check CHECK (unit_price >= 0),
    CONSTRAINT order_items_discount_percent_check CHECK (discount_percent BETWEEN 0 AND 100),
    CONSTRAINT order_items_discount_amount_check CHECK (discount_amount >= 0),
    CONSTRAINT order_items_total_amount_check CHECK (total_amount >= 0)
);
