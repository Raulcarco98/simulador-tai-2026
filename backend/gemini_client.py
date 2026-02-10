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
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 8192,
    "response_mime_type": "application/json",
}

# Configuración de Modelos
if API_KEY:
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        generation_config=generation_config,
    )

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
    # --- PROMPT OFICIAL TAI (Solo para EXPERTO - OPTIMIZADO) ---
    if difficulty.upper() == "EXPERTO":
        return f"""
    Actúa como examinador TAI C1. Genera {num_questions} preguntas avanzadas.
    REQUISITOS:
    - Temas: Casos prácticos, sintaxis y excepciones.
    - Estructura: 25% preguntas negativas (¿Cuál es FALSA?).
    - Concisión: Explicación de 1 línea (máx 15 palabras).
    - Formato: Responde ÚNICAMENTE el array JSON, sin texto previo ni posterior. PROHIBIDO usar caracteres especiales innecesarios.

    COHERENCIA CRÍTICA:
    - Antes de cerrar el JSON, verifica que correct_index apunte EXACTAMENTE a la opción que validas en la explanation.
    - En preguntas negativas, correct_index debe ser el índice de la opción intrínsecamente FALSA o no requerida según la ley.

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
    
    # --- PROMPT LEGACY SIMPLIFICADO (Para BÁSICO/INTERMEDIO) ---
    return f"""
    Actúa como un Preparador de Oposiciones. Genera un examen tipo test de {num_questions} preguntas.
    
    NIVEL: {difficulty.upper()} (Básico/Intermedio)
    ESTILO: Preguntas claras. Explicación didáctica.
    REALISMO: Usa "Todas/Ninguna es correcta" en 20% de preguntas.
    
    CRITÉRIO JSON:
    - "explanation" empieza con "La respuesta correcta es [Letra]...".
    
    COHERENCIA CRÍTICA:
    - Antes de cerrar el JSON, verifica que correct_index apunte EXACTAMENTE a la opción que validas en la explanation.
    - En preguntas negativas, correct_index debe ser el índice de la opción FALSA o no requerida.
    
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

async def _generate_chunk(chunk_prompt, current_context_text, current_context_limit):
    if not API_KEY: return []
    
    max_retries = 5
    base_delay = 10
    
    for attempt in range(max_retries):
        final_prompt = chunk_prompt
        
        # Apply context limit
        import re
        def clean_text(text):
            if not text: return ""
            text = re.sub(r'\n+', '\n', text)
            text = re.sub(r'\s+', ' ', text)
            return text.strip()

        if current_context_text:
            cleaned = clean_text(current_context_text[:current_context_limit])
            final_prompt += f"\n\nCONTEXTO:\n{cleaned}"
        
        try:
            print(f"DEBUG: Calling gemini-2.0-flash (Attempt {attempt+1})...")
            # Force minimal output tokens by standardizing
            response = await model.generate_content_async(final_prompt)
            print("DEBUG: Generation successful.")
            return json.loads(response.text)
        except Exception as e:
            error_str = str(e)
            is_rate_limit = "429" in error_str or "ResourceExhausted" in str(type(e).__name__)
            
            if is_rate_limit:
                if attempt < max_retries - 1:
                    current_context_limit = int(current_context_limit * 0.75)
                    wait_time = base_delay * (2 ** attempt)
                    print(f"Retry (Attempt {attempt+1}): Rate limit. Context: {current_context_limit}. Waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
            
            print(f"DEBUG: Generation failed: {error_str}")
            return []

    return []


async def generate_exam(num_questions: int, context_text: str = None, topic: str = None, difficulty: str = "Intermedio"):
    if not API_KEY:
         return [{"question": "Error: API Key no configurada", "options": ["A", "B", "C", "D"], "correct_index": 0, "explanation": "Configura .env"}]

    prompt = get_base_prompt(num_questions, difficulty)
    
    # === SINGLE REQUEST EXECUTION (NO BATCHING) ===
    # We use a conservative context limit (25000) to ensure the single request fits and doesn't trigger 429 easily on input.
    # The output is also optimized by the prompt.
    
    print("Executing Single Request Mode...")
    return await _generate_chunk(prompt, context_text, 25000) # Reduced from 35000 to 30000
