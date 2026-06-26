# Промт: Парсинг метрических книг из Яндекс.Архива

## Задача

Скачать структурированные данные (рождения и бракосочетания) из Яндекс.Архива по ссылкам из `links.md`, извлечь персоны и связи, дедуплицировать и сохранить в `all-nodes.json` / `all-edges.json`.

Процесс разделён на два независимых этапа:

1. **scraper.py** — скачивание сырых API-ответов в `raw_api/{uuid}/page_{pn}.json`
2. **parse.py** — чтение raw-файлов, извлечение персон/рёбер, дедупликация, сохранение результата

---

## Этап 1: Download (scraper.py)

### Вход: `links.md`

Строки вида:
```
https://yandex.ru/archive/catalog/{UUID}?sheet_page_from={from}&sheet_page_to={to}
```

### Процесс

Для каждой страницы `pn` от `from` до `to`:

1. Проверить `raw_api/{uuid}/page_{pn}.json` — если существует, пропустить (resume)
2. Открыть `https://yandex.ru/archive/catalog/{uuid}/{pn}` через Playwright (headless Chromium)
3. Распарсить `<script id="__NEXT_DATA__">`:
   - `props.pageProps.currentNode.id` → `nodeId`
   - `props.pageProps.currentNode.hasStructuredMarkup` — если `false`, пропустить
4. Извлечь год: в breadcrumbs найти элемент с `type: "File"`, из `dateFrom` взять 4 цифры года
5. Вызвать API через `page.request.get()` (браузерный HTTP-клиент, использует ту же сессию):
   ```
   GET https://yandex.ru/archive/api/structuredMarkup?id={nodeId}
   ```
6. Сохранить в файл обёртку:
   ```json
   {
     "year": 1882,
     "page": 66,
     "node_id": "...",
     "has_markup": true,
     "entries": [ ... ]
   }
   ```
7. Случайная задержка 4–8 секунд между страницами

### Выход

`raw_api/{uuid}/page_66.json`, `page_67.json`, ... — только страницы с `hasMarkup=true`

---

## Этап 2: Парсинг (parse.py)

### Чтение raw-файлов

Из каждого `raw_api/{uuid}/page_{pn}.json` читаются:
- `year` — год записи
- `entries` — массив метрических записей

### Формат записи (entry)

```json
{
  "entry_id": "uuid...",
  "type": "BIRTH" | "WEDDING",
  "people": [
    {
      "name": "Феодосия",
      "second_name": "Павлова",    // отчество
      "surname": "",                // фамилия (редко)
      "status": "MOTHER",           // см. таблицу
      "sex": "FEMALE",
      "geo": "сельцо Злобино",      // населённый пункт
      "info": "крестьянская девица", // соц. статус / примечания
      "age": ""
    }
  ]
}
```

### Маппинг статусов

| Статус API | `record_type` | `relation_type` |
|---|---|---|
| `BORN` | `Родившийся` | `Родившийся` |
| `MOTHER` | `Родившийся` | `Родитель` |
| `FATHER` | `Родившийся` | `Родитель` |
| `GODFATHER` | `Родившийся` | `Восприемник` |
| `GODMOTHER` | `Родившийся` | `Восприемник` |
| `OTHER` | `Родившийся` | `Другой` |
| `GROOM` | `Бракосочетание` | `Жених` |
| `BRIDE` | `Бракосочетание` | `Невеста` |
| `WITNESS` | `Бракосочетание` | `Свидетель` |

### Поля персоны

| Поле | Источник |
|------|----------|
| `first_name` | `name` |
| `patronymic` | `second_name` (null если пусто) |
| `surname` | `surname` (null если пусто) |
| `year` | год из обёртки файла |
| `relation_type` | из маппинга статусов |
| `record_type` | `Родившийся` / `Бракосочетание` |
| `settlement` | `geo` → нормализация (см. ниже) |
| `landowner` | из `info` (см. ниже) |

### Settlement: раскрытие контекста

В пределах одной записи (entry) разрешаются отсылки:

- `та же деревня` → последняя `деревня` в этой записи
- `то же село` → последнее `село` в этой записи
- `то же сельцо` → последнее `сельцо` в этой записи
- `той же ...` → ищем совпадение по ключевому слову в последнем полном settlement
- `тот же уезд, деревня X` → уезд из последнего полного адреса + `деревня X`

После раскрытия применить `normalize_settlement()` из `reader.py`.

### Landowner: извлечение из `info`

Поле `info` может содержать "помещицы N крестьянин". Извлечь:
```
(?:помещиц[аы]|помещика)\s+(.+?)(?:\s+крестьянин|\s+крестьянка|\s*$)
```

Если `info` содержит указание `той же помещицы` / `того же помещика` — скопировать landowner последней персоны с landowner в этой записи.

### Связи (edges)

| Тип записи | source | target | relation |
|---|---|---|---|
| `BIRTH` | `BORN` | `MOTHER` / `FATHER` | `child_of` |
| `BIRTH` | `GODFATHER` / `GODMOTHER` | `BORN` | `godparent_of` |
| `WEDDING` | `GROOM` | `BRIDE` | `married_to` |
| `WEDDING` | `WITNESS` | `GROOM` | `witnessed_for` |
| `WEDDING` | `WITNESS` | `BRIDE` | `witnessed_for` |

### Дедупликация

Глобально по всем персонам:

1. Сортировка по полноте данных (settlement > landowner > patronymic > name)
2. Совпадение: одинаковые `first_name` + `patronymic` + хотя бы одно из:
   - одинаковый `settlement` (не null)
   - одинаковый `landowner` (не null)
3. При совпадении — оставить запись с более полными данными

### Сохранение

- `all-nodes.json` — массив персон с финальными `id` (без служебных полей)
- `all-edges.json` — массив рёбер с финальными `id`

---

## Файлы проекта

| Файл | Назначение |
|------|-----------|
| `links.md` | Входные ссылки на Яндекс.Архив |
| `scraper.py` | Скачивание raw API → `raw_api/{uuid}/` |
| `parse.py` | Парсинг raw → `all-nodes.json` + `all-edges.json` |
| `raw_api/{uuid}/` | Сырые ответы API (page_{pn}.json) |
| `reader.py` | `normalize_settlement()`, `add_settlement_synonym()` |
| `settlement-synonyms.json` | Вариант → каноническое название села |
| `all-nodes.json` | Выход: персоны |
| `all-edges.json` | Выход: связи |

## Использование

```bash
python3 scraper.py   # скачать все страницы (resume-ready)
python3 parse.py     # собрать all-nodes.json + all-edges.json
```
