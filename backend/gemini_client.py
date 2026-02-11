import os
import json
import asyncio
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types, errors as genai_errors

load_dotenv()

# === MULTI-PROJECT KEY MANAGEMENT ===
# Each key belongs to an independent GCP project with separate quotas
PROJECT_KEYS = []
_key1 = os.getenv("GEMINI_API_KEY")
_key2 = os.getenv("GEMINI_API_KEY_2")
if _key1:
    PROJECT_KEYS.append({"label": "Proyecto A", "key": _key1})
if _key2:
    PROJECT_KEYS.append({"label": "Proyecto Backup", "key": _key2})

current_project = 0
clients = [genai.Client(api_key=p["key"]) for p in PROJECT_KEYS]


def _get_client():
    """Returns the current active project client."""
    if not clients:
        return None, "Sin proyecto"
    idx = current_project % len(clients)
    return clients[idx], PROJECT_KEYS[idx]["label"]


def _rotate_project():
    """Switches to the next independent GCP project. Fast: separate quotas."""
    global current_project
    if len(clients) > 1:
        old_label = PROJECT_KEYS[current_project % len(clients)]["label"]
        current_project = (current_project + 1) % len(clients)
        new_label = PROJECT_KEYS[current_project]["label"]
        return old_label, new_label
    return None, None


# Generation config
generation_config = types.GenerateContentConfig(
    temperature=0.8,
    top_p=0.95,
    top_k=40,
    max_output_tokens=8192,  # Single request needs more tokens
    response_mime_type="application/json",
)

MODEL_NAME = "gemini-2.0-flash"


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


