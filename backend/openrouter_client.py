import os
import json
import asyncio
import re
import random
import aiohttp
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_NAME = "openai/gpt-oss-120b:free"

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
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    text = text.strip()
    b_start = text.find('[')
    if b_start != -1: text = text[b_start:]
    b_end = text.rfind(']')
    if b_end != -1: text = text[:b_end+1]
    return text

def validate_and_fix_question(question):
    try:
        explanation = question.get("explanation", "").strip()
        options = question.get("options", [])
        correct_idx = question.get("correct_index", 0)
        
        detected_letter = None
        m = re.search(r"respuesta\s+correcta\s+(?:es|sea)\s+(?:la\s+)?([A-D])\b", explanation, re.IGNORECASE)
        if m: detected_letter = m.group(1).upper()
        if not detected_letter:
            m2 = re.search(r"correcta:\s*\[?([A-D])\]?", explanation, re.IGNORECASE)
            if m2: detected_letter = m2.group(1).upper()
            
        if detected_letter:
            expected_index = ord(detected_letter) - ord('A')
            if 0 <= expected_index < len(options) and correct_idx != expected_index:
                question["correct_index"] = expected_index
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

def get_base_prompt(num_questions, difficulty, has_context=False):
    ctx_rule = "Basa las preguntas en el texto proporcionado." if has_context else "Temas: TAI C1 (Leyes 39/40, Informática, Redes)."
    
    return f"""Genera EXACTAMENTE {num_questions} preguntas tipo test de nivel {difficulty.upper()}.
{ctx_rule}

REGLAS:
- 4 opciones (A, B, C, D).
- Solo 1 correcta.
- Prohibido "Todas las anteriores".
- La explicación empieza con: "La respuesta correcta es [Letra] porque..."

JSON format:
[
  {{
    "id": 1,
    "question": "...",
    "options": ["A", "B", "C", "D"],
    "correct_index": 0,
    "explanation": "La respuesta correcta es A porque..."
  }}
]"""

async def generate_exam_streaming(num_questions: int, context_text: str = None, topic: str = None, difficulty: str = "Intermedio", mode: str = "manual"):
    if not OPENROUTER_API_KEY:
        yield {"type": "log", "msg": "[ERROR] OPENROUTER_API_KEY no configurada en .env"}
        return

    yield {"type": "log", "msg": f"[INICIO] {num_questions} preguntas | Motor: OpenRouter ({MODEL_NAME})"}
    
    clean_ctx = _clean_text(context_text) if context_text else ""
    current_prompt = get_base_prompt(num_questions, difficulty, has_context=bool(clean_ctx))
    if topic: current_prompt += f"\n\nTEMA: {topic}"
    if clean_ctx: current_prompt += f"\n\nCONTEXTO:\n{clean_ctx[:15000]}"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://github.com/Raulcarco98/simulador-tai-2026", # Requerido por OpenRouter
        "X-Title": "Simulador TAI 2026",
        "Content-Type": "application/json"
    }

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "Eres un Examinador TAI. Responde SOLO con el JSON array."},
            {"role": "user", "content": current_prompt}
        ],
        "temperature": 0.5,
        "max_tokens": 4000
    }

    all_raw_questions = []
    
    try:
        yield {"type": "log", "msg": "[LOG] Llamando a OpenRouter API..."}
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=300)) as response:
                if response.status != 200:
                    text = await response.text()
                    raise Exception(f"HTTP {response.status}: {text}")
                result = await response.json()
        
        raw_text = result['choices'][0]['message']['content']
        yield {"type": "log", "msg": "[OR] Respuesta recibida. Parseando..."}
        
        try:
            current_questions = json.loads(raw_text)
        except json.JSONDecodeError:
            current_questions = json.loads(_clean_json_response(raw_text))
        
        if isinstance(current_questions, list):
            validated = []
            for i, q in enumerate(current_questions):
                if isinstance(q, dict):
                    q["id"] = i + 1
                    validated.append(shuffle_options(validate_and_fix_question(q)))
            yield {"type": "log", "msg": f"\n[COMPLETO] {len(validated)} preguntas generadas."}
            yield validated
    except Exception as e:
        yield {"type": "log", "msg": f"[ERROR] OpenRouter: {str(e)[:150]}"}
