"""
5_export.py — объединяет cleaned.json + llm_checkpoint.json → data.json
"""

import json
from pathlib import Path

CLEANED     = "data/cleaned.json"
CHECKPOINT  = "data/llm_checkpoint.json"
OUTPUT      = "data/data.json"


def export():
    vacancies = json.loads(Path(CLEANED).read_text(encoding="utf-8"))
    checkpoint = json.loads(Path(CHECKPOINT).read_text(encoding="utf-8"))

    print(f"Вакансий в cleaned.json: {len(vacancies)}")
    print(f"LLM-результатов в checkpoint: {len(checkpoint)}")

    merged = []
    llm_enriched = 0

    for vac in vacancies:
        vid = vac["id"]
        llm = checkpoint.get(vid)
        if llm:
            vac["hard_skills"]      = llm.get("hard_skills", [])
            vac["soft_skills"]      = llm.get("soft_skills", [])
            vac["salary_mentioned"] = llm.get("salary_mentioned")
            vac["remote_possible"]  = llm.get("remote_possible", False)
            vac["domain"]           = llm.get("domain", vac.get("category", "other"))
            vac["perspective_score"]= llm.get("perspective_score", 3)
            vac["key_requirement"]  = llm.get("key_requirement", "")
            vac["llm_analyzed"]     = True
            llm_enriched += 1
        else:
            vac["hard_skills"]      = vac.get("skills", [])
            vac["soft_skills"]      = []
            vac["salary_mentioned"] = None
            vac["remote_possible"]  = False
            vac["domain"]           = vac.get("category", "other")
            vac["perspective_score"]= 3
            vac["key_requirement"]  = ""
            vac["llm_analyzed"]     = False

        # убираем сырое описание — не нужно на фронте
        vac.pop("description", None)
        merged.append(vac)

    Path(OUTPUT).write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\n✓ Итого записей:    {len(merged)}")
    print(f"  LLM обогащено:    {llm_enriched} ({llm_enriched/len(merged)*100:.0f}%)")
    print(f"  Только wrangling: {len(merged)-llm_enriched}")
    print(f"✓ Сохранено → {OUTPUT}")

    # быстрая статистика
    from collections import Counter
    domains = Counter(v["domain"] for v in merged)
    print("\nДомены:")
    for d, n in domains.most_common():
        print(f"  {d}: {n}")

    remote = sum(1 for v in merged if v.get("remote_possible"))
    print(f"\nУдалёнка: {remote} ({remote/len(merged)*100:.0f}%)")

    sal = [v["salary_mentioned"] for v in merged if v.get("salary_mentioned")]
    if sal:
        sal.sort()
        print(f"Зарплата (LLM): {len(sal)} вакансий, медиана {sal[len(sal)//2]:,} руб")

    print("\nСледующий шаг: открой index.html в браузере")


if __name__ == "__main__":
    export()
