from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import os
import json
import random
from dotenv import load_dotenv
from pypdf import PdfReader
import io
from pydantic import BaseModel
from typing import List, Optional

# We import all generator methods
from gemini_client import generate_exam_streaming as generate_exam_gemini
from ollama_client import generate_exam_streaming as generate_exam_ollama
from groq_client import generate_exam_streaming as generate_exam_groq
from lmstudio_client import generate_exam_streaming as generate_exam_lmstudio
from openrouter_client import generate_exam_streaming as generate_exam_openrouter
from question_bank import get_file_info, get_questions_for_file, save_questions_for_file, get_bank_stats

load_dotenv()

app = FastAPI()

# CORS: Restrict to known origins in production
ALLOWED_ORIGINS = ["*"] # Allow all origins for mobile access

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def extract_text_from_pdf(file_bytes):
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        print(f"Error reading PDF: {e}")
        return ""

@app.get("/")
def read_root():
    return {"message": "Simulador TAI 2026 API is running"}

# === QUESTION BANK ENDPOINTS ===

class CheckBankRequest(BaseModel):
    filename: str

class SaveToBankRequest(BaseModel):
    filename: str
    questions: List[dict]

@app.post("/check-bank")
async def check_bank(req: CheckBankRequest):
    """Check if there are cached questions for a given filename."""
    info = await get_file_info(req.filename)
    print(f"[BANCO] Check: {req.filename} -> {info['available_count']} preguntas")
    return info

@app.post("/save-to-bank")
async def save_to_bank(req: SaveToBankRequest):
    """Save selected questions to the bank for a given filename."""
    result = await save_questions_for_file(req.filename, req.questions)
    print(f"[BANCO] Guardadas {result['saved_count']} preguntas para {req.filename} (total: {result['total_for_file']})")
    return result

@app.get("/bank-stats")
async def bank_stats():
    """Get overall question bank statistics."""
    return await get_bank_stats()

