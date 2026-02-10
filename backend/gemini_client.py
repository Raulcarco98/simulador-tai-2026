import os
import json
import asyncio
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types, errors as genai_errors

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
API_KEY_2 = os.getenv("GEMINI_API_KEY_2")
API_KEYS = [k for k in [API_KEY, API_KEY_2] if k]
current_key_index = 0

# Create clients for each key
clients = []
for key in API_KEYS:
    clients.append(genai.Client(api_key=key))

def _get_client():
    """Returns the current active client."""
    global current_key_index
    if not clients:
        return None
    return clients[current_key_index % len(clients)]

def _rotate_key():
    """Switches to the next API key."""
    global current_key_index
    if len(clients) > 1:
        current_key_index = (current_key_index + 1) % len(clients)
        return True
    return False

# Generation config
generation_config = types.GenerateContentConfig(
    temperature=0.8,
    top_p=0.95,
    top_k=40,
    max_output_tokens=4096,
    response_mime_type="application/json",
)

MODEL_NAME = "gemini-2.0-flash"


# === UTILIDADES ===
def _clean_text(text):
    """Colapsa saltos de línea y espacios múltiples."""
    if not text:
        return ""
    text = re.sub(r'\n+', '\n', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _clean_json_response(raw_text):
    """
    Limpia la respuesta de la IA antes de parsear JSON.
    Elimina markdown code fences, texto extra, etc.
    """
    if not raw_text:
        return "[]"
    
    text = raw_text.strip()
    
    # Remove invisible control characters (BOM, zero-width spaces, etc.)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufeff\u200b\u200c\u200d\u2060]', '', text)
    
    # Remove markdown code fences: ```json ... ``` or ``` ... ```
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    text = text.strip()
    
    # If it doesn't start with '[', try to find the array
    if not text.startswith('['):
        bracket_start = text.find('[')
        if bracket_start != -1:
            text = text[bracket_start:]
    
    # If it doesn't end with ']', try to find the last ']'
    if not text.endswith(']'):
        bracket_end = text.rfind(']')
        if bracket_end != -1:
            text = text[:bracket_end + 1]
    
    return text


def _segment_text(text, num_segments):
    """
    Divide el texto en N segmentos proporcionales distribuidos uniformemente.
    Cada segmento cubre una franja distinta del documento para garantizar cobertura total.
    """
    if not text or num_segments <= 0:
        return [text] if text else [""]
    
    cleaned = _clean_text(text)
    total_len = len(cleaned)
    
    if total_len < 200 or num_segments == 1:
        return [cleaned]
    
    segment_size = total_len // num_segments
    overlap = min(100, segment_size // 4)
    
    segments = []
    for i in range(num_segments):
        start = max(0, i * segment_size - overlap)
        end = min(total_len, (i + 1) * segment_size + overlap)
        segment = cleaned[start:end].strip()
        if segment:
            segments.append(segment)
    
    return segments if segments else [cleaned]


def validate_and_fix_question(question):
    """
    Checks if the explanation states the correct answer letter via multiple patterns
    and safeguards that 'correct_index' matches it.
    """
    try:
        explanation = question.get("explanation", "")
        detected_letter = None
        
        match = re.search(r"respuesta\s+correcta\s+(?:es|sea)\s+(?:la\s+)?([A-D])\b", explanation, re.IGNORECASE)
        if match:
            detected_letter = match.group(1).upper()
        
        if not detected_letter:
            match2 = re.search(r"[Cc]orrecta:\s*\[?([A-D])\]?", explanation)
            if match2:
                detected_letter = match2.group(1).upper()
        
        if not detected_letter:
            match3 = re.search(r"^\s*[Ee]s\s+la\s+([A-D])\b", explanation)
            if match3:
                detected_letter = match3.group(1).upper()
        
        if detected_letter:
            expected_index = ord(detected_letter) - ord('A')
            if 0 <= expected_index <= 3:
                current_index = question.get("correct_index")
                if current_index != expected_index:
                    print(f"FIX APPLIED for Q{question.get('id')}: Index {current_index} -> {expected_index} (explanation says '{detected_letter}')")
                    question["correct_index"] = expected_index
    except Exception as e:
        print(f"Validation Error: {e}")
    
    return question


def get_base_prompt(num_questions, difficulty):
    if difficulty.upper() == "EXPERTO":
        return f"""
    Actúa como examinador TAI C1. Genera {num_questions} preguntas avanzadas.
    REQUISITOS:
    - Temas: Casos prácticos, sintaxis y excepciones.
    - Estructura: 25% preguntas negativas (¿Cuál es FALSA?).
    - Distractores: Cambia cifras (10→15 días), confunde leyes (39↔40), usa siglas parecidas (ENS↔ENI).
    - Cobertura: Tu objetivo es evaluar el conocimiento de TODO el temario. Se te proporcionan fragmentos de diferentes secciones; genera una pregunta específica para CADA fragmento sin omitir los finales.
    - Concisión: Explicación de 1 línea (máx 15 palabras).
    - Formato: Responde ÚNICAMENTE el array JSON, sin texto previo ni posterior.

    PROCESO INTERNO (para cada pregunta):
    PASO 1: Determina la respuesta correcta y redacta la explicación breve.
    PASO 2: Basándote ÚNICAMENTE en el Paso 1, asigna correct_index (0=A, 1=B, 2=C, 3=D).

    REGLA DE ORO: Si en la explicación mencionas una letra (ej: "Es la B"), correct_index DEBE ser obligatoriamente el índice de esa letra.
    En preguntas negativas, correct_index = índice de la opción FALSA.

    BLINDAJE: Para cada pregunta, verifica internamente: ¿La explanation confirma que la opción [X] es la correcta? Entonces correct_index debe ser imperativamente el valor numérico de [X].

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
    Actúa como un Preparador de Oposiciones. Genera un examen tipo test de {num_questions} preguntas.
    
    NIVEL: {difficulty.upper()} (Básico/Intermedio)
    ESTILO: Preguntas claras. Explicación didáctica.
    REALISMO: Usa "Todas/Ninguna es correcta" en 20% de preguntas.
    COBERTURA: Tu objetivo es evaluar el conocimiento de TODO el temario proporcionado. Genera una pregunta específica para cada fragmento sin omitir los finales.
    
    CRITÉRIO JSON:
    - "explanation" empieza con "La respuesta correcta es [Letra]...".
    
    PROCESO INTERNO (para cada pregunta):
    PASO 1: Determina la respuesta correcta y redacta la explicación comenzando con "La respuesta correcta es [Letra] porque...".
    PASO 2: Basándote ÚNICAMENTE en el Paso 1, asigna correct_index (0=A, 1=B, 2=C, 3=D).

    REGLA DE ORO: Si en la explicación escribes "La respuesta correcta es B", correct_index DEBE ser 1. Siempre.
    BLINDAJE: Para cada pregunta, verifica: ¿La explanation confirma que la opción [X] es la correcta? Entonces correct_index = valor numérico de [X].
    
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


# === CORE API CALL (google-genai + JSON cleaning + Exponential Backoff) ===
async def _generate_chunk(chunk_prompt, context_text, context_limit, log_fn=None):
    """Single API call with JSON robustness, key rotation, and exponential backoff."""
    active_client = _get_client()
    if not active_client:
        return []
    
    def log(msg):
        print(msg)
        if log_fn:
            log_fn(msg)
    
    max_retries = 5
    base_delay = 10

    # Build prompt once
    final_prompt = chunk_prompt
    if context_text:
        cleaned = _clean_text(context_text[:context_limit])
        final_prompt += f"\n\nCONTENIDO PROPORCIONADO:\n{cleaned}"

    for attempt in range(max_retries):
        try:
            active_client = _get_client()
            log(f"Llamando a {MODEL_NAME} (intento {attempt+1}/{max_retries}, key {current_key_index+1}/{len(clients)})...")
            response = await active_client.aio.models.generate_content(
                model=MODEL_NAME,
                contents=final_prompt,
                config=generation_config,
            )
            
            raw_text = response.text
            log("Respuesta recibida. Parseando JSON...")
            
            # Robust JSON parsing with cleaning
            try:
                result = json.loads(raw_text)
                log(f"JSON válido: {len(result)} preguntas parseadas.")
                return result
            except json.JSONDecodeError:
                log("JSON directo falló. Limpiando respuesta...")
                cleaned_json = _clean_json_response(raw_text)
                try:
                    result = json.loads(cleaned_json)
                    log(f"JSON limpiado: {len(result)} preguntas recuperadas.")
                    return result
                except json.JSONDecodeError as je:
                    log(f"JSON irrecuperable: {je}. Raw: {raw_text[:150]}...")
                    return []
        
        except genai_errors.ClientError as e:
            error_str = str(e)
            is_rate_limit = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str
            
            if is_rate_limit:
                # Try rotating key first
                if _rotate_key():
                    log(f"⚠️ Rate limit. Rotando a API Key {current_key_index+1}...")
                    await asyncio.sleep(2)
                    continue
                elif attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt)
                    log(f"⚠️ Rate limit en todas las keys. Esperando {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
            
            log(f"❌ ClientError: {error_str[:200]}")
            return []
                    
        except Exception as e:
            error_str = str(e)
            log(f"❌ Error inesperado: {type(e).__name__}: {error_str[:200]}")
            
            if attempt < max_retries - 1:
                wait_time = base_delay * (2 ** attempt)
                log(f"   Reintentando en {wait_time}s...")
                await asyncio.sleep(wait_time)
                continue
            return []

    return []


async def generate_exam_streaming(num_questions: int, context_text: str = None, topic: str = None, difficulty: str = "Intermedio"):
    """
    Async generator that yields:
    - dict {"type": "log", "msg": "..."} for terminal logs
    - list [...questions...] for question batches
    """
    logs_queue = []
    
    def collect_log(msg):
        logs_queue.append(msg)
    
    if not clients:
        yield {"type": "log", "msg": "❌ No hay API Keys configuradas. Revisa .env"}
        yield [{"id": 1, "question": "Error: API Key no configurada", "options": ["A","B","C","D"], "correct_index": 0, "explanation": "Configura .env"}]
        return

    yield {"type": "log", "msg": f"🚀 Iniciando generación: {num_questions} preguntas | Dificultad: {difficulty} | Keys: {len(clients)}"}

    if topic and not context_text:
        context_text = f"Tema solicitado: {topic}"
        yield {"type": "log", "msg": f"📌 Tema: {topic}"}

    BATCH_SIZE = 5
    generated_count = 0
    batch_number = 0
    
    # Pre-segment the full text into proportional chunks
    segments = _segment_text(context_text, num_questions) if context_text else []
    if segments:
        yield {"type": "log", "msg": f"📄 Documento segmentado en {len(segments)} fragmentos"}

    while generated_count < num_questions:
        batch_count = min(BATCH_SIZE, num_questions - generated_count)
        prompt = get_base_prompt(batch_count, difficulty)
        
        # Select the segments for this batch
        if segments:
            batch_segments = segments[generated_count:generated_count + batch_count]
            batch_context = "\n---\n".join(batch_segments)
        else:
            batch_context = None
        
        batch_number += 1
        yield {"type": "log", "msg": f"\n📦 Batch {batch_number}: generando {batch_count} preguntas..."}
        
        logs_queue.clear()
        raw_questions = await _generate_chunk(prompt, batch_context, 25000, log_fn=collect_log)
        
        # Flush collected logs
        for log_msg in logs_queue:
            yield {"type": "log", "msg": f"   {log_msg}"}
        
        if isinstance(raw_questions, list) and raw_questions:
            validated = []
            for i, q in enumerate(raw_questions):
                if q:
                    q["id"] = generated_count + i + 1
                    validated.append(validate_and_fix_question(q))
            
            generated_count += len(validated)
            yield {"type": "log", "msg": f"✅ Batch {batch_number} OK: {len(validated)} preguntas ({generated_count}/{num_questions})"}
            yield validated
        else:
            yield {"type": "log", "msg": f"❌ Batch {batch_number} FALLIDO. Deteniendo generación."}
            break
        
        # Cooldown between batches
        if generated_count < num_questions:
            yield {"type": "log", "msg": "⏳ Cooldown 3s entre batches..."}
            await asyncio.sleep(3)
    
    yield {"type": "log", "msg": f"\n🏁 Generación completa: {generated_count} preguntas generadas."}
