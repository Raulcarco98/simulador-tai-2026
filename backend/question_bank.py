"""
Question Bank — Local cache for AI-generated questions.
Saves questions linked to source files using Turso (libSQL) or local SQLite for efficiency.
Includes semantic embeddings for intelligent deduplication.
"""

import os
import json
import hashlib
from datetime import datetime
import numpy as np
import libsql_client
from libsql_client import Statement

# Local bank database location fallback
LOCAL_DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "question_bank.db")

# Semantic similarity threshold (0.85 = 85% meaning overlap)
SIMILARITY_THRESHOLD = 0.85

def _get_client() -> libsql_client.Client:
    """Get a connection to the libSQL database (Turso or local)."""
    db_url = os.environ.get("TURSO_DATABASE_URL")
    auth_token = os.environ.get("TURSO_AUTH_TOKEN")
    
    if db_url and auth_token:
        # Sanitize URL: use https:// instead of libsql:// for maximum compatibility (prevents WebSocket 505 errors)
        if db_url.startswith("libsql://"):
            db_url = db_url.replace("libsql://", "https://")
        client = libsql_client.create_client_sync(db_url, auth_token=auth_token)
    else:
        # Fallback to local SQLite file
        client = libsql_client.create_client_sync(f"file:{LOCAL_DB_FILE}")

    # Ensure tables exist
    client.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_hash TEXT NOT NULL,
            filename TEXT NOT NULL,
            text_hash TEXT NOT NULL,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            correct_index INTEGER NOT NULL,
            explanation TEXT NOT NULL,
            embedding BLOB,
            saved_at TEXT NOT NULL
        )
    ''')
    client.execute('CREATE INDEX IF NOT EXISTS idx_file_hash ON questions(file_hash)')
    client.execute('CREATE INDEX IF NOT EXISTS idx_text_hash ON questions(text_hash)')
    
    return client


def _row_to_dict(row, keys) -> dict:
    """Helper to safely convert a libSQL row to dictionary."""
    return {k: row[k] for k in keys}


def _get_file_key(filename: str) -> str:
    """Generate a stable key from a filename (basename, lowercase, MD5)."""
    normalized = os.path.basename(filename).strip().lower()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def _question_hash(question_text: str) -> str:
    """Hash a question's text for fast exact-match dedup (fallback)."""
    return hashlib.md5(question_text.strip().lower().encode("utf-8")).hexdigest()


def get_questions_for_file(filename: str) -> list:
    """Get all saved questions for a given filename."""
    client = _get_client()
    try:
        file_hash = _get_file_key(filename)
        rs = client.execute("SELECT * FROM questions WHERE file_hash = ?", [file_hash])
        
        results = []
        if rs.rows:
            keys = rs.columns
            for row in rs.rows:
                q = _row_to_dict(row, keys)
                q['options'] = json.loads(q['options'])
                # Reconstruct embedding from BLOB
                if q['embedding']:
                    q['embedding'] = np.frombuffer(q['embedding'], dtype=np.float32).tolist()
                results.append(q)
        return results
    finally:
        client.close()


def get_file_info(filename: str) -> dict:
    """Check if a file has cached questions. Returns count and metadata."""
    client = _get_client()
    try:
        file_hash = _get_file_key(filename)
        rs = client.execute("SELECT COUNT(*) as cnt FROM questions WHERE file_hash = ?", [file_hash])
        count = int(rs.rows[0]["cnt"]) if rs.rows else 0
        
        return {
            "has_cache": count > 0,
            "available_count": count,
            "filename": os.path.basename(filename)
        }
    finally:
        client.close()


def save_questions_for_file(filename: str, questions: list) -> dict:
    """
    Add questions to the bank for a file.
    Uses semantic deduplication: compares meaning, not just exact text.
    Returns stats about what was saved.
    """
    client = _get_client()
    try:
        file_hash = _get_file_key(filename)
        basename = os.path.basename(filename)
        
        # 1. Get existing questions for dedup
        existing_questions = get_questions_for_file(filename)
        existing_hashes = {q['text_hash'] for q in existing_questions}
        
        # Filter out exact duplicates first
        candidates = []
        exact_dupes = 0
        for q in questions:
            h = _question_hash(q.get("question", ""))
            if h in existing_hashes:
                exact_dupes += 1
            else:
                q['temp_hash'] = h
                candidates.append(q)
                
        if not candidates:
            return {
                "saved_count": 0,
                "duplicates_skipped": exact_dupes,
                "semantic_duplicates": [],
                "total_for_file": len(existing_questions)
            }

        semantic_duplicates = []
        saved_count = 0
        statements = []
        
        try:
            from semantic_engine import get_embedding, find_best_match
            
            for q in candidates:
                q_text = q.get("question", "")
                h = q.pop('temp_hash')
                new_emb = get_embedding(q_text)
                
                # Check semantic similarity
                match = find_best_match(new_emb, existing_questions, threshold=SIMILARITY_THRESHOLD)
                
                if match:
                    semantic_duplicates.append({
                        "new_question": q_text,
                        "existing_question": match["question"],
                        "similarity": match["similarity"]
                    })
                else:
                    # Save to DB
                    emb_blob = np.array(new_emb, dtype=np.float32).tobytes()
                    saved_at = datetime.now().isoformat()
                    options_json = json.dumps(q.get("options", []))
                    
                    statements.append(Statement('''
                        INSERT INTO questions (
                            file_hash, filename, text_hash, question, 
                            options, correct_index, explanation, embedding, saved_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', [
                        file_hash, basename, h, q_text, 
                        options_json, q.get("correct_index", 0), q.get("explanation", ""),
                        emb_blob, saved_at
                    ]))
                    
                    saved_count += 1
                    
                    # Add to existing_questions so subsequent candidates check against this new one
                    q_copy = dict(q)
                    q_copy["embedding"] = new_emb
                    existing_questions.append(q_copy)
                    
            if statements:
                client.batch(statements)
                
        except ImportError as e:
            print(f"[BANCO] Semantic engine no disponible ({e}). Usando solo hash dedup.")
            statements = []
            for q in candidates:
                h = q.pop('temp_hash')
                saved_at = datetime.now().isoformat()
                options_json = json.dumps(q.get("options", []))
                
                statements.append(Statement('''
                    INSERT INTO questions (
                        file_hash, filename, text_hash, question, 
                        options, correct_index, explanation, embedding, saved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', [
                    file_hash, basename, h, q.get("question", ""), 
                    options_json, q.get("correct_index", 0), q.get("explanation", ""),
                    None, saved_at
                ]))
                saved_count += 1
            if statements:
                client.batch(statements)

        rs = client.execute("SELECT COUNT(*) as cnt FROM questions WHERE file_hash = ?", [file_hash])
        total_for_file = int(rs.rows[0]["cnt"]) if rs.rows else 0
        
        return {
            "saved_count": saved_count,
            "duplicates_skipped": exact_dupes + len(semantic_duplicates),
            "semantic_duplicates": semantic_duplicates,
            "total_for_file": total_for_file
        }
    finally:
        client.close()


def get_bank_stats() -> dict:
    """Get overall bank statistics."""
    client = _get_client()
    try:
        rs = client.execute("SELECT filename, COUNT(*) as count FROM questions GROUP BY file_hash")
        
        files = []
        total_questions = 0
        if rs.rows:
            for row in rs.rows:
                files.append({
                    "filename": row['filename'],
                    "count": int(row['count'])
                })
                total_questions += int(row['count'])
            
        return {
            "total_files": len(files),
            "total_questions": total_questions,
            "files": files
        }
    finally:
        client.close()


def tag_duplicates(questions: list, filename: str) -> list:
    """
    Check newly generated questions against the bank.
    Tags them with `is_already_in_bank` flag so frontend can disable saving.
    """
    if not filename:
        return questions
        
    existing = get_questions_for_file(filename)
    if not existing:
        for q in questions:
            q['is_already_in_bank'] = False
        return questions
        
    try:
        from semantic_engine import get_embedding, find_best_match
        
        for q in questions:
            q_text = q.get("question", "")
            # Fast check first
            h = _question_hash(q_text)
            if any(ex['text_hash'] == h for ex in existing):
                q['is_already_in_bank'] = True
                continue
                
            # Semantic check
            new_emb = get_embedding(q_text)
            match = find_best_match(new_emb, existing, threshold=SIMILARITY_THRESHOLD)
            q['is_already_in_bank'] = bool(match)
            
    except ImportError:
        # If semantic engine fails, fall back to simple hash check
        for q in questions:
            h = _question_hash(q.get("question", ""))
            q['is_already_in_bank'] = any(ex['text_hash'] == h for ex in existing)
            
    return questions
