"""
4_llm.py — анализ описаний вакансий через LLM (Ollama)
Прогоняет ВСЕ вакансии с описанием, продолжает с чекпоинта.

Запуск: python 4_llm.py
"""

import json
import os
import re
import time

import requests

INPUT_JSON  = "data/cleaned.json"
OUTPUT_JSON = "data/llm_results.json"
CHECKPOINT  = "data/llm_checkpoint.json"

OLLAMA_URL  = "http://localhost:11434/api/generate"
MODEL       = "qwen2.5:3b"
MAX_DESC_LEN = 1200   # обрезаем длинные описания

# ── Промпт ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
Ты — аналитик рынка труда в сфере AI/ML в России.
Извлеки структурированную информацию из описания вакансии.
Отвечай ТОЛЬКО валидным JSON без markdown-блоков и пояснений.\
"""

USER_PROMPT = """\
Проанализируй вакансию:

НАЗВАНИЕ: {title}
УРОВЕНЬ: {level}
ГОРОД: {city}
ОПИСАНИЕ: {description}

Верни JSON строго в таком формате (без лишних полей):
{{
  "hard_skills": ["до 8 конкретных технологий/инструментов из описания"],
  "soft_skills": ["до 4 мягких навыков из описания"],
  "salary_mentioned": null,
  "remote_possible": false,
  "domain": "одно из: data_science | ml_engineer | ai_engineer | llm_genai | computer_vision | nlp | mlops | data_engineer | research | other",
  "perspective_score": 4,
  "key_requirement": "главное требование одной короткой фразой на русском"
}}

