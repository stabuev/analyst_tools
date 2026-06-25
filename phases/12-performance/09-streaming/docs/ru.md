# Streaming и пакетная обработка

> Chunking ограничивает память только тогда, когда между партиями остается ограниченное и
> математически корректное состояние.

**Тип:** Build
**Треки:** Data, ML
**Пререквизиты:** `12-performance/08-lazy-execution`
**Время:** ~75 минут
**Результат:** проектирует chunked/streaming обработку для ограниченной памяти, отличает
ассоциативные агрегаты от операций с полной координацией и выпускает checkpointed batch
report.

## Цели обучения

- Обработать набор Parquet-файлов по одной партии, не собирая весь input в памяти.
- Выделить partial state для `sum`, `count` и среднего через `sum + count`.
- Показать контрпример, где median-of-medians меняет результат.
- Сохранить атомарный checkpoint и безопасно продолжить расчет после сбоя.
- Сверить ручной processor с pandas control и `Polars collect(engine="streaming")`.

## Проблема

После lazy optimization вход все равно может быть больше доступной памяти. Простая
реакция - "читать по чанкам". Но разрезать input недостаточно:

- если складывать средние партий, результат зависит от их размеров;
- если брать median от batch medians, теряется глобальный порядок;
- если хранить set всех пользователей для exact distinct, state растет вместе с
  кардинальностью;
- если после сбоя запустить цикл заново, уже учтенные партии попадут в отчет второй раз;
- если вход изменился между попытками, старый checkpoint больше не описывает тот же
  расчет.

Поэтому streaming pipeline - это договор о трех вещах:

1. единица чтения;
2. merge-состояние;
3. граница повторного запуска.

## Концепция

Для группы `week_start, platform, region` суммы и количества можно считать независимо в
каждой партии:

```text
partial_a = {orders: 120, net_revenue: 500000}
partial_b = {orders: 80,  net_revenue: 310000}
merged    = {orders: 200, net_revenue: 810000}
```

Операция merge ассоциативна:

```text
(a + b) + c = a + (b + c)
```

Поэтому порядок партий не меняет результат. Производные метрики считаются после merge:

```text
revenue_per_paid_order = total_net_revenue / total_paid_orders
```

Не каждую операцию можно свести к фиксированному state:

| Операция | Стратегия | State ограничен? |
|---|---|---:|
| `sum`, `count`, `min`, `max` | merge partial scalar | да |
| mean | merge `sum + count` | да |
| exact median/quantile | нужен глобальный порядок или exact selection | нет |
| exact distinct | можно merge set, но он растет с cardinality | нет |
| global rank | нужна координация всех кандидатов | нет |

`safe_for_chunk_merge` и `bounded_state` - разные свойства. Exact distinct set можно
объединять корректно, но это не гарантирует ограниченную память.

## Соберите это

Артефакт создает несколько Parquet-файлов и обрабатывает их по одному.

### Шаг 1. Зафиксируйте manifest

```python
manifest = build_input_manifest(data_dir)
```

Для каждого файла сохраняются:

- имя;
- число строк;
- размер;
- SHA-256.

Общий `manifest_sha256` входит в checkpoint. Если любой input изменился, resume
останавливается вместо смешивания двух версий данных.

### Шаг 2. Рассчитайте partial aggregate

```python
partial_groups = aggregate_batch(batch)
merge_partial_groups(state, partial_groups)
```

В state лежат только additive metrics:

```text
orders
paid_orders
gross_revenue_cents
refund_amount_cents
net_revenue_cents
support_ticket_count
```

`refund_rate_bp` и `revenue_per_paid_order_cents` не усредняются между партиями. Они
считаются один раз в `finalize_state`.

### Шаг 3. Поставьте durable checkpoint

После полного merge одного файла processor записывает:

```text
checkpoint.json.tmp
```

и атомарно заменяет им:

```text
checkpoint.json
```

В checkpoint есть manifest hash, завершенные файлы, число обработанных строк и partial
groups. Файл помечается завершенным только после того, как вся партия прошла чтение,
валидацию и merge.

### Шаг 4. Симулируйте сбой

Артефакт специально прерывается после двух партий:

```python
process_batches(..., stop_after_files=2)
```

Повторный вызов читает checkpoint, пропускает два завершенных файла и продолжает с
третьего. Итог сверяется с полным pandas control, чтобы доказать отсутствие пропусков и
двойного учета.

### Шаг 5. Сломайте median-of-medians

Контрольный пример:

```text
chunks = [[1, 2, 100], [3, 4]]
chunk medians = [2, 3.5]
median of medians = 2.75
exact median = 3
```

Это не проблема конкретной библиотеки. Потеря происходит в момент, когда каждая партия
сводится к одной медиане.

## Используйте это

Запустите демонстрационный пример:

```bash
uv run --locked python phases/12-performance/09-streaming/code/main.py
```

Запустите CLI:

```bash
uv run --locked python phases/12-performance/09-streaming/outputs/streaming_batch_processor.py \
  --rows 4800 \
  --batch-size 600 \
  --users 640 \
  --interrupt-after 2 \
  --output-dir /tmp/streaming-batch-report
```

Пакет содержит:

- `data/batch-*.parquet` - входные партии;
- `input-manifest.json` - immutable input identity;
- `checkpoint.json` - durable partial state;
- `batch-output.csv` - результат ручного processor;
- `pandas-control.csv` - полный контрольный расчет;
- `polars-streaming-output.csv` - результат Polars streaming engine;
- `streaming-plan.txt` - optimized lazy plan;
- `correctness-report.json` и `report.json` - проверки.

Polars-версия pipeline запускается так:

```python
lazy_frame.collect(engine="streaming")
```

Это запрос streaming engine, а не абсолютная гарантия. Polars может откатиться к
in-memory engine для неподдерживаемой операции. Кроме того, group state может быть
слишком большим даже при потоковом чтении. Поэтому отчет сохраняет план и отдельную
оговорку о fallback.

## Сломайте это

### Усредните средние партий

Партии разного размера получают одинаковый вес. Храните `sum` и `count`, а деление
делайте после merge.

### Сложите batch distinct counts

Один пользователь может встретиться в нескольких файлах. Сумма `n_unique` по партиям
завысит exact distinct. Для точного результата нужен глобальный set или другой exact
алгоритм; для ограниченной памяти часто выбирают approximate sketch с явной погрешностью.

### Пометьте файл завершенным до merge

Сбой после такой записи создаст пропуск: resume решит, что партия уже учтена.

### Продолжите после изменения входа

Без manifest hash checkpoint незаметно объединит partial state старых файлов с новыми
данными.

### Считайте любой lazy query потоковым

Streaming-friendly scan не делает автоматически потоковыми exact median, global rank,
полную сортировку или state с высокой кардинальностью.

## Проверьте это

Точечные тесты:

```bash
uv run --locked python -m unittest discover \
  -s phases/12-performance/09-streaming/tests -v
```

Контракт готового отчета:

- input разбит минимум на две партии;
- максимальное число строк файла не превышает `batch_size`;
- после simulated interruption существует durable checkpoint;
- resume пропускает уже завершенные файлы;
- checkpoint покрывает весь manifest;
- ручной processor совпадает с pandas control;
- Polars streaming совпадает с pandas control;
- output grain уникален;
- median-of-medians counterexample действительно расходится с exact median.

## Поставьте результат

Именованный артефакт - CLI `streaming-batch-processor`:

```bash
uv run --locked python phases/12-performance/09-streaming/outputs/streaming_batch_processor.py \
  --rows 4800 \
  --batch-size 600 \
  --interrupt-after 2 \
  --output-dir /tmp/streaming-batch-report
```

Используйте его как основу batch runbook:

1. зафиксируйте identity входов;
2. сформулируйте merge state для каждой метрики;
3. проверьте одновременно correctness и boundedness state;
4. ставьте checkpoint только на завершенной единице работы;
5. симулируйте restart;
6. сверяйте итог с независимым control.

## Упражнения

1. Добавьте `min_order_cents` и `max_order_cents` в partial state и докажите
   эквивалентность полному расчету.
2. Попробуйте сложить `nunique(user_id)` по партиям, найдите расхождение и замените
   partial scalar на set. Измерьте рост state.
3. Добавьте corrupted checkpoint с неизвестным именем файла и убедитесь, что resume
   отклоняет его до чтения данных.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Chunking | Любой цикл по кускам экономит память | В памяти находится ограниченная партия и контролируемое межпартийное state |
| Associative merge | Все агрегаты можно сложить | Порядок группировки partial state не меняет результат |
| Bounded state | State меньше исходного DataFrame | Размер state имеет верхнюю границу, не зависящую от числа строк или cardinality |
| Checkpoint | Просто лог номера партии | Durable state плюс identity входа и завершенные атомарные единицы |
| Streaming fallback | Ошибка выполнения | Допустимый переход к in-memory engine, который нужно учитывать в memory claim |

## Дополнительное чтение

- [Polars: Streaming](https://docs.pola.rs/user-guide/concepts/streaming/) - разберите `collect(engine="streaming")`, physical graph и предупреждение о fallback.
- [Polars: LazyFrame.collect](https://docs.pola.rs/api/python/stable/reference/lazyframe/api/polars.LazyFrame.collect.html) - проверьте контракт параметра `engine` и границу материализации результата.
- [pandas: Scaling to large datasets](https://pandas.pydata.org/docs/user_guide/scale.html) - сопоставьте load-less-data, chunking и переход к другим библиотекам.
- [Python: `os.replace`](https://docs.python.org/3/library/os.html#os.replace) - прочитайте контракт атомарной замены файла, используемой для checkpoint.
