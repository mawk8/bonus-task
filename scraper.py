"""
scraper.py — парсинг hh.ru через Playwright
pip install playwright beautifulsoup4 playwright-stealth
playwright install chromium
"""

import asyncio
import json
import os
import random
import re
import signal
from collections import Counter
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

try:
    from playwright_stealth import stealth_async
except ImportError:
    stealth_async = None
    print("⚠️  playwright-stealth не установлен: pip install playwright-stealth")

OUTPUT_PATH     = "data/raw_vacancies.json"
CHECKPOINT_PATH = "data/checkpoint.json"
BLOCKED_DIR     = "data/blocked_pages"
TARGET_CARDS     = 4000
TARGET_FULL_DESC = 3000
HEADLESS         = False

BASE_URL = "https://hh.ru"

CARD_SELECTORS = [
    "[data-qa='vacancy-serp__vacancy']",
    "[data-qa='vacancy-serp__vacancy_standard']",
    "[data-qa='vacancy-serp__vacancy_premium']",
    "[class*='vacancy-serp-item__layout']",
]
CARD_SELECTOR_WAIT = ", ".join(CARD_SELECTORS)

SEARCH_QUERIES = [
    "Machine Learning Engineer", "Data Scientist", "ML Engineer",
    "NLP Engineer", "Computer Vision Engineer", "MLOps Engineer",
    "LLM Engineer", "AI Engineer", "Deep Learning Engineer",
    "Data Science", "ML разработчик", "Машинное обучение",
    "искусственный интеллект разработчик", "аналитик данных ML",
]

JUNIOR_KW = ["junior","джун","джуниор","стажёр","стажер","intern","trainee","начинающий"]
SENIOR_KW = ["senior","сеньор","lead","лид","head","principal","staff","chief","архитект","руководитель"]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# ── Утилиты ───────────────────────────────────────────────────────────────────

def classify_level(title, exp):
    t, e = title.lower(), exp.lower()
    if any(k in t for k in JUNIOR_KW): return "junior"
    if any(k in t for k in SENIOR_KW): return "senior"
    if any(x in e for x in ["без опыта","1–3","1-3","не требуется"]): return "junior"
    if any(x in e for x in ["более 6","5–6","5-6","более 5"]): return "senior"
    if any(x in e for x in ["3–6","3-6","4–6","4-6"]): return "middle"
    return "middle"


def parse_salary(text):
    if not text: return {"from": None, "to": None}
    text = re.sub(r"[\s\u202f\xa0]", "", text)
    sf = re.search(r"от(\d+)", text)
    st = re.search(r"до(\d+)", text)
    s_from = int(sf.group(1)) if sf else None
    s_to   = int(st.group(1)) if st else None
    if not s_from and not s_to:
        m = re.search(r"(\d{4,})", text)
        if m: s_from = int(m.group(1))
    if s_from and not (10_000 <= s_from <= 10_000_000): s_from = None
    if s_to   and not (10_000 <= s_to   <= 10_000_000): s_to   = None
    return {"from": s_from, "to": s_to}


def save_checkpoint(vacs: dict):
    os.makedirs("data", exist_ok=True)
    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump(list(vacs.values()), f, ensure_ascii=False, indent=2)


def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT_PATH):
        try:
            data = json.load(open(CHECKPOINT_PATH, encoding="utf-8"))
            if data:
                print(f"✓ Чекпоинт: {len(data)} вакансий "
                      f"({sum(1 for v in data if v.get('description'))} с описанием)")
                return {v["id"]: v for v in data}
        except Exception:
            pass
    print("Начинаем с нуля")
    return {}


def parse_search_page(html):
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for sel in CARD_SELECTORS:
        cards = soup.select(sel)
        if cards: break

    result = []
    for card in cards:
        try:
            a = (
                card.select_one("a[data-qa='serp-item__title']") or
                card.select_one("a[data-qa='vacancy-serp__vacancy-title']") or
                card.select_one("a[href*='/vacancy/']")
            )
            if not a: continue
            m = re.search(r"/vacancy/(\d+)", a.get("href", ""))
            if not m: continue
            vid   = m.group(1)
            title = a.get_text(strip=True)
            sal_el  = card.select_one("[data-qa*='compensation']") or card.select_one("[data-qa*='salary']")
            comp_el = card.select_one("[data-qa*='employer-name']") or card.select_one("[data-qa*='employer']")
            city_el = card.select_one("[data-qa*='vacancy-serp__vacancy-address']") or card.select_one("[data-qa*='address']")
            exp_el  = card.select_one("[data-qa*='vacancy-serp__vacancy-work-experience']") or card.select_one("[data-qa*='work-experience']")
            tags     = [t.get_text(strip=True) for t in card.select("[data-qa='bloko-tag__text']")]
            exp_text = exp_el.get_text(strip=True) if exp_el else ""
            result.append({
                "id":         vid,
                "url":        f"https://hh.ru/vacancy/{vid}",
                "title":      title,
                "company":    comp_el.get_text(strip=True) if comp_el else "",
                "city":       city_el.get_text(strip=True) if city_el else "",
                "experience": exp_text,
                "level":      classify_level(title, exp_text),
                "salary":     parse_salary(sal_el.get_text(strip=True) if sal_el else ""),
                "tags":       tags,
                "description": "",
            })
        except Exception:
            continue
    return result


