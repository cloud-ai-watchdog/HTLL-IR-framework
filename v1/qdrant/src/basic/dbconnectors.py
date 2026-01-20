from abc import ABC, abstractmethod
import psycopg2
from typing import Any, Dict

from .logger import get_colorlogger
logger = get_colorlogger(__name__)

class BaseConnector(ABC):
    @abstractmethod
    def connect(self, username: str, password: str, database: str, host: str, port: int):
        pass    
    @abstractmethod
    def execute_and_return_result(self, query: str) -> Any:
        pass

    def _validate_dbargs(self, dbargs):
        required_keys = ['username', 'password', 'database', 'host', 'port']
        for key in required_keys:
            if key not in dbargs:
                raise ValueError(f"Missing required database argument: {key}")
    
    @abstractmethod
    def __exit__(self, exc_type, exc_value, traceback):
        pass



    



class PostgressConnector(BaseConnector):
    def __init__(self, dbargs: Dict[str, Any]):
        self._validate_dbargs(dbargs)
        self.dbargs = dbargs
        self.connection = None
        try:
            self.connect(
                username=dbargs['username'],
                password=dbargs['password'],
                database=dbargs['database'],
                host=dbargs['host'],
                port=dbargs['port']
            )
            logger.info("Successfully connected to the database.")
        except Exception as e:
            logger.error(f"Failed to connect to the database: {e}")
            self.connection = None

    def connect(self, username: str, password: str, database: str, host: str, port: int):
        self.connection = psycopg2.connect(
            dbname=database,
            user=username,
            password=password,
            host=host,
            port=port
        )
    
    def execute_and_return_result(self, query: str, params=None):
        try:
            with self.connection.cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)

                if cursor.description:
                    result = cursor.fetchall()
                else:
                    result = []
                
                self.connection.commit()
                logger.info(f"[Query {query[:20]}...] executed successfully. Length of result: {len(result)}".replace("\n", " "))
                return result
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            try:
                self.connection.rollback()
            except Exception as rollback_error:
                logger.error(f"Error during rollback: {rollback_error}")
            raise e
        
    def __exit__(self, exc_type, exc_value, traceback):
        if self.connection:
            self.connection.close()
            self.connection = None
            logger.info("Database connection closed.")







def get_database_connector(db_type: str, username: str, password: str, database: str, host: str, port: int) -> BaseConnector:
    dbargs = {
        'username': username,
        'password': password,
        'database': database,
        'host': host,
        'port': port
    }
    if db_type.lower() == 'postgresql':
        logger.info("Created PostgreSQL connector.")
        return PostgressConnector(dbargs)
    else:
        logger.error(f"Unsupported database type: {db_type}")
        raise ValueError(f"Unsupported database type: {db_type}")