# Arrow memory model

> Zero-copy в Arrow - это проверяемое свойство конкретной границы обмена, а не
> обещание для любой конвертации.

**Тип:** Learn
**Треки:** Data, ML
**Пререквизиты:** `12-performance/04-parquet-pushdown`
**Время:** ~75 минут
**Результат:** разбирает Arrow buffers, null bitmaps, offsets, chunks и dictionary
encoding, инспектирует PyArrow Table/Array и отличает zero-copy обмен от скрытого
копирования.

## Цели обучения

- Разложить Arrow Array на physical buffers и понять роль каждого buffer.
- Отличить primitive values buffer от validity bitmap и offsets buffer.
- Увидеть, как dictionary encoding заменяет repeated strings на integer indices.
- Объяснить, почему `ChunkedArray` не равен одному непрерывному buffer.
- Проверить zero-copy и hidden copy через адреса buffers и `zero_copy_only=True`.

## Проблема

После урока про Parquet pushdown команда видит, что PyArrow, DuckDB и pandas могут
обмениваться таблицами. Возникает соблазн сказать:

```text
Перейдем на Arrow - и копий больше не будет.
```

Это неверно. Arrow задает columnar memory format, но копия зависит от конкретной
операции:

- primitive numeric array без null может дать NumPy view на тот же values buffer;
- nullable numeric array требует validity bitmap, с которой NumPy без nullable маски
  не справляется zero-copy;
- string array хранит offsets и values отдельно;
- chunked column состоит из нескольких arrays, а не одного непрерывного куска памяти;
- dictionary chunks могут иметь разные словари и требовать унификации;
- pandas DataFrame boundary имеет собственную block layout.

Если не проверить эти границы, можно получить красивый "Arrow pipeline" и неожиданный
memory spike на `to_pandas`, `combine_chunks` или dictionary unification.

## Концепция

Arrow Table состоит из columns. В PyArrow колонка таблицы обычно является
`ChunkedArray`: списком chunks, где каждый chunk - отдельный `Array`.

Каждый `Array` ссылается на physical buffers. Для разных типов набор buffers разный:

| Тип | Типичные buffers |
|---|---|
| `int64` без null | `values` |
| `int64` с null | `validity_bitmap`, `values` |
| `string` | `validity_bitmap`, `offsets`, `values` |
| `dictionary<string>` | `validity_bitmap`, `indices` плюс отдельный dictionary array |

### Validity bitmap

Validity bitmap хранит, какие позиции являются null. Это битовая маска, поэтому размер
маленький, но семантика большая: без нее нельзя отличить "значение равно 0" от "значения
нет".

### Offsets

Строки и binary values имеют переменную длину. Arrow не кладет каждую строку как
отдельный Python object. Вместо этого values buffer содержит байты, а offsets buffer
показывает границы каждой строки.

### Dictionary encoding

Repeated dimensions вроде `platform` можно хранить как integer indices плюс dictionary
values. Это экономит память и ускоряет некоторые операции, но dictionary chunks могут
иметь разные словари. Перед объединением или передачей в другой engine словари иногда
нужно унифицировать.

### Chunks

Chunked column появляется после чтения dataset, streaming batches или склейки таблиц.
Много chunks удобно для обработки по партиям, но это не один continuous buffer. Поэтому
операция, которая требует contiguous array, часто делает copy.

### Zero-copy

Zero-copy означает: consumer использует тот же memory buffer, не создавая новый массив
значений. Это можно проверить:

- вызвать conversion с `zero_copy_only=True`;
- сравнить адрес NumPy data pointer с адресом Arrow values buffer;
- посмотреть, сохранились ли buffer addresses после `slice`, `combine_chunks` или
  dictionary operation.

## Соберите это

Артефакт урока строит маленькую Arrow-таблицу `customer_revenue_health_weekly`. Она
специально содержит разные memory layouts:

- `net_revenue_cents` - primitive `int64` без null;
- `support_ticket_count` - nullable `int16`;
- `support_notes` - string with offsets;
- `platform` и `plan` - dictionary-encoded strings;
- все колонки chunked через `chunk_size`.

### Шаг 1. Создайте Arrow Table

```python
table = build_customer_revenue_arrow_table(rows=48, chunk_size=16, seed=42)
```

Это не pandas DataFrame, а `pyarrow.Table`. Данные уже лежат в Arrow arrays и chunks.

### Шаг 2. Инспектируйте колонку

```python
detail = inspect_chunked_array("support_notes", table["support_notes"])
```

Для string column вы увидите buffers:

```text
validity_bitmap
offsets
values
```

Если в chunk есть null, validity bitmap присутствует. Если null нет, buffer может быть
`None`: Arrow не тратит память на маску, когда все значения valid.

### Шаг 3. Найдите dictionary layout

```python
detail = inspect_chunked_array("platform", table["platform"])
```

Dictionary chunk содержит:

- indices buffer - integer ids в основной колонке;
- dictionary array - реальные значения вроде `web`, `ios`, `android`;
- dictionary buffers - offsets и values для строкового dictionary.

Это важно для dimensions: экономия памяти приходит не от "сжатия строк", а от замены
повторов на индексы.

### Шаг 4. Проверьте zero-copy NumPy

```python
audit = build_copy_audit(table)
```

Для первого chunk `net_revenue_cents` артефакт вызывает:

```python
array.to_numpy(zero_copy_only=True)
```

и сравнивает:

```text
Arrow values buffer address == NumPy data address
```

Если адреса совпали, это настоящий zero-copy view для этой конкретной границы.

### Шаг 5. Проверьте места копирования

Тот же audit показывает failure modes:

- nullable numeric array не проходит `zero_copy_only=True`;
- `ChunkedArray.to_numpy(zero_copy_only=True)` запрещен;
- multi-column `Table.to_pandas(zero_copy_only=True)` не проходит из-за pandas block
  layout;
- `split_blocks=True` все еще не помогает, пока columns остаются chunked;
- `combine_chunks()` делает contiguous single-chunk columns, но сама операция требует
  copy;
- `unify_dictionaries()` может переписать indices/dictionaries.

Именно поэтому "у нас Arrow" не равно "у нас нет копий".

## Используйте это

Запустите демонстрационный пример:

```bash
uv run --locked python phases/12-performance/05-arrow-memory/code/main.py
```

Запустите CLI-артефакт:

```bash
uv run --locked python phases/12-performance/05-arrow-memory/outputs/arrow_memory_inspector.py \
  --rows 48 \
  --chunk-size 16 \
  --seed 42 \
  --output /tmp/arrow-memory-report.json
```

В отчете смотрите три блока:

- `table.columns_detail` - schema, chunks, buffers, addresses, sizes;
- `buffer_findings` - короткие проверяемые выводы про layouts;
- `copy_audit` - успешные и неуспешные zero-copy boundaries.

Хороший минимальный результат:

```text
copy_audit.zero_copy_numpy.shares_arrow_values_buffer = true
copy_audit.combine_chunks.requires_copy = true
interpretation.safe_to_ship = true
```

## Сломайте это

### Добавьте null в numeric zero-copy candidate

Если `net_revenue_cents` станет nullable, NumPy zero-copy без nullable representation
сломается. Это не баг: у NumPy view нет отдельной Arrow validity bitmap.

### Увеличьте число chunks

Поставьте `chunk_size=4`. Таблица станет более фрагментированной, и границы, которым
нужен contiguous memory, начнут чаще требовать `combine_chunks()`.

### Уберите dictionary encoding

Сделайте `platform` обычной string column. Вы увидите offsets/values вместо indices и
dictionary. Для low-cardinality dimensions это часто дороже.

### Поверьте только `nbytes`

`nbytes` полезен, но он не объясняет, где лежат buffers и будут ли они переиспользованы.
Для copy audit нужны адреса buffers и явные проверки операций.

