"""
4_llm.py — анализ описаний вакансий через LLM
Использует Ollama (локально) или OpenAI-совместимый API.

Установка Ollama: https://ollama.com/download
Модель: ollama pull llama3.2:3b   (лёгкая, ~2GB)
        ollama pull mistral        (лучше качество, ~4GB)
"""

import json
import os
import re
import time
import random
from pathlib import Path

import requests

INPUT_JSON   = "data/cleaned.json"
OUTPUT_JSON  = "data/llm_results.json"
CHECKPOINT   = "data/llm_checkpoint.json"

# ── Конфиг LLM ────────────────────────────────────────────────────────────────
OLLAMA_URL   = "http://localhost:11434/api/generate"
MODEL        = "qwen2.5:3b"      # меняй на mistral / deepseek-r1 / qwen2.5 если есть
BATCH_SIZE   = 500                 # сколько вакансий прогоняем через LLM
MAX_DESC_LEN = 1500                # обрезаем длинные описания

SYSTEM_PROMPT = """Ты — аналитик рынка труда в сфере AI/ML.
Твоя задача — извлечь структурированную информацию из описания вакансии.
Отвечай ТОЛЬКО валидным JSON, без пояснений и markdown-блоков."""

USER_PROMPT_TEMPLATE = """Проанализируй описание вакансии:

НАЗВАНИЕ: {title}
УРОВЕНЬ: {level}
ГОРОД: {city}
ОПИСАНИЕ: {description}

Верни JSON в точно таком формате:
{{
  "hard_skills": ["список технологий и инструментов (макс 10)"],
  "soft_skills": ["коммуникация", "командная работа" и т.д. (макс 5)"],
  "salary_mentioned": null или число (руб/мес, если указана),
  "remote_possible": true или false,
  "domain": "одно из: computer_vision | nlp | mlops | data_science | research | general_ml | other",
  "perspective_score": число от 1 до 5 (насколько востребована профессия в 2025-2026),
  "key_requirement": "главное требование одной фразой"
}}"""


def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT):
        try:
            return json.load(open(CHECKPOINT, encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_checkpoint(results: dict):
    with open(CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def ask_ollama(prompt: str, retries: int = 3) -> str | None:
    """Запрос к локальному Ollama."""
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 600,
        }
    }
    for attempt in range(retries):
        try:
            r = requests.post(OLLAMA_URL, json=payload, timeout=120)
            if r.status_code == 200:
                return r.json().get("response", "")
            print(f"  [HTTP {r.status_code}] попытка {attempt+1}")
        except requests.ConnectionError:
            print("  ✗ Ollama не запущен! Запусти: ollama serve")
            return None
        except Exception as e:
            print(f"  Ошибка: {e}")
        time.sleep(2)
    return None


def parse_llm_response(text: str) -> dict | None:
    if not text:
        return None
    # Удаляем возможные markdown-блоки
    text = re.sub(r"```(?:json)?", "", text).strip()
    # Ищем первую '{' и последнюю '}'
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        return None
    json_str = text[start:end+1]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # иногда модель ставит запятые в конце списков или другие мелкие ошибки
        # можно попробовать простую очистку: убрать запятые перед закрывающими скобками
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)
        try:
            return json.loads(json_str)
        except:
            return None


def check_ollama_running() -> bool:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def analyze():
    print(f"Загружаем {INPUT_JSON}...")
    data = json.load(open(INPUT_JSON, encoding="utf-8"))

    # Берём только те у кого есть описание
    with_desc = [v for v in data if v.get("description")]
    print(f"Вакансий с описанием: {len(with_desc)}")

    # Стратифицированная выборка: по ~равному числу с каждого уровня
    by_level = {"junior": [], "middle": [], "senior": []}
    for v in with_desc:
        by_level.get(v.get("level", "middle"), by_level["middle"]).append(v)

    per = BATCH_SIZE // 3
    sample = []
    for lvl, items in by_level.items():
        take = random.sample(items, min(per, len(items)))
        sample.extend(take)
        print(f"  {lvl}: {len(take)}")

    print(f"\nВсего в батче: {len(sample)}")

    # Проверяем что Ollama запущен
    if not check_ollama_running():
        print("\n✗ Ollama не запущен!")
        print("  1. Установи: https://ollama.com/download")
        print(f"  2. Скачай модель: ollama pull {MODEL}")
        print("  3. Запусти сервер: ollama serve")
        print("  4. Запусти скрипт снова")
        return

    print(f"✓ Ollama запущен, модель: {MODEL}")

    # Загружаем чекпоинт
    results = load_checkpoint()
    print(f"✓ Чекпоинт: {len(results)} уже обработано\n")

    errors = 0
    for i, vac in enumerate(sample):
        vid = vac["id"]
        if vid in results:
            continue

        desc = vac.get("description", "")[:MAX_DESC_LEN]
        prompt = USER_PROMPT_TEMPLATE.format(
            title=vac.get("title", ""),
            level=vac.get("level", ""),
            city=vac.get("city", ""),
            description=desc,
        )
        full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"

        response = ask_ollama(full_prompt)
        parsed   = parse_llm_response(response)

        if parsed:
            results[vid] = {
                "id":      vid,
                "title":   vac.get("title"),
                "level":   vac.get("level"),
                "city":    vac.get("city"),
                **parsed,
            }
            errors = 0
        else:
            errors += 1
            print(f"  [{i+1}] не распарсился ответ для {vid}")
            if errors >= 5:
                print("  5 ошибок подряд — что-то не так с LLM, останавливаемся")
                break

        if (i + 1) % 10 == 0:
            save_checkpoint(results)
            pct = (i + 1) / len(sample) * 100
            print(f"  [{i+1}/{len(sample)} {pct:.0f}%] обработано: {len(results)}")

        # Небольшая пауза чтобы не перегревать GPU
        time.sleep(0.3)

    save_checkpoint(results)

    # Сохраняем финальный результат
    final = list(results.values())
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"✓ LLM-анализ готов: {len(final)} вакансий → {OUTPUT_JSON}")

    # Быстрая сводка
    if final:
        from collections import Counter
        domains = Counter(r.get("domain") for r in final)
        print(f"\nДомены:")
        for d, cnt in domains.most_common():
            print(f"  {d}: {cnt}")

        remote = sum(1 for r in final if r.get("remote_possible"))
        print(f"\nС удалёнкой: {remote} ({remote/len(final)*100:.0f}%)")

        scores = [r.get("perspective_score") for r in final if isinstance(r.get("perspective_score"), (int, float))]
        if scores:
            by_level_score = {}
            for r in final:
                lvl = r.get("level", "?")
                s = r.get("perspective_score")
                if isinstance(s, (int, float)):
                    by_level_score.setdefault(lvl, []).append(s)
            print(f"\nСредний perspective_score по уровням:")
            for lvl, sc in sorted(by_level_score.items()):
                print(f"  {lvl}: {sum(sc)/len(sc):.2f}")

    print(f"\nСледующий шаг: python 5_report.py  (или открой llm_results.json)")


if __name__ == "__main__":
    analyze()
