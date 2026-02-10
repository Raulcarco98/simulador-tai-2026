import os
import google.generativeai as genai
import json
import asyncio
import re
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

if API_KEY:
    genai.configure(api_key=API_KEY)

# Configuration for JSON response
generation_config = {
    "temperature": 0.8,
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 4096,
    "response_mime_type": "application/json",
}

# Create model
model = None
if API_KEY:
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        generation_config=generation_config,
    )


# === UTILIDADES ===
def _clean_text(text):
    """Colapsa saltos de línea y espacios múltiples."""
    if not text:
        return ""
    text = re.sub(r'\n+', '\n', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def validate_and_fix_question(question):
    """
    Checks if the explanation states the correct answer letter via multiple patterns
    and safeguards that 'correct_index' matches it.
    """
    try:
        explanation = question.get("explanation", "")
        detected_letter = None
        
        # Pattern 1: "respuesta correcta es [la] X"
        match = re.search(r"respuesta\s+correcta\s+(?:es|sea)\s+(?:la\s+)?([A-D])\b", explanation, re.IGNORECASE)
        if match:
            detected_letter = match.group(1).upper()
        
        # Pattern 2: "Correcta: X" or "Correcta: [X]"
        if not detected_letter:
            match2 = re.search(r"[Cc]orrecta:\s*\[?([A-D])\]?", explanation)
            if match2:
                detected_letter = match2.group(1).upper()
        
        # Pattern 3: "Es la X" at start
        if not detected_letter:
            match3 = re.search(r"^\s*[Ee]s\s+la\s+([A-D])\b", explanation)
            if match3:
                detected_letter = match3.group(1).upper()
        
        if detected_letter:
            expected_index = ord(detected_letter) - ord('A')
            if 0 <= expected_index <= 3:
                current_index = question.get("correct_index")
                if current_index != expected_index:
                    print(f"FIX APPLIED for Q{question.get('id')}: Index {current_index} mismatch with explanation '{detected_letter}'. Updating to {expected_index}.")
                    question["correct_index"] = expected_index
    except Exception as e:
        print(f"Validation Error: {e}")
    
    return question


def get_base_prompt(num_questions, difficulty):
    if difficulty.upper() == "EXPERTO":
        return f"""
    Actúa como examinador TAI C1. Genera {num_questions} preguntas avanzadas.
    REQUISITOS:
    - Temas: Casos prácticos, sintaxis y excepciones.
    - Estructura: 25% preguntas negativas (¿Cuál es FALSA?).
    - Distractores: Cambia cifras (10→15 días), confunde leyes (39↔40), usa siglas parecidas (ENS↔ENI).
    - Cobertura: Distribuye preguntas por TODO el contexto, no solo el inicio.
    - Concisión: Explicación de 1 línea (máx 15 palabras).
    - Formato: Responde ÚNICAMENTE el array JSON, sin texto previo ni posterior.

    PROCESO INTERNO (para cada pregunta):
    PASO 1: Determina la respuesta correcta y redacta la explicación breve.
    PASO 2: Basándote ÚNICAMENTE en el Paso 1, asigna correct_index (0=A, 1=B, 2=C, 3=D).

    REGLA DE ORO: Si en la explicación mencionas una letra (ej: "Es la B"), correct_index DEBE ser obligatoriamente el índice de esa letra.
    En preguntas negativas, correct_index = índice de la opción FALSA.

    JSON SCHEMA:
    [
        {{
            "id": 1,
            "question": "Texto",
            "options": ["A", "B", "C", "D"],
            "correct_index": 0,
            "explanation": "Ref: [Concepto/Art]. Motivo: [Breve]"
        }}
    ]
    """
    
    return f"""
    Actúa como un Preparador de Oposiciones. Genera un examen tipo test de {num_questions} preguntas.
    
    NIVEL: {difficulty.upper()} (Básico/Intermedio)
    ESTILO: Preguntas claras. Explicación didáctica.
    REALISMO: Usa "Todas/Ninguna es correcta" en 20% de preguntas.
    
    CRITÉRIO JSON:
    - "explanation" empieza con "La respuesta correcta es [Letra]...".
    
    PROCESO INTERNO (para cada pregunta):
    PASO 1: Determina la respuesta correcta y redacta la explicación comenzando con "La respuesta correcta es [Letra] porque...".
    PASO 2: Basándote ÚNICAMENTE en el Paso 1, asigna correct_index (0=A, 1=B, 2=C, 3=D).

    REGLA DE ORO: Si en la explicación escribes "La respuesta correcta es B", correct_index DEBE ser 1. Siempre.
    En preguntas negativas, correct_index = índice de la opción FALSA.
    
    Formato JSON:
    [
        {{
            "id": 1,
            "question": "Enunciado...",
            "options": ["A", "B", "C", "D"],
            "correct_index": 0,
            "explanation": "La respuesta correcta es A porque..."
        }}
    ]
    """


# === CORE API CALL (with pure Exponential Backoff) ===
async def _generate_chunk(chunk_prompt, context_text, context_limit):
    """Single API call with exponential backoff on 429. No key rotation."""
    if not API_KEY or not model:
        return []
    
    max_retries = 5
    base_delay = 15

    # Build prompt once
    final_prompt = chunk_prompt
    if context_text:
        cleaned = _clean_text(context_text[:context_limit])
        final_prompt += f"\n\nCONTEXTO:\n{cleaned}"

    for attempt in range(max_retries):
        try:
            print(f"Calling gemini-2.0-flash (Attempt {attempt+1})...")
            response = await model.generate_content_async(final_prompt)
            print("Generation successful.")
            return json.loads(response.text)
        except Exception as e:
            error_str = str(e)
            is_rate_limit = "429" in error_str or "ResourceExhausted" in str(type(e).__name__)
            
            if is_rate_limit and attempt < max_retries - 1:
                wait_time = base_delay * (2 ** attempt)
                print(f"Rate limit (Attempt {attempt+1}). Exponential backoff: {wait_time}s...")
                await asyncio.sleep(wait_time)
                continue
            
            print(f"Generation failed: {error_str}")
            return []

    return []


# === STREAMING GENERATOR (2x5 batching with SSE) ===
async def generate_exam_streaming(num_questions: int, context_text: str = None, topic: str = None, difficulty: str = "Intermedio"):
    """
    Async generator that yields batches of 5 validated questions.
    Each yield keeps the SSE connection alive, preventing 504 timeout.
    """
    if not API_KEY:
        yield [{"id": 1, "question": "Error: API Key no configurada", "options": ["A","B","C","D"], "correct_index": 0, "explanation": "Configura .env"}]
        return

    if topic and not context_text:
        context_text = f"Tema solicitado: {topic}"

    BATCH_SIZE = 5
    generated_count = 0
    batch_number = 0

    while generated_count < num_questions:
        batch_count = min(BATCH_SIZE, num_questions - generated_count)
        prompt = get_base_prompt(batch_count, difficulty)
        
        batch_number += 1
        print(f"--- Batch {batch_number}: Generating {batch_count} questions (offset: {generated_count}) ---")
        
        raw_questions = await _generate_chunk(prompt, context_text, 25000)
        
        if isinstance(raw_questions, list) and raw_questions:
            validated = []
            for i, q in enumerate(raw_questions):
                if q:
                    q["id"] = generated_count + i + 1
                    validated.append(validate_and_fix_question(q))
            
            generated_count += len(validated)
            print(f"Batch {batch_number} complete: {len(validated)} questions. Total: {generated_count}/{num_questions}")
            yield validated
        else:
            print(f"Batch {batch_number} FAILED. Stopping generation.")
            break
        
        # Cooldown between batches to avoid rate limit on second batch
        if generated_count < num_questions:
            print("Cooldown 3s between batches...")
            await asyncio.sleep(3)
