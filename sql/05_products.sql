-- Target database: zava. Execute as postgres after 04_product_types.sql.
-- Create the table only; an existing table causes an error.
-- Preserve source IDs without identity generation or column defaults.
-- Products form a shared catalog; store-specific stock belongs in inventory.
-- Preserve the source margin without recalculation or an extra range rule.

CREATE TABLE retail.products (
    product_id integer NOT NULL,
    sku text NOT NULL,
    product_name text NOT NULL,
    category_id integer NOT NULL,
    type_id integer NOT NULL,
    cost numeric(10,2) NOT NULL,
    base_price numeric(10,2) NOT NULL,
    gross_margin_percent numeric(5,2),
    product_description text NOT NULL,

    CONSTRAINT products_pkey PRIMARY KEY (product_id),
    CONSTRAINT products_sku_key UNIQUE (sku),
    CONSTRAINT products_category_id_fkey
        FOREIGN KEY (category_id) REFERENCES retail.categories (category_id)
        ON DELETE NO ACTION ON UPDATE NO ACTION,
    CONSTRAINT products_type_id_category_id_fkey
        FOREIGN KEY (type_id, category_id)
        REFERENCES retail.product_types (type_id, category_id)
        ON DELETE NO ACTION ON UPDATE NO ACTION,
    CONSTRAINT products_cost_check CHECK (cost >= 0),
    CONSTRAINT products_base_price_check CHECK (base_price >= 0)
);
