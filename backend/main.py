from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import os
import json
from dotenv import load_dotenv
from pypdf import PdfReader
import io
from gemini_client import generate_exam_streaming

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

@app.post("/generate-exam")
async def create_exam(
    file: UploadFile = File(None),
    num_questions: int = Form(10),
    topic: str = Form(None),
    difficulty: str = Form("Intermedio"),
    context: str = Form(None),
    directory_path: str = Form(None),
    mode: str = Form("manual")
):
    context_text = context
    selected_topics = []

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
            import random
            
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

    print(f"Generating -> Questions: {num_questions} | Difficulty: {difficulty} | Topic: {topic or 'Default'} | Mode: {mode}")

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

        async for item in generate_exam_streaming(num_questions, context_text, topic, difficulty, mode=mode):
            if isinstance(item, dict) and item.get("type") == "log":
                yield f"data: {json.dumps(item)}\n\n"
            elif isinstance(item, list):
                yield f"data: {json.dumps(item)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Prevents Nginx/proxy buffering
        }
    )
