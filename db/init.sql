-- Creates the application's two login roles and the `shiptrack` schema in the database that
-- `python -m shiptrack db-init` is connected to, and grants the application what it needs. Safe to run
-- again: it creates what is missing and resets both passwords to the values it was given, which is how a
-- rotated password reaches the database.
--
-- It runs as the database administrator, who is not a superuser (an RDS master or a Cloud SQL
-- administrator). The passwords and connection limits arrive as session settings set by the command:
-- shiptrack.app_password, shiptrack.migrator_password, shiptrack.app_connection_limit, and
-- shiptrack.migrator_connection_limit. No password is ever a literal in this file.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'shiptrack_migrator') THEN
    CREATE ROLE shiptrack_migrator LOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'shiptrack_app') THEN
    CREATE ROLE shiptrack_app LOGIN;
  END IF;
  EXECUTE format('ALTER ROLE shiptrack_migrator PASSWORD %L CONNECTION LIMIT %s',
    current_setting('shiptrack.migrator_password'), current_setting('shiptrack.migrator_connection_limit')::int);
  EXECUTE format('ALTER ROLE shiptrack_app PASSWORD %L CONNECTION LIMIT %s',
    current_setting('shiptrack.app_password'), current_setting('shiptrack.app_connection_limit')::int);
END
$$;

-- The administrator must be able to SET ROLE to the migrator before it creates anything owned by it.
-- The grant is removed again at the end.
GRANT shiptrack_migrator TO CURRENT_USER WITH SET TRUE;

-- The migrator owns the database where the administrator is allowed to hand it over. A managed service
-- may have made another role the owner, so a refusal is not an error: the migrator owns the schema, and
-- that is all it needs.
DO $$
BEGIN
  EXECUTE format('ALTER DATABASE %I OWNER TO shiptrack_migrator', current_database());
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'the database keeps its owner';
END
$$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE SCHEMA IF NOT EXISTS shiptrack AUTHORIZATION shiptrack_migrator;
ALTER SCHEMA shiptrack OWNER TO shiptrack_migrator;

DO $$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO shiptrack_migrator, shiptrack_app', current_database());
END
$$;
GRANT USAGE ON SCHEMA shiptrack TO shiptrack_app;

-- Tables and sequences the migrator creates later are usable by the application without a new grant.
ALTER DEFAULT PRIVILEGES FOR ROLE shiptrack_migrator IN SCHEMA shiptrack
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO shiptrack_app;
ALTER DEFAULT PRIVILEGES FOR ROLE shiptrack_migrator IN SCHEMA shiptrack
  GRANT USAGE, SELECT ON SEQUENCES TO shiptrack_app;

-- Objects that already exist (a re-run after the first migration) get the same privileges.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA shiptrack TO shiptrack_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA shiptrack TO shiptrack_app;

REVOKE shiptrack_migrator FROM CURRENT_USER;
