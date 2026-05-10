"""
Semantic Engine — Local embedding model for intelligent question deduplication.
Uses paraphrase-multilingual-MiniLM-L12-v2 (supports Spanish natively).
Lazy-loaded: model only downloads/loads on first use, not at server start.
"""

import numpy as np

# Singleton — model loaded once on first call
_model = None

def _get_model():
    """
    Lazy load the sentence-transformers model.
    First call: downloads (~470 MB) if not cached, then loads into RAM (~1 GB). Takes ~3-5s.
    Subsequent calls: returns cached instance instantly.
    """
    global _model
    if _model is None:
        print("[SEMANTIC] Cargando modelo de embeddings (primera vez puede tardar)...")
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        print("[SEMANTIC] Modelo cargado correctamente.")
    return _model


def get_embedding(text: str) -> list:
    """Generate normalized embedding vector for a single text."""
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def get_embeddings_batch(texts: list) -> list:
    """Generate normalized embeddings for multiple texts in one batch (more efficient)."""
    if not texts:
        return []
    model = _get_model()
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=32)
    return vecs.tolist()


def cosine_similarity(vec_a: list, vec_b: list) -> float:
    """
    Compute cosine similarity between two vectors.
    With normalized vectors, this is just the dot product.
    """
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    return float(np.dot(a, b))


def find_best_match(new_embedding: list, existing_embeddings: list, threshold: float = 0.85) -> dict | None:
    """
    Compare a new embedding against a list of existing embeddings.
    Returns the best match above threshold, or None if no match found.
    
    Args:
        new_embedding: Vector of the new question
        existing_embeddings: List of dicts with 'embedding' and 'question' keys
        threshold: Minimum cosine similarity to consider a duplicate (default 0.85)
    
    Returns:
        dict with 'question', 'similarity' of the best match, or None
    """
    if not existing_embeddings:
        return None
    
    new_vec = np.array(new_embedding, dtype=np.float32)
    best_match = None
    best_sim = 0.0
    
    for entry in existing_embeddings:
        emb = entry.get("embedding")
        if emb is None:
            continue
        existing_vec = np.array(emb, dtype=np.float32)
        sim = float(np.dot(new_vec, existing_vec))
        
        if sim > best_sim:
            best_sim = sim
            best_match = entry
    
    if best_sim >= threshold and best_match is not None:
        return {
            "question": best_match.get("question", ""),
            "similarity": round(best_sim, 4)
        }
    
    return None