def get_base_prompt(num_questions, difficulty):
    # === REGLAS UNIVERSALES DE BLINDAJE ===
    # 1. UNICIDAD: 1 Verdadera, 3 Falsas.
    # 2. EXCLUSION: Prohibido "Todas/Ninguna es correcta", "A y B", etc.
    # 3. OBJETIVIDAD: Distractores falsos por dato, no por interpretacion.
    
    if difficulty.upper() == "EXPERTO":
        return f"""
    Actua como examinador TAI C1. Genera {num_questions} preguntas avanzadas.
    
    BLINDAJE DE RESPUESTA UNICA Y EXCLUYENTE:
    - REGLA DE ORO: Cada pregunta debe tener EXACTAMENTE una opcion verdadera y tres indiscutiblemente falsas.
    - PROHIBIDO TERMINANTEMENTE: Opciones compuestas ("A y B son ciertas", "Todas las anteriores", "Ninguna es correcta").
    
    CONSTRUCCION DE DISTRACTORES (Falsas):
    - Usa la tecnica "Alteracion de Atributo Unico": Cambia un dato objetivo (un plazo de 10 a 5 dias, un organo de Gobierno a Congreso, una condicion de 'preceptivo' a 'facultativo').
    - NUNCA inventes normativa inexistente. Modifica sutilmente la real.
    
    REQUISITOS ADICIONALES:
    - Temas: Casos practicos, sintaxis y excepciones.
    - Estructura: 25% preguntas negativas (Cual es FALSA?).
    - Leyes 39/40: Usa plazos y datos EXACTOS del texto.
    
    PROCESO DE GENERACION (SELF-CORRECTION):
    1. Piensa la pregunta y la opcion VERDADERA.
    2. Genera 3 opciones FALSAS modificando un atributo unico en cada una.
    3. SELF-CHECK: "¿Existe alguna interpretacion rebuscada bajo la cual una opcion falsa pudiera considerarse verdadera?". Si es SI, reescribela.
    4. REDACTA la explicacion comenzando OBLIGATORIAMENTE asi: "La respuesta correcta es [Letra] porque...".
    5. Verifica: Si has escrito "La respuesta correcta es B", el campo "correct_index" DEBE ser 1.

    JSON SCHEMA:
    [
        {{
            "id": 1,
            "question": "Texto",
            "options": ["A", "B", "C", "D"],
            "correct_index": 0, <--- DEBE COINCIDIR CON LA LETRA DE LA EXPLICACION
            "explanation": "La respuesta correcta es A porque [Explicacion breve]..."
        }}
    ]
    """
    
    # BASICO / INTERMEDIO
    return f"""
    Actua como un Preparador de Oposiciones. Genera un examen tipo test de {num_questions} preguntas.
    
    NIVEL: {difficulty.upper()} (Basico/Intermedio)
    
    REGLAS DE ORO (BLINDAJE):
    1. UNA sola opcion correcta. Tres opciones CLARAMENTE falsas.
    2. PROHIBIDO: "Todas son correctas", "Ninguna es correcta", "A y C son correctas".
    3. DISTRACTORES: Cambia un dato concreto (fecha, numero, palabra clave) para hacer la opcion falsa.
    
    PLAZOS Y LEYES: Se preciso con los dias y los silencios administrativos.
    
    CRITERIO OBLIGATORIO:
    - "explanation" DEBE empezar con la frase exacta: "La respuesta correcta es [Letra]...".
    
    PROCESO INTERNO:
    1. Determina la respuesta correcta.
    2. Asegurate de que las otras 3 son falsas sin ambiguedad.
    3. Escribe la explicacion: "La respuesta correcta es [Letra] porque..."
    4. Asigna correct_index basandote en esa letra (0=A, 1=B...).
    
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


# === STREAMING GENERATOR (Single Request Strategy) ===
async def generate_exam_streaming(num_questions: int, context_text: str = None, topic: str = None, difficulty: str = "Intermedio"):
    """
    Async generator: single unified request for all questions.
    Yields log events and the full question list.
    """
    
    if not clients:
        yield {"type": "log", "msg": "[ERROR] No hay API Keys configuradas. Revisa .env"}
        yield [{"id": 1, "question": "Error: API Key no configurada", "options": ["A","B","C","D"], "correct_index": 0, "explanation": "Configura .env"}]
        return

    # Log inicial
    _, initial_project = _get_client()
    yield {"type": "log", "msg": f"[INICIO] {num_questions} preguntas | Dificultad: {difficulty} | Proyectos: {len(clients)}"}
    yield {"type": "log", "msg": f"[INICIO] Proyecto activo: {initial_project}"}

    if topic and not context_text:
        context_text = f"Tema solicitado: {topic}"
        yield {"type": "log", "msg": f"[INICIO] Tema: {topic}"}
    
    # Preparar Prompt y Contexto
    prompt = get_base_prompt(num_questions, difficulty)
    if context_text:
        clean_len = len(_clean_text(context_text))
        yield {"type": "log", "msg": f"[INICIO] Contexto: {clean_len} caracteres"}
        cleaned_context = _clean_text(context_text[:30000])
        prompt += f"\n\nCONTENIDO PROPORCIONADO:\n{cleaned_context}"

    yield {"type": "log", "msg": f"\n[GENERANDO] Peticion unica de {num_questions} preguntas..."}

    # === CORE GENERATION LOOP INLINED ===
    raw_questions = []
    max_retries = 6 

    for attempt in range(max_retries):
        try:
            active_client, project_label = _get_client()
            yield {"type": "log", "msg": f"[{project_label}] Llamando a {MODEL_NAME} (intento {attempt+1}/{max_retries})..."}
            _safe_print(f"[{project_label}] Request start...")
            
            response = await active_client.aio.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=generation_config,
            )
            
            raw_text = response.text
            yield {"type": "log", "msg": f"[{project_label}] Respuesta recibida. Parseando JSON..."}
            
            # Robust JSON parsing
            try:
                raw_questions = json.loads(raw_text)
                yield {"type": "log", "msg": f"[{project_label}] JSON OK: {len(raw_questions)} preguntas."}
                break # Success!
            except json.JSONDecodeError:
                yield {"type": "log", "msg": f"[{project_label}] JSON directo fallo. Limpiando..."}
                cleaned_json = _clean_json_response(raw_text)
                try:
                    raw_questions = json.loads(cleaned_json)
                    yield {"type": "log", "msg": f"[{project_label}] JSON limpiado: {len(raw_questions)} preguntas recuperadas."}
                    break # Success!
                except json.JSONDecodeError as je:
                    yield {"type": "log", "msg": f"[{project_label}] JSON irrecuperable: {je}. Raw: {raw_text[:150]}..."}
                    # Non-retriable error unless we want to retry generation? 
                    # Usually bad JSON is result of bad generation, so maybe retry?
                    # For now, treat as failure of this attempt.
        
        except genai_errors.ClientError as e:
            error_str = str(e)
            is_rate_limit = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str
            
            if is_rate_limit:
                old_label, new_label = _rotate_project()
                if old_label:
                    # Progressive backoff: 5s, 10s, then 20s cap
                    backoff_times = [5, 10]
                    wait_time = backoff_times[attempt] if attempt < len(backoff_times) else 20
                    
                    yield {"type": "log", "msg": f"[DEBUG] Limite alcanzado. Reintentando en {wait_time}s con el siguiente proyecto..."}
                    _safe_print(f"[DEBUG] {wait_time}s sleep triggered...")
                    await asyncio.sleep(wait_time)
                    continue
                elif attempt < max_retries - 1:
                    wait_time = 10 * (2 ** min(attempt, 3))
                    yield {"type": "log", "msg": f"[DEBUG] Todos los proyectos agotados. Esperando {wait_time}s..."}
                    await asyncio.sleep(wait_time)
                    continue
            
            yield {"type": "log", "msg": f"[ERROR] ClientError: {error_str[:200]}"}
            # Continue to next attempt if possible
                    
        except Exception as e:
            error_str = str(e)
            yield {"type": "log", "msg": f"[ERROR] {type(e).__name__}: {error_str[:200]}"}
            
            if attempt < max_retries - 1:
                wait_time = 5 * (2 ** min(attempt, 3))
                yield {"type": "log", "msg": f"[DEBUG] Reintentando en {wait_time}s..."}
                await asyncio.sleep(wait_time)
                continue
    
    # === VALIDATION & OUTPUT ===
    if isinstance(raw_questions, list) and raw_questions:
        # === BLINDAJE FINAL ===
        yield {"type": "log", "msg": f"\n[BLINDAJE] Validando coherencia de {len(raw_questions)} preguntas..."}
        
        validated = []
        fixes_count = 0
        for i, q in enumerate(raw_questions):
            if q:
                q["id"] = i + 1
                old_idx = q.get("correct_index")
                fixed_q = validate_and_fix_question(q)
                if fixed_q.get("correct_index") != old_idx:
                    fixes_count += 1
                validated.append(fixed_q)
        
        if fixes_count > 0:
            yield {"type": "log", "msg": f"[BLINDAJE] {fixes_count} correcciones de correct_index aplicadas."}
        else:
            yield {"type": "log", "msg": "[BLINDAJE] Todas las preguntas son coherentes."}
        
        yield {"type": "log", "msg": f"\n[COMPLETO] {len(validated)} preguntas generadas y validadas."}
        yield validated
    else:
        yield {"type": "log", "msg": "[ERROR] No se generaron preguntas tras todos los intentos."}
