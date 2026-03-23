import sqlite3
from contextlib import contextmanager
from pathlib import Path

import psycopg2


class DatabaseManager:
    def __init__(self, config):

        self.config = config
        self.logger = None
        self.database_engine = getattr(self.config, 'DATABASE_ENGINE', 'postgres')
        self.table_name = getattr(self.config, 'DATABASE_TABLE', self.config.POSTGRESQL_TABLE)
        self.sqlite_db_path = None

        self._initialize_sqlite_schema_if_needed()

    def _initialize_sqlite_schema_if_needed(self):
        if self.database_engine != 'sqlite':
            return

        sqlite_db_path = getattr(self.config, 'SQLITE_DB_PATH', None)
        if not sqlite_db_path:
            raise ValueError('SQLITE_DB_PATH is required when DATABASE_ENGINE=sqlite')

        current_file = Path(__file__).resolve()
        project_root = current_file.parents[3]
        schema_path = project_root / 'docker' / 'sqlite' / 'init' / '001-init-seek_jobs.sqlite.sql'

        if not schema_path.is_file():
            raise FileNotFoundError(f'SQLite schema file not found: {schema_path}')

        sqlite_path = self._resolve_sqlite_db_path(project_root)

        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        with schema_path.open('r', encoding='utf-8') as schema_file:
            schema_sql = schema_file.read()

        with sqlite3.connect(sqlite_path) as conn:
            conn.executescript(schema_sql)

        self.sqlite_db_path = sqlite_path
        self.log('info', f'SQLite schema initialized at: {sqlite_path}')

    def _resolve_sqlite_db_path(self, project_root):
        sqlite_path = Path(self.config.SQLITE_DB_PATH)
        if not sqlite_path.is_absolute():
            sqlite_path = project_root / sqlite_path
        return sqlite_path

    def _normalize_query_and_params(self, query, params):
        normalized_params = tuple(params or ())
        if self.database_engine == 'sqlite':
            return query.replace('%s', '?'), normalized_params
        return query, normalized_params

    def set_logger(self, logger):
        self.logger = logger

    def log(self, level, msg):
        if self.logger:
            getattr(self.logger, level)(msg)

    @contextmanager
    def get_connection(self):
        conn = None
        try:
            if self.database_engine == 'sqlite':
                if not self.sqlite_db_path:
                    current_file = Path(__file__).resolve()
                    project_root = current_file.parents[3]
                    self.sqlite_db_path = self._resolve_sqlite_db_path(project_root)
                conn = sqlite3.connect(self.sqlite_db_path)
                self.log('debug', f'Database connection established (engine: sqlite, path: {self.sqlite_db_path})')
            else:
                conn = psycopg2.connect(
                    host=self.config.POSTGRESQL_HOST,
                    port=self.config.POSTGRESQL_PORT,
                    user=self.config.POSTGRESQL_USER,
                    password=self.config.POSTGRESQL_PASSWORD,
                    database=self.config.POSTGRESQL_DATABASE
                )
                with conn.cursor() as cur:
                    cur.execute("SET timezone = 'Australia/Perth'")
                self.log('debug', 'Database connection established (engine: postgres, timezone: Australia/Perth)')
            yield conn
        except Exception as e:
            self.log('error', f'Database connection error: {str(e)}')
            raise
        finally:
            if conn:
                conn.close()
                self.log('debug', 'Database connection closed')

    @contextmanager
    def get_cursor(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
                conn.commit()
            except Exception as e:
                self.log('error', f'Database operation error: {str(e)}')
                conn.rollback()
                raise
            finally:
                cursor.close()

    def execute_query(self, query, params=None):
        with self.get_cursor() as cur:
            try:
                normalized_query, normalized_params = self._normalize_query_and_params(query, params)
                cur.execute(normalized_query, normalized_params)
                return cur.fetchall()
            except Exception as e:
                self.log('error', f'Query execution error: {str(e)}')
                raise

    def execute_update(self, query, params=None):
        with self.get_cursor() as cur:
            try:
                normalized_query, normalized_params = self._normalize_query_and_params(query, params)
                cur.execute(normalized_query, normalized_params)
                return cur.rowcount
            except Exception as e:
                self.log('error', f'Update execution error: {str(e)}')
                raise

    def get_existing_job_ids(self):
        query = f'SELECT "Id" FROM "{self.table_name}"'
        results = self.execute_query(query)
        return {str(row[0]) for row in results}

    def insert_job(self, job_data):
        columns = ', '.join([f'"{k}"' for k in job_data.keys()])
        placeholders = ', '.join(['%s'] * len(job_data))
        query = f'''
            INSERT INTO "{self.table_name}" ({columns})
            VALUES ({placeholders})
        '''
        self.execute_update(query, list(job_data.values()))
        self.log('info', f'Inserted job with ID: {job_data.get("Id")}')

    def update_job(self, job_id, job_data):
        """
        Update a job record in the database.

        Args:
            job_id: The ID of the job to update
            job_data: Dictionary containing the fields to update

        Returns:
            Number of rows affected (0 if job already had description, 1 if updated)

        Note:
            UpdatedAt field is automatically set to current timestamp,
            do not include it in job_data.
            When updating JobDescription, only updates if current value is empty
            (prevents race conditions in concurrent execution).
        """
        set_clause = ', '.join([f'"{k}" = %s' for k in job_data.keys()])

        # Check if we're updating JobDescription
        if 'JobDescription' in job_data:
            # Add condition to only update if JobDescription is currently empty
            # This is an atomic check-and-set operation at the database level
            query = f'''
                UPDATE "{self.table_name}"
                SET {set_clause}, "UpdatedAt" = CURRENT_TIMESTAMP
                WHERE "Id" = %s
                AND ("JobDescription" IS NULL OR "JobDescription" = '' OR "JobDescription" = 'None')
            '''
        else:
            # For other updates, no special condition needed
            query = f'''
                UPDATE "{self.table_name}"
                SET {set_clause}, "UpdatedAt" = CURRENT_TIMESTAMP
                WHERE "Id" = %s
            '''

        affected = self.execute_update(query, list(job_data.values()) + [job_id])

        if 'JobDescription' in job_data and affected == 0:
            self.log('debug', f'Job {job_id} already has description, skipped update (race condition avoided)')
        else:
            self.log('info', f'Updated job {job_id}, affected rows: {affected}')

        return affected

    def mark_jobs_inactive(self, job_ids):
        if not job_ids:
            return 0

        id_placeholders = ', '.join(['%s'] * len(job_ids))
        active_value = 1 if self.database_engine == 'sqlite' else 'TRUE'
        inactive_value = 0 if self.database_engine == 'sqlite' else 'FALSE'

        query = f'''
            UPDATE "{self.table_name}"
            SET "IsActive" = {inactive_value},
                "UpdatedAt" = CURRENT_TIMESTAMP,
                "ExpiryDate" = CURRENT_TIMESTAMP
            WHERE "Id" IN ({id_placeholders})
            AND "IsActive" = {active_value}
        '''
        affected = self.execute_update(query, [str(job_id) for job_id in job_ids])
        self.log('info', f'Marked {affected} jobs as inactive')
        return affected

    def get_unprocessed_jobs(self):
        query = f'''
            SELECT "Id", "JobDescription" 
            FROM "{self.table_name}" 
            WHERE "TechStack" IS NULL 
            AND "JobDescription" IS NOT NULL
        '''
        return self.execute_query(query)
