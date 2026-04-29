import os
import json
import asyncio
import re
import random
import aiohttp
from dotenv import load_dotenv

load_dotenv()

LMSTUDIO_API_URL = "http://localhost:1234/v1/chat/completions"
# ID exacto proporcionado por el usuario desde LMStudio
MODEL_NAME = "qwen/qwen3-vl-4b" 

# === UTILIDADES ===
def _safe_print(msg):
    try:
        print(msg)
    except:
        pass

def _clean_text(text):
    if not text: return ""
    return re.sub(r'\s+', ' ', re.sub(r'\n+', '\n', text)).strip()

def _clean_json_response(raw_text):
    if not raw_text: return "[]"
    text = raw_text.strip()
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufeff\u200b\u200c\u200d\u2060]', '', text)
    # Remove thinking tags (Qwen3 tends to include <think>...</think>)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    text = text.strip()
    b_start = text.find('[')
    if b_start != -1: text = text[b_start:]
    b_end = text.rfind(']')
    if b_end != -1: text = text[:b_end+1]
    return text

def validate_and_fix_question(question):
    """Valida y corrige correct_index basándose en la explicación."""
    try:
        explanation = question.get("explanation", "").strip()
        options = question.get("options", [])
        correct_idx = question.get("correct_index", 0)
        
        # --- FIX: Forzar exactamente 4 opciones ---
        if len(options) > 4:
            _safe_print(f"[FIX] Q{question.get('id')}: {len(options)} opciones detectadas. Recortando a 4.")
            # Si correct_index apunta a una opción que se va a eliminar, moverla
            if correct_idx >= 4:
                # Mover la opción correcta a la posición 3 (D)
                correct_option = options[correct_idx]
                options[3] = correct_option
                correct_idx = 3
            options = options[:4]
            question["options"] = options
            question["correct_index"] = correct_idx
        
        detected_letter = None
        m = re.search(r"respuesta\s+correcta\s+(?:es|sea)\s+(?:la\s+)?([A-D])\b", explanation, re.IGNORECASE)
        if m: detected_letter = m.group(1).upper()
        if not detected_letter:
            m2 = re.search(r"correcta:\s*\[?([A-D])\]?", explanation, re.IGNORECASE)
            if m2: detected_letter = m2.group(1).upper()
            
        if detected_letter:
            expected_index = ord(detected_letter) - ord('A')
            if 0 <= expected_index < len(options) and correct_idx != expected_index:
                _safe_print(f"[FIX] Q{question.get('id')}: correct_index {correct_idx} -> {expected_index} (letra {detected_letter})")
                question["correct_index"] = expected_index
        
        # Validar rango final
        final_idx = question.get("correct_index", 0)
        if not isinstance(final_idx, int) or final_idx < 0 or final_idx >= len(options):
            question["correct_index"] = 0
    except: pass
    return question

def shuffle_options(question):
    try:
        options = question.get("options", [])
        current_idx = question.get("correct_index", 0)
        if not options or len(options) < 2: return question
        if current_idx < 0 or current_idx >= len(options): return question
            
        items = [{"text": opt, "is_correct": (i == current_idx)} for i, opt in enumerate(options)]
        random.shuffle(items)
        
        question["options"] = [item["text"] for item in items]
        question["correct_index"] = next(i for i, item in enumerate(items) if item["is_correct"])
        
        # Actualizar letra en explicación
        old_letter = chr(65 + current_idx)
        new_letter = chr(65 + question["correct_index"])
        if old_letter != new_letter:
            exp = question.get("explanation", "")
            exp = re.sub(
                r"(respuesta\s+correcta\s+(?:es|sea)\s+(?:la\s+)?)" + old_letter + r"\b",
                r"\g<1>" + new_letter, exp, flags=re.IGNORECASE
            )
            question["explanation"] = exp
    except: pass
    return question


