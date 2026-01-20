
from typing import List, Dict, Optional
from .basic.vector_store import VectorStore, Insertable
from .basic.embedder import LshEmbedder
from .basic.dbconnectors import get_database_connector
from .basic.filter_adapter import adapter_specs_to_filters
from .basic.utils import get_time

from .lookup_db_store import LookupDbStore

from .basic.logger import get_colorlogger
logger = get_colorlogger(__name__)

class LogIngestionHtbridHandler:
    def __init__(self, 
                 qdrant_lsh_collection_name: str,
                 qdrant_lsh_shingle_size: int,
                 qdrant_lsh_num_hashes: int,
                 qdrant_lsh_bands: int,
                 qdrant_lsh_seed: int,
                 qdrant_lsh_normalize: bool,
                 qdrant_lsh_lowercase: bool,
                 qdrant_lsh_collapse_whitespace: bool,
                 qdrant_lsh_stop_short_lines: int,
                 qdrant_lsh_url: str,
                 pg_lookupdb_username: str,
                 pg_lookupdb_password: str,
                 pg_lookupdb_database: str,
                 pg_lookupdb_host: str,
                 pg_lookupdb_port: int,
                 pg_lookupdb_table_name: str,
                 insert_sim_threshold: float,
                 sim_sync_batch_size: int
                 ):
        
        self.vector_store = VectorStore(
            collection_name=qdrant_lsh_collection_name,
            embedder=LshEmbedder(
                shingle_size=qdrant_lsh_shingle_size,
                num_hashes=qdrant_lsh_num_hashes,
                bands=qdrant_lsh_bands,
                seed=qdrant_lsh_seed,
                normalize=qdrant_lsh_normalize,
                lowercase=qdrant_lsh_lowercase,
                collapse_whitespace=qdrant_lsh_collapse_whitespace,
                stop_short_lines=qdrant_lsh_stop_short_lines
            ),
            url=qdrant_lsh_url
        )

        self.lookup_db_store = LookupDbStore(
            username=pg_lookupdb_username,
            password=pg_lookupdb_password,
            database=pg_lookupdb_database,
            host=pg_lookupdb_host,
            port=pg_lookupdb_port,
            table_name=pg_lookupdb_table_name
        )
        
        self.insert_sim_threshold = insert_sim_threshold
        self.sim_sync_batch_size = sim_sync_batch_size

    def insert_logs(self, log_entries: List[Dict]):
        # Check with vector store for near-duplicates
        texts = [entry['text'] for entry in log_entries]
        search_results = self.vector_store.search_batch(
            queries=texts,
            top_k=1
        )

        if search_results is None or len(search_results) == 0:
            search_results = [None]*len(log_entries)
            
        vector_store_inserts = []
        for entry, result in zip(log_entries, search_results):
            entry['insert_timestamp'] = get_time()
            entry["metadata"]["sim_sync"] = False
            hashval = self.vector_store._hash(Insertable(text=entry['text'], metadata=entry.get('metadata', {})))
            if result.points:
                top_point = result.points[0]
                sim = top_point.score

                # sim = self.vector_store.embedder.compare(
                #     a=self.vector_store.embedder.embed(entry['text']),
                #     b=top_point.vector
                # )
                logger.info(f"{entry['text'][:30]}... <=> Top match ID: {top_point.id}/{top_point.payload.get('text','')[:30]}... with similarity: {sim}")
                
                if sim >= self.insert_sim_threshold:
                    logger.info(f"Skipping insert for log (ID: {hashval}) due to high similarity ({sim}) with existing log (ID: {top_point.id})")
                    # Only insert into lookup DB
                    self.lookup_db_store.insert_into_lookup_db(
                        log_id=hashval,
                        closest_log_id=str(top_point.id),
                        similarity=sim,
                        timestamp=entry.get('metadata', {}).get('timestamp', ''),
                        location=entry.get('metadata', {}).get('pod_name', '')
                    )
                else:
                    logger.info(f"Inserting new log (ID: {hashval}) into vector store and lookup DB")
                    # Insert into vector store and lookup DB ( Considered new log)
                    self.lookup_db_store.insert_into_lookup_db(
                        log_id=hashval,
                        closest_log_id=hashval,
                        similarity=1.0,
                        timestamp=entry.get('metadata', {}).get('timestamp', ''),
                        location=entry.get('metadata', {}).get('pod_name', '')
                    )
                    vector_store_inserts.append(entry)

            else:
                logger.info(f"No existing points found. Inserting new log (ID: {hashval}) into vector store and lookup DB")
                self.lookup_db_store.insert_into_lookup_db(
                    log_id=hashval,
                    closest_log_id=hashval,
                    similarity=1.0,
                    timestamp=entry.get('metadata', {}).get('timestamp', ''),
                    location=entry.get('metadata', {}).get('pod_name', '')
                )
                vector_store_inserts.append(entry)

        if vector_store_inserts:
            self.vector_store.inserts(vector_store_inserts)

    def search(self, query: str, filter_: Optional[List[Dict]] = None, top_k: int = 5):
        qdrant_filter = adapter_specs_to_filters(filter_) if filter_ else None
        results = self.vector_store.search(
            query=query,
            filter_=qdrant_filter,
            top_k=top_k
        )
        return results
    
    def scroll(self, filter_: Optional[List[Dict]] = None, batch_size: int = 10):
        qdrant_filter = adapter_specs_to_filters(filter_) if filter_ else None
        results = self.vector_store.scroll(
            filters=qdrant_filter,
            batch_size=batch_size
        )
        return results
    
    def find_near_occurrences(self, log_id):
        return self.lookup_db_store.find_near_occurrences(log_id)

    def clear(self):
        self.vector_store.delete_collection_if_exists()
        self.lookup_db_store.clear_lookup_db()
        logger.info("Cleared vector store and lookup DB.")

    def reset(self):
        self.clear()
        self.vector_store.create_collection_if_not_exists(
                vector_size=self.vector_store.embedder.vector_size,
                distance=self.vector_store.embedder.distance
        )
        self.lookup_db_store._warmup_lookup_db()
        logger.info("Reset vector store and lookup DB.")

    def sync_similarty(self):
        ##### IN-PROGRESS #####
        # Fetch all entries from vector store where sim_sync is False
        filter = adapter_specs_to_filters([
            {"key": "sim_sync", "dtype": "boolean", "op": "equals", "value": False}
        ], mode="and")

        unsync_points = self.vector_store.scroll(
            filters=filter,
            batch_size=self.sim_sync_batch_size
        )[0]


        texts = [p.payload.get("textPayload", "") for p in unsync_points]
        search_results = self.vector_store.search_batch(
            queries=texts,
            filters=[filter]*len(texts),
            top_k=2
        ) # 2 to skip self-match

        logger.info(f"Processing batch of {len(unsync_points)} vs {len(search_results)}")

        edges_to_update = []
        for point, result in zip(unsync_points, search_results):
            if result.points and len(result.points) > 0:
                top_point = result.points[1] # 1 to skip self-match
                sim = top_point.score
                logger.info(f"Log ID: {point.id} <=> Top match ID: {top_point.id} with similarity: {sim}")
                edges_to_update.append([point.id, str(top_point.id), sim])

        return edges_to_update