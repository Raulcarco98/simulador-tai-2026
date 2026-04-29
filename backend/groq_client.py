import os
import json
import asyncio
import re
import random
import aiohttp
from dotenv import load_dotenv

load_dotenv()

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# === MODEL LADDER ===
# Orden de preferencia: mejor modelo primero, fallback automático por rate limit.
# Groq free tier limits (approx):
#   llama-3.3-70b-versatile: 6000 tokens/min, 30 req/min
#   llama-3.1-8b-instant:    6000 tokens/min, 30 req/min (pero mucho más rápido)
MODEL_LADDER = [
    {
        "id": "llama-3.3-70b-versatile",
        "label": "Llama 3.3 70B",
        "max_output": 4096,     # Groq limit for 70B completion tokens
        "temperature": 0.4,
    },
    {
        "id": "llama-3.1-8b-instant",
        "label": "Llama 3.1 8B",
        "max_output": 8192,     # 8B allows more output tokens
        "temperature": 0.5,     # Slightly higher to compensate smaller model
    },
]

# Errores que indican rate limit o token limit → trigger fallback
RATE_LIMIT_INDICATORS = [
    "rate_limit",
    "rate limit",
    "tokens per minute",
    "requests per minute",
    "too many requests",
    "429",
    "quota",
    "limit exceeded",
    "resource_exhausted",
]


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
    
    # Remove invisible control characters
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


def _is_rate_limit_error(error_text):
    """Detecta si un error es de rate limit / token limit para activar fallback."""
    lower = error_text.lower()
    return any(indicator in lower for indicator in RATE_LIMIT_INDICATORS)


def validate_and_fix_question(question):
    """
    BLINDAJE STRICTO: La explicacion es la fuente de la verdad.
    """
    try:
        explanation = question.get("explanation", "").strip()
        options = question.get("options", [])
        correct_idx = question.get("correct_index", 0)
        
        # --- FIX: Forzar exactamente 4 opciones ---
        if len(options) > 4:
            _safe_print(f"[FIX] Q{question.get('id')}: {len(options)} opciones -> recortando a 4.")
            if correct_idx >= 4:
                correct_option = options[correct_idx]
                options[3] = correct_option
                correct_idx = 3
            options = options[:4]
            question["options"] = options
            question["correct_index"] = correct_idx
        
        detected_letter = None
        m = re.search(r"respuesta\s+correcta\s+(?:es|sea)\s+(?:la\s+)?([A-D])\b", explanation, re.IGNORECASE)
        if m:
            detected_letter = m.group(1).upper()
        
        if not detected_letter:
            m2 = re.search(r"correcta:\s*\[?([A-D])\]?", explanation, re.IGNORECASE)
            if m2: detected_letter = m2.group(1).upper()
            
        if not detected_letter:
            m3 = re.search(r"^([A-D])[).\s]", explanation)
            if m3: detected_letter = m3.group(1).upper()

        if detected_letter:
            expected_index = ord(detected_letter) - ord('A')
            if 0 <= expected_index < len(options):
                if correct_idx != expected_index:
                    _safe_print(f"[BLINDAJE] Q{question.get('id')}: CORRECCION {correct_idx} ({chr(65+correct_idx)}) -> {expected_index} ({detected_letter})")
                    question["correct_index"] = expected_index
        
        current_idx = question.get("correct_index")
        if not isinstance(current_idx, int) or current_idx < 0 or current_idx >= len(options):
             question["correct_index"] = 0

    except Exception:
        pass
    
    return question


def shuffle_options(question):
    """
    Aleatoriza el orden de las opciones para evitar el sesgo de posicion.
    """
    try:
        options = question.get("options", [])
        current_idx = question.get("correct_index", 0)
        
        if not options or len(options) < 2:
            return question
            
        if current_idx < 0 or current_idx >= len(options):
            return question
            
        items = [{"text": opt, "is_correct": (i == current_idx)} for i, opt in enumerate(options)]
        random.shuffle(items)
        
        new_options = [item["text"] for item in items]
        new_idx = next(i for i, item in enumerate(items) if item["is_correct"])
        
        question["options"] = new_options
        question["correct_index"] = new_idx
        
        old_letter = chr(65 + current_idx)
        new_letter = chr(65 + new_idx)
        
        if old_letter != new_letter:
            explanation = question.get("explanation", "")
            patterns = [
                (r"(respuesta\s+correcta\s+(?:es|sea)\s+(?:la\s+)?){}\b".format(old_letter), r"\g<1>" + new_letter),
                (r"(correcta:\s*\[?){}\]?".format(old_letter), r"\g<1>" + new_letter),
                (r"(soluci[oó]n:\s*){}\b".format(old_letter), r"\g<1>" + new_letter),
                (r"^{}([.\)])".format(old_letter), new_letter + r"\1")
            ]
            for pat, repl in patterns:
                explanation = re.sub(pat, repl, explanation, flags=re.IGNORECASE)
            question["explanation"] = explanation
            
    except Exception:
        pass
    return question


def _strip_reasoning_field(questions):
    """
    Elimina el campo 'reasoning' de las preguntas antes de enviarlas al frontend.
    El reasoning es útil para que el modelo piense mejor pero no se muestra al usuario.
    """
    for q in questions:
        if isinstance(q, dict):
            q.pop("reasoning", None)
    return questions


def get_base_prompt(num_questions, difficulty, has_context=False, is_small_model=False):
    """
    Genera el prompt base. Adapta la complejidad según el modelo:
    - 70B: Puede usar reasoning (chain of thought interno) para mejor calidad.
    - 8B: Prompt más directo, sin reasoning, para ahorrar tokens y evitar confusión.
    """
    requisitos_contexto = ""
    if has_context:
        requisitos_contexto = "- Cíñete ESTRICTAMENTE al texto proporcionado."
    else:
        requisitos_contexto = "- Temas: Administrativo (Leyes 39/40), plazos y datos EXACTOS."

    if is_small_model:
        # === PROMPT COMPACTO PARA 8B ===
        # Sin reasoning field (ahorra ~30% tokens de output)
        # Instrucciones más explícitas y redundantes
        return f"""Genera EXACTAMENTE {num_questions} preguntas tipo test de oposición TAI C1.
Nivel: {difficulty.upper()}.
{requisitos_contexto}

REGLAS OBLIGATORIAS:
- EXACTAMENTE 4 opciones por pregunta: A, B, C, D. Ni más ni menos.
- Solo 1 opción correcta. Las otras 3 son FALSAS.
- PROHIBIDO: "Todas las anteriores", "Ninguna", "A y B son correctas".
- Cada pregunta debe ser DIFERENTE. NO repitas preguntas.
- Explicación SIEMPRE empieza: "La respuesta correcta es [A/B/C/D] porque..."

JSON (array de {num_questions} objetos):
[
  {{
    "id": 1,
    "question": "Enunciado técnico...",
    "options": ["Opción A.", "Opción B.", "Opción C.", "Opción D."],
    "correct_index": 0,
    "explanation": "La respuesta correcta es A porque..."
  }}
]

IMPORTANTE: {num_questions} preguntas, 4 opciones cada una, JSON válido."""

    # === PROMPT COMPLETO PARA 70B ===
    if difficulty.upper() == "EXPERTO":
        return f"""OBJETIVO: Genera {num_questions} preguntas de nivel EXPERTO para oposiciones TAI C1.
{requisitos_contexto}

JSON SCHEMA:
[
    {{
        "id": 1,
        "question": "Enunciado complejo centrado en excepciones o casos prácticos.",
        "options": ["A", "B", "C", "D"],
        "correct_index": 0,
        "explanation": "La respuesta correcta es A porque [Análisis detallado]..."
    }}
]

REGLAS:
1. EXACTAMENTE 4 opciones (A, B, C, D). Ni más ni menos.
2. 1 Verdadera, 3 Falsas indiscutibles.
3. PROHIBIDO: "Todas las anteriores", "Ninguna", "A y B correctas".
4. Opciones falsas: altera 1 dato objetivo (plazo, órgano, condición).
5. Explicación SIEMPRE empieza: "La respuesta correcta es [Letra] porque..."
6. 25% preguntas negativas ("¿Cuál NO es...?").
7. Cada pregunta debe ser ÚNICA y diferente."""
    
    # BASICO / INTERMEDIO
    return f"""OBJETIVO: Test de {num_questions} preguntas de nivel {difficulty.upper()} para oposiciones.
{requisitos_contexto}

Formato JSON (array de {num_questions} objetos):
[
    {{
        "id": 1,
        "question": "Enunciado...",
        "options": ["A", "B", "C", "D"],
        "correct_index": 0,
        "explanation": "La respuesta correcta es [Letra] porque..."
    }}
]

REGLAS:
1. EXACTAMENTE 4 opciones por pregunta.
2. 1 correcta, 3 falsas claras.
3. PROHIBIDO: "Todas/Ninguna correctas", "A y C".
4. Explicación empieza con: "La respuesta correcta es [Letra]..."
5. Todas las preguntas deben ser DIFERENTES entre sí."""


async def generate_exam_streaming(num_questions: int, context_text: str = None, topic: str = None, difficulty: str = "Intermedio", mode: str = "manual"):
    if not GROQ_API_KEY:
        yield {"type": "log", "msg": "[ERROR] GROQ_API_KEY no encontrada en el entorno. Revisa el archivo .env"}
        return

    yield {"type": "log", "msg": f"[INICIO] {num_questions} preguntas | Dificultad: {difficulty} | Motor: Groq (Fallback automático)"}
    yield {"type": "log", "msg": f"[MODELOS] Ladder: {' → '.join(m['label'] for m in MODEL_LADDER)}"}
    
    clean_ctx = _clean_text(context_text) if context_text else ""
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    all_raw_questions = []
    
    # === MODEL LADDER LOOP ===
    # Intenta con cada modelo del ladder. Si falla por rate limit, baja al siguiente.
    for model_idx, model_spec in enumerate(MODEL_LADDER):
        model_id = model_spec["id"]
        model_label = model_spec["label"]
        model_temp = model_spec["temperature"]
        model_max_output = model_spec["max_output"]
        is_small = model_idx > 0  # Cualquier modelo después del primero es "small"
        
        # Construir prompt adaptado al modelo
        has_content = bool(clean_ctx or topic)
        current_prompt = get_base_prompt(num_questions, difficulty, has_context=has_content, is_small_model=is_small)
        
        if topic:
            current_prompt += f"\n\nCONTEXTO TEMÁTICO: {topic}"
            
        if clean_ctx:
            # Limitar contexto según modelo (8B necesita menos para no saturarse)
            max_ctx_chars = 20000 if is_small else 30000
            block_ctx = clean_ctx[:max_ctx_chars]
            current_prompt += f"\n\nDOCUMENTO NORMATIVO DE REFERENCIA:\n{block_ctx}"
            
            current_prompt += "\n\n⚠️ INSTRUCCIÓN CRÍTICA:"
            if mode == "simulacro_3":
                current_prompt += "\n0. SIMULACRO MULTITEMA: genera preguntas equilibradas por cada bloque temático."
            
            current_prompt += """
1. Solo pregunta sobre información PRESENTE en el documento.
2. NO inventes datos que no estén en el texto.
3. NO menciones "el documento" o "el texto" en los enunciados.
4. Genera EXACTAMENTE el número de preguntas solicitado."""
        
        current_prompt += "\n\nResponde SOLO con el JSON array. Sin texto adicional."

        # System prompt (más conciso para 8B)
        if is_small:
            system_prompt = (
                "Eres un generador de exámenes tipo test para oposiciones. "
                "Responde ÚNICAMENTE con un JSON array válido. "
                "Sin markdown, sin explicaciones fuera del JSON."
            )
        else:
            system_prompt = """Eres un Examinador Senior para oposiciones TAI C1 (Tecnologías de la Información).
Tu tarea es generar preguntas técnicas, precisas y difíciles que sigan estas reglas:
1. UNICIDAD: 1 Verdadera, 3 Falsas indiscutibles.
2. EXCLUSIÓN: Prohibido "Todas las anteriores", "A y B son correctas", etc.
3. OBJETIVIDAD: Las opciones falsas deben ser erróneas por datos técnicos o legales, no por interpretación.
4. EXPLICACIÓN: 'explanation' DEBE empezar siempre con 'La respuesta correcta es [Letra]...'.

Solo respondes en JSON (lista de objetos). Sin markdown."""

        # Calcular max_tokens dinámicamente
        # ~300 tokens por pregunta para 8B (sin reasoning), ~400 para 70B
        tokens_per_q = 300 if is_small else 400
        calculated_tokens = num_questions * tokens_per_q
        max_tokens = min(max(calculated_tokens, 2000), model_max_output)

        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": current_prompt}
            ],
            "temperature": model_temp,
            "max_tokens": max_tokens,
            "stream": False
        }

        yield {"type": "log", "msg": f"\n[MODELO] Probando {model_label} (max_tokens: {max_tokens})..."}

        # === RETRY LOOP PER MODEL ===
        max_retries = 2  # 2 intentos por modelo antes de bajar al siguiente
        model_success = False
        
        for attempt in range(max_retries):
            try:
                yield {"type": "log", "msg": f"[LOG] {model_label} - Intento {attempt+1}/{max_retries}..."}
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(GROQ_API_URL, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as response:
                        result_body = await response.text()
                        
                        if response.status != 200:
                            # Detectar si es rate limit para hacer fallback
                            if _is_rate_limit_error(result_body):
                                yield {"type": "log", "msg": f"[RATE LIMIT] {model_label}: Límite alcanzado."}
                                
                                if model_idx < len(MODEL_LADDER) - 1:
                                    next_model = MODEL_LADDER[model_idx + 1]["label"]
                                    yield {"type": "log", "msg": f"[FALLBACK] Cambiando a {next_model}..."}
                                    # Esperar un poco antes de intentar con el siguiente modelo
                                    await asyncio.sleep(3)
                                    break  # Sale del retry loop, pasa al siguiente modelo
                                else:
                                    yield {"type": "log", "msg": f"[ERROR] Sin modelos disponibles. Esperando 30s..."}
                                    await asyncio.sleep(30)
                                    continue  # Reintenta con el mismo modelo
                            
                            raise Exception(f"HTTP {response.status}: {result_body[:300]}")
                        
                        result = json.loads(result_body)

                raw_text = result['choices'][0]['message']['content']
                
                # Log de tokens
                usage = result.get("usage", {})
                if usage:
                    prompt_tokens = usage.get('prompt_tokens', 0)
                    completion_tokens = usage.get('completion_tokens', 0)
                    total_tokens = usage.get('total_tokens', 0)
                    yield {"type": "log", "msg": f"[TOKENS] Prompt: {prompt_tokens} | Respuesta: {completion_tokens} | Total: {total_tokens}"}
                    
                    # Detectar si se cortó por max_tokens
                    finish_reason = result['choices'][0].get('finish_reason', '')
                    if finish_reason == 'length':
                        yield {"type": "log", "msg": f"[WARN] Respuesta TRUNCADA (finish_reason=length). Puede haber preguntas incompletas."}

                yield {"type": "log", "msg": f"[{model_label}] Respuesta recibida ({len(raw_text)} chars). Parseando..."}
                
                # Intentar parsear JSON
                try:
                    current_questions = json.loads(raw_text)
                except json.JSONDecodeError:
                    cleaned_json = _clean_json_response(raw_text)
                    yield {"type": "log", "msg": f"[{model_label}] JSON directo falló. Limpiando..."}
                    current_questions = json.loads(cleaned_json)
                
                if current_questions and isinstance(current_questions, list) and len(current_questions) > 0:
                    all_raw_questions = current_questions
                    yield {"type": "log", "msg": f"[{model_label}] ✅ {len(all_raw_questions)} preguntas parseadas."}
                    model_success = True
                    break  # Éxito!
                else:
                    raise ValueError("Respuesta no es una lista válida o está vacía")

            except json.JSONDecodeError as je:
                yield {"type": "log", "msg": f"[ERROR] JSON irrecuperable: {str(je)[:100]}"}
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                continue
                
            except Exception as e:
                error_str = str(e)
                yield {"type": "log", "msg": f"[ERROR] {type(e).__name__}: {error_str[:200]}"}
                
                # Check if this error is a rate limit even from non-HTTP path
                if _is_rate_limit_error(error_str):
                    if model_idx < len(MODEL_LADDER) - 1:
                        next_model = MODEL_LADDER[model_idx + 1]["label"]
                        yield {"type": "log", "msg": f"[FALLBACK] Rate limit detectado. Cambiando a {next_model}..."}
                        await asyncio.sleep(3)
                        break  # Pasa al siguiente modelo
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                continue
        
        if model_success:
            break  # No necesitamos probar más modelos
    
    # === VALIDACIÓN Y OUTPUT ===
    if all_raw_questions:
        yield {"type": "log", "msg": f"\n[BLINDAJE] Validando {len(all_raw_questions)} preguntas..."}
        
        # Limpiar campo reasoning (útil para el modelo, no para el usuario)
        all_raw_questions = _strip_reasoning_field(all_raw_questions)
        
        validated = []
        fixes_count = 0
        for i, q in enumerate(all_raw_questions):
            if q and isinstance(q, dict) and "question" in q:
                q["id"] = i + 1
                old_idx = q.get("correct_index")
                fixed_q = validate_and_fix_question(q)
                if fixed_q.get("correct_index") != old_idx:
                    fixes_count += 1
                shuffled_q = shuffle_options(fixed_q)
                validated.append(shuffled_q)
        
        if fixes_count > 0:
            yield {"type": "log", "msg": f"[BLINDAJE] {fixes_count} correcciones de correct_index aplicadas."}
        else:
            yield {"type": "log", "msg": "[BLINDAJE] Todas las preguntas son coherentes."}
        
        yield {"type": "log", "msg": f"\n[COMPLETO] {len(validated)} preguntas listas."}
        yield validated
    else:
        yield {"type": "log", "msg": "[ERROR] No se pudo generar el examen con Groq API tras agotar todos los modelos."}
