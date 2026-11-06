-- Target database: zava. Execute as postgres after 05_products.sql and 16_vector_extension.sql.
CREATE TABLE retail.product_embeddings (
    product_id integer PRIMARY KEY REFERENCES retail.products (product_id),
    embedding vector(768) NOT NULL CHECK (vector_norm(embedding) > 0)
);
