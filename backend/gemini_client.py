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
    # === REGLAS UNIVERSALES DE BLINDAJE (OPTIMIZADO) ===
    # 1. UNICIDAD: 1 Verdadera, 3 Falsas.
    # 2. EXCLUSION: Prohibido "Todas/Ninguna", "A y B".
    # 3. OBJETIVIDAD: Falsas por dato, no interpretacion.
    
    if difficulty.upper() == "EXPERTO":
        return f"""
    Rol: Examinador TAI C1. Genera {num_questions} preguntas.
    
    BLINDAJE RESPUESTA UNICA:
    - REGLA: 1 Verdadera, 3 Falsas indiscutibles.
    - PROHIBIDO: Compuestas ("Todas", "Ninguna", "A y B").
    
    DISTRACTORES (Falsas):
    - Altera 1 dato objetivo (plazo, organo, condicion).
    - No inventes normativa. Modifica la real.
    
    REQUISITOS:
    - Temas: Practicos, sintaxis, excepciones.
    - 25% Negativas.
    - Leyes 39/40: Plazos y datos EXACTOS.
    
    PROCESO (SELF-CORRECTION):
    1. Piensa pregunta y Verdadera.
    2. Genera 3 Falsas (dato alterado).
    3. SELF-CHECK: ¿Alguna falsa es defendible? Si -> Reescribela.
    4. REDACTA explicacion: "La respuesta correcta es [Letra] porque...".
    5. Verifica: Si dices "Es la B", correct_index=1.

    JSON SCHEMA:
    [
        {{
            "id": 1,
            "question": "Texto",
            "options": ["A", "B", "C", "D"],
            "correct_index": 0,
            "explanation": "La respuesta correcta es A porque [Breve]..."
        }}
    ]
    """
    
    # BASICO / INTERMEDIO (OPTIMIZADO)
    return f"""
    Rol: Preparador Oposiciones. Test de {num_questions} preguntas.
    
    NIVEL: {difficulty.upper()}
    
    REGLAS (BLINDAJE):
    1. 1 Correcta, 3 Falsas claras.
    2. PROHIBIDO: "Todas/Ninguna correctas", "A y C".
    3. FALSAS: Cambia 1 dato concreto.
    
    PLAZOS: Exactitud total en dias/silencios.
    
    CRITERIO OBLIGATORIO:
    - "explanation" DEBE empezar: "La respuesta correcta es [Letra]...".
    
    PROCESO:
    1. Define Correcta.
    2. Asegura 3 Falsas sin ambiguedad.
    3. Explicacion: "La respuesta correcta es [Letra]..."
    4. Asigna correct_index (0=A...).
    
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


# === STREAMING GENERATOR (Unified with Segmentation) ===
async def generate_exam_streaming(num_questions: int, context_text: str = None, topic: str = None, difficulty: str = "Intermedio"):
    """
    Async generator. 
    Expert Mode: Splits generation into 2 blocks (Half 1 / Half 2) to ensure full context coverage.
    Other Modes: Single unified request.
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
    
    # === SEGMENTATION STRATEGY ===
    generation_tasks = []
    
    if difficulty.upper() == "EXPERTO" and context_text and len(context_text) > 1000:
        # Split context in two halves
        clean_full = _clean_text(context_text)
        mid_point = len(clean_full) // 2
        # Find nearest space to avoid cutting words
        split_idx = clean_full.find(' ', mid_point)
        if split_idx == -1: split_idx = mid_point
        
        part1 = clean_full[:split_idx]
        part2 = clean_full[split_idx:]
        
        q_count1 = num_questions // 2
        q_count2 = num_questions - q_count1
        
        generation_tasks.append({
            "context": part1, 
            "count": q_count1, 
            "desc": f"1-{q_count1} (Primera mitad del contexto)"
        })
        generation_tasks.append({
            "context": part2, 
            "count": q_count2, 
            "desc": f"{q_count1+1}-{num_questions} (Segunda mitad del contexto)"
        })
        yield {"type": "log", "msg": f"[ESTRATEGIA] Segmentacion activada: 2 bloques de contexto para cobertura total."}
    else:
        # Standard single block
        clean_ctx = _clean_text(context_text) if context_text else ""
        generation_tasks.append({
            "context": clean_ctx, 
            "count": num_questions, 
            "desc": "completo"
        })

    all_raw_questions = []
    max_retries = 6 
    
    # === SESSION MEMORY ===
    # Tracks the best working model tier index (0=2.0, 2=Lite, 4=Exp)
    # If Block 1 fails on 2.0 and succeeds on Lite (attempt 2), Block 2 starts at attempt 2.
    current_tier_start = 0 

    # === EXECUTION LOOP ===
    for task_idx, task in enumerate(generation_tasks):
        if len(generation_tasks) > 1:
            yield {"type": "log", "msg": f"\n[EXPERTO] Generando preguntas {task['desc']}..."}
            if current_tier_start > 0:
                 model_name = "gemini-2.0-flash-lite" if current_tier_start == 2 else "gemini-exp-1206"
                 yield {"type": "log", "msg": f"[OPTIMIZACION] Saltando modelos agotados. Iniciando con {model_name} (Tier {current_tier_start})..."}
        else:
            yield {"type": "log", "msg": f"\n[GENERANDO] Peticion unica de {num_questions} preguntas..."}
        
        # Build Prompt for this block
        current_prompt = get_base_prompt(task["count"], difficulty)
        
        # Inject Topic (Critical for context)
        if topic:
             current_prompt += f"\n\nCONTEXTO TEMATICO: {topic}"

        if task["context"]:
            # Limit context length per block if needed, though splitting helps handling limits naturally
            # Using 25000 chars roughly per block if full doc is huge
            block_ctx = task["context"][:30000] 
            # Use generic header to avoid confusing the model into writing "Según el fragmento..."
            current_prompt += f"\n\nDOCUMENTO NORMATIVO DE REFERENCIA:\n{block_ctx}"
            
            # STRICT CONTEXT INSTRUCTION (REFINED)
            current_prompt += "\n\n⚠️ INSTRUCCION CRITICA DE JEFE DE TRIBUNAL:"
            current_prompt += "\n1. Genera las preguntas BASANDOTE UNICAMENTE EN EL TEXTO DE ARRIBA."
            current_prompt += "\n2. IMPORTANTE: NO menciones 'el texto', 'el fragmento', 'la fuente' o 'el documento' en los enunciados. Formula la pregunta como si fuera un examen oficial (ej: 'Segun la Ley 39/2015...')."
            current_prompt += "\n3. Si el texto es un fragmento, ignora el corte y pregunta solo sobre lo visible, PERO SIN MENCIONAR QUE ES UN FRAGMENTO."
            
            yield {"type": "log", "msg": f"[DEBUG] Bloque {task_idx+1}: Contexto de {len(block_ctx)} caracteres inyectado."}
        
        # Retry Loop for this Block
        block_success = False
        
        # Start attempts from the memorized tier
        for attempt in range(current_tier_start, max_retries):
            try:
                active_client, project_label = _get_client()
                
                # === MODEL FALLBACK STRATEGY ===
                # Intentos 0-1: gemini-2.0-flash
                # Intentos 2-3: gemini-2.0-flash-lite (Quota bucket distinta)
                # Intentos 4+:  gemini-exp-1206 (Experimental/Thinking - Respaldo final)
                current_model = "gemini-2.0-flash"
                if attempt >= 2:
                    current_model = "gemini-2.0-flash-lite"
                if attempt >= 4:
                    current_model = "gemini-exp-1206"

                if attempt == 2 and current_model == "gemini-2.0-flash-lite":
                     yield {"type": "log", "msg": f"[ALERTA] Cuota de Gemini 2.0 Flash agotada. Probando con Gemini 2.0 Flash-Lite..."}
                elif attempt == 4:
                     yield {"type": "log", "msg": f"[ALERTA] Cuota de Flash-Lite agotada. Probando con Gemini Exp 1206..."}
                
                yield {"type": "log", "msg": f"[{project_label}] Llamando a {current_model} (intento {attempt+1}/{max_retries})..."}
                _safe_print(f"[{project_label}] Request start {current_model}...")
                
                response = await active_client.aio.models.generate_content(
                    model=current_model,
                    contents=current_prompt,
                    config=generation_config,
                )
                
                raw_text = response.text
                yield {"type": "log", "msg": f"[{project_label}] Respuesta recibida. Parseando JSON..."}
                
                # Robust JSON parsing
                current_questions = []
                try:
                    current_questions = json.loads(raw_text)
                    yield {"type": "log", "msg": f"[{project_label}] JSON OK: {len(current_questions)} preguntas."}
                    all_raw_questions.extend(current_questions)
                    
                    # === UPDATE SESSION MEMORY ===
                    # If we succeeded at a higher tier (e.g. attempt 2 or 3 -> tier 2), remember it for next block.
                    # Round down to even number (0, 2, 4) to ensure we start at the beginning of the tier.
                    new_tier = (attempt // 2) * 2
                    if new_tier > current_tier_start:
                        current_tier_start = new_tier
                        # Only log if it's the first time we realize this
                        # yield {"type": "log", "msg": f"[MEMORIA] Tier {current_tier_start} guardado para siguientes bloques."}
                    
                    block_success = True
                    break # Block Success!
                except json.JSONDecodeError:
                    yield {"type": "log", "msg": f"[{project_label}] JSON directo fallo. Limpiando..."}
                    cleaned_json = _clean_json_response(raw_text)
                    try:
                        current_questions = json.loads(cleaned_json)
                        yield {"type": "log", "msg": f"[{project_label}] JSON limpiado: {len(current_questions)} preguntas recuperadas."}
                        all_raw_questions.extend(current_questions)
                        
                        # === UPDATE SESSION MEMORY ===
                        new_tier = (attempt // 2) * 2
                        if new_tier > current_tier_start:
                            current_tier_start = new_tier

                        block_success = True
                        break # Block Success!
                    except json.JSONDecodeError as je:
                        yield {"type": "log", "msg": f"[{project_label}] JSON irrecuperable: {je}. Raw: {raw_text[:150]}..."}
            
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
                if attempt < max_retries - 1:
                     await asyncio.sleep(5)
                     continue
                        
            except Exception as e:
                error_str = str(e)
                yield {"type": "log", "msg": f"[ERROR] {type(e).__name__}: {error_str[:200]}"}
                
                if attempt < max_retries - 1:
                    wait_time = 5 * (2 ** min(attempt, 3))
                    yield {"type": "log", "msg": f"[DEBUG] Reintentando en {wait_time}s..."}
                    await asyncio.sleep(wait_time)
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
                q["id"] = i + 1 # Renumber sequentially
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
