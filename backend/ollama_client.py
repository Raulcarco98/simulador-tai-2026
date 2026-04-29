import os
import json
import asyncio
import re
import random
import aiohttp
from dotenv import load_dotenv

load_dotenv()

# We don't need API keys for local Ollama, but we'll leave this empty for structural similarity
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"


# === UTILIDADES ===
def _safe_print(msg):
    """Print with encoding safety for Windows cp1252 console."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', 'replace').decode('ascii'))


def _clean_text(text):
    """Colapsa saltos de linea y espacios multiples."""
    if not text:
        return ""
    text = re.sub(r'\n+', '\n', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _clean_json_response(raw_text):
    """
    Limpia la respuesta de la IA antes de parsear JSON.
    Elimina markdown code fences, caracteres de control, texto extra.
    """
    if not raw_text:
        return "[]"
    
    text = raw_text.strip()
    
    # Remove invisible control characters (BOM, zero-width spaces, etc.)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufeff\u200b\u200c\u200d\u2060]', '', text)
    
    # Remove markdown code fences
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    text = text.strip()
    
    # Find the JSON array
    if not text.startswith('['):
        bracket_start = text.find('[')
        if bracket_start != -1:
            text = text[bracket_start:]
    
    if not text.endswith(']'):
        bracket_end = text.rfind(']')
        if bracket_end != -1:
            text = text[:bracket_end + 1]
    
    return text


def validate_and_fix_question(question):
    """
    BLINDAJE STRICTO: La explicacion es la fuente de la verdad.
    Si la explicacion dice 'La respuesta correcta es B', el indice DEBE ser 1.
    """
    try:
        explanation = question.get("explanation", "").strip()
        options = question.get("options", [])
        correct_idx = question.get("correct_index", 0)
        
        # 1. Extraer la letra que la explicacion AFIRMA ser correcta
        detected_letter = None
        
        # Pattern Prioritario: "La respuesta correcta es [la] X" (Formato forzado en prompt)
        m = re.search(r"respuesta\s+correcta\s+(?:es|sea)\s+(?:la\s+)?([A-D])\b", explanation, re.IGNORECASE)
        if m:
            detected_letter = m.group(1).upper()
        
        # Fallbacks (por si el modelo alucina el formato)
        if not detected_letter:
            # "Correcta: X"
            m2 = re.search(r"correcta:\s*\[?([A-D])\]?", explanation, re.IGNORECASE)
            if m2: detected_letter = m2.group(1).upper()
            
        if not detected_letter:
            # Empieza por "X)" o "X."
            m3 = re.search(r"^([A-D])[).\s]", explanation)
            if m3: detected_letter = m3.group(1).upper()

        # 2. Aplicar correccion si hay discrepancia
        if detected_letter:
            expected_index = ord(detected_letter) - ord('A')
            
            # Verificar rango valido
            if 0 <= expected_index < len(options):
                if correct_idx != expected_index:
                    _safe_print(f"[BLINDAJE] Q{question.get('id')}: CORRECCION APLICADA. Indice {correct_idx} ({chr(65+correct_idx)}) -> {expected_index} ({detected_letter}) basado en explicacion.")
                    question["correct_index"] = expected_index
            else:
                 _safe_print(f"[BLINDAJE] Q{question.get('id')}: Letra detectada '{detected_letter}' fuera de rango de opciones. No se puede corregir.")
        
        # 3. Validacion final de rango
        current_idx = question.get("correct_index")
        if not isinstance(current_idx, int) or current_idx < 0 or current_idx >= len(options):
             _safe_print(f"[BLINDAJE] Q{question.get('id')}: Indice {current_idx} invalido. Reseteando a 0 (Safeguard).")
             question["correct_index"] = 0

    except Exception as e:
        _safe_print(f"[BLINDAJE] Error critico en validacion: {e}")
    
    return question



def shuffle_options(question):
    """
    Aleatoriza el orden de las opciones para evitar el sesgo de posicion (siempre A).
    Actualiza correct_index y la explicacion para reflejar la nueva letra.
    """
    try:
        options = question.get("options", [])
        current_idx = question.get("correct_index", 0)
        
        if not options or len(options) < 2:
            return question
            
        # 1. Identificar la respuesta correcta actual (texto)
        if current_idx < 0 or current_idx >= len(options):
            return question # Indice invalido, no tocar
            
        correct_text = options[current_idx]
        
        # 2. Barajar opciones
        # Creamos pares (texto, es_correcta)
        items = [{"text": opt, "is_correct": (i == current_idx)} for i, opt in enumerate(options)]
        random.shuffle(items)
        
        # 3. Reconstruir
        new_options = [item["text"] for item in items]
        new_idx = next(i for i, item in enumerate(items) if item["is_correct"])
        
        question["options"] = new_options
        question["correct_index"] = new_idx
        
        # 4. Actualizar Explicacion (Reflejar cambio de letra)
        # El modelo suele escribir "La respuesta correcta es A...".
        # Debemos cambiar esa A por la nueva letra (B, C, D...).
        old_letter = chr(65 + current_idx)
        new_letter = chr(65 + new_idx)
        
        if old_letter != new_letter:
            explanation = question.get("explanation", "")
            
            # Regex para patrones comunes de explicacion
            patterns = [
                # "La respuesta correcta es (la) X"
                (r"(respuesta\s+correcta\s+(?:es|sea)\s+(?:la\s+)?){}\b".format(old_letter), r"\g<1>" + new_letter),
                # "Correcta: X"
                (r"(correcta:\s*\[?){}\]?".format(old_letter), r"\g<1>" + new_letter),
                # "SoluciÃ³n: X"
                (r"(soluci[oÃ³]n:\s*){}\b".format(old_letter), r"\g<1>" + new_letter),
                # Inicio con "X)" o "X."
                (r"^{}([.\)])".format(old_letter), new_letter + r"\1")
            ]
            
            for pat, repl in patterns:
                explanation = re.sub(pat, repl, explanation, flags=re.IGNORECASE)
                
            question["explanation"] = explanation
            
    except Exception as e:
        _safe_print(f"[SHUFFLE] Error barajando pregunta {question.get('id')}: {e}")
        
    return question
def get_base_prompt(num_questions, difficulty, has_context=False):
    # Requirements for context
    requisitos_contexto = ""
    if has_context:
        requisitos_contexto = "- Cíñete ESTRICTAMENTE al texto proporcionado."
    else:
        requisitos_contexto = "- Temas: Administrativo (Leyes 39/40), plazos y datos EXACTOS."

    if difficulty.upper() == "EXPERTO":
        return f"""
    OBJETIVO: Genera {num_questions} preguntas de nivel EXPERTO para oposiciones TAI C1.
    {requisitos_contexto}

    JSON SCHEMA (MANDATORIO):
    [
        {{
            "id": 1,
            "reasoning": "Breve análisis técnico del concepto antes de redactar (Chain of Thought).",
            "question": "Enunciado complejo centrando en excepciones o casos prácticos.",
            "options": ["A", "B", "C", "D"],
            "correct_index": 0,
            "explanation": "La respuesta correcta es A porque [Análisis detallado]..."
        }}
    ]

    EXAMPLE (Expert Quality):
    {{
        "id": 0,
        "reasoning": "La Ley 39/2015 establece plazos específicos para la subsanación. El artículo 68 indica 10 días, pero con posibilidad de ampliación de 5 días si no es procedimiento selectivo o de concurrencia competitiva.",
        "question": "En un procedimiento administrativo común, no sujeto a concurrencia competitiva, se requiere al interesado la subsanación de una solicitud. ¿Cuál es el plazo máximo total de ampliación que podría otorgar la Administración si se cumplen las condiciones de dificultad técnica?",
        "options": [
            "10 días hábiles en total, no siendo posible la ampliación.",
            "5 días hábiles, siempre que el plazo original no haya expirado.",
            "15 días hábiles, sumando el plazo ordinario y la ampliación máxima.",
            "La mitad del plazo ordinario, siempre que las circunstancias lo aconsejen."
        ],
        "correct_index": 1,
        "explanation": "La respuesta correcta es B. Según el Art. 68 de la Ley 39/2015, el plazo de subsanación es de 10 días, ampliable en 5 días (un máximo del 50% según la regla general de ampliación de plazos del Art. 32) si la dificultad técnica lo requiere y no es concurrencia competitiva."
    }}
    """
    
    # BASICO / INTERMEDIO (OPTIMIZADO)
    return f"""
    OBJETIVO: Preparador Oposiciones. Test de {num_questions} preguntas de nivel {difficulty.upper()}.
    {requisitos_contexto.replace("- Temas:", "REQUISITO:").replace("- ", "")}
    
    Formato JSON:
    [
        {{
            "id": 1,
            "reasoning": "Lógica de la pregunta.",
            "question": "Enunciado...",
            "options": ["A", "B", "C", "D"],
            "correct_index": 0,
            "explanation": "La respuesta correcta es [Letra] porque..."
        }}
    ]
    """
   


# === STREAMING GENERATOR (Unified with Segmentation) ===
async def generate_exam_streaming(num_questions: int, context_text: str = None, topic: str = None, difficulty: str = "Intermedio", mode: str = "manual", model_name: str = "deepseek-v3.2:cloud"):
    """
    Async generator that calls the local Ollama instance.
    """
    
    # Log inicial
    yield {"type": "log", "msg": f"[INICIO] {num_questions} preguntas | Dificultad: {difficulty} | Motor: Ollama Local"}
    yield {"type": "log", "msg": f"[INICIO] Model: {model_name}"}

    if topic and not context_text:
        context_text = f"Tema solicitado: {topic}"
        yield {"type": "log", "msg": f"[INICIO] Tema: {topic}"}
    
    # === SEGMENTATION STRATEGY ===
    generation_tasks = []
    
    # Standard single block for ALL modes (Expert splitting removed)
    clean_ctx = _clean_text(context_text) if context_text else ""
    generation_tasks.append({
        "context": clean_ctx, 
        "count": num_questions, 
        "desc": "completo"
    })

    all_raw_questions = []
    max_retries = 3 
    
    # === EXECUTION LOOP ===
    for task_idx, task in enumerate(generation_tasks):
        if len(generation_tasks) > 1:
            yield {"type": "log", "msg": f"\n[EXPERTO] Generando preguntas {task['desc']}..."}
        else:
            yield {"type": "log", "msg": f"\n[GENERANDO] Peticion unica de {num_questions} preguntas..."}
        
        # Build Prompt for this block
        has_content = bool(task["context"] or topic)
        current_prompt = get_base_prompt(task["count"], difficulty, has_context=has_content)
        
        # Inject Topic (Critical for context)
        if topic:
             current_prompt += f"\n\nCONTEXTO TEMATICO: {topic}"

        if task["context"]:
            block_ctx = task["context"][:30000] 
            current_prompt += f"\n\nDOCUMENTO NORMATIVO DE REFERENCIA:\n{block_ctx}"
            
            # STRICT CONTEXT INSTRUCTION (REFINED)
            current_prompt += "\n\n⚠️ INSTRUCCION CRITICA DE JEFE DE TRIBUNAL:"
            
            if mode == "simulacro_3":
                 current_prompt += "\n0. ESTÁS ANTE UN SIMULACRO MULTITEMA (3 Bloques). Debes generar preguntas equilibradas (aprox. una cantidad igual por cada bloque temático)."
            
            current_prompt += """
