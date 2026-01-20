from typing import List, Any, Iterable
from .minhash import LSHMinHashEmbedder

from .logger import get_colorlogger
logger = get_colorlogger(__name__)

class BaseEmbedder:
    def __init__(self, vector_size: int, distance: str = "cosine"):
        self.vector_size = vector_size
        if distance not in {"cosine", "euclidean", "dot"}:
            logger.error(f"Unsupported distance metric: {distance}")
            raise ValueError(f"Unsupported distance metric: {distance}")
        self.distance = distance
    def embed(self, text:str) -> List[Any]:
        raise NotImplementedError
    def embeds(self, texts:List[str]) -> List[List[Any]]:
        raise NotImplementedError
    def compare(self, a:List[Any], b:List[Any]) -> float:
        raise NotImplementedError
    



class LshEmbedder(BaseEmbedder):
    def __init__(self, 
                 shingle_size: int,
                 num_hashes: int,
                 bands: int,
                 seed: int,
                 normalize: bool,
                 lowercase: bool,
                 collapse_whitespace: bool,
                 stop_short_lines: int
    ):
        """
        Docstring for __init__
        
        Common choices:
        - shingle_size: 5
        - num_hashes: 128 , 256
        - bands: 32 (for 128 hashes), 64 (for 256 hashes )
        - seed: any integer
        - normalize: True
        - lowercase: True
        - collapse_whitespace: True
        - stop_short_lines: 0
        """
        self.lsh = LSHMinHashEmbedder(
            shingle_size=shingle_size,
            num_hashes=num_hashes,
            bands=bands,
            seed=seed,
            normalize=normalize,
            lowercase=lowercase,
            collapse_whitespace=collapse_whitespace,
            stop_short_lines=stop_short_lines
        )
        super().__init__(vector_size=num_hashes, distance="cosine")
        logger.info(f"LSH Embedder initialized with vector_size={self.vector_size}, distance={self.distance}")

    def embed(self, text: str) -> List[int]:
        try:
            lsh_emb = self.lsh.embed(text)
            result = lsh_emb.signature
            # logger.info("Text embedded successfully.")
            return result
        except Exception as e:
            logger.error(f"Error embedding text: {e}")
            raise

    def embeds(self, texts: List[str]) -> Iterable[List[int]]:
        try:
            for text in texts:
                yield self.embed(text)
            logger.info(f"Embedded {len(texts)} texts successfully.")
        except Exception as e:
            logger.error(f"Error embedding texts: {e}")
            raise

    def compare(self, a: List[int], b: List[int]) -> float:
        def jaccard(sig_a: List[int], sig_b: List[int]) -> float:
            if len(sig_a) != len(sig_b):
                logger.error("Signatures must be of the same length for comparison.")
                raise ValueError("Signatures must be of the same length for comparison.")
            matches = sum(1 for x, y in zip(sig_a, sig_b) if x == y)
            return matches / len(sig_a)
        
        def cosine(sig_a: List[int], sig_b: List[int]) -> float:
            # vec_a = [1 if x != (1 << 32) - 1 else 0 for x in sig_a]
            # vec_b = [1 if x != (1 << 32) - 1 else 0 for x in sig_b]
            # dot_product = sum(x * y for x, y in zip(vec_a, vec_b))
            # norm_a = sum(x * x for x in vec_a) ** 0.5
            # norm_b = sum(y * y for y in vec_b) ** 0.5
            # if norm_a == 0 or norm_b == 0:
            #     return 0.0
            # return dot_product / (norm_a * norm_b)
            
            # Regular cosine on integer vectors
            dot_product = sum(x * y for x, y in zip(sig_a, sig_b))
            norm_a = sum(x * x for x in sig_a) ** 0.5
            norm_b = sum(y * y for y in sig_b) ** 0.5
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot_product / (norm_a * norm_b)
    
        try:
            result = jaccard(a, b)
            logger.info("Signatures compared successfully.")
            return result
        except Exception as e:
            logger.error(f"Error comparing signatures: {e}")
            raise