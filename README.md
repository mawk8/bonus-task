# AI/ML Job Market Analysis — Russia 2026

Анализ рынка труда в сфере AI/ML в России на основе вакансий с hh.ru.

## Что сделано

Собрали вакансии с hh.ru → почистили → провели EDA → прогнали через LLM для извлечения структурированных данных → визуализировали на дашборде.

## Стек

Python · pandas · Ollama (qwen2.5:3b) · Jupyter · HTML/CSS/JS

## Data Pipeline

```
scraper.py          →  raw_vacancies.json   (сырые вакансии с hh.ru API)
    ↓
wrangling.py      →  cleaned.csv / cleaned.json
                        - фильтрация по релевантности (ML/AI ключевые слова)
                        - нормализация городов и зарплат
                        - извлечение навыков регулярками
                        - категоризация вакансий
    ↓
eda.ipynb         →  разведочный анализ данных
                        - распределения по уровням, городам, зарплатам
                        - топ навыков, корреляции
    ↓
llm.py            →  llm_checkpoint.json
                        - локальная LLM (Ollama) извлекает hard/soft skills
                        - определяет домен, remote, perspective score
    ↓
profile.py        →  profiles.json
                        -профилирование по профессиям и скиллам через llm
    ↓
export.py         →  data/data.json       (финальный датасет для дашборда)
    ↓
index.html          →  интерактивный дашборд
```


## Данные

- Вакансий собрано: ~5 000
- После фильтрации: ~2 000
- LLM-обогащено: ~500+
- Период сбора: май-апрель 2026

## Структура

```
├── scraper.py
├── wrangling.py
├── eda.ipynb
├── llm.py
├── export.py
├── index.html
├── data/
│   ├── cleaned.csv
│   ├── profile.json
│   └── data.json
└── README.md
```

