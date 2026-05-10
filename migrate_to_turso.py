"""
Migration Script — Copies all local SQLite questions to the remote Turso database.
"""
import os
import sqlite3
import libsql_client
from libsql_client import Statement
from dotenv import load_dotenv

# 1. Load env from root
root_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(root_dir, ".env")
load_dotenv(dotenv_path=env_path)

db_url = os.environ.get("TURSO_DATABASE_URL")
auth_token = os.environ.get("TURSO_AUTH_TOKEN")

if not db_url or not auth_token:
    print("[ERROR] No se encontraron TURSO_DATABASE_URL o TURSO_AUTH_TOKEN en el archivo .env.")
    exit(1)

local_db_path = os.path.join(root_dir, "backend", "question_bank.db")
if not os.path.exists(local_db_path):
    print(f"[ERROR] No se encontro la base de datos local en: {local_db_path}")
    exit(1)

print("[INFO] Conectando a bases de datos...")
print(f"  Local: {local_db_path}")
print(f"  Turso: {db_url}")

# Connect local SQLite
local_conn = sqlite3.connect(local_db_path)
local_conn.row_factory = sqlite3.Row
local_cursor = local_conn.cursor()

try:
    # Read local questions
    local_cursor.execute("SELECT * FROM questions")
    rows = local_cursor.fetchall()
    
    if not rows:
        print("[WARNING] No hay preguntas guardadas en la base de datos local para migrar.")
        exit(0)
        
    print(f"[INFO] Se encontraron {len(rows)} preguntas para migrar.")
    
    # Sanitize URL: use https:// instead of libsql:// for maximum compatibility
    if db_url.startswith("libsql://"):
        db_url = db_url.replace("libsql://", "https://")
    
    # Connect remote Turso
    remote_client = libsql_client.create_client_sync(db_url, auth_token=auth_token)
    
    # Ensure tables exist on remote
    remote_client.execute('''
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
    remote_client.execute('CREATE INDEX IF NOT EXISTS idx_file_hash ON questions(file_hash)')
    remote_client.execute('CREATE INDEX IF NOT EXISTS idx_text_hash ON questions(text_hash)')
    
    # Get existing hashes on remote to avoid double-inserting
    print("[INFO] Comprobando si hay preguntas ya guardadas en Turso para evitar duplicados...")
    rs_existing = remote_client.execute("SELECT text_hash FROM questions")
    existing_hashes = {r["text_hash"] for r in rs_existing.rows} if rs_existing.rows else set()
    
    print(f"  ({len(existing_hashes)} hashes encontrados en Turso)")
    
    # Migrate rows
    migrated_count = 0
    skipped_count = 0
    statements = []
    
    for r in rows:
        text_hash = r["text_hash"]
        if text_hash in existing_hashes:
            skipped_count += 1
            continue
            
        # Add statement
        statements.append(Statement('''
            INSERT INTO questions (
                file_hash, filename, text_hash, question, 
                options, correct_index, explanation, embedding, saved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', [
            r["file_hash"],
            r["filename"],
            text_hash,
            r["question"],
            r["options"],
            r["correct_index"],
            r["explanation"],
            r["embedding"],
            r["saved_at"]
        ]))
        migrated_count += 1
        
    if statements:
        print(f"[INFO] Subiendo {len(statements)} preguntas a Turso en lotes...")
        remote_client.batch(statements)
            
    print("[SUCCESS] ¡Migracion completada con exito!")
    print(f"  🚀 Preguntas subidas a Turso: {migrated_count}")
    print(f"  ⏭️ Duplicadas omitidas: {skipped_count}")
    
    remote_client.close()
    
except Exception as e:
    print(f"[ERROR] Ocurrio un error durante la migracion: {e}")
finally:
    local_conn.close()