@app.post("/generate-exam")
async def create_exam(
    file: UploadFile = File(None),
    num_questions: int = Form(10),
    topic: str = Form(None),
    difficulty: str = Form("Intermedio"),
    context: str = Form(None),
    directory_path: str = Form(None),
    mode: str = Form("manual"),
    ai_engine: str = Form("gemini"),
    ollama_model: str = Form("deepseek-v3.2:cloud"),
    local_model: str = Form("ollama"),
    use_bank: str = Form("false"),
    source_filename: str = Form(None)
):
    context_text = context
    selected_topics = []

    # Ensure source_filename is available for duplicate tagging
    if not source_filename and file and file.filename:
        source_filename = file.filename

    # === QUESTION BANK: Serve from cache if requested ===
    if use_bank.lower() == "true" and source_filename:
        bank_questions = get_questions_for_file(source_filename)
        if bank_questions:
            # Select random subset if more than requested
            if len(bank_questions) > num_questions:
                selected = random.sample(bank_questions, num_questions)
            else:
                selected = list(bank_questions)
            
            # Assign sequential IDs
            for i, q in enumerate(selected):
                q["id"] = i + 1
            
            print(f"[BANCO] Sirviendo {len(selected)} de {len(bank_questions)} preguntas para {source_filename}")
            
            async def bank_stream():
                yield f"data: {json.dumps({'type': 'log', 'msg': f'💾 [BANCO] Cargando {len(selected)} preguntas de {len(bank_questions)} disponibles para {source_filename}...'})}\n\n"
                yield f"data: {json.dumps({'type': 'log', 'msg': '⚡ [BANCO] Sin llamada a IA. Carga instantánea.'})}\n\n"
                yield f"data: {json.dumps({'type': 'from_bank', 'value': True})}\n\n"
                yield f"data: {json.dumps(selected)}\n\n"
                yield "data: [DONE]\n\n"
            
            return StreamingResponse(
                bank_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
            )

    # Helper function for reading fragments
    def get_file_fragment(filepath, chunk_size=3000):
        try:
            if filepath.endswith(".pdf"):
                with open(filepath, "rb") as f:
                    text = extract_text_from_pdf(f.read())
            else:
                with open(filepath, "r", encoding="utf-8") as f:
                    text = f.read()
            
            # Simple truncation for now, can be improved to random slice
            return text[:chunk_size]
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            return ""

    # 1. Handle File Upload (Manual)
    if mode == "manual" and file:
        content = await file.read()
        if file.filename.endswith(".pdf"):
            context_text = extract_text_from_pdf(content)
        elif file.filename.endswith(".txt") or file.filename.endswith(".md"):
            context_text = content.decode("utf-8")
        
        if context_text and len(context_text) < 50:
             print("Warning: Extracted text is too short or empty.")

    # 2. Handle Directory Modes (Roulette & Simulacro)
    elif directory_path and (mode == "random_1" or mode == "simulacro_3" or mode == "random"): # 'random' for legacy compatibility
        try:
            import glob
            
            files = glob.glob(os.path.join(directory_path, "*.md")) + \
                    glob.glob(os.path.join(directory_path, "*.txt")) + \
                    glob.glob(os.path.join(directory_path, "*.pdf"))
            
            if not files:
                print(f"[RULETA] No se encontraron archivos compatibles en: {directory_path}")
            else:
                if mode == "simulacro_3":
                    # --- REAL SIMULATOR MODE ---
                    # Select up to 3 unique files
                    k = min(3, len(files))
                    selected_files = random.sample(files, k)
                    
                    context_parts = []
                    for fpath in selected_files:
                        fname = os.path.basename(fpath)
                        selected_topics.append(fname)
                        fragment = get_file_fragment(fpath)
                        context_parts.append(f"### TEMA: {fname} ###\n{fragment}\n")
                    
                    context_text = "\n".join(context_parts)
                    print(f"[SIMULACRO] Temas elegidos: {', '.join(selected_topics)}")
                    
                else: 
                    # --- SINGLE TOPIC ROULETTE ---
                    selected_file = random.choice(files)
                    fname = os.path.basename(selected_file)
                    selected_topics.append(fname)
                    print(f"[RULETA] Tema seleccionado al azar: {fname}")
                    
                    # Read full content for single mode
                    if selected_file.endswith(".pdf"):
                        with open(selected_file, "rb") as f:
                            context_text = extract_text_from_pdf(f.read())
                    else:
                        with open(selected_file, "r", encoding="utf-8") as f:
                            context_text = f.read()

        except Exception as e:
            print(f"[RULETA] Error al leer directorio: {e}")

    print(f"Generating -> Questions: {num_questions} | Difficulty: {difficulty} | Topic: {topic or 'Default'} | Mode: {mode} | Engine: {ai_engine} ({ollama_model if ai_engine == 'ollama' else 'N/A'})")

    async def event_stream():
        """SSE stream: yields logs and question batches."""
        
        # Log selected topics to Frontend
        if selected_topics:
             if mode == "simulacro_3":
                 msg = f"🎲 [SIMULACRO] Temas: {', '.join(selected_topics)}"
             else:
                 msg = f"🎲 [RULETA] Tema: {selected_topics[0]}"
                 
             yield f"data: {json.dumps({'type': 'log', 'msg': msg})}\n\n"
             
             # Yield context for persistence (optional, maybe heavy for 3 topics but useful)
             if context_text:
                 yield f"data: {json.dumps({'type': 'context', 'content': context_text})}\n\n"

        # Yield context first if it was extracted from a file
        if (mode == "manual") and file and context_text:
             yield f"data: {json.dumps({'type': 'context', 'content': context_text})}\n\n"

        # Dynamically choose generator based on engine
        if ai_engine == "ollama" or ai_engine == "local":
            if local_model == "lmstudio":
                generator_source = generate_exam_lmstudio(num_questions, context_text, topic, difficulty, mode=mode)
            else:
                generator_source = generate_exam_ollama(num_questions, context_text, topic, difficulty, mode=mode, model_name=ollama_model)
        elif ai_engine == "groq":
            generator_source = generate_exam_groq(num_questions, context_text, topic, difficulty, mode=mode)
        elif ai_engine == "openrouter":
            generator_source = generate_exam_openrouter(num_questions, context_text, topic, difficulty, mode=mode)
        else:
            generator_source = generate_exam_gemini(num_questions, context_text, topic, difficulty, mode=mode)

        from question_bank import tag_duplicates

        async for item in generator_source:
            if isinstance(item, dict) and item.get("type") == "log":
                yield f"data: {json.dumps(item)}\n\n"
            elif isinstance(item, list):
                # Check bank and tag duplicates before sending to frontend
                tagged_questions = await tag_duplicates(item, source_filename)
                yield f"data: {json.dumps(tagged_questions)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Prevents Nginx/proxy buffering
        }
    )
