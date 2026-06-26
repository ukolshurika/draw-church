---
name: parsing
description: >
  Extract persons and relationships from Yandex Archive metric-book API
  responses (BIRTH/WEDDING entries). Covers status mapping, settlement
  context resolution, landowner extraction, edge building, and global
  deduplication. Use when adding new parish data, fixing extraction
  bugs, or extending the status/relation mapping.
---

# Parsing Metric Books from Yandex Archive

Извлечение персон и родственных/социальных связей из структурированных
API-ответов Яндекс.Архива (XIX век, метрические книги).

## Pipeline

```
links.md  ──►  scraper.py  ──►  raw_api/{uuid}/page_*.json
                                        │
                                        ▼
                                   parse.py  ──►  all-nodes.json
                                                   all-edges.json
```

---

## Entry Format (API Response)

Каждый файл `page_*.json` содержит массив `entries`. Запись:

```json
{
  "entry_id": "uuid...",
  "type": "BIRTH | WEDDING",
  "people": [
    {
      "name": "Феодосия",
      "second_name": "Павлова",
      "surname": "",
      "status": "MOTHER",
      "sex": "FEMALE",
      "geo": "сельцо Злобино",
      "info": "крестьянская девица",
      "age": ""
    }
  ]
}
```

Поля персоны:
- `name` → `first_name`
- `second_name` → `patronymic` (null если пусто)
- `surname` → `surname` (null если пусто, очень редко заполнено)
- `status` → `relation_type` через таблицу ниже
- `geo` → `settlement` (после разрешения контекста и нормализации)
- `info` → источник `landowner`

---

## Status Mapping

### BIRTH

| API Status  | relation_type | record_type     |
|-------------|---------------|-----------------|
| `BORN`      | Родившийся    | Родившийся      |
| `MOTHER`    | Родитель      | Родившийся      |
| `FATHER`    | Родитель      | Родившийся      |
| `GODFATHER` | Восприемник   | Родившийся      |
| `GODMOTHER` | Восприемник   | Родившийся      |
| `OTHER`     | Другой        | Родившийся      |

### WEDDING

| API Status | relation_type   | record_type       |
|------------|-----------------|-------------------|
| `GROOM`    | Жених           | Бракосочетание    |
| `BRIDE`    | Невеста         | Бракосочетание    |
| `WITNESS`  | Свидетель       | Бракосочетание    |

---

## Settlement Resolution

### Контекстные ссылки внутри записи

Выполняется в `parse.py:resolve_context_settlement()`. Для каждой персоны
просматриваются все предыдущие персоны **в этой же записи** и между записями
(через `global_ctx`):

| Сырая строка               | Разрешается как             |
|----------------------------|-----------------------------|
| `та же деревня`            | Последняя `деревня`         |
| `то же сельцо`             | Последнее `сельцо`          |
| `то же село`               | Последнее `село`            |
| `тот же уезд, деревня N`   | Последний `уезд` + `деревня N` |

Начинается с локального контекста записи, затем глобального контекста страницы.

### Нормализация

После разрешения вызывается `reader.normalize_settlement()` → `settlement-synonyms.json`

---

## Landowner Extraction

Из поля `info` регуляркой:
```
(?:помещиц[аы]|помещика)\s+(.+?)(?:\s+крестьянин|\s+крестьянка|\s*$)
```

Контекстные ссылки в `info`: если `той же помещицы` / `того же помещика` —
копируется landowner последней персоны с landowner в записи.

---

## Edge Building

### BIRTH → `child_of`, `godparent_of`

```
BORN ── child_of ──► MOTHER, FATHER
GODFATHER, GODMOTHER ── godparent_of ──► BORN
```

### WEDDING → `married_to`, `witnessed_for`

```
GROOM ── married_to ──► BRIDE
WITNESS ── witnessed_for ──► GROOM
WITNESS ── witnessed_for ──► BRIDE
```

Все персоны внутри записи соединяются со всеми целевыми персонами того же
статуса (all-to-all в пределах группы).

Выходное ребро:
```json
{"source_id": 44, "target_id": 1212, "relation": "married_to"}
```

---

## Deduplication

Глобальная дедупликация по всем персонам (`parse.py:deduplicate()`):

1. **Сортировка** по полноте: surname > patronymic > name > settlement > landowner
2. **Совпадение**: одинаковые `first_name` + `patronymic` + **согласованы**
   `settlement` и `landowner` (если оба не-null, должны совпадать)
3. **Конфликт**: если `settlement` или `landowner` различаются у двух записей
   с одинаковым именем — это **разные** люди (не объединяются)
4. При совпадении — оставляется запись с более полными данными

`_temp_id` → финальный `id` через `temp_id_to_final` mapping.

---

## Output Schema

### all-nodes.json

```json
{
  "id": 1,
  "first_name": "Иван",
  "patronymic": "Ильин",
  "surname": null,
  "year": 1882,
  "relation_type": "Жених",
  "record_type": "Бракосочетание",
  "landowner": null,
  "settlement": "Деревня Гавшино"
}
```

### all-edges.json

```json
{"source_id": 44, "target_id": 1212, "relation": "married_to"}
```

---

## Scraper (scraper.py)

Скачивает сырые API-ответы. Resume-capable — пропускает уже существующие
файлы `raw_api/{uuid}/page_{pn}.json`.

Алгоритм на страницу:
1. Открыть `https://yandex.ru/archive/catalog/{uuid}/{pn}` (Playwright)
2. Из `__NEXT_DATA__` извлечь `nodeId` и флаг `hasStructuredMarkup`
3. Если нет разметки — пропустить
4. Год из breadcrumbs (`dateFrom`)
5. API: `GET /archive/api/structuredMarkup?id={nodeId}`
6. Сохранить с обёрткой `{year, page, node_id, entries}`
7. Задержка 4-8 секунд

Вход: `links.md` — строки вида:
```
https://yandex.ru/archive/catalog/{UUID}?sheet_page_from={from}&sheet_page_to={to}
```

---

## Related Files

| Файл                      | Назначение                                |
|---------------------------|-------------------------------------------|
| `links.md`                | Входные ссылки на Яндекс.Архив            |
| `scraper.py`              | Скачивание raw API                        |
| `parse.py`                | Извлечение + дедупликация                 |
| `reader.py`               | `normalize_settlement()`                  |
| `settlement-synonyms.json` | Словарь синонимов поселений              |
| `normalize_geo.py`        | Массовая пост-нормализация               |
