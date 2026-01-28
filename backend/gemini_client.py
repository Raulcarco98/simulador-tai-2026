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
    - Experto: DIFICULTAD MÁXIMA EN LAS OPCIONES. Las respuestas incorrectas deben ser MUY SIMILARES a la correcta (cambiar una palabra clave, plazos muy cercanos, excepciones sutiles). Obliga al usuario a tener conocimiento preciso. EVITA distractores obvios o ridículos.

    ESTRATEGIA DE COBERTURA PROFUNDA (OBLIGATORIO):
    El usuario necesita evaluar TODO el documento. Tienes prohibido quedarte solo en el inicio.
    
    1. ESCANEO INICIAL: Lee el texto completo hasta la última línea antes de generar nada. Identifica el rango total.
    2. DISTRIBUCIÓN FORZADA (Ejemplo para 10 preguntas):
       - Preguntas 1-3: Primer tercio del documento.
       - Preguntas 4-7: Parte central del documento.
       - Preguntas 8-10: ÚLTIMO TERCIO del documento (Es vital llegar al final).
    3. Si el texto tiene Artículos, asegúrate de citar Artículos del final.
    
    INSTRUCCIONES DE ESTILO:
    - Las preguntas deben ser técnicas, precisas y desafiantes.
    - La EXPLICACIÓN debe ser DIDÁCTICA y DETALLADA. 
    
    CRITÉRIO DE INTEGRIDAD JSON (CRÍTICO):
    - "correct_index" DEBE corresponder EXACTAMENTE a la posición en el array "options" (0 para A, 1 para B, etc.).
    - La "explanation" debe decir explícitamente "La respuesta correcta es [Letra]..." y coincidir con "correct_index".
    
    ESTRUCTURA DE LA EXPLICACIÓN (IMPORTANTE):
        1. "La respuesta correcta es [Letra] porque... [razón fundamental]".
        2. "Referencia: Basado en la sección/artículo X..." (CITA).
    
    ESTRUCTURA DE REFUTACIONES (NUEVO):
    - Debes generar un objeto "refutations" donde expliques por qué CADA opción incorrecta falla.
    - Clave: El índice de la opción (0, 1, 2, 3).
    - Valor: "Esta opción es incorrecta porque..." (Análisis específico).
    
    Formato JSON requerido (Array de objetos):
    [
        {{
            "id": 1,
            "question": "Enunciado técnico...",
            "options": ["Opción A", "Opción B", "Opción C", "Opción D"],
            "correct_index": 0,
            "explanation": "La respuesta correcta es A porque... Referencia: Art. 14.",
            "refutations": {{
                "1": "B es incorrecta porque...",
                "2": "C es incorrecta porque...",
                "3": "D es incorrecta porque..."
            }}
        }},
        ...
    ]
    """

async def generate_exam(num_questions: int, context_text: str = None, topic: str = None, difficulty: str = "Intermedio"):
    if not API_KEY:
         return [{"question": "Error: API Key no configurada", "options": ["A", "B", "C", "D"], "correct_index": 0, "explanation": "Configura .env"}]

    prompt = get_base_prompt(num_questions, difficulty)
    
    max_retries = 5
    base_delay = 5
    
    # Adaptive Context Strategy: Start safe (35k) and reduce if needed
    current_context_limit = 35000

    for attempt in range(max_retries):
        # Re-build prompt dynamically for each attempt (to allow context reduction)
        prompt = get_base_prompt(num_questions, difficulty)
        
        import re
        def clean_text(text):
            if not text: return ""
            text = re.sub(r'\n+', '\n', text)
            text = re.sub(r'\s+', ' ', text)
            return text.strip()

        # PRIORITY LOGIC (inside loop to use current_context_limit)
        if context_text:
            cleaned_context = clean_text(context_text[:current_context_limit])
            prompt += f"\n\nFUENTE DE CONTEXTO (PRIORIDAD 1):\nUsa EXCLUSIVAMENTE el siguiente texto para generar las preguntas. Lee hasta el final:\n{cleaned_context}"
            
            if len(cleaned_context) > 5000:
                 prompt += "\n\nNOTA: Texto extenso detectado. RECUERDA llegar hasta el final del documento en tus preguntas."

        elif topic and topic.strip():
            cleaned_topic = clean_text(topic)
            prompt += f"\n\nFUENTE DE TEMA (PRIORIDAD 2):\nGenera preguntas EXCLUSIVAMENTE sobre el siguiente tema: '{cleaned_topic}'.\nUsa tu conocimiento general para crear preguntas relevantes sobre este tema."
        else:
            prompt += "\n\nFUENTE POR DEFECTO (PRIORIDAD 3):\nNO HAY CONTEXTO NI TEMA ESPECÍFICO. Genera preguntas variadas del temario oficial de Técnicos Auxiliares de Informática (TAI)."

        try:
            # We wrap the sync call in a thread or just use it directly
            response = await model.generate_content_async(prompt)
            return json.loads(response.text)
            
        except Exception as e:
            error_str = str(e)
            print(f"Attempt {attempt + 1} failed: {error_str}")
            
            if "429" in error_str:
                if attempt < max_retries - 1:
                    # Adaptive Reduction: Slash context by 25% on each fail
                    old_limit = current_context_limit
                    current_context_limit = int(current_context_limit * 0.75)
                    
                    wait_time = base_delay * (2 ** attempt)
                    print(f"Rate limit hit (429). Reducing context ({old_limit} -> {current_context_limit}) and waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    return [{
                        "question": "¡El servidor de IA está saturado (Error 429)!",
                        "options": ["Inténtalo de nuevo en 1 minuto", "Reduce un poco el texto", "Verifica tu API Key", "Contacta soporte"],
                        "correct_index": 0,
                        "explanation": f"Hemos intentado reducir el texto hasta {current_context_limit} caracteres, pero la API sigue saturada. Espera un poco.",
                        "refutations": {}
                    }]
            else:
                 return [{
                    "question": f"Error inesperado: {error_str[:100]}...",
                    "options": ["Reintentar", "Ignorar", "Salir", "Ayuda"],
                    "correct_index": 0,
                    "explanation": "Ocurrió un error técnico al procesar la solicitud.",
                    "refutations": {}
                }]
    
    return []
