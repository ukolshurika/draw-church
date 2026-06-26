# Draw Church

Интерактивный граф родственных и социальных связей из метрических книг
Российской Империи (XIX век), размещённых в [Яндекс.Архиве](https://yandex.ru/archive).

На входе — ссылки на каталог архива, на выходе — `graph.html` с родословным графом.

**1958 персон, 2658 связей** — рождения, браки, восприемники, свидетели —
из Богоявленского прихода г. Серпухова, 1882 г.

▶ **[Как пользоваться графом](https://ukolshurika.github.io/draw-church/)** — инструкция по интерфейсу

## Архитектура

```
links.md  ──►  scraper.py  ──►  raw_api/  ──►  parse.py  ──►  all-nodes.json
                                                               all-edges.json
                                                                  │
                                                     normalize_geo.py ──►  viz.py  ──►  graph.html
```

| Файл | Назначение |
|------|-----------|
| `scraper.py` | Playwright — скачивание structuredMarkup API из Яндекс.Архива (resume-capable) |
| `parse.py` | Извлечение персон и связей, разрешение контекстных ссылок, дедупликация |
| `normalize_geo.py` | Нормализация названий поселений (канонизация + словарь синонимов) |
| `reader.py` | Рантайм-нормализация `normalize_settlement()` |
| `viz.py` | NetworkX + vis-network.js — построение `graph.html` |
| `settlement-synonyms.json` | 617+ синонимов поселений |
| `raw_api/` | Сырые API-ответы (89 файлов) |
| `all-nodes.json` | 1958 уникальных персон |
| `all-edges.json` | 2658 связей |
| `graph.html` | Самодостаточная интерактивная визуализация |
| `links.md` | Входные ссылки на Яндекс.Архив |

## Запуск

Python 3, без Docker:

```bash
pip install playwright networkx
playwright install chromium

python3 scraper.py          # 1. скачать данные (resume-ready)
python3 parse.py            # 2. извлечь персоны + связи
python3 normalize_geo.py    # 3. нормализовать гео-названия
python3 viz.py              # 4. построить graph.html
```

Скрипты не привязаны к приходу — можно использовать для любых метрических
книг Яндекс.Архива. При смене прихода необходимо расширить словарь
`settlement-synonyms.json`.

## Область данных

Метрические книги за **1882–1883 гг.**, Богоявленская церковь г. Серпухова
и окрестные приходы Пущинской, Высотской, Туровской, Кошкинской волостей.
Охватывает уезды: Серпуховский, Алексинский, Тарусский, Каширский,
Одоевский и смежные.

## Agents

Проект использует два AI-скилла для расширения:

- **parsing** — `.agents/skills/parsing/SKILL.md` — извлечение персон/связей из API
- **geo-normalization** — `.agents/skills/geo-normalization/SKILL.md` — нормализация гео-названий

Полная документация для AI-агентов в [AGENTS.md](AGENTS.md).
