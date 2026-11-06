-- Target database: zava. Execute as postgres after 11_reader_privileges.sql,
-- 17_product_embeddings.sql and 18_embedding_writer_role.sql.
BEGIN;

GRANT CONNECT ON DATABASE zava TO zava_embedding_writer;
GRANT USAGE ON SCHEMA retail TO zava_embedding_writer;
GRANT SELECT (product_id, product_name, product_description)
    ON retail.products TO zava_embedding_writer;
GRANT SELECT (product_id), INSERT (product_id, embedding), UPDATE (embedding)
    ON retail.product_embeddings TO zava_embedding_writer;
GRANT SELECT ON retail.product_embeddings TO zava_mcp_reader;

COMMIT;