def _deduplicate_questions(questions):
    """
    Elimina preguntas duplicadas o casi idénticas comparando enunciados.
    Usa similitud simple: si dos enunciados comparten >80% de palabras, es duplicada.
    """
    seen = []
    unique = []
    
    for q in questions:
        q_text = q.get("question", "").strip().lower()
        q_words = set(re.findall(r'\w+', q_text))
        
        is_dupe = False
        for seen_words in seen:
            if not q_words or not seen_words:
                continue
            overlap = len(q_words & seen_words) / max(len(q_words), len(seen_words))
            if overlap > 0.80:
                is_dupe = True
                _safe_print(f"[DEDUP] Pregunta duplicada eliminada: '{q_text[:60]}...'")
                break
        
        if not is_dupe:
            seen.append(q_words)
            unique.append(q)
    
    return unique


def get_base_prompt(num_questions, difficulty, has_context=False):
    """
    Prompt optimizado para modelos locales pequeños (Qwen 4B).
    Principios:
    - Instrucciones ultra-claras y repetitivas (los modelos pequeños necesitan redundancia).
    - Restricciones numéricas explícitas (EXACTAMENTE 4 opciones, EXACTAMENTE N preguntas).
    - Prohibiciones explícitas de errores comunes.
    - Sin razonamiento interno (no pedir self-check, gasta tokens).
    """
    ctx_rule = "Basa TODAS las preguntas en el DOCUMENTO proporcionado." if has_context else "Temas: Derecho Administrativo, Leyes 39/2015 y 40/2015, plazos, órganos."
    
    return f"""Genera EXACTAMENTE {num_questions} preguntas tipo test de oposición.
Nivel: {difficulty.upper()}.
{ctx_rule}

REGLAS OBLIGATORIAS:
- Cada pregunta tiene EXACTAMENTE 4 opciones: A, B, C, D. NI MÁS NI MENOS.
- Solo 1 opción es correcta. Las otras 3 son FALSAS.
- PROHIBIDO usar "Todas las anteriores", "Ninguna de las anteriores", "A y B son correctas".
- Cada pregunta debe ser DIFERENTE. NO repitas la misma pregunta.
- Las opciones falsas deben cambiar UN dato concreto (plazo, órgano, porcentaje).
- La explicación SIEMPRE empieza con: "La respuesta correcta es [A/B/C/D] porque..."

FORMATO JSON OBLIGATORIO (array de {num_questions} objetos):
[
  {{
    "id": 1,
    "question": "Enunciado de la pregunta",
    "options": ["Opción A.", "Opción B.", "Opción C.", "Opción D."],
    "correct_index": 0,
    "explanation": "La respuesta correcta es A porque..."
  }}
]

RECUERDA: {num_questions} preguntas, 4 opciones cada una, todas diferentes."""


