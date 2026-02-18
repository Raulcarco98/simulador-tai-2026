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
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")

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
    directory_path: str = Form(None)
):
    context_text = context
    
    # 1. Handle File Upload
    if file:
        content = await file.read()
        if file.filename.endswith(".pdf"):
            context_text = extract_text_from_pdf(content)
        elif file.filename.endswith(".txt") or file.filename.endswith(".md"):
            context_text = content.decode("utf-8")
        
        if context_text and len(context_text) < 50:
             print("Warning: Extracted text is too short or empty.")

    # 2. Handle Roulette Mode (Directory)
    elif directory_path:
        try:
            # Find all compatible files
            import glob
            import random
            
            # Search for md and txt files
            files = glob.glob(os.path.join(directory_path, "*.md")) + \
                    glob.glob(os.path.join(directory_path, "*.txt")) + \
                    glob.glob(os.path.join(directory_path, "*.pdf"))
            
            if not files:
                print(f"[RULETA] No se encontraron archivos compatibles en: {directory_path}")
                # Fallback or error? For now, let it fail gracefully in generation or prompt
            else:
                selected_file = random.choice(files)
                print(f"[RULETA] Tema seleccionado al azar: {os.path.basename(selected_file)}")
                
                # Yield log about selection
                # We can't yield here directly, but we can print it and maybe send a log event first in the stream
                
                # Check file type
                if selected_file.endswith(".pdf"):
                    with open(selected_file, "rb") as f:
                        context_text = extract_text_from_pdf(f.read())
                else:
                    with open(selected_file, "r", encoding="utf-8") as f:
                        context_text = f.read()

                # LOGGING: We will send this as a log event in the stream
                
        except Exception as e:
            print(f"[RULETA] Error al leer directorio: {e}")

    print(f"Generating -> Questions: {num_questions} | Difficulty: {difficulty} | Topic: {topic or 'Default'}")

    async def event_stream():
        """SSE stream: yields logs and question batches."""
        
        # [RULETA] Log the selected file to Frontend
        if directory_path and 'selected_file' in locals():
             filename = os.path.basename(selected_file)
             yield f"data: {json.dumps({'type': 'log', 'msg': f'🎲 [RULETA] Tema seleccionado: {filename}'})}\n\n"
             # Also yield context so it can be saved for "Generate another like this" (optional, but good for UX)
             if context_text:
                 yield f"data: {json.dumps({'type': 'context', 'content': context_text})}\n\n"

        # Yield context first if it was extracted from a file
        if file and context_text:
             yield f"data: {json.dumps({'type': 'context', 'content': context_text})}\n\n"

        async for item in generate_exam_streaming(num_questions, context_text, topic, difficulty):
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
