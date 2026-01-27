import os
import google.generativeai as genai
import json
import asyncio
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

if API_KEY:
    # Primary model
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        generation_config=generation_config,
    )

def get_base_prompt(num_questions):
    return f"""
    Actúa como un Preparador de Oposiciones para TAI (Técnicos Auxiliares de Informática) con 20 años de experiencia.
    Genera un examen tipo test de {num_questions} preguntas.

    INSTRUCCIONES DE ESTILO:
    - Las preguntas deben ser técnicas, precisas y desafiantes, nivel real de oposición.
    - La EXPLICACIÓN debe ser DIDÁCTICA y DETALLADA. 
    - ESTRUCTURA DE LA EXPLICACIÓN:
        1. Confirma por qué la opción correcta es acertada (fundamento técnico/teórico).
        2. Explica brevemente por qué las otras opciones son incorrectas (trampas típicas, conceptos confusos).
    
    CRITERIO DE CONTEXTO:
    Si hay TEXTO DE CONTEXTO, úsalo como fuente primaria. Si no, usa el temario oficial actual.

    Formato JSON requerido (Array de objetos):
    [
        {{
            "id": 1,
            "question": "Enunciado técnico...",
            "options": ["Opción A", "Opción B", "Opción C", "Opción D"],
            "correct_index": 0,
            "explanation": "Correcta: [Razón técnica confirmada]. Incorrectas: B no es válida porque... C se refiere a..."
        }},
        ...
    ]
    """

async def generate_exam(num_questions: int, context_text: str = None):
    if not API_KEY:
         return [{"question": "Error: API Key no configurada", "options": ["A", "B", "C", "D"], "correct_index": 0, "explanation": "Configura .env"}]

    prompt = get_base_prompt(num_questions)
    
    # Reduced context limit to avoid hitting TPM limits quickly on free tier
    MAX_CONTEXT_CHARS = 30000 
    
    if context_text:
        prompt += f"\n\nTEXTO DE CONTEXTO (Resumido):\n{context_text[:MAX_CONTEXT_CHARS]}"
    else:
        prompt += "\n\nNO HAY CONTEXTO ESPECÍFICO. Genera preguntas variadas del temario general."

    max_retries = 3
    base_delay = 2

    for attempt in range(max_retries):
        try:
            # We wrap the sync call in a thread or just use it directly (it's blocking but fast enough usually, 
            # though proper way is run_in_executor if blocking). 
            # The library supports async now? generate_content_async check.
            response = await model.generate_content_async(prompt)
            return json.loads(response.text)
            
        except Exception as e:
            error_str = str(e)
            print(f"Attempt {attempt + 1} failed: {error_str}")
            
            if "429" in error_str:
                if attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt)
                    print(f"Rate limit hit. Waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    return [{
                        "question": "¡Ups! Demasiadas peticiones a la IA (Error 429).",
                        "options": ["Espera 1 minuto", "Reduce el texto", "Intenta de nuevo", "Revisa tu API Key"],
                        "correct_index": 0,
                        "explanation": "La API de Gemini tiene un límite de usos por minuto. Por favor, espera un poco antes de volver a intentar."
                    }]
            else:
                 return [{
                    "question": f"Error inesperado: {error_str[:100]}...",
                    "options": ["Reintentar", "Reportar", "Ignorar", "Salir"],
                    "correct_index": 0,
                    "explanation": "Ocurrió un error al procesar la solicitud."
                }]
    
    return []
