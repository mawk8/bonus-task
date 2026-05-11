"""
2_wrangling.py — чистка и обогащение данных
pip install pandas
"""

import json
import re
import pandas as pd
from collections import Counter

INPUT_PATH  = "data/raw_vacancies.json"
OUTPUT_CSV  = "data/cleaned.csv"
OUTPUT_JSON = "data/cleaned.json"

# ── Категории профессий (для сайта) ──────────────────────────────────────────
# Каждая вакансия получит одну категорию — самую специфичную
CATEGORIES = [
    ("computer_vision", ["computer vision", "cv engineer", "машинное зрение", "opencv", "yolo", "распознавани"]),
    ("nlp",             ["nlp", "natural language", "обработк.*текст", "речев", "text mining", "тональност"]),
    ("mlops",           ["mlops", "ml ops", "ml platform", "ml infrastructure", "ml-инфраструктур"]),
    ("llm",             ["llm", "large language", "prompt engineer", "rag", "генератив", "gpt"]),
    ("data_science",    ["data scien", "аналитик данн", "data analyst", "бизнес-аналитик", "bi analyst"]),
    ("data_engineer",   ["data engineer", "data eng", "инженер данных", "etl", "data pipeline"]),
    ("research",        ["research", "исследовател", "researcher", "r&d", "нир"]),
    ("ml_engineer",     ["ml engineer", "machine learning engineer", "ml-инженер", "ml инженер",
                          "ml разработ", "ml-разработ"]),
    ("ai_engineer",     ["ai engineer", "ai-инженер", "ai инженер", "deep learning", "нейросет",
                          "нейрон.*сет", "искусствен.*интеллект"]),
]

# Фильтр релевантности — хотя бы одно из этих слов в тайтле или описании
RELEVANT_KW = [
    "ml", "machine learning", "data sci", "data eng", "nlp", "llm",
    "deep learn", "нейр", "аналитик данн", "искусствен", "computer vision",
    "cv engineer", "mlops", "ai engineer", "ai-инженер", "ai инженер",
    "ml-инженер", "ml инженер", "data analyst", "разметк", "ml-разработ",
    "machine vision", "машинн", "reinforcement", "речев", "генератив",
    "prompt", "rag ", "трансформер", "transformer",
]

# ── Навыки — только конкретные, без широких русских слов ─────────────────────
# (паттерн, отображаемое название)
SKILLS = [
    # Языки
    (r"\bpython\b",          "Python"),
    (r"\bc\+\+",             "C++"),
    (r"\bscala\b",           "Scala"),
    (r"\bjulia\b",           "Julia"),
    (r"\bsql\b",             "SQL"),
    (r"\bbash\b",            "Bash"),
    (r"\bgo\b|\bgolang\b",   "Go"),
    # ML/DL фреймворки
    (r"\bpytorch\b",         "PyTorch"),
    (r"\btensorflow\b",      "TensorFlow"),
    (r"\bkeras\b",           "Keras"),
    (r"\bjax\b",             "JAX"),
    (r"\bxgboost\b",         "XGBoost"),
    (r"\blightgbm\b",        "LightGBM"),
    (r"\bcatboost\b",        "CatBoost"),
    (r"scikit[\-\s]?learn|sklearn", "scikit-learn"),
    # NLP / LLM
    (r"\btransformers\b",    "Transformers"),
    (r"\bbert\b",            "BERT"),
    (r"\bgpt\b",             "GPT"),
    (r"\bllm\b",             "LLM"),
    (r"\blangchain\b",       "LangChain"),
    (r"\bllamaindex\b|llama.?index", "LlamaIndex"),
    (r"\bspacy\b",           "spaCy"),
    (r"\bnltk\b",            "NLTK"),
    (r"hugging.?face",       "HuggingFace"),
    (r"\brag\b",             "RAG"),
    # CV
    (r"\bopencv\b",          "OpenCV"),
    (r"\byolo\b",            "YOLO"),
    (r"\bonnx\b",            "ONNX"),
    (r"\btensorrt\b",        "TensorRT"),
    (r"\bopenvino\b",        "OpenVINO"),
    (r"\bultralytics\b",     "Ultralytics"),
    # MLOps / инфра
    (r"\bmlflow\b",          "MLflow"),
    (r"\bairflow\b",         "Airflow"),
    (r"\bkubeflow\b",        "Kubeflow"),
    (r"\bclearml\b",         "ClearML"),
    (r"\bwandb\b",           "W&B"),
    (r"\bdvc\b",             "DVC"),
    (r"\bdocker\b",          "Docker"),
    (r"\bkubernetes\b|\bk8s\b", "Kubernetes"),
    (r"\bfastapi\b",         "FastAPI"),
    (r"\bflask\b",           "Flask"),
    (r"\bkafka\b",           "Kafka"),
    (r"\bspark\b",           "Spark"),
    (r"\bhadoop\b",          "Hadoop"),
    (r"\bdask\b",            "Dask"),
    # БД
    (r"\bpostgres(ql)?\b",   "PostgreSQL"),
    (r"\bmongodb\b",         "MongoDB"),
    (r"\bredis\b",           "Redis"),
    (r"\bclickhouse\b",      "ClickHouse"),
    (r"\belasticsearch\b",   "Elasticsearch"),
    (r"\bs3\b",              "S3"),
    # Облака
    (r"\baws\b",             "AWS"),
    (r"\bgcp\b",             "GCP"),
    (r"\bazure\b",           "Azure"),
    (r"yandex.?cloud",       "Yandex Cloud"),
    # Инструменты
    (r"\bgit\b",             "Git"),
    (r"\bjupyter\b",         "Jupyter"),
    (r"\bgrafana\b",         "Grafana"),
]


