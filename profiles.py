"""
6_profiles.py — генерация профилей идеального кандидата из реальных LLM-данных

Читает llm_checkpoint.json → агрегирует hard/soft skills по доменам →
прогоняет через Ollama → пишет data/profiles.json

Запуск: python 6_profiles.py
"""

import json
import re
import time
from collections import Counter
from pathlib import Path

import requests

CHECKPOINT  = "data/llm_checkpoint.json"
OUTPUT      = "data/profiles.json"
OLLAMA_URL  = "http://localhost:11434/api/generate"
MODEL       = "qwen2.5:3b"

# Домены которые нас интересуют + как они называются на сайте
TARGET_DOMAINS = {
    "data_science": {
        "label": "Data Scientist",
        "domains": ["data_science"],
        "emoji": "📊",
        "color": "blue",
    },
    "ml_engineer": {
        "label": "ML / AI Engineer",
        "domains": ["ml_engineer", "ai_engineer", "mlops"],
        "emoji": "⚙️",
        "color": "emerald",
    },
    "llm_genai": {
        "label": "LLM & GenAI",
        "domains": ["llm_genai", "nlp"],
        "emoji": "🤖",
        "color": "amber",
    },
}

PROMPT_TEMPLATE = """\
Ты — аналитик рынка труда. На основе агрегированных данных из {n} вакансий напиши \
2-3 предложения о том, кого ищут работодатели на роль "{label}" в России в 2026 году. \
Пиши конкретно, без воды, опирайся на приведённые данные.

Топ hard skills (из реальных вакансий): {hard}
Топ soft skills (из реальных вакансий): {soft}
Частые ключевые требования: {reqs}

Отвечай только текстом описания, без заголовков и списков.\
"""


def ask_ollama(prompt: str) -> str | None:
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.3, "num_predict": 300}
        }, timeout=60)
        if r.status_code == 200:
            return r.json().get("response", "").strip()
    except Exception as e:
        print(f"  Ollama error: {e}")
    return None


def check_ollama():
    try:
        return requests.get("http://localhost:11434/api/tags", timeout=5).status_code == 200
    except Exception:
        return False


def aggregate(vacancies: list[dict], domains: list[str]) -> dict:
    subset = [v for v in vacancies if v.get("domain") in domains]

    hard_counter = Counter()
    soft_counter = Counter()
    req_counter  = Counter()

    for v in subset:
        for s in v.get("hard_skills", []):
            if s and len(s) > 1:
                hard_counter[s] += 1
        for s in v.get("soft_skills", []):
            if s and len(s) > 1:
                soft_counter[s] += 1
        req = v.get("key_requirement", "")
        if req and len(req) > 5:
            req_counter[req] += 1

    return {
        "count": len(subset),
        "hard_skills": [s for s, _ in hard_counter.most_common(10)],
        "soft_skills": [s for s, _ in soft_counter.most_common(6)],
        "key_requirements": [r for r, _ in req_counter.most_common(5)],
        "perspective_scores": [v.get("perspective_score", 3) for v in subset
                               if isinstance(v.get("perspective_score"), (int, float))],
    }


def salary_stats(vacancies, domains):
    sals = [v["salary_mentioned"] for v in vacancies
            if v.get("domain") in domains and v.get("salary_mentioned")]
    if not sals:
        return None
    sals.sort()
    return {"median": sals[len(sals)//2], "min": sals[0], "max": sals[-1], "n": len(sals)}


def main():
    print(f"Читаем {CHECKPOINT}...")
    raw = json.loads(Path(CHECKPOINT).read_text(encoding="utf-8"))
    vacancies = list(raw.values()) if isinstance(raw, dict) else raw
    print(f"Загружено: {len(vacancies)} записей")

    use_ollama = check_ollama()
    if use_ollama:
        print(f"✓ Ollama доступна, будем генерировать описания")
    else:
        print("  Ollama недоступна — описания будут пропущены (заполни вручную)")

    profiles = {}

    for key, meta in TARGET_DOMAINS.items():
        domains = meta["domains"]
        label   = meta["label"]
        print(f"\n── {label} ({', '.join(domains)}) ──")

        agg  = aggregate(vacancies, domains)
        sal  = salary_stats(vacancies, domains)
        n    = agg["count"]
        print(f"   вакансий: {n}")
        print(f"   топ hard: {agg['hard_skills'][:5]}")
        print(f"   топ soft: {agg['soft_skills'][:3]}")

        avg_score = (sum(agg["perspective_scores"]) / len(agg["perspective_scores"])
                     if agg["perspective_scores"] else 3.5)

        # Генерируем описание через Ollama
        description = ""
        if use_ollama and n > 0:
            prompt = PROMPT_TEMPLATE.format(
                n=n, label=label,
                hard=", ".join(agg["hard_skills"][:8]),
                soft=", ".join(agg["soft_skills"][:5]),
                reqs="; ".join(agg["key_requirements"][:3]) or "нет данных",
            )
            description = ask_ollama(prompt) or ""
            print(f"   описание: {description[:80]}...")
            time.sleep(0.5)

        profiles[key] = {
            "label":          label,
            "emoji":          meta["emoji"],
            "color":          meta["color"],
            "count":          n,
            "hard_skills":    agg["hard_skills"],
            "soft_skills":    agg["soft_skills"],
            "key_requirements": agg["key_requirements"],
            "perspective_score": round(avg_score, 1),
            "salary":         sal,
            "description":    description,
        }

    Path(OUTPUT).write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n✓ Сохранено → {OUTPUT}")
    print("Следующий шаг: открой index.html в браузере")


if __name__ == "__main__":
    main()
