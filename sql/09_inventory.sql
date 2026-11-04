-- Target database: zava. Execute as postgres after 02_stores.sql and 05_products.sql.
-- Create the table only; an existing table causes an error.
-- Each row represents one store/product pair and its current stock.
-- Require explicit stock values: zero is valid, but missing stock is not.

CREATE TABLE retail.inventory (
    store_id integer NOT NULL,
    product_id integer NOT NULL,
    stock_level integer NOT NULL,

    CONSTRAINT inventory_pkey PRIMARY KEY (store_id, product_id),
    CONSTRAINT inventory_store_id_fkey
        FOREIGN KEY (store_id) REFERENCES retail.stores (store_id)
        ON DELETE NO ACTION ON UPDATE NO ACTION,
    CONSTRAINT inventory_product_id_fkey
        FOREIGN KEY (product_id) REFERENCES retail.products (product_id)
        ON DELETE NO ACTION ON UPDATE NO ACTION,
    CONSTRAINT inventory_stock_level_check CHECK (stock_level >= 0)
);