1. ESTRICTA ADHERENCIA: Solo puedes preguntar sobre la informacion PRESENTE en el documento.
2. CERO INVENTIVA NORMATIVA: Si el documento enumera 3 requisitos, NO puedes inventar un 4o como distractor. Usa los datos del texto modificandolos sutilmente.
3. CERO LITERALIDAD CIEGA: No uses frases de relleno como "segun el documento". Ve al grano.
4. OBLIGATORIO: Genera exactamente el numero de preguntas solicitado.
"""
            
            yield {"type": "log", "msg": f"[DEBUG] Bloque {task_idx+1}: Contexto de {len(block_ctx)} caracteres inyectado."}
        
        # Retry Loop for this Block
        block_success = False
        
        system_prompt = """Eres un Examinador Senior para oposiciones TAI C1 (Tecnologías de la Información).
Tu tarea es generar preguntas técnicas, precisas y difíciles que sigan estas reglas:
1. UNICIDAD: 1 Verdadera, 3 Falsas indiscutibles.
2. EXCLUSIÓN: Prohibido "Todas las anteriores", "A y B son correctas", etc.
3. OBJETIVIDAD: Las opciones falsas deben ser erróneas por datos técnicos o legales, no por interpretación.
4. RAZONAMIENTO: Antes de cada objeto JSON, desarrolla el campo 'reasoning' analizando la base legal o técnica para asegurar que no hay ambigüedad.
5. EXPLICACIÓN: 'explanation' DEBE empezar siempre con 'La respuesta correcta es [Letra]...'.