def parse_vacancy_page(html, vac):
    soup = BeautifulSoup(html, "html.parser")
    d = (
        soup.select_one("[data-qa='vacancy-description']") or
        soup.select_one("div.vacancy-description") or
        soup.select_one("[class*='vacancy-description']")
    )
    if d:
        vac["description"] = d.get_text(separator=" ", strip=True)
    if not vac["tags"]:
        vac["tags"] = [s.get_text(strip=True) for s in soup.select("[data-qa='bloko-tag__text']")]
    return vac


def save_blocked_html(html, prefix="blocked"):
    try:
        os.makedirs(BLOCKED_DIR, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S")
        with open(f"{BLOCKED_DIR}/{prefix}_{ts}.html", "w", encoding="utf-8") as f:
            f.write(html)
    except Exception:
        pass


# ── Браузер ───────────────────────────────────────────────────────────────────

async def human_like_scroll(page):
    try:
        await page.mouse.wheel(0, random.randint(200, 500))
        await page.wait_for_timeout(random.randint(200, 500))
        await page.mouse.wheel(0, -random.randint(50, 100))
    except Exception:
        pass


async def make_fresh_context(pw):
    browser = await pw.chromium.launch(
        headless=HEADLESS,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
    )
    context = await browser.new_context(
        viewport={"width": random.randint(1200, 1920), "height": random.randint(800, 1080)},
        user_agent=random.choice(USER_AGENTS),
        locale="ru-RU",
        timezone_id="Europe/Moscow",
    )
    # Кука региона — чтобы не редиректило на поддомены (работает не всегда, но помогает)
    await context.add_cookies([{
        "name": "hhregion", "value": "113",
        "domain": ".hh.ru", "path": "/",
    }])

    page = await context.new_page()
    if stealth_async:
        await stealth_async(page)
    else:
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'en-US'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            window.chrome = { runtime: {} };
        """)

    print("    Прогрев сессии...")
    try:
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector("header", timeout=10000)
        await human_like_scroll(page)
    except Exception:
        pass
    await page.wait_for_timeout(random.randint(2000, 3500))
    return browser, context, page


async def fix_subdomain(page):
    """Если попали на kazan.hh.ru — тихо редиректим на hh.ru."""
    m = re.match(r"https://([a-z-]+)\.hh\.ru(.*)", page.url)
    if m and m.group(1) not in ("www", "api", "m", "im", "cdn", "static", "img"):
        fixed = f"https://hh.ru{m.group(2) or '/'}"
        await page.goto(fixed, wait_until="domcontentloaded", timeout=30000)
        return True
    return False


async def safe_goto(page, url, retries=1):
    """
    Навигация с одной попыткой retry.
    НЕ использует networkidle — он вызывает CancelledError при Ctrl+C.
    """
    for attempt in range(retries + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await fix_subdomain(page)
            return True
        except PWTimeout:
            if attempt == retries:
                return False
            await page.wait_for_timeout(1500)
    return False


async def wait_for_cards(page, timeout=20000):
    """'found' | 'empty' | 'interstitial' | 'blocked'"""
    try:
        await page.wait_for_selector(
            f"{CARD_SELECTOR_WAIT}, "
            "[data-qa='vacancy-serp__nothing-found'], "
            "[data-qa='search-serp-empty'], "
            "input[type='tel']",
            timeout=timeout,
        )
    except PWTimeout:
        html = await page.content()
        save_blocked_html(html, "timeout")
        return "blocked"

    if await page.query_selector("input[type='tel'], input[name='phone']"):
        return "interstitial"
    cnt = await page.content()
    if "Напишите телефон" in cnt:
        return "interstitial"

    if await page.query_selector("[data-qa='vacancy-serp__nothing-found'], [data-qa='search-serp-empty']"):
        return "empty"

    for sel in CARD_SELECTORS:
        if await page.query_selector(sel):
            return "found"

    save_blocked_html(cnt, "unknown")
    return "blocked"


async def wait_for_vacancy(page, timeout=15000):
    try:
        await page.wait_for_selector(
            "[data-qa='vacancy-description'], div.vacancy-description, [class*='vacancy-description']",
            timeout=timeout,
        )
        return True
    except PWTimeout:
        return False


# ── Основной скрипт ───────────────────────────────────────────────────────────

async def scrape():
    os.makedirs("data", exist_ok=True)
    all_vacs = load_checkpoint()

    # Graceful Ctrl+C — сохраняем прогресс перед выходом
    loop = asyncio.get_event_loop()
    def _sigint_handler():
        print("\n⚠️  Прерывание! Сохраняем чекпоинт...")
        save_checkpoint(all_vacs)
        print(f"✓ Сохранено {len(all_vacs)} вакансий → {CHECKPOINT_PATH}")
        loop.stop()
    try:
        loop.add_signal_handler(signal.SIGINT, _sigint_handler)
    except NotImplementedError:
        pass  # Windows не поддерживает add_signal_handler

    async with async_playwright() as pw:
        browser, context, page = await make_fresh_context(pw)
        print("✓ Браузер запущен\n")
        session_pages = 0

        async def reset_session(wait_min=8, wait_max=15):
            nonlocal browser, context, page, session_pages
            print("    ♻️  Пересоздаём браузер...")
            try: await browser.close()
            except Exception: pass
            wait = random.randint(wait_min, wait_max)
            print(f"    Пауза {wait}с...")
            await asyncio.sleep(wait)
            browser, context, page = await make_fresh_context(pw)
            session_pages = 0
            print("    ✓ Новая сессия")

        # ── ШАГ 1: Карточки ───────────────────────────────────────────────────
        if len(all_vacs) < TARGET_CARDS:
            print(f"=== ШАГ 1: Карточки (есть: {len(all_vacs)}, цель: {TARGET_CARDS}) ===")

            for query in SEARCH_QUERIES:
                if len(all_vacs) >= TARGET_CARDS:
                    break
                print(f"\n  Запрос: '{query}'")
                block_retries = 0
                page_num = 0
                failed_urls = {}

                while page_num < 40:
                    if len(all_vacs) >= TARGET_CARDS:
                        break

                    # Превентивный сброс каждые 12 страниц
                    if session_pages > 0 and session_pages % 12 == 0:
                        print(f"    Превентивный сброс (страниц: {session_pages})")
                        await reset_session()

                    url = (
                        f"{BASE_URL}/search/vacancy"
                        f"?text={query.replace(' ', '+')}"
                        f"&area=113&per_page=50&page={page_num}"
                    )

                    # Пропускаем URL с 2+ неудачами
                    if failed_urls.get(url, 0) >= 2:
                        print(f"    Стр.{page_num}: пропускаем (2 неудачи)")
                        page_num += 1
                        continue

                    ok = await safe_goto(page, url)
                    if not ok:
                        print(f"    Стр.{page_num}: timeout goto")
                        failed_urls[url] = failed_urls.get(url, 0) + 1
                        await reset_session()
                        continue

                    session_pages += 1
                    status = await wait_for_cards(page)

                    if status == "interstitial":
                        block_retries += 1
                        print(f"    Стр.{page_num}: интерстишл #{block_retries}")
                        await reset_session()
                        if block_retries >= 2:
                            print("    2 интерстишла подряд — следующий запрос")
                            break
                        continue

                    if status == "blocked":
                        block_retries += 1
                        failed_urls[url] = failed_urls.get(url, 0) + 1
                        print(f"    Стр.{page_num}: блок #{block_retries}")
                        await reset_session()
                        if block_retries >= 2:
                            print("    2 блока подряд — следующий запрос")
                            break
                        continue

                    if status == "empty":
                        print(f"    Стр.{page_num}: конец выдачи")
                        break

                    block_retries = 0
                    await human_like_scroll(page)
                    html  = await page.content()
                    found = parse_search_page(html)

                    if not found:
                        print(f"    Стр.{page_num}: ⚠️ карточки не распарсились (html={len(html)}б)")
                        page_num += 1
                        continue

                    prev = len(all_vacs)
                    for v in found:
                        all_vacs[v["id"]] = v
                    new_count = len(all_vacs) - prev
                    print(f"    Стр.{page_num}: найдено={len(found)}, новых={new_count} | всего: {len(all_vacs)}")
                    save_checkpoint(all_vacs)

                    if new_count == 0 and page_num > 0:
                        print("    Новых нет — конец выдачи")
                        break
                    if len(found) < 5:
                        print(f"    Конец выдачи ({len(found)} шт)")
                        break

                    page_num += 1
                    # Быстрее: 2–4с между страницами
                    await page.wait_for_timeout(random.randint(2000, 4000))

            lvl = Counter(v["level"] for v in all_vacs.values())
            print(f"\n✓ Шаг 1: {len(all_vacs)} вакансий")
            print(f"  junior: {lvl['junior']} | middle: {lvl['middle']} | senior: {lvl['senior']}")
            save_checkpoint(all_vacs)

        # ── ШАГ 2: Описания ───────────────────────────────────────────────────
        already = sum(1 for v in all_vacs.values() if v["description"])
        if already < TARGET_FULL_DESC and all_vacs:
            print(f"\n=== ШАГ 2: Описания (есть: {already}, цель: {TARGET_FULL_DESC}) ===")

            # Берём только те у кого нет описания
            need_desc = [
                v for v in all_vacs.values()
                if not v["description"]
            ]
            # Стратифицируем по уровням
            by_level = {"junior": [], "middle": [], "senior": []}
            for v in need_desc:
                by_level[v["level"]].append(v["id"])

            still_need = TARGET_FULL_DESC - already
            per = still_need // 3
            ids_to_fetch = []
            for lvl_name, ids in by_level.items():
                sample = random.sample(ids, min(per, len(ids)))
                ids_to_fetch.extend(sample)
                print(f"  {lvl_name}: {len(sample)}")

            random.shuffle(ids_to_fetch)
            print(f"  Итого: {len(ids_to_fetch)} (~{len(ids_to_fetch)*1.5/60:.0f} мин)\n")

            consecutive_fails = 0  # если много подряд не грузится — сброс

            for i, vid in enumerate(ids_to_fetch):
                vac = all_vacs.get(vid)
                # Пропускаем если уже есть описание (мог загрузиться в предыдущем прогоне)
                if not vac or vac["description"]:
                    continue

                if session_pages > 0 and session_pages % 12 == 0:
                    await reset_session()

                try:
                    ok = await safe_goto(page, vac["url"], retries=1)
                    if not ok:
                        print(f"  [{i+1}] timeout — пропускаем {vid}")
                        consecutive_fails += 1
                        if consecutive_fails >= 3:
                            print("  3 подряд не загрузились — сбрасываем сессию")
                            await reset_session()
                            consecutive_fails = 0
                        continue

                    session_pages += 1
                    loaded = await wait_for_vacancy(page)

                    if loaded:
                        await human_like_scroll(page)
                        html = await page.content()
                        all_vacs[vid] = parse_vacancy_page(html, vac)
                        consecutive_fails = 0
                    else:
                        # Одна попытка — не загрузилась, пропускаем
                        if await page.query_selector("input[type='tel']"):
                            print(f"  [{i+1}] интерстишл — сброс")
                            await reset_session()
                        else:
                            print(f"  [{i+1}] не загрузилась {vid} — пропускаем")
                            consecutive_fails += 1
                            if consecutive_fails >= 3:
                                print("  3 подряд — сбрасываем сессию")
                                await reset_session()
                                consecutive_fails = 0

                except Exception as e:
                    print(f"  [{i+1}] ошибка: {e}")
                    consecutive_fails += 1

                # Checkpoint каждые 5 итераций — не теряем прогресс при краше
                if (i + 1) % 5 == 0:
                    save_checkpoint(all_vacs)

                if (i + 1) % 50 == 0:
                    done = sum(1 for v in all_vacs.values() if v["description"])
                    print(f"  [{i+1}/{len(ids_to_fetch)} {(i+1)/len(ids_to_fetch)*100:.0f}%] описаний: {done}")

                # Быстрее: 1–2с между вакансиями
                await page.wait_for_timeout(random.randint(1000, 2000))

        try:
            await browser.close()
        except Exception:
            pass

    final = list(all_vacs.values())
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    save_checkpoint(all_vacs)

    print(f"\n{'='*50}")
    print(f"✓ ГОТОВО! {len(final)} вакансий → {OUTPUT_PATH}")
    print(f"  С описанием:  {sum(1 for v in final if v['description'])}")
    print(f"  С зарплатой:  {sum(1 for v in final if v['salary']['from'] or v['salary']['to'])}")
    print(f"  С тегами:     {sum(1 for v in final if v['tags'])}")
    lvl = Counter(v["level"] for v in final)
    print(f"  junior={lvl['junior']} | middle={lvl['middle']} | senior={lvl['senior']}")
    print(f"\nСледующий шаг: python 2_wrangling.py")


if __name__ == "__main__":
    asyncio.run(scrape())
