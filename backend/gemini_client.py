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
    BLINDAJE FINAL: Verifica que correct_index sea coherente con explanation.
    Aplica fix automatico si detecta discrepancia.
    """
    try:
        explanation = question.get("explanation", "")
        options = question.get("options", [])
        correct_idx = question.get("correct_index", 0)
        detected_letter = None
        
        # Pattern 1: "respuesta correcta es [la] X"
        m = re.search(r"respuesta\s+correcta\s+(?:es|sea)\s+(?:la\s+)?([A-D])\b", explanation, re.IGNORECASE)
        if m:
            detected_letter = m.group(1).upper()
        
        # Pattern 2: "Correcta: X" or "Correcta: [X]"
        if not detected_letter:
            m2 = re.search(r"[Cc]orrecta:\s*\[?([A-D])\]?", explanation)
            if m2:
                detected_letter = m2.group(1).upper()
        
        # Pattern 3: "Es la X" at start
        if not detected_letter:
            m3 = re.search(r"^\s*[Ee]s\s+la\s+([A-D])\b", explanation)
            if m3:
                detected_letter = m3.group(1).upper()
        
        # Pattern 4: Starts with a letter reference "A)" or "A."
        if not detected_letter:
            m4 = re.search(r"^([A-D])[).\s]", explanation.strip())
            if m4:
                detected_letter = m4.group(1).upper()
        
        # Pattern 5: "opcion X es correcta"
        if not detected_letter:
            m5 = re.search(r"opci[oó]n\s+([A-D])\s+(?:es|sea)\s+(?:la\s+)?correcta", explanation, re.IGNORECASE)
            if m5:
                detected_letter = m5.group(1).upper()
        
        if detected_letter:
            expected_index = ord(detected_letter) - ord('A')
            if 0 <= expected_index <= 3 and correct_idx != expected_index:
                _safe_print(f"[BLINDAJE] Q{question.get('id')}: correct_index {correct_idx} -> {expected_index} (explanation dice '{detected_letter}')")
                question["correct_index"] = expected_index
        
        # Validate correct_index is in range
        if not isinstance(correct_idx, int) or correct_idx < 0 or correct_idx >= len(options):
            _safe_print(f"[BLINDAJE] Q{question.get('id')}: correct_index {correct_idx} fuera de rango. Reseteando a 0.")
            question["correct_index"] = 0
            
    except Exception as e:
        _safe_print(f"[BLINDAJE] Error validando pregunta: {e}")
    
    return question


def get_base_prompt(num_questions, difficulty):
    if difficulty.upper() == "EXPERTO":
        return f"""
    Actua como examinador TAI C1. Genera {num_questions} preguntas avanzadas.
    REQUISITOS:
    - Temas: Casos practicos, sintaxis y excepciones.
    - Estructura: 25% preguntas negativas (Cual es FALSA?).
    - Distractores: Cambia cifras (10->15 dias), confunde leyes (39<->40), usa siglas parecidas (ENS<->ENI).
    - Cobertura: Evalua TODO el contenido proporcionado. Distribuye las preguntas uniformemente por todo el texto.
    - Concision: Explicacion de 1 linea (max 15 palabras).
    - Formato: Responde UNICAMENTE el array JSON, sin texto previo ni posterior.

    PROCESO INTERNO (para cada pregunta):
    PASO 1: Determina la respuesta correcta y redacta la explicacion breve.
    PASO 2: Basandote UNICAMENTE en el Paso 1, asigna correct_index (0=A, 1=B, 2=C, 3=D).

    REGLA DE ORO: Si en la explicacion mencionas una letra (ej: "Es la B"), correct_index DEBE ser obligatoriamente el indice de esa letra.
    En preguntas negativas, correct_index = indice de la opcion FALSA.

    BLINDAJE: Para cada pregunta, verifica internamente: La explanation confirma que la opcion [X] es la correcta? Entonces correct_index debe ser imperativamente el valor numerico de [X].

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
    Actua como un Preparador de Oposiciones. Genera un examen tipo test de {num_questions} preguntas.
    
    NIVEL: {difficulty.upper()} (Basico/Intermedio)
    ESTILO: Preguntas claras. Explicacion didactica.
    REALISMO: Usa "Todas/Ninguna es correcta" en 20% de preguntas.
    COBERTURA: Evalua TODO el contenido proporcionado. Distribuye las preguntas uniformemente.
    
    CRITERIO JSON:
    - "explanation" empieza con "La respuesta correcta es [Letra]...".
    
    PROCESO INTERNO (para cada pregunta):
    PASO 1: Determina la respuesta correcta y redacta la explicacion comenzando con "La respuesta correcta es [Letra] porque...".
    PASO 2: Basandote UNICAMENTE en el Paso 1, asigna correct_index (0=A, 1=B, 2=C, 3=D).

    REGLA DE ORO: Si en la explicacion escribes "La respuesta correcta es B", correct_index DEBE ser 1. Siempre.
    BLINDAJE: Para cada pregunta, verifica: La explanation confirma que la opcion [X] es la correcta? Entonces correct_index = valor numerico de [X].
    
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
