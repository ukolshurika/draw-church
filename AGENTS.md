# AGENTS.md — Draw Church

**Draw Church** — пайплайн для извлечения, нормализации и визуализации
генеалогических связей из метрических книг Российской Империи (XIX век),
размещённых в Яндекс.Архиве.

На входе — ссылки на каталог архива, на выходе — интерактивный граф
персон и их родственных/социальных отношений (рождения, браки,
восприемники, свидетели).

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

## Skills

- **building-graph** — `.agents/skills/building-graph/SKILL.md`
  Полный пайплайн: от ссылок на Яндекс.Архив до готового графа.
  Публикация на GitHub Pages через OpenCode.
- **geo-normalization** — `.agents/skills/geo-normalization/SKILL.md`
  Нормализация названий поселений, расширение словаря синонимов,
  разрешение контекстных ссылок. Использовать при проблемах с
  дедупликацией персон или при добавлении данных нового прихода.
- **manual-merging** — `.agents/skills/manual-merging/SKILL.md`
  Ручное объединение дубликатов персон и их связей.

---

## Notes for Agents

- **Проверка зависимостей.** В начале сессии проверь наличие
  Python-зависимостей (`pip list`) и Playwright (`playwright install --dry-run`
  или попробуй импорт). Если чего-то не хватает — установи:
  ```bash
  pip install -r requirements.txt
  playwright install chromium
  ```

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