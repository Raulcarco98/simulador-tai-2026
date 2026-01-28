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
    
    INSTRUCCIONES DE REALISMO (META-RESPUESTAS):
    - En aproximadamente el 20% de las preguntas, incluye opciones tipo "Todas las anteriores son correctas" o "Ninguna es correcta".
    - Esto añade realismo y dificultad. Asegúrate de que la lógica se sostenga (ej: si "Todas" es correcta, A, B y C deben ser verdaderas). 
    
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
    
    # Internal function for individual chunks (contains the retry/adaptive logic)
    async def _generate_chunk(chunk_prompt, current_context_text, current_context_limit):
         for attempt in range(max_retries):
            # Re-build prompt logic locally if needed, but here we just append context
            # We assume chunk_prompt is the base instructions.
            
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
                final_prompt += f"\n\nCONTEXTO (FRAGMENTO):\n{cleaned}"
            
            try:
                response = await model.generate_content_async(final_prompt)
                return json.loads(response.text)
            except Exception as e:
                error_str = str(e)
                if "429" in error_str:
                    if attempt < max_retries - 1:
                        current_context_limit = int(current_context_limit * 0.75)
                        wait_time = base_delay * (2 ** attempt)
                        print(f"Batch Retry: Rate limit hit. Reducing context to {current_context_limit} chars. Waiting {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue
                print(f"Chunk generation failed: {error_str}")
                return [] # Return empty on final failure to allow other chunks to succeed
         return []

    # === SMART BATCHING LOGIC ===
    
    # Determine if we need batching (More than 5 questions AND we have context)
    if num_questions > 5 and context_text:
        print("Smart Batching Triggered: Splitting request...")
        
        # Split Context
        mid_point = len(context_text) // 2
        chunk1_text = context_text[:mid_point]
        chunk2_text = context_text[mid_point:]
        
        # Split Questions (e.g. 10 -> 5 + 5, 9 -> 5 + 4)
        q1_count = text_questions = int(num_questions / 2 + 0.5) # Ceil
        q2_count = num_questions - q1_count
        
        prompt1 = get_base_prompt(q1_count, difficulty) + "\n\nNOTA: Este es el FRAGMENTO 1 (INICIO) del documento."
        prompt2 = get_base_prompt(q2_count, difficulty) + "\n\nNOTA: Este es el FRAGMENTO 2 (FINAL) del documento. Céntrate en el final."
        
        # Execute Parallel
        task1 = _generate_chunk(prompt1, chunk1_text, 30000) # Lower initial limit for safety
        task2 = _generate_chunk(prompt2, chunk2_text, 30000)
        
        results = await asyncio.gather(task1, task2)
        
        # Merge & Re-ID
        merged_questions = []
        current_id = 1
        
        for batch in results:
            if isinstance(batch, list):
                for q in batch:
                    q['id'] = current_id
                    merged_questions.append(q)
                    current_id += 1
        
        if not merged_questions:
             return [{
                "question": "Error en Batching: La IA no pudo generar preguntas.",
                "options": ["Reintentar", "Reducir preguntas", "Verificar API", "Soporte"],
                "correct_index": 0,
                "explanation": "Ambos intentos paralelos fallaron por saturación.",
                "refutations": {}
            }]
            
        return merged_questions

    # === STANDARD SINGLE EXECUTION (<= 5 questions OR No Context) ===
    
    current_context_limit = 35000
    for attempt in range(max_retries):
        prompt = get_base_prompt(num_questions, difficulty)
        
        import re
        def clean_text(text):
            if not text: return ""
            text = re.sub(r'\n+', '\n', text)
            text = re.sub(r'\s+', ' ', text)
            return text.strip()

        if context_text:
            cleaned_context = clean_text(context_text[:current_context_limit])
            prompt += f"\n\nFUENTE DE CONTEXTO (PRIORIDAD 1):\nUsa EXCLUSIVAMENTE el siguiente texto:\n{cleaned_context}"
        elif topic and topic.strip():
            cleaned_topic = clean_text(topic)
            prompt += f"\n\nFUENTE DE TEMA (PRIORIDAD 2):\nGenera preguntas EXCLUSIVAMENTE sobre: '{cleaned_topic}'."
        else:
            prompt += "\n\nFUENTE POR DEFECTO (PRIORIDAD 3):\nTemario TAI oficial."

        try:
            response = await model.generate_content_async(prompt)
            return json.loads(response.text)
        except Exception as e:
            error_str = str(e)
            if "429" in error_str:
                if attempt < max_retries - 1:
                    current_context_limit = int(current_context_limit * 0.75)
                    wait_time = base_delay * (2 ** attempt)
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    return [{
                        "question": "¡Error 429 Persistente!",
                        "options": ["Intenta con 5 preguntas", "Espera un momento", "Revisa API", "Soporte"],
                        "correct_index": 0,
                        "explanation": f"Incluso reduciendo a {current_context_limit} chars, la API está saturada.",
                        "refutations": {}
                    }]
            else:
                 return [{"question": f"Error: {error_str[:50]}", "options": ["A"], "correct_index": 0, "explanation": "Error técnico.", "refutations": {}}]
    
    return []