## Проверьте это

Точечная проверка урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/12-performance/05-arrow-memory/tests
```

Проверка артефакта:

```bash
uv run --locked python phases/12-performance/05-arrow-memory/outputs/arrow_memory_inspector.py \
  --rows 32 \
  --chunk-size 8 \
  --output /tmp/arrow-memory-report.json
```

Контракт отчета:

- numeric column без null не имеет validity bitmap;
- nullable numeric column имеет validity bitmap;
- string column имеет offsets и values buffers;
- dictionary column показывает indices и dictionary values;
- slice переиспользует source buffers;
- primitive numeric chunk проходит zero-copy NumPy;
- chunked table boundary явно показывает copy или отказ от zero-copy.

## Поставьте результат

Именованный артефакт урока:

```text
outputs/arrow_memory_inspector.py
```

Используйте его как шаблон перед изменением движка или формата:

1. выберите критичные колонки вашего pipeline;
2. посмотрите chunks и buffers;
3. проверьте null bitmaps, offsets и dictionary encoding;
4. отдельно проверьте границы `Arrow -> NumPy`, `Arrow -> pandas`, `combine_chunks`,
   `unify_dictionaries`;
5. оформите вывод как copy audit, а не как общую веру в zero-copy.

Для handoff приложите:

- schema и типы Arrow columns;
- список buffers для ключевых колонок;
- copy audit с успешными и неуспешными boundaries;
- ограничения, где copy ожидаем и допустим;
- решение, где оставлять Arrow, где идти в pandas, а где менять layout.

## Упражнения

1. Добавьте колонку `is_trial` типа `bool` и посмотрите, как Arrow хранит boolean values.
2. Сравните `platform` как dictionary и как plain string по `total_buffer_size`.
3. Постройте таблицу с `chunk_size=1` и объясните, почему это плохо для границ обмена.
4. Добавьте `timestamp[ns, tz=UTC]` и проверьте, сохраняется ли timezone при
   `to_pandas`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Arrow Array | "Это просто список Python objects" | Columnar array, который ссылается на typed buffers и metadata. |
| Validity bitmap | "Null хранится как отдельное значение" | Битовая маска, которая сообщает, какие позиции valid. |
| Offsets buffer | "Строки лежат отдельными объектами" | Буфер границ для variable-length values, байты лежат в values buffer. |
| Dictionary encoding | "Это compression без последствий" | Значения представлены integer indices, а dictionary хранится отдельно и может требовать унификации. |
| ChunkedArray | "Это один array" | Последовательность Arrow arrays, часто возникающая после dataset/streaming операций. |
| Zero-copy | "Arrow всегда без копий" | Конкретная операция переиспользует тот же memory buffer без allocation. |
| `combine_chunks` | "Просто косметика" | Операция делает contiguous chunks и обычно копирует buffers. |

## Дополнительное чтение

- [PyArrow Data Types and In-Memory Data Model](https://arrow.apache.org/docs/python/data.html) - прочитайте разделы про Arrays, Tables и Schemas как Python API к Arrow memory model.
- [Arrow Columnar Format](https://arrow.apache.org/docs/format/Columnar.html) - изучите layouts для validity bitmap, variable-size binary и dictionary encoding.
- [pyarrow.Array API](https://arrow.apache.org/docs/python/generated/pyarrow.Array.html) - посмотрите `buffers()`, `get_total_buffer_size()`, `slice()` и `to_numpy(zero_copy_only=True)`.
- [pyarrow.ChunkedArray API](https://arrow.apache.org/docs/python/generated/pyarrow.ChunkedArray.html) - разберите `chunks`, `combine_chunks()` и `unify_dictionaries()`.
- [PyArrow Pandas Integration](https://arrow.apache.org/docs/python/pandas.html) - прочитайте раздел `Memory Usage and Zero Copy`, чтобы не обещать zero-copy там, где pandas layout требует копию.
