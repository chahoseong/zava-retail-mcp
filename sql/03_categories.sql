-- Target database: zava. Execute as postgres after 01_schema.sql.
-- Create the table only; an existing table causes an error.
-- Preserve source IDs without identity generation or column defaults.
-- Store category names as supplied, without case or whitespace normalization.

CREATE TABLE retail.categories (
    category_id integer NOT NULL,
    category_name text NOT NULL,

    CONSTRAINT categories_pkey PRIMARY KEY (category_id),
    CONSTRAINT categories_category_name_key UNIQUE (category_name)
);
