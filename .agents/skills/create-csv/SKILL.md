---
name: create-csv
description: >
  Create a CSV file of all BIRTH (baptism/birth) entries from Yandex.Archive
  metric books. Downloads raw structured API data for the given parish URL(s)
  into a prefixed directory, then generates a flat CSV with 22 fields per row:
  baby/father/mother/godparents names, estates, residences, landowner,
  officiating clergy (priest/deacon/psalomshchik), and source metadata.
  Use when exporting birth records for spreadsheet analysis, when adding new
  parish data, or when a user requests «создать CSV» or «экспорт в CSV».
---

# create-csv — метрические книги в CSV

Скачивает структурированные записи о рождениях из метрических книг
Яндекс.Архива и преобразует их в плоский CSV для анализа в Excel / Google Sheets.

---

## Pipeline

```
links (аргументы)
  │
  ▼
create_csv.py  ──(backup links.md, записать новые)──►  links.md
  │
  ▼
scraper.py  ──(--output-dir raw_api_{PREFIX}/)──►  raw_api_{PREFIX}/{uuid}/page_*.json
  │
  ▼
raw_to_csv.py  ──(BIRTH entries → CSV)──►  {PREFIX}_births.csv
```

---

## Команда

```bash
python3 create_csv.py PREFIX URL1 [URL2 ...]
```

- `PREFIX` — префикс для папки с сырыми данными и выходного CSV:
  - `raw_api_{PREFIX}/` — папка с сырыми API-ответами
  - `{PREFIX}_births.csv` — выходной CSV
- `URL1 URL2 ...` — одна или несколько ссылок на Яндекс.Архив в формате:
  ```
  https://yandex.ru/archive/catalog/{UUID}?sheet_page_from=X&sheet_page_to=Y
  ```

---

## Примеры

### Новый приход

```bash
python3 create_csv.py moscow_alexeev_1913 \
  "https://yandex.ru/archive/catalog/0fd4127e-4fec-422f-985e-e105fa18ba88?sheet_page_from=2&sheet_page_to=343" \
  "https://yandex.ru/archive/catalog/91f9cf81-be8f-45f7-99ea-3a8a91a5e9dd?sheet_page_from=1&sheet_page_to=356"
```

Результат:
- `raw_api_moscow_alexeev_1913/` — сырые данные
- `moscow_alexeev_1913_births.csv` — 22 колонки с рождениями

Если скрапер уже запускался и часть страниц скачана — он пропускает существующие
файлы (resume-capable). CSV-файл при повторном запуске перезаписывается полностью.

---

## Поля выходного CSV

| # | Поле | Описание |
|---|------|----------|
| 1 | Дата рождения | НЕ ЗАПОЛНЕНО (в structured API нет дат) |
| 2 | Дата крещения | НЕ ЗАПОЛНЕНО |
| 3 | Имя родившегося | `name patronymic surname` (без отчества если пусто) |
| 4 | Имя отца | `name patronymic surname` |
| 5 | Имя матери | `name patronymic surname` |
| 6 | Сословие отца | Из поля `info` (крестьянин, мещанин…) с очисткой помещика |
| 7 | Сословие матери | Из поля `info` |
| 8 | Место проживания отца | `geo` с разрешением контекстных ссылок и нормализацией |
| 9 | Место проживания матери | `geo`, fallback от отца если пусто |
| 10 | Имя помещика | Извлечено из `info` (помещица/помещик) |
| 11 | Имя восприемника | Крёстный отец (несколько — через `; `) |
| 12 | Имя восприемницы | Крёстная мать (несколько — через `; `) |
| 13 | Сословие восприемника | Из `info` |
| 14 | Сословие восприемницы | Из `info` |
| 15 | Место проживания восприемника | `geo` крёстного |
| 16 | Место проживания восприемницы | `geo` крёстной |
| 17 | ФИО священника | Из записи (OTHER) или page-level fallback |
| 18 | ФИО диакона | Из записи или page-level |
| 19 | ФИО псаломщика | Из записи или page-level |
| 20 | _год | Год записи |
| 21 | _страница | Номер страницы дела |
| 22 | _источник | URL на Яндекс.Архив с entry_id |

Несколько восприемников одного пола — объединяются через `; `. Сословия и
поселения дедуплицируются при объединении.

---

## Скрипты

| Файл | Назначение |
|------|-----------|
| `create_csv.py` | Оркестратор: links → scraper → raw_to_csv |
| `scraper.py` | Скачивает structuredMarkup API (Playwright) |
| `raw_to_csv.py` | Извлекает BIRTH entries → CSV. Переиспользует `parsing/*` и `reader.py` без изменений |

---

## Изоляция данных

Каждый вызов `create_csv.py PREFIX ...` пишет в собственную папку
`raw_api_{PREFIX}/` и в `{PREFIX}_births.csv`. Несколько приходов / временных
срезов сосуществуют независимо.

Оригинальный `links.md` бекапится на время работы скрапера и
восстанавливается после его завершения.

---

## Ограничения

- **Даты рождения/крещения** отсутствуют — structured markup API Яндекс.Архива
  не содержит дат в entries, только имена/роли/локации. Даты есть в OCR-тексте
  страницы, который не скачивается.
- **Священник/диакон/псаломщик** — ищется сначала внутри записи (статус `OTHER`
  с ролью в `info`), затем среди всех записей страницы (статусы `GODFATHER`,
  `WITNESS`, `OTHER` кроме `FATHER`/`MOTHER`/`BORN`/`GROOM`/`BRIDE`).
  На титульной странице (page 1) имена причта есть в тексте, но не в structured
  markup — эти страницы скачиваются скрапером только если у них есть разметка.
  В CSV попадают те, кого удалось найти в записях.
