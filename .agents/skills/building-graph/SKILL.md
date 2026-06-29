---
name: building-graph
description: >
  Build an interactive family-relationship graph from Yandex Archive
  metric books (19th-century Russian Empire parish registers). Covers
  the full pipeline: scraping, parsing, geo normalization, and HTML
  rendering. Use when setting up a new parish, adding a different time
  period for the same parish, regenerating the graph from scratch, or
  publishing it on GitHub Pages.
---

# Building Graph — полный пайплайн

Сборка графа родственных/социальных связей из метрических книг Яндекс.Архива
(XIX век). Pipeline: `links.md → scraper → parse → normalize_geo → viz → graph.html`.

---

## Pipeline

```
links.md
  │
  ▼
scraper.py  ──(Playwright, resume-capable)──►  raw_api/{uuid}/page_*.json
  │
  ▼
parse.py  ──(extract, deduplicate, resolve context)──►  all-nodes.json
                                                         all-edges.json
  │
  ▼
normalize_geo.py  ──(canonicalize settlement names)──►  all-nodes.json (нормализован)
  │
  ▼
viz.py  ──(NetworkX, split components, Jinja2)──►  graph.html
```

---

## Инструменты

| Команда | Назначение |
|---------|-----------|
| `scraper.py` | Скачать structuredMarkup API из Яндекс.Архива |
| `parse.py` | Извлечь персоны и связи, дедуплицировать |
| `normalize_geo.py` | Нормализация названий поселений |
| `viz.py` | Построить graph.html (NetworkX + vis-network) |

Входные/выходные файлы:

| Файл | Назначение |
|------|-----------|
| `links.md` | Ссылки на Яндекс.Архив (uuid + page range) |
| `raw_api/` | Сырые API-ответы |
| `all-nodes.json` | Персоны |
| `all-edges.json` | Связи |
| `graph.html` | Финальный интерактивный граф |

---

## Порядок действий

### 1. Подготовка окружения

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Scraper — скачивание данных

Записать ссылки на Яндекс.Архив в `links.md`, по одной на строку.
Формат: полный URL вида `https://yandex.ru/archive/catalog/{uuid}/{page}`
с параметрами `sheet_page_from` и `sheet_page_to`.

```bash
python3 scraper.py
```

Скрипт resume-capable: пропускает уже скачанные страницы.

Результат: `raw_api/{uuid}/page_{pn}.json` + `_meta.json`.

### 3. Parser — извлечение персон и связей

```bash
python3 parse.py
```

Параметры (опционально):

```
--input-dir PATH     каталог с raw API JSON (по умолчанию: raw_api/)
--output-nodes PATH  выходной all-nodes.json
--output-edges PATH  выходной all-edges.json
--dry-run            только вывод статистики, без записи
```

Результат: `all-nodes.json` (дедуплицированные персоны), `all-edges.json` (рёбра: `child_of`, `godparent_of`, `married_to`, `witnessed_for`).

### 4. Geo Normalization — унификация названий

```bash
python3 normalize_geo.py
```

См. скилл **geo-normalization** для деталей. При смене прихода необходимо
расширить `settlement-synonyms.json`.

Результат: `all-nodes.json` — канонические названия поселений.

### 5. Visualization — построение графа

```bash
python3 viz.py
```

Результат: `graph.html` — самодостаточный HTML с vis-network.js.

---

## Изоляция данных разных приходов

`scraper.py` всегда пишет в `raw_api/`, `normalize_geo.py` и `viz.py` читают
`all-nodes.json`/`all-edges.json` из корня проекта. Чтобы данные разных
приходов или временных срезов не пересекались:

1. **Рекомендуется:** скопировать проект целиком для каждого прихода/среза
   (`draw-church-serpuhov-1882`, `draw-church-serpuhov-1883` и т.д.)
2. **Альтернатива:** `parse.py` принимает `--input-dir`, `--output-nodes`,
   `--output-edges` — можно держать несколько датасетов в одном каталоге
   и переключаться между ними:
   ```
   python3 parse.py --input-dir raw_api_приход_а --output-nodes nodes_a.json --output-edges edges_a.json
   python3 parse.py --input-dir raw_api_приход_б --output-nodes nodes_b.json --output-edges edges_b.json
   ```
   После этого вручную скопировать нужную пару в `all-nodes.json`/`all-edges.json`
   перед запуском `normalize_geo.py` и `viz.py`.

---

## Публикация на GitHub Pages

Условия: проект форкнут на GitHub, установлен [OpenCode](https://opencode.ai/download).

1. Форкнуть репозиторий на GitHub
2. Собрать данные (шаги 1–5 выше)
3. В OpenCode выполнить промт: *«Опубликуй проект на GitHub Pages»*

OpenCode настроит GitHub Actions и включит GitHub Pages в настройках
репозитория. Граф будет доступен по адресу `https://{username}.github.io/draw-church/`.

---

## Типовые проблемы

| Проблема | Решение |
|----------|---------|
| После смены прихода много новых вариантов названий | См. скилл **geo-normalization**: расширить `settlement-synonyms.json` |
| Граф распадается на сотни мелких компонент | Не хватает синонимов поселений → дедупликация не работает |
| `scraper.py` не скачивает страницы | Проверить `links.md`, убедиться что Playwright установлен: `playwright install chromium` |
| `graph.html` не открывается в браузере | Открыть через Chrome/Firefox/Edge, а не через текстовый редактор |
| Данные одного прихода затирают данные другого | Использовать отдельные копии проекта (см. раздел изоляции) |