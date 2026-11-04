-- Target database: zava. Execute as postgres after 06_customers.sql.
-- Create the table only; an existing table causes an error.
-- Preserve source IDs and order dates without generated values or defaults.
-- The order's store may differ from the customer's primary store.
-- The composite unique key supports future order item/store references.

CREATE TABLE retail.orders (
    order_id integer NOT NULL,
    customer_id integer NOT NULL,
    store_id integer NOT NULL,
    order_date date NOT NULL,

    CONSTRAINT orders_pkey PRIMARY KEY (order_id),
    CONSTRAINT orders_order_id_store_id_key UNIQUE (order_id, store_id),
    CONSTRAINT orders_customer_id_fkey
        FOREIGN KEY (customer_id) REFERENCES retail.customers (customer_id)
        ON DELETE NO ACTION ON UPDATE NO ACTION,
    CONSTRAINT orders_store_id_fkey
        FOREIGN KEY (store_id) REFERENCES retail.stores (store_id)
        ON DELETE NO ACTION ON UPDATE NO ACTION
);