async def generate_exam_streaming(num_questions: int, context_text: str = None, topic: str = None, difficulty: str = "Intermedio", mode: str = "manual"):
    yield {"type": "log", "msg": f"[INICIO] {num_questions} preguntas | Nivel: {difficulty} | Motor: LMStudio/Qwen"}
    
    clean_ctx = _clean_text(context_text) if context_text else ""
    current_prompt = get_base_prompt(num_questions, difficulty, has_context=bool(clean_ctx or topic))
    
    if topic:
        current_prompt += f"\n\nTEMA: {topic}"
        
    if clean_ctx:
        # Limitar contexto para no agotar la ventana del modelo local
        max_ctx = min(len(clean_ctx), 15000)
        current_prompt += f"\n\nDOCUMENTO:\n{clean_ctx[:max_ctx]}"
        yield {"type": "log", "msg": f"[DEBUG] Contexto: {max_ctx} caracteres inyectados."}

    # System prompt claro y restrictivo
    system_prompt = (
        "Eres un generador de exámenes tipo test. "
        "Responde ÚNICAMENTE con un JSON array válido. "
        "No incluyas texto antes ni después del JSON. "
        "No uses markdown. No uses ```."
    )

    # Calcular max_tokens dinámicamente:
    # ~350 tokens por pregunta (enunciado + 4 opciones + explicación)
    estimated_tokens = num_questions * 400
    max_tokens = max(estimated_tokens, 3000)
    # Tope de seguridad para modelos locales
    max_tokens = min(max_tokens, 8192)

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": current_prompt}
        ],
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": max_tokens,
        "stream": False
    }

    yield {"type": "log", "msg": f"[DEBUG] max_tokens: {max_tokens} | temperature: 0.7"}

    all_raw_questions = []
    
    for attempt in range(3):
        try:
            yield {"type": "log", "msg": f"[LOG] Intento {attempt+1}/3: Llamando a LMStudio API..."}
            async with aiohttp.ClientSession() as session:
                async with session.post(LMSTUDIO_API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=300)) as response:
                    if response.status != 200:
                        error_body = await response.text()
                        raise Exception(f"HTTP {response.status}: {error_body[:200]}")
                    result = await response.json()
            
            # Robust extraction 
            if isinstance(result, dict) and 'choices' in result:
                raw_text = result['choices'][0]['message']['content']
            elif isinstance(result, dict) and 'content' in result:
                raw_text = result['content']
            else:
                raw_text = str(result)
            
            # Log de tokens usados
            usage = result.get("usage", {})
            if usage:
                yield {"type": "log", "msg": f"[TOKENS] Prompt: {usage.get('prompt_tokens', '?')} | Respuesta: {usage.get('completion_tokens', '?')} | Total: {usage.get('total_tokens', '?')}"}
                
            yield {"type": "log", "msg": f"[LS] Respuesta recibida ({len(raw_text)} chars). Parseando..."}
            
            try:
                current_questions = json.loads(raw_text)
            except json.JSONDecodeError:
                cleaned = _clean_json_response(raw_text)
                yield {"type": "log", "msg": f"[LS] JSON directo falló. Limpiando ({len(cleaned)} chars)..."}
                current_questions = json.loads(cleaned)
            
            if isinstance(current_questions, list) and len(current_questions) > 0:
                all_raw_questions = current_questions
                yield {"type": "log", "msg": f"[LS] JSON parseado: {len(all_raw_questions)} preguntas brutas."}
                break
            else:
                yield {"type": "log", "msg": f"[WARN] Respuesta vacía o formato incorrecto. Reintentando..."}
                
        except json.JSONDecodeError as je:
            yield {"type": "log", "msg": f"[ERROR] JSON irrecuperable: {str(je)[:100]}"}
            yield {"type": "log", "msg": f"[DEBUG] Raw text (primeros 300 chars): {raw_text[:300]}"}
            await asyncio.sleep(2)
        except Exception as e:
            yield {"type": "log", "msg": f"[ERROR] Problema con LMStudio: {str(e)[:150]}"}
            await asyncio.sleep(2)

    if all_raw_questions:
        # === PIPELINE DE VALIDACIÓN ===
        
        # 1. Deduplicar preguntas repetidas
        before_dedup = len(all_raw_questions)
        all_raw_questions = _deduplicate_questions(all_raw_questions)
        after_dedup = len(all_raw_questions)
        if before_dedup != after_dedup:
            yield {"type": "log", "msg": f"[DEDUP] {before_dedup - after_dedup} preguntas duplicadas eliminadas."}
        
        # 2. Validar, corregir y barajar
        validated = []
        for i, q in enumerate(all_raw_questions):
            if isinstance(q, dict) and "question" in q and "options" in q:
                q["id"] = i + 1
                q = validate_and_fix_question(q)
                q = shuffle_options(q)
                validated.append(q)
            else:
                _safe_print(f"[SKIP] Pregunta {i+1} descartada: formato inválido.")
        
        yield {"type": "log", "msg": f"\n[COMPLETO] {len(validated)} preguntas generadas y validadas."}
        yield validated
    else:
        yield {"type": "log", "msg": "[ERROR] No se pudo generar con LMStudio. Revisa que el puerto 1234 esté activo y el modelo cargado."}
