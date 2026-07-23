---
name: llm-dedup
description: >
  LLM-based person deduplication for draw-church. Uses an LLM to classify
  whether two person records represent the same individual by analyzing
  relationship context (shared spouses, children, godchildren), attribute
  similarity, and 19th-century domain knowledge. Complements the
  deterministic dedup algorithm by catching false negatives caused by
  OCR errors, spelling variants, and context-resolution failures.
  Use when the automatic dedup keeps obviously-same persons separate,
  or after adding new parish data that needs intelligent merging.
---

# LLM-based Person Deduplication

Детерминированный алгоритм дедупликации в `parsing/dedup.py` консервативен:
любое различие в `surname`, `settlement` или `landowner` = разные люди.
Это приводит к тому, что один и тот же человек, записанный с небольшими
вариациями (OCR-ошибки, разные падежи помещика, неразрешённые контекстные
ссылки), остаётся разделённым на несколько узлов.

`llm_dedup.py` использует LLM для интеллектуального разрешения таких случаев,
опираясь на:
- **Контекст связей**: общие супруги, дети, крестники — сигналы того,
  что две записи относятся к одному человеку
- **Доменные знания**: варианты имён (Георгий=Егор), отчеств (Иванов=Иоаннов),
  орфографические варианты помещиков (Ешевский=Ежевский)
- **Временные ограничения**: восприемник должен быть старше 10 лет,
  персона не может появляться в записях до своего рождения

---

## Pipeline

```
all-nodes.json + all-edges.json
        │
        ▼
llm_dedup.py candidates ──► candidate pairs (JSON)
        │
        ▼
llm_dedup.py classify ──► merge suggestions (JSON)
        │
        ▼
merge_persons.py merge ──► merged data
```

---

## Usage

### 1. Статистика: оценить масштаб проблемы

```bash
python3 llm_dedup.py stats
```

Показывает: количество мульти-бакетов (одинаковые имя+отчество, разные
персоны), сколько кандидатов имеют общих супругов, детей, крестников.

### 2. Генерация кандидатов

```bash
# Посмотреть топ-20 кандидатов с высоким overlap score
python3 llm_dedup.py candidates --min-score 3 --limit 20

# Сохранить кандидатов в JSON для инспекции
python3 llm_dedup.py candidates --min-score 1 --limit 200 --json > candidates.json
```

**Фильтры:**
- `--min-score N` — минимальный overlap score (по умолчанию 0)
  - 0 = все пары с общим атрибутом или связью
  - 3+ = только пары с общими связями (супруг, дети) — самые надёжные
- `--limit N` — ограничение количества кандидатов (по умолчанию 500)

### 3. Классификация через LLM

```bash
# Потребуется API-ключ
export LLM_DEDUP_API_KEY="sk-..."
export LLM_DEDUP_MODEL="gpt-4o"          # по умолчанию
export LLM_DEDUP_API_BASE="https://api.openai.com/v1"  # по умолчанию

# Классифицировать и сохранить результат
python3 llm_dedup.py classify --min-score 3 --limit 100 --output results.json

# С другим провайдером (совместимым с OpenAI API)
export LLM_DEDUP_API_BASE="https://api.deepseek.com/v1"
export LLM_DEDUP_MODEL="deepseek-chat"
python3 llm_dedup.py classify --min-score 3 --limit 100 --output results.json
```

**Параметры:**
- `--min-score N` — минимальный score кандидата (рекомендуется 3)
- `--limit N` — макс. количество кандидатов для LLM
- `--batch-size N` — сколько пар в одном LLM-запросе (по умолчанию 15)
- `--output FILE` — путь для сохранения результатов (JSON)

### 4. Автоматическое применение слияний

```bash
# Dry-run: посмотреть, что будет сделано
python3 llm_dedup.py apply --min-score 3 --limit 100 --dry-run

# Реальное применение (с бекапом через merge_persons.py)
python3 llm_dedup.py apply --min-score 3 --limit 100
```

Применяет HIGH-confidence слияния автоматически:
- Создаёт бекап `.merge-backups/`
- Вызывает `merge_persons.py` для каждого слияния
- Записывает в `manual-merges.json` для повторного применения после ребилда

---

## How Candidates Are Generated

### Bucketing

Все персоны группируются по `(first_name, patronymic)`. В бакетах с более чем
одной записью детерминированный алгоритм оставил их раздельными из-за
конфликтов в surname/settlement/landowner.

### Filtering

Из всех пар в мульти-бакетах (4059 для текущего датасета) отбираются только те, которые:

1. **Разделяют хотя бы один атрибут** (settlement, landowner, surname)
   — исключаются заведомо разные люди из разных деревень
2. **Годы в пределах 40 лет** — одна и та же персона не может жить вечно
3. **Нет ролевого противоречия** — персона не может появиться в записи
   до своего рождения

### Scoring

Каждая пара получает overlap score:

| Сигнал | Вес | Значение |
|--------|-----|----------|
| Общий супруг | 10 | Практически гарантия — один человек |
| Общий ребёнок | 5 | Один и тот же родитель |
| Общие крестники | 3 | Сильный сигнал |
| Общие родители | 1 | Слабый сигнал (братья/сёстры с одинаковым именем) |
| Общий settlement | 1 | Живут в одной деревне |
| Общий landowner | 1 | Принадлежат одному помещику |

**Score ≥ 3** — кандидаты, которые точно стоит проверить (обычно 100-130 пар).

---

## LLM Prompt Structure

Для каждой пары LLM получает:

1. **Доменные правила** (варианты имён, ограничения по возрасту,
   интерпретация общих связей)
2. **Полные данные персоны A**: год, поселение, помещик, фамилия, роли
3. **Полные данные персоны B**: то же самое
4. **Контекст связей A**: супруги, дети, родители, крестники (с именами)
5. **Контекст связей B**: то же самое
6. **Причина разделения**: какие атрибуты конфликтуют и не дали детерминированному
   алгоритму объединить записи
7. **Общие связи**: список общих супругов, детей, крестников

LLM возвращает JSON с полями: `decision` (SAME/DIFFERENT),
`confidence` (high/medium/low), `reasoning`.

---

## Domain Knowledge Injected Into Prompts

### Именные эквиваленты
- Георгий = Егор = Егорий
- Иоанн = Иван
- Феодор = Федор, Феодосий = Федосей
- Косма = Кузьма
- Онисим = Анисим
- Осип = Иосиф
- Димитрий = Дмитрий
- Кодрат = Кондрат

### Отчества-эквиваленты
- Иванов = Иоаннов
- Феодоров = Федоров
- Осипов = Иосифов

### Правила интерпретации
- **Общий супруг + общий settlement** = **один и тот же человек**
  (вариации в landowner — OCR-ошибки или грамматические формы)
- **Восприемник должен быть старше 10 лет**
- **Статусные слова в поле landowner** ("крестьянин", "дворовый",
  "крестьянская девица") — это НЕ помещики, игнорировать при сравнении
- **"та же деревня", "то же сельцо"** — контекстные ссылки, могут быть
  не разрешены в одной из записей

---

## Output Format

### Classifications

```json
{
  "model": "gpt-4o",
  "total_candidates": 50,
  "total_classified": 50,
  "same_count": 23,
  "classifications": [
    {
      "id_a": 1086,
      "id_b": 1088,
      "label_a": "Михаил Афанасьев",
      "label_b": "Михаил Афанасьев",
      "decision": "SAME",
      "confidence": "high",
      "reasoning": "Оба женаты на одной женщине (id=1910), живут в одной деревне, разные роли — один человек",
      "edge_score": 10,
      "shares_settlement": true,
      "shares_landowner": true,
      "shared_spouses": [1910]
    }
  ],
  "merge_groups": [
    {
      "target_id": 1086,
      "source_ids": [1088],
      "members": [1086, 1088],
      "reasoning": "Оба женаты на одной женщине..."
    }
  ]
}
```

### Merge Groups

Классификации `SAME` объединяются транзитивно: если A=B и B=C, то A, B, C
сливаются в один кластер с одним target (наименьший id) и несколькими sources.

---

## When NOT to Use

- **Очевидные разные люди**: если у двух персон разные поселения, разные
  помещики И нет общих связей — LLM не поможет, это действительно разные люди
- **Первая дедупликация**: детерминированный алгоритм работает хорошо для
  базового случая. LLM — только для спорных случаев
- **Массовые переименования**: если нужно систематически исправить написание
  имени (напр. везде заменить Феодор→Федор), используй нормализацию имён

---

## Related Files

| Файл | Назначение |
|------|-----------|
| `llm_dedup.py` | Инструмент LLM-дедупликации |
| `parsing/dedup.py` | Детерминированный алгоритм дедупликации |
| `merge_persons.py` | Ручное слияние персон |
| `manual-merges.json` | Манифест слияний |
| `all-nodes.json` | Данные персон |
| `all-edges.json` | Рёбра графа |
