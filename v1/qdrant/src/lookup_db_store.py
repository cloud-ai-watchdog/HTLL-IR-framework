from .basic.dbconnectors import get_database_connector

from .basic.logger import get_colorlogger
logger = get_colorlogger(__name__)

class LookupDbStore:
    def __init__(self, username: str, password: str, database: str, host: str, port: int, table_name: str):
        self.db_connector = get_database_connector(
            db_type="postgresql",
            username=username,
            password=password,
            database=database,
            host=host,
            port=port
        )
        self.table_name = table_name
        self._warmup_lookup_db()

    def _warmup_lookup_db(self):
        try:
            # Simple query to test connection
            result = self.db_connector.execute_and_return_result("SELECT 1;")
            create_table_query = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id TEXT PRIMARY KEY,
                closest_log_id TEXT NOT NULL,
                similarity FLOAT NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                location TEXT
            );
            """
            res = self.db_connector.execute_and_return_result(create_table_query)
            logger.info("Lookup DB warmed up successfully.")
            return res
        except Exception as e:
            logger.error(f"Failed to warmup lookup DB: {e}")
            raise

    def insert_into_lookup_db(self, 
                               log_id: str, 
                               closest_log_id: str, 
                               similarity: float, 
                               timestamp: str, 
                               location: str):
        try:
            insert_query = f"""
            INSERT INTO {self.table_name} (id, closest_log_id, similarity, timestamp, location)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING;
            """
            params = (log_id, closest_log_id, similarity, timestamp, location)
            self.db_connector.execute_and_return_result(insert_query, params)
            logger.info(f"Inserted into lookup DB: log_id={log_id}")
        except Exception as e:
            logger.error(f"Failed to insert into lookup DB for log_id {log_id}: {e}")
            raise

    def find_near_occurrences(self, log_id):
        try:
            # Fetch log entry from lookup DB
            fetch_query = f"""
            SELECT closest_log_id, similarity FROM {self.table_name}
            WHERE id = %s;
            """
            params = (log_id,)
            result = self.db_connector.execute_and_return_result(fetch_query, params)
            logger.info(f"Fetched near occurrences for log_id {log_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to find near occurrences for log_id {log_id}: {e}")
            raise

    def clear_lookup_db(self):
        try:
            delete_query = f"DELETE FROM {self.table_name};"
            self.db_connector.execute_and_return_result(delete_query)
            logger.info("Cleared lookup DB.")
        except Exception as e:
            logger.error(f"Failed to clear lookup DB: {e}")
            raise