def get_category(title: str, description: str) -> str:
    text = (title + " " + description[:800]).lower()
    for cat, keywords in CATEGORIES:
        for kw in keywords:
            if re.search(kw, text):
                return cat
    return "general_ml"


def is_relevant(title: str, description: str) -> bool:
    text = (title + " " + description[:500]).lower()
    return any(re.search(kw, text) for kw in RELEVANT_KW)


def extract_skills(text: str) -> list[str]:
    text_lower = text.lower()
    found = []
    seen = set()
    for pattern, label in SKILLS:
        if label in seen:
            continue
        if re.search(pattern, text_lower):
            found.append(label)
            seen.add(label)
    return found


def extract_salary_from_desc(text: str) -> dict:
    """
    Зарплата в hh.ru описаниях почти всегда качественная ("конкурентная").
    Ищем только явные числовые вилки.
    """
    s_from, s_to = None, None

    # "от 150 000" / "от 150к"
    m = re.search(r"от\s*([\d][\d\s\xa0\u202f]{2,7})\s*(?:руб|₽|тыс|до\b)", text, re.I)
    if m:
        raw = re.sub(r"[\s\xa0\u202f]", "", m.group(1))
        try:
            n = int(raw)
            if 10_000 <= n <= 2_000_000:
                s_from = n
            elif 30 <= n <= 1000:
                s_from = n * 1000
        except Exception:
            pass

    # "до 200 000"
    m = re.search(r"до\s*([\d][\d\s\xa0\u202f]{2,7})\s*(?:руб|₽|тыс)", text, re.I)
    if m:
        raw = re.sub(r"[\s\xa0\u202f]", "", m.group(1))
        try:
            n = int(raw)
            if 10_000 <= n <= 2_000_000:
                s_to = n
            elif 30 <= n <= 1000:
                s_to = n * 1000
        except Exception:
            pass

    # "150 000 – 250 000 руб"
    m = re.search(
        r"(\d[\d\s\xa0\u202f]{3,7}\d)\s*[–—\-]\s*(\d[\d\s\xa0\u202f]{3,7}\d)\s*(?:руб|₽)",
        text, re.I
    )
    if m and not s_from and not s_to:
        def parse(s):
            raw = re.sub(r"[\s\xa0\u202f]", "", s)
            try:
                n = int(raw)
                return n if 10_000 <= n <= 2_000_000 else None
            except Exception:
                return None
        s_from = parse(m.group(1))
        s_to   = parse(m.group(2))

    return {"from": s_from, "to": s_to}


