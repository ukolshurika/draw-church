# AGENTS.md — Draw Church

## Project Overview

**Draw Church** — пайплайн для извлечения, нормализации и визуализации
генеалогических связей из метрических книг Российской Империи (XIX век),
размещённых в Яндекс.Архиве.

На входе — ссылки на каталог архива, на выходе — интерактивный граф
персон и их родственных/социальных отношений (рождения, браки,
восприемники, свидетели).

---

## Architecture

```
draw-church/
├── scraper.py               # Playwright — скачивание сырых API-ответов
├── parse.py                 # Извлечение персон/связей, дедупликация
├── normalize_geo.py         # Нормализация названий поселений
├── viz.py                   # Построение интерактивного graph.html
├── reader.py                # Рантайм-нормализация: normalize_settlement()
├── settlement-synonyms.json # Словарь синонимов (617+ записей)
├── raw_api/                 # Сырые API-ответы (89+ файлов)
├── all-nodes.json           # Выход: 1772 персоны
├── all-edges.json           # Выход: 2245 связей
├── graph.html               # Выход: интерактивная визуализация (vis-network)
└── .agents/skills/geo-normalization/  # Скилл нормализации гео-имён
```

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
viz.py  ──(NetworkX, split components)──►  graph.html
```

---

## Running Commands

Все скрипты — чистый Python 3, без Docker. Зависимости:

```bash
pip install playwright networkx
playwright install chromium
```

Запуск:

```bash
python3 scraper.py          # скачать данные (resume-ready)
python3 parse.py            # извлечь персоны + связи
python3 normalize_geo.py    # нормализовать гео-названия
python3 viz.py              # построить graph.html
```

---

## Key Flows

1. **Scraper** — `scraper.py:main()`: читает ссылки из `links.md`, через
   Playwright заходит на страницы Яндекс.Архива, извлекает `structuredMarkup`
   через API, сохраняет в `raw_api/{uuid}/page_{pn}.json`. Поддерживает
   resume — пропускает уже скачанные страницы.

2. **Parser** — `parse.py:main()`: читает raw-файлы, для каждой записи (BIRTH /
   WEDDING) извлекает персон, разрешает контекстные ссылки (`та же деревня`,
   `тот же уезд`), извлекает помещиков из `info`, строит рёбра
   (`child_of`, `godparent_of`, `married_to`, `witnessed_for`),
   дедуплицирует персон глобально.

3. **Geo Normalization** — `normalize_geo.py:main()`: извлекает каноническое
   имя поселения из административной иерархии, нормализует грамматические
   варианты (родительный падеж → именительный), унифицирует названия
   уездов/волостей через словарь синонимов.

4. **Visualization** — `viz.py:main()`: строит NetworkX-граф, разбивает на
   компоненты связности, генерирует `graph.html` с vis-network.js.
   Раскраска по поселениям, поиск/фильтр, масштабирование размера узлов
   по степени.

---

## Geo-Name Normalization

См. скилл **geo-normalization** (`.agents/skills/geo-normalization/SKILL.md`).

Кратко:
- `settlement-synonyms.json` покрывает Богоявленский приход г. Серпухова
- При добавлении данных других приходов словарь необходимо расширять
- Алгоритм: извлечение ядра → грамматическая нормализация → унификация
  админ. единиц → разрешение контекстных ссылок

---

## Data Scope

Текущие данные: метрические книги за **1882 год**, Богоявленская церковь
г. Серпухова и окрестные приходы Пущинской, Высотской, Туровской,
Кошкинской волостей. Охватывает уезды: Серпуховский, Алексинский,
Тарусский, Каширский, Одоевский и др.

1772 уникальных персоны, 2245 связей, 59 компонент связности.

---

## Skills

- **geo-normalization** — `.agents/skills/geo-normalization/SKILL.md`
  Нормализация названий поселений, расширение словаря синонимов,
  разрешение контекстных ссылок. Использовать при проблемах с
  дедупликацией персон или при добавлении данных нового прихода.

---

## Notes for Agents

- **Автокоммит.** После каждого успешного изменения данных (`all-nodes.json`,
  `all-edges.json`, `manual-merges.json`, `settlement-synonyms.json` и т.п.) —
  автоматически создавай коммит с осмысленным сообщением. Если пользователь
  явно просит не коммитить — не коммить.

- **Откат изменений в данных.** Если агент испортил `all-nodes.json`,
  `all-edges.json` или другие файлы — восстанови их через git:
  1. Покажи пользователю последние коммиты: `git log --oneline -10`
  2. Спроси, до какого состояния откатиться (название коммита, количество
     шагов назад, или конкретные файлы).
  3. Выполни откат — `git checkout <commit> -- <файлы>` для отдельных файлов
     или `git reset --hard <commit>` для полного возврата.
  Не выполняй `git reset --hard` без явного подтверждения пользователя.
