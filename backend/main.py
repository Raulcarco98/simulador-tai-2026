from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
from pypdf import PdfReader
import io
from gemini_client import generate_exam

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    difficulty: str = Form("Intermedio")
):
    context_text = None
    
    if file:
        content = await file.read()
        if file.filename.endswith(".pdf"):
            context_text = extract_text_from_pdf(content)
        elif file.filename.endswith(".txt") or file.filename.endswith(".md"):
            context_text = content.decode("utf-8")
        
        if context_text and len(context_text) < 50:
             print("Warning: Extracted text is too short or empty.")
    
    print(f"Generating -> Questions: {num_questions} | Difficulty: {difficulty} | Topic: {topic or 'Default'}")
    
    questions = await generate_exam(num_questions, context_text, topic, difficulty)
    return questions
