-- Target database: zava. Execute as postgres after 01_schema.sql.
-- Create the table only; an existing table causes an error.
-- Preserve source IDs without identity generation or column defaults.
-- rls_user_id preserves source metadata and is not an authorization claim.

CREATE TABLE retail.stores (
    store_id integer NOT NULL,
    store_name text NOT NULL,
    rls_user_id uuid,
    is_online boolean NOT NULL,

    CONSTRAINT stores_pkey PRIMARY KEY (store_id),
    CONSTRAINT stores_store_name_key UNIQUE (store_name)
);