def normalize_city(city: str) -> str:
    city = re.sub(r",\s*(р-н|р\.н\.|район).*", "", city, flags=re.I).strip()
    city_lower = city.lower()
    if any(x in city_lower for x in ["москва", "химки", "мытищ", "красногорск", "зеленоград"]):
        return "Москва"
    if any(x in city_lower for x in ["санкт-петербург", "петербург", "спб"]):
        return "Санкт-Петербург"
    return city


# ── Основная логика ───────────────────────────────────────────────────────────

def wrangle():
    print(f"Загружаем {INPUT_PATH}...")
    raw = json.load(open(INPUT_PATH, encoding="utf-8"))
    print(f"Исходных записей: {len(raw)}")

    records = []
    skipped = 0

    for v in raw:
        title = v.get("title", "")
        desc  = v.get("description", "")

        if not is_relevant(title, desc):
            skipped += 1
            continue

        sal = v.get("salary", {}) or {}
        sal_from = sal.get("from")
        sal_to   = sal.get("to")

        # Если нет зарплаты из поля — пробуем из текста
        if not sal_from and not sal_to and desc:
            extracted = extract_salary_from_desc(desc)
            sal_from = extracted.get("from")
            sal_to   = extracted.get("to")

        sal_mid = None
        if sal_from and sal_to:
            sal_mid = (sal_from + sal_to) // 2
        elif sal_from:
            sal_mid = sal_from
        elif sal_to:
            sal_mid = sal_to

        skills   = extract_skills(desc) if desc else []
        category = get_category(title, desc)

        records.append({
            "id":          v["id"],
            "title":       title,
            "company":     v.get("company", ""),
            "city":        normalize_city(v.get("city", "")),
            "level":       v.get("level", "middle"),
            "category":    category,
            "experience":  v.get("experience", ""),
            "salary_from": sal_from,
            "salary_to":   sal_to,
            "salary_mid":  sal_mid,
            "skills":      skills,         # список в JSON
            "has_desc":    bool(desc),
            "description": desc,
            "url":         v.get("url", ""),
        })

    print(f"После фильтрации: {len(records)} (отфильтровано: {skipped})")

    df = pd.DataFrame(records)

    # ── Статистика ────────────────────────────────────────────────────────────
    print(f"\n=== Статистика ===")
    print(f"Уровни:\n{df['level'].value_counts().to_string()}")
    print(f"\nКатегории:\n{df['category'].value_counts().to_string()}")
    print(f"\nТоп-10 городов:\n{df['city'].value_counts().head(10).to_string()}")
    print(f"\nС зарплатой: {df['salary_mid'].notna().sum()} ({df['salary_mid'].notna().mean()*100:.1f}%)")
    print(f"С описанием: {df['has_desc'].sum()}")

    all_skills = [s for skills in df["skills"] for s in skills]
    skill_counts = Counter(all_skills)
    print(f"\nТоп-20 навыков:")
    for skill, cnt in skill_counts.most_common(20):
        print(f"  {skill}: {cnt}")

    sal_df = df[df["salary_mid"].notna() & (df["salary_mid"] > 20_000)]
    if len(sal_df) > 0:
        print(f"\nМедианная зарплата по уровням (руб/мес):")
        print(sal_df.groupby("level")["salary_mid"]
              .agg(["median", "count"])
              .rename(columns={"median": "Медиана", "count": "Вакансий"})
              .to_string())

    # ── Сохраняем ─────────────────────────────────────────────────────────────
    # CSV — skills как строка через |
    df_csv = df.copy()
    df_csv["skills"] = df_csv["skills"].apply(lambda x: "|".join(x))
    df_csv = df_csv.drop(columns=["description"])
    df_csv.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n✓ CSV  → {OUTPUT_CSV} ({len(df_csv)} строк)")

    # JSON — полные данные
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"✓ JSON → {OUTPUT_JSON} ({len(records)} записей)")
    print(f"\nСледующий шаг: запусти 3_eda.ipynb")


if __name__ == "__main__":
    wrangle()
