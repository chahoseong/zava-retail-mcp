-- Target database: zava. Execute as the postgres administrator.
-- Create the login role only; an existing role causes an error.
-- Set its password separately from the local, Git-ignored .env.reader file.
-- Database, schema and table privileges will be configured in the next step.

CREATE ROLE zava_mcp_reader
    LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION
    NOBYPASSRLS;
