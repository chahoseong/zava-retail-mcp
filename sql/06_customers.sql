-- Target database: zava. Execute as postgres after 02_stores.sql.
-- Create the table only; an existing table causes an error.
-- Preserve source IDs without identity generation or column defaults.
-- Preserve email text and source timestamps without normalization or timezone conversion.
-- A customer's primary store does not restrict the store of their orders.

CREATE TABLE retail.customers (
    customer_id integer NOT NULL,
    first_name text NOT NULL,
    last_name text NOT NULL,
    email text NOT NULL,
    phone text,
    primary_store_id integer,
    created_at timestamp without time zone NOT NULL,

    CONSTRAINT customers_pkey PRIMARY KEY (customer_id),
    CONSTRAINT customers_email_key UNIQUE (email),
    CONSTRAINT customers_primary_store_id_fkey
        FOREIGN KEY (primary_store_id) REFERENCES retail.stores (store_id)
        ON DELETE NO ACTION ON UPDATE NO ACTION
);