Правила:
- domain выбирай по основному направлению работы
- salary_mentioned: число в руб/мес если явно указана, иначе null
- remote_possible: true если есть слова "удалённо", "remote", "дистанционно"
- perspective_score: 1-5 (5 = очень востребовано в 2025-2026)
- Только валидный JSON, ничего кроме JSON\
"""


def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT):
        try:
            data = json.load(open(CHECKPOINT, encoding="utf-8"))
            return data
        except Exception:
            pass
    return {}


def save_checkpoint(results: dict):
    with open(CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def ask_ollama(prompt: str, retries: int = 2) -> str | None:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.05,   # почти детерминированно
            "num_predict": 400,
            "num_ctx": 4096,
        }
    }
    for attempt in range(retries):
        try:
            r = requests.post(OLLAMA_URL, json=payload, timeout=90)
            if r.status_code == 200:
                return r.json().get("response", "")
            print(f"  [HTTP {r.status_code}]")
        except requests.ConnectionError:
            print("  ✗ Ollama не запущен — запусти: ollama serve")
            return None
        except Exception as e:
            print(f"  Ошибка: {e}")
        time.sleep(1)
    return None


VALID_DOMAINS = {
    "data_science", "ml_engineer", "ai_engineer", "llm_genai",
    "computer_vision", "nlp", "mlops", "data_engineer", "research", "other"
}


def parse_response(text: str) -> dict | None:
    if not text:
        return None
    # Убираем markdown-блоки
    text = re.sub(r"```(?:json)?", "", text).strip()
    # Берём от первой { до последней }
    s = text.find("{")
    e = text.rfind("}")
    if s == -1 or e == -1:
        return None
    json_str = text[s:e+1]
    # Чиним trailing commas
    json_str = re.sub(r",\s*}", "}", json_str)
    json_str = re.sub(r",\s*]", "]", json_str)
    try:
        d = json.loads(json_str)
    except Exception:
        return None

    # Нормализация domain — если не из списка, ставим other
    dom = str(d.get("domain", "other")).lower().strip()
    # Обрабатываем составные домены типа "nlp | computer_vision"
    if "|" in dom:
        dom = dom.split("|")[0].strip()
    if dom not in VALID_DOMAINS:
        dom = "other"
    d["domain"] = dom

    # Нормализация salary_mentioned
    sal = d.get("salary_mentioned")
    if sal is not None:
        try:
            sal = int(float(str(sal).replace(" ", "").replace(",", ".")))
            if not (20_000 <= sal <= 2_000_000):
                sal = None
        except Exception:
            sal = None
    d["salary_mentioned"] = sal

    # Нормализация remote_possible
    d["remote_possible"] = bool(d.get("remote_possible", False))

    # Нормализация perspective_score
    try:
        sc = float(d.get("perspective_score", 3))
        d["perspective_score"] = max(1, min(5, round(sc)))
    except Exception:
        d["perspective_score"] = 3

    # Обязательные поля
    if "hard_skills" not in d:
        d["hard_skills"] = []
    if "soft_skills" not in d:
        d["soft_skills"] = []
    if "key_requirement" not in d:
        d["key_requirement"] = ""

    return d


def check_ollama() -> bool:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def analyze():
    print(f"Загружаем {INPUT_JSON}...")
    data = json.load(open(INPUT_JSON, encoding="utf-8"))

    # Берём ВСЕ вакансии с описанием, сортируем по id для воспроизводимости
    with_desc = sorted(
        [v for v in data if v.get("description")],
        key=lambda x: x["id"]
    )
    print(f"Всего с описанием: {len(with_desc)}")

    if not check_ollama():
        print("✗ Ollama не запущен! Запусти: ollama serve")
        return

    print(f"✓ Ollama запущен, модель: {MODEL}")

    results = load_checkpoint()
    already = len(results)
    print(f"✓ Чекпоинт: {already} уже обработано")

    todo = [v for v in with_desc if v["id"] not in results]
    print(f"  Осталось обработать: {len(todo)}")
    print(f"  Примерное время: ~{len(todo)*4/60:.0f} мин\n")

    consecutive_errors = 0

    for i, vac in enumerate(todo):
        vid = vac["id"]
        desc = vac.get("description", "")[:MAX_DESC_LEN]

        prompt = SYSTEM_PROMPT + "\n\n" + USER_PROMPT.format(
            title=vac.get("title", ""),
            level=vac.get("level", ""),
            city=vac.get("city", ""),
            description=desc,
        )

        response = ask_ollama(prompt)
        parsed   = parse_response(response)

        if parsed:
            results[vid] = {
                "id":       vid,
                "title":    vac.get("title", ""),
                "level":    vac.get("level", ""),
                "city":     vac.get("city", ""),
                "category": vac.get("category", ""),
                **parsed,
            }
            consecutive_errors = 0
        else:
            consecutive_errors += 1
            print(f"  [{i+1}] ✗ не распарсился {vid[:8]}... | ответ: {repr((response or '')[:80])}")
            if consecutive_errors >= 8:
                print("  8 ошибок подряд — сохраняем и выходим")
                break

        # Сохраняем каждые 10
        if (i + 1) % 10 == 0:
            save_checkpoint(results)

        # Прогресс каждые 50
        if (i + 1) % 50 == 0:
            done_total = already + i + 1
            pct = (i + 1) / len(todo) * 100
            sal_count = sum(1 for r in results.values() if r.get("salary_mentioned"))
            print(f"  [{i+1}/{len(todo)} {pct:.0f}%] "
                  f"всего: {len(results)} | с зарплатой: {sal_count}")

        time.sleep(0.1)

    save_checkpoint(results)

    # ── Финальный файл ────────────────────────────────────────────────────────
    final = list(results.values())
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"✓ Готово: {len(final)} вакансий → {OUTPUT_JSON}")

    # Статистика
    from collections import Counter
    print(f"\nДомены:")
    for d, cnt in Counter(r.get("domain") for r in final).most_common():
        print(f"  {d}: {cnt}")

    sal_list = [r["salary_mentioned"] for r in final if r.get("salary_mentioned")]
    print(f"\nЗарплата (из LLM): {len(sal_list)} вакансий")
    if sal_list:
        print(f"  Медиана: {sorted(sal_list)[len(sal_list)//2]:,} руб")
        by_level = {}
        for r in final:
            if r.get("salary_mentioned"):
                by_level.setdefault(r["level"], []).append(r["salary_mentioned"])
        for lvl, sals in sorted(by_level.items()):
            med = sorted(sals)[len(sals)//2]
            print(f"  {lvl}: {med:,} руб (n={len(sals)})")

    remote = sum(1 for r in final if r.get("remote_possible"))
    print(f"\nУдалёнка: {remote} ({remote/len(final)*100:.0f}%)")

    scores = [r["perspective_score"] for r in final
              if isinstance(r.get("perspective_score"), (int, float))]
    if scores:
        print(f"Средний perspective_score: {sum(scores)/len(scores):.2f}")
        by_lvl = {}
        for r in final:
            s = r.get("perspective_score")
            if isinstance(s, (int, float)):
                by_lvl.setdefault(r["level"], []).append(s)
        for lvl, sc in sorted(by_lvl.items()):
            print(f"  {lvl}: {sum(sc)/len(sc):.2f}")

    print(f"\nСледующий шаг: python 5_export.py")


if __name__ == "__main__":
    analyze()
