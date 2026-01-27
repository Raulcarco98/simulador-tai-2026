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

def get_base_prompt(num_questions, difficulty):
    return f"""
    Actúa como un Preparador de Oposiciones y Experto en Evaluación con 20 años de experiencia.
    Genera un examen tipo test de {num_questions} preguntas.
    
    NIVEL DE DIFICULTAD: {difficulty.upper()}
    - Básico: Conceptos fundamentales y definiciones.
    - Intermedio: Relación de conceptos y casos prácticos estándar.
    - Experto: Detalles técnicos profundos, excepciones y casos complejos.

    INSTRUCCIONES DE ESTILO:
    - Las preguntas deben ser técnicas, precisas y desafiantes.
    - La EXPLICACIÓN debe ser DIDÁCTICA y DETALLADA. 
    - ESTRUCTURA DE LA EXPLICACIÓN:
        1. Confirma por qué la opción correcta es acertada (fundamento técnico/teórico).
        2. Explica brevemente por qué las otras opciones son incorrectas (trampas típicas, conceptos confusos).
    
    Formato JSON requerido (Array de objetos):
    [
        {{
            "id": 1,
            "question": "Enunciado técnico...",
            "options": ["Opción A", "Opción B", "Opción C", "Opción D"],
            "correct_index": 0,
            "explanation": "Correcta: [Razón técnica]..."
        }},
        ...
    ]
    """

async def generate_exam(num_questions: int, context_text: str = None, topic: str = None, difficulty: str = "Intermedio"):
    if not API_KEY:
         return [{"question": "Error: API Key no configurada", "options": ["A", "B", "C", "D"], "correct_index": 0, "explanation": "Configura .env"}]

    prompt = get_base_prompt(num_questions, difficulty)
    
    # Reduced context limit to avoid hitting TPM limits quickly on free tier
    MAX_CONTEXT_CHARS = 30000 
    
    import re
    def clean_text(text):
        if not text: return ""
        # Replace multiple newlines with single newline
        text = re.sub(r'\n+', '\n', text)
        # Replace multiple spaces with single space
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    # PRIORITY LOGIC
    if context_text:
        cleaned_context = clean_text(context_text[:MAX_CONTEXT_CHARS])
        prompt += f"\n\nFUENTE DE CONTEXTO (PRIORIDAD 1):\nUsa EXCLUSIVAMENTE el siguiente texto para generar las preguntas:\n{cleaned_context}"
        
        if len(cleaned_context) > 5000:
             prompt += "\n\nNOTA: El texto es extenso. Céntrate en los PUNTOS CLAVE y conceptos más importantes. Evita detalles triviales para maximizar la calidad de las preguntas."

    elif topic and topic.strip():
        cleaned_topic = clean_text(topic)
        prompt += f"\n\nFUENTE DE TEMA (PRIORIDAD 2):\nGenera preguntas EXCLUSIVAMENTE sobre el siguiente tema: '{cleaned_topic}'.\nUsa tu conocimiento general para crear preguntas relevantes sobre este tema."
    else:
        prompt += "\n\nFUENTE POR DEFECTO (PRIORIDAD 3):\nNO HAY CONTEXTO NI TEMA ESPECÍFICO. Genera preguntas variadas del temario oficial de Técnicos Auxiliares de Informática (TAI)."

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
