-- Execute as postgres. Set the role password separately in the local setup.
CREATE ROLE zava_embedding_writer
    LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION
    NOBYPASSRLS;
