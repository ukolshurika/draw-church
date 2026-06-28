---
name: manual-merging
description: >
  Manual merging of duplicate persons and their relationships in the
  draw-church pipeline. Records merges in a manifest so they can be
  re-applied after `parse.py` rebuild. Use when automatic deduplication
  misses duplicates (different settlements for the same person, role-based
  conflicts blocking merge, or same person appearing across parishes).
---

# Manual Person Merging

Автоматическая дедупликация в `parse.py` не может поймать все дубликаты:
- Одна и та же персона записана в разных приходах → разный `settlement`
- Ролевые конфликты (напр. Родившийся vs Восприемник) блокируют автослияние
- Разночтения в имени/отчестве

Инструмент `merge_persons.py` позволяет вручную объединять персон и
сохраняет действия в манифесте для повторного применения после перезапуска
пайплайна.

---

## Workflow

### 1. Найти дубликаты

Просмотреть граф (`graph.html`), найти подозрительные дубли — одинаковые
имена рядом, подозрительно малые компоненты связности и т.д.

Или напрямую в `all-nodes.json`:

```bash
# Пример: найти всех Иванов Ивановичей
python3 -c "
import json
nodes = json.load(open('all-nodes.json'))
for n in nodes:
    if n['first_name'] == 'Иван' and n.get('patronymic') == 'Иванов':
        print(f\"id={n['id']:5}  {n['first_name']} {n['patronymic']} {n.get('surname','') or '':10}  {n.get('settlement','') or ''}\")
"
```

### 2. Выполнить слияние

```bash
python3 merge_persons.py merge <source_id> <target_id> --reason "описание причины"
```

Что происходит:
- В `all-nodes.json`: данные source → target (скалярные поля дополняют null-ы,
  списки all_roles/all_record_types склеиваются, archive_urls/sources дедуплицируются),
  source удаляется.
- В `all-edges.json`: все рёбра source → target переподключаются на target,
  дубликаты рёбер схлопываются, самопетли удаляются.
- В `manual-merges.json`: записывается запись с entry_id source и target
  для повторного применения после ребилда.

Автоматически создаётся backup в `.merge-backups/` перед каждым изменением.

### 3. Применить после ребилда

После `python3 parse.py` (когда `all-nodes.json` пересоздан с новыми ID):

```bash
python3 merge_persons.py apply
```

Скрипт находит персон по entry_id (из `archive_urls`) и повторяет слияния.

### 4. Просмотр и откат

```bash
python3 merge_persons.py list
python3 merge_persons.py undo   # интерактивный выбор из backup
```

---

## Manifest Format (`manual-merges.json`)

```json
[
  {
    "source_entry_ids": ["b049b5ce-e03f-463a-84d4-2d31ab9cb0b0_5"],
    "target_entry_ids": ["c05a6dfe-1234-5678-90ab-cdef01234567_3"],
    "source_id": 123,
    "target_id": 456,
    "source_label": "Иван Иванов",
    "target_label": "Иван Иванов",
    "reason": "один и тот же человек в разных приходах"
  }
]
```

`entry_ids` — единственный стабильный идентификатор персоны между
перезапусками пайплайна (ID пересчитываются заново при дедупликации).

---

## When to Merge

| Ситуация | Пример | Действие |
|----------|--------|----------|
| Одна персона в двух записях | Иван Петров как родившийся (id=10) и как восприемник (id=20) в той же книге, но автослияние не сработало из-за ролевого конфликта | `merge 20 10` |
| Персона в разных приходах | Матрёна Васильева в Серпуховском уезде и в Тарусском (одна и та же женщина, вышедшая замуж) | `merge ...` |
| Разночтения в написании | "Анна" vs "Анна" но разный патроним из-за опечатки в исходнике | Только если уверены, что одно лицо |
| Одна персона записана дважды в одной записи | Например, повторное появление того же восприемника | `merge ...` |

Не объединять, если есть сомнения — лучше оставить как есть.

---

## Related Files

| Файл | Назначение |
|------|-----------|
| `merge_persons.py` | Инструмент слияния |
| `manual-merges.json` | Манифест ручных слияний |
| `.merge-backups/` | Автоматические бекапы перед изменениями |
| `all-nodes.json` | Данные персон |
| `all-edges.json` | Рёбра графа |
