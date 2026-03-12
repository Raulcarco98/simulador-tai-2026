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
MODEL_NAME = "llama-3.3-70b-versatile"

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


def validate_and_fix_question(question):
    """
    BLINDAJE STRICTO: La explicacion es la fuente de la verdad.
    """
    try:
        explanation = question.get("explanation", "").strip()
        options = question.get("options", [])
        correct_idx = question.get("correct_index", 0)
        
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
                    _safe_print(f"[BLINDAJE] Q{question.get('id')}: CORRECCION APLICADA. Indice {correct_idx} ({chr(65+correct_idx)}) -> {expected_index} ({detected_letter}) basado en explicacion.")
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
                (r"(soluci[oÃ³]n:\s*){}\b".format(old_letter), r"\g<1>" + new_letter),
                (r"^{}([.\)])".format(old_letter), new_letter + r"\1")
            ]
            for pat, repl in patterns:
                explanation = re.sub(pat, repl, explanation, flags=re.IGNORECASE)
            question["explanation"] = explanation
            
    except Exception:
        pass
    return question


def get_base_prompt(num_questions, difficulty, has_context=False):
    # === REGLAS UNIVERSALES DE BLINDAJE (OPTIMIZADO) ===
    # 1. UNICIDAD: 1 Verdadera, 3 Falsas.
    # 2. EXCLUSION: Prohibido "Todas/Ninguna", "A y B".
    # 3. OBJETIVIDAD: Falsas por dato, no interpretacion.
    
    # Requisitos dinámicos según el contexto
    requisitos_contexto = ""
    if has_context:
        requisitos_contexto = "- Cíñete ESTRICTAMENTE al texto proporcionado."
    else:
        requisitos_contexto = "- Temas: Administrativo (Leyes 39/40), plazos y datos EXACTOS."

    if difficulty.upper() == "EXPERTO":
        return f"""
    Rol: Examinador TAI C1. Genera {num_questions} preguntas.
    
    BLINDAJE RESPUESTA UNICA:
    - REGLA: 1 Verdadera, 3 Falsas indiscutibles.
    - PROHIBIDO: Compuestas ("Todas", "Ninguna", "A y B").
    
    DISTRACTORES (Falsas):
    - Altera 1 dato objetivo (plazo, organo, condicion).
    - No inventes normativa ni conceptos. Modifica los reales del texto.
    
    REQUISITOS:
    - Temas: Practicos, sintaxis, excepciones.
    - 25% Negativas.
    {requisitos_contexto}
    
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
    
    {requisitos_contexto.replace("- Temas:", "REQUISITO:").replace("- ", "")}
    
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

async def generate_exam_streaming(num_questions: int, context_text: str = None, topic: str = None, difficulty: str = "Intermedio", mode: str = "manual"):
    if not GROQ_API_KEY:
        yield {"type": "log", "msg": "[ERROR] GROQ_API_KEY no encontrada en el entorno. Revisa el archivo .env"}
        return

    yield {"type": "log", "msg": f"[INICIO] {num_questions} preguntas | Dificultad: {difficulty} | Motor: Groq ({MODEL_NAME})"}
    
    clean_ctx = _clean_text(context_text) if context_text else ""
    current_prompt = get_base_prompt(num_questions, difficulty, has_context=bool(clean_ctx))
    if topic:
        current_prompt += f"\n\nCONTEXTO TEMATICO: {topic}"
        
    if clean_ctx:
        block_ctx = clean_ctx[:30000]
        current_prompt += f"\n\nDOCUMENTO NORMATIVO DE REFERENCIA:\n{block_ctx}"
        current_prompt += "\n\n⚠️ INSTRUCCION CRITICA DE JEFE DE TRIBUNAL:"
        if mode == "simulacro_3":
             current_prompt += "\n0. ESTÁS ANTE UN SIMULACRO MULTITEMA (3 Bloques). Debes generar preguntas equilibradas (aprox. una cantidad igual por cada bloque temático)."
        
        current_prompt += """
1. ESTRICTA ADHERENCIA: Solo puedes preguntar sobre la informacion PRESENTE en el documento.
2. CERO INVENTIVA NORMATIVA: Si el documento enumera 3 requisitos, NO puedes inventar un 4o como distractor. Usa los datos del texto modificandolos sutilmente.
3. CERO LITERALIDAD CIEGA: No uses frases de relleno como "segun el documento". Ve al grano.
4. OBLIGATORIO: Genera exactamente el numero de preguntas solicitado.
"""
    
    current_prompt += "\n\nResponde solo con el JSON minificado. No incluyas nada más."

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "Eres una API que solo responde en JSON. No añadas texto fuera del JSON."},
            {"role": "user", "content": current_prompt}
        ],
        "temperature": 0.5,
        "max_tokens": 4000,
        "stream": False,
        "response_format": {"type": "json_object"}
    }
    
    # We remove response_format if problems arise, but it's officially supported for JSON mode in Llama 3
    # Note: Llama 3 on Groq WITH JSON mode requires the word "JSON" in the system prompt (which we have).
    # Since we want an Array of Objects, and response_format={"type": "json_object"} sometimes forces an outer object,
    # let's be safe and let the model return the raw array and use our _clean_json_response.
    del payload["response_format"]

    all_raw_questions = []
    max_retries = 3

    for attempt in range(max_retries):
        try:
            yield {"type": "log", "msg": f"[LOG] Intento {attempt+1}/{max_retries}: Llamando a Groq API..."}
            
            async with aiohttp.ClientSession() as session:
                async with session.post(GROQ_API_URL, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"Groq API HTTP {response.status}: {error_text}")
                    
                    result = await response.json()
                    raw_text = result['choices'][0]['message']['content']

            yield {"type": "log", "msg": f"[Groq] Respuesta recibida. Parseando..."}
            
            try:
                current_questions = json.loads(raw_text)
            except json.JSONDecodeError:
                cleaned_json = _clean_json_response(raw_text)
                current_questions = json.loads(cleaned_json)
            
            if current_questions and isinstance(current_questions, list):
                all_raw_questions = current_questions
                break
            else:
                raise ValueError("Respuesta no es una lista válida")

        except Exception as e:
            yield {"type": "log", "msg": f"[ERROR] {type(e).__name__}: {str(e)[:100]}"}
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
            continue

    if all_raw_questions:
        yield {"type": "log", "msg": f"\n[BLINDAJE] Validando {len(all_raw_questions)} preguntas..."}
        validated = []
        for i, q in enumerate(all_raw_questions):
            if q and isinstance(q, dict):
                q["id"] = i + 1
                fixed_q = validate_and_fix_question(q)
                shuffled_q = shuffle_options(fixed_q)
                validated.append(shuffled_q)
        
        yield {"type": "log", "msg": f"\n[COMPLETO] {len(validated)} preguntas listas."}
        yield validated
    else:
        yield {"type": "log", "msg": "[ERROR] No se pudo generar el examen con Groq API."}
