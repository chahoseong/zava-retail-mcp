-- Target database: zava. Execute as postgres after 03_categories.sql.
-- Create the table only; an existing table causes an error.
-- Preserve source IDs without identity generation or column defaults.
-- The composite unique key supports future product type/category references.

CREATE TABLE retail.product_types (
    type_id integer NOT NULL,
    category_id integer NOT NULL,
    type_name text NOT NULL,

    CONSTRAINT product_types_pkey PRIMARY KEY (type_id),
    CONSTRAINT product_types_type_id_category_id_key UNIQUE (type_id, category_id),
    CONSTRAINT product_types_category_id_fkey
        FOREIGN KEY (category_id) REFERENCES retail.categories (category_id)
        ON DELETE NO ACTION ON UPDATE NO ACTION
);