Solo respondes en JSON minificado (lista de objetos)."""

        # Start attempts
        for attempt in range(0, max_retries):
            try:
                yield {"type": "log", "msg": f"[LOG] Intento {attempt+1}/{max_retries}: Llamando a Ollama ({model_name})..."}
                _safe_print(f"[Ollama] Request start {model_name}...")
                
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": current_prompt}
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.3, # Consistent with Groq
                        "num_predict": 4000
                    }
                }
                
                # Ollama /api/chat is better for system instructions
                async with aiohttp.ClientSession() as session:
                    async with session.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=aiohttp.ClientTimeout(total=600)) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            raise Exception(f"Ollama returned HTTP {response.status}: {error_text}")
                            
                        result = await response.json()
                        raw_text = result.get("message", {}).get("content", "")
        
                yield {"type": "log", "msg": f"[Ollama] Respuesta recibida. Parseando JSON..."}
                
                # Robust JSON parsing
                current_questions = []
                try:
                    current_questions = json.loads(raw_text)
                    if isinstance(current_questions, dict):
                        current_questions = [current_questions]
                    if not current_questions:
                        raise ValueError("JSON structure is empty")
                    yield {"type": "log", "msg": f"[Ollama] JSON OK: {len(current_questions)} preguntas."}
                    all_raw_questions.extend(current_questions)
                    
                    block_success = True
                    break # Block Success!
                except (json.JSONDecodeError, ValueError) as e:
                    yield {"type": "log", "msg": f"[Ollama] JSON directo fallo ({e}). Limpiando..."}
                    cleaned_json = _clean_json_response(raw_text)
                    try:
                        current_questions = json.loads(cleaned_json)
                        if isinstance(current_questions, dict):
                            current_questions = [current_questions]
                        if not current_questions:
                            raise ValueError("JSON limpiado structure is empty")
                        yield {"type": "log", "msg": f"[Ollama] JSON limpiado: {len(current_questions)} preguntas recuperadas."}
                        all_raw_questions.extend(current_questions)
                        
                        block_success = True
                        break # Block Success!
                    except (json.JSONDecodeError, ValueError) as je:
                        raise Exception(f"JSON Parsing fully failed: {je}. Raw output snip: {raw_text[:200]}...")
            
            except Exception as e:
                error_str = str(e)
                yield {"type": "log", "msg": f"[ERROR] {type(e).__name__}: {error_str[:200]}"}
                
                if attempt < max_retries - 1:
                    yield {"type": "log", "msg": f"[DEBUG] Error inesperado. Probando de nuevo en 5s..."}
                    await asyncio.sleep(5)
                continue
        
        if not block_success:
            yield {"type": "log", "msg": f"[ERROR] Fallo critico en bloque {task_idx+1}. Se devolveran resultados parciales."}
            # Decide whether to stop or continue to next block. 
            # If prompt integrity is huge, maybe continue? 
            # But likely we should try next block to salvage something.
            continue

    # === VALIDATION & OUTPUT ===
    if all_raw_questions:
        # === BLINDAJE FINAL ===
        yield {"type": "log", "msg": f"\n[BLINDAJE] Validando coherencia de {len(all_raw_questions)} preguntas totales..."}
        
        validated = []
        fixes_count = 0
        for i, q in enumerate(all_raw_questions):
            if q:
                if type(q) != dict:
                    continue
                q["id"] = i + 1 # Renumber sequentially
                old_idx = q.get("correct_index")
                fixed_q = validate_and_fix_question(q)
                if fixed_q.get("correct_index") != old_idx:
                    fixes_count += 1
                
                # === SHUFFLE PARA EVITAR SESGO ===
                shuffled_q = shuffle_options(fixed_q)
                validated.append(shuffled_q)
        
        if fixes_count > 0:
            yield {"type": "log", "msg": f"[BLINDAJE] {fixes_count} correcciones de correct_index aplicadas."}
        else:
            yield {"type": "log", "msg": "[BLINDAJE] Todas las preguntas son coherentes."}
        
        yield {"type": "log", "msg": f"\n[COMPLETO] {len(validated)} preguntas generadas y validadas."}
        yield validated
    else:
        yield {"type": "log", "msg": "[ERROR] No se generaron preguntas tras todos los intentos."}
