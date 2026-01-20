from qdrant_client import QdrantClient, models
from typing import List, Any, Optional, Dict
from pydantic import BaseModel
import datetime
from .embedder import BaseEmbedder
import hashlib
from .utils import get_time, hash_text_to_string
import re

from .logger import get_colorlogger
logger = get_colorlogger(__name__)

class Insertable(BaseModel):
    text: str
    metadata: dict
    insert_timestamp: Optional[str] = None

class VectorStore:
    def __init__(
        self,
        collection_name,
        embedder: BaseEmbedder,
        url:str
    ):
        """
        Common choices:
        - distance: "cosine", "euclidean", "dot"
        - collection_name: any string
        - embedder: any subclass of BaseEmbedder
        - url: Qdrant URL, e.g., "http://localhost:6333
        """
        self.collection_name = collection_name
        self.embedder = embedder
        self.url = url

        try:
            self.client = QdrantClient(url=self.url)
            logger.info(f"Connected to Qdrant at {self.url}")
        except Exception as e:
            logger.error(f"Failed to connect to Qdrant at {self.url}: {e}")
            raise

        self.create_collection_if_not_exists(
                vector_size=embedder.vector_size,
                distance=embedder.distance
            )

    def create_collection_if_not_exists(self, 
                                        vector_size: int, 
                                        distance: str):
        
        if distance == "cosine":
            dist = models.Distance.COSINE
        elif distance == "euclidean":
            dist = models.Distance.EUCLIDEAN
        elif distance == "dot":
            dist = models.Distance.DOT
        else:
            logger.error("Unsupported distance metric")
            raise ValueError("Unsupported distance metric")


        if not self.client.collection_exists(collection_name=self.collection_name):
            try:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=dist
                    )
                )
                logger.info(f"Created collection: {self.collection_name}")
            except Exception as e:
                logger.error(f"Failed to create collection {self.collection_name}: {e}")
                raise
        else:
            logger.info(f"Collection {self.collection_name} already exists.")
    
    def delete_collection_if_exists(self):
        if self.client.collection_exists(collection_name=self.collection_name):
            try:
                self.client.delete_collection(collection_name=self.collection_name)
                logger.info(f"Deleted collection: {self.collection_name}")
            except Exception as e:
                logger.error(f"Failed to delete collection {self.collection_name}: {e}")
                raise

    def _hash(self, insertable: Insertable) -> str:
        stringifoed_obj = f"{insertable.text}-{insertable.metadata}"
        return hash_text_to_string(stringifoed_obj)
    
    def inserts(self, objects: List[Dict]):
        # Validate inputs to check 'text' and 'metadata' keys
        insertables = [Insertable(**obj) for obj in objects]
        texts = [obj.text for obj in insertables]
        logger.info(f"Embedding {len(texts)} texts for insertion.")
        for insertable, embedding in zip(insertables, self.embedder.embeds(texts)):
            _id = self._hash(insertable)
            # Current timestamp
            ISO_8601_UTC_REGEX = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"

            if insertable.insert_timestamp is None:
                insertable.insert_timestamp = get_time()
            else:
                if not re.match(ISO_8601_UTC_REGEX, insertable.insert_timestamp):
                    logger.error(
                        f"insert_timestamp must be in ISO 8601 UTC format (…Z): {insertable.insert_timestamp}"
                    )
                    raise ValueError(
                        f"insert_timestamp must be in ISO 8601 UTC format (…Z): {insertable.insert_timestamp}"
                    )

            logger.info(f"Inserting ID: {_id}")
            try:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=[
                        {
                            "id": self._hash(insertable),
                            "vector": embedding,
                            "payload": {
                                **insertable.metadata,
                                "insert_timestamp": insertable.insert_timestamp,
                            }
                        }
                    ]
                )
                logger.info(f"Successfully inserted point with ID: {_id}")
            except Exception as e:
                logger.error(f"Failed to insert point with ID {_id}: {e}")
                raise

    def insert(self, obj: Dict):
        objs = [obj]
        self.inserts(objs)

    def search(self, query: str, filter_: Optional[models.Filter] = None, top_k: int = 5):
        try:
            query_embedding = self.embedder.embed(query)
            results = self.client.query_points(
                collection_name=self.collection_name,
                query=query_embedding,
                query_filter=filter_,
                limit=top_k,
                with_payload=True
            )
            logger.info(f"Search completed for query, returned {len(results.points)} results.")
            return results
        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            raise

    def search_batch(self, queries: List[str], filters: List[Optional[models.Filter]] = None, top_k: int = 5):
        assert filters is None or len(filters) == len(queries), "Filters length must match queries length"
        try:
            search_queries = [
                models.QueryRequest(
                    query=self.embedder.embed(q),
                    filter=f if filters else None,
                    limit=top_k,
                    with_payload=True
                ) for q, f in zip(queries, filters or [None]*len(queries))
            ]

            res = self.client.query_batch_points(
                collection_name=self.collection_name,
                requests=search_queries
            )
            logger.info(f"Batch search completed for {len(queries)} queries.")
            return res
        except Exception as e:
            logger.error(f"Batch search failed: {e}")
            raise
    
    def scroll(self, filters: Optional[models.Filter] = None, batch_size: int = 10):
        try:
            scroll_result = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=filters,
                limit=batch_size,
                with_payload=True
            )
            logger.info(f"Scroll completed, returned {len(scroll_result[0])} points.")
            return scroll_result
        except Exception as e:
            logger.error(f"Scroll failed: {e}")
            raise
    
    def delete_conditional(self, filters: Optional[models.Filter] = None):
        try:
            res = self.client.delete_points(
                collection_name=self.collection_name,
                points_selector=models.PointsSelector(filter=filters)
            )
            logger.info(f"Deleted {res.points_count} points conditionally.")
            return res
        except Exception as e:
            logger.error(f"Conditional delete failed: {e}")
            raise
    
    def update_payload_conditional(self, new_payload: Dict[str, Any], filters: Optional[models.Filter] = None):
        try:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload=new_payload,
                points=models.PointsSelector(filter=filters)
            )
            logger.info("Payload updated conditionally.")
        except Exception as e:
            logger.error(f"Conditional payload update failed: {e}")
            raise