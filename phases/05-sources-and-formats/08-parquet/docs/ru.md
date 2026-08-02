# Parquet и колоночное хранение

> Расширение `.parquet` ещё не доказывает надёжную поставку: зафиксируйте типы до записи
> и проверьте фактические schema, values, nulls и writer metadata после неё.

**Тип:** Learn  
**Треки:** Core  
**Пререквизиты:** 05/07  
**Время:** ~75 минут  
**Результат:** преобразует ограниченный UTF-8 CSV-снимок в Parquet по явному контракту,
проверяет roundtrip и физические metadata и передаёт файл вместе с checksum-manifest.

## Цели обучения

После урока вы сможете:

- объяснить разницу между строковым CSV и типизированным Parquet;
- связать table, row group, column chunk и page без погружения в бинарную спецификацию;
- объявить порядок колонок, logical types, null policy, grain и writer settings до записи;
- безопасно преобразовать деньги в `decimal128` и однозначное время в UTC timestamp;
- проверить после записи схему, значения, порядок, пропуски, compression, statistics и row groups;
- передать Parquet и manifest без локальных абсолютных путей и молчаливой обрезки входа.

## Связь с предыдущими уроками

В `05/01` вы уже увидели исходную проблему: CSV хранит текстовые токены, а encoding,
dialect, null policy и типы живут во внешнем договоре. Там источник проверялся до
анализа. В `05/07` SQLAlchemy-reader отделил извлечение из БД от проверяемого snapshot и
не разрешал успешному `execute()` подменять проверку результата.

Теперь появляется следующий рабочий вопрос: **в каком формате сохранить проверенную
таблицу, чтобы следующий инструмент не угадывал типы заново?**

```text
проверенный CSV или срез БД
→ явные типы, null policy, domain и grain
→ Arrow Table как объект writer API
→ Parquet candidate
→ roundtrip + physical metadata checks
→ Parquet + checksum-manifest
```

CSV снова используется намеренно: на одних и тех же строках видна разница между
внешней схемой текстового источника и схемой внутри Parquet. В рабочем pipeline строки
могут прийти и из SQLAlchemy, API или другой системы; правила поставки от этого не
меняются.

`pyarrow.Table` в этом уроке — прозрачный типизированный объект, который принимает
Parquet writer. Устройство Arrow buffers, обмен с pandas и вопрос zero-copy относятся к
`05/09`. Здесь они не являются скрытым пререквизитом.

## Проблема

Есть UTF-8 CSV заказов:

```csv
order_id,user_id,ordered_at,amount,currency,comment
O2401,U001,2026-05-01T10:00:00Z,1200.50,RUB,first
O2402,U002,2026-05-02T08:30:00Z,950.00,RUB,
```

После `csv.DictReader` все шесть значений остаются строками. По самим байтам нельзя
доказать, что:

- `1200.50` — точная денежная сумма, а не binary float;
- пустой `comment` означает `null`, а пустой `user_id` запрещён;
- `ordered_at` содержит однозначный момент времени;
- `order_id` не повторяется;
- `currency` ограничена договорным доменом;
- порядок и типы колонок не изменились.

Наивная конвертация решает только вопрос расширения файла:

```python
table = pa.Table.from_pylist(rows)
pq.write_table(table, "orders.parquet")
```

Inference может выбрать `string`, `double` или другой правдоподобный тип. Даже если
writer завершился без исключения, остаются независимые риски:

1. naive timestamp был молча истолкован как UTC;
2. `1200.501` был округлён до scale 2;
3. пустой обязательный идентификатор сохранился как допустимая строка;
4. новый `USD` прошёл вне бизнес-домена;
5. повторный `order_id` изменил grain;
6. writer settings в файле не совпали с ожидаемыми;
7. повреждённый candidate заменил предыдущую поставку.

Нужна не просто команда записи, а проверяемая граница формата.

## Концепция

### Что меняется по сравнению с CSV

| Свойство | CSV | Parquet |
|---|---|---|
| Значения | Текстовые токены | Типизированные encoded values |
| Схема | Отдельный контракт | Физические и logical types записаны в metadata |
| Null | Договорный текстовый маркер | Отдельное представление отсутствия значения |
| Организация | Последовательность строк | Column chunks внутри row groups |
| Compression | Обычно снаружи всего файла | Отдельно для column chunks/pages |
| Частичное чтение | Парсер обычно проходит текст | Reader может запросить только нужные колонки |
| Бизнес-смысл | Не хранится автоматически | Тоже не возникает автоматически |

Parquet хранит больше технического контекста, но не заменяет data contract. Файл знает,
что `amount` имеет logical type decimal, однако не знает, должна ли сумма быть
неотрицательной. Он может хранить `order_id` как required string, но сам формат не
доказывает его уникальность.

Поэтому контракт урока содержит и то, что станет schema файла, и внешние ожидания:

```text
columns     → имена, порядок, logical type, nullable, empty_as_null, domain
grain       → ключ уникальности строк
allow_empty → допустима ли поставка без наблюдений
writer      → compression, statistics и учебный row_group_size
```

### От таблицы к pages

Представьте пять заказов и шесть колонок. Writer с `row_group_size=3` разделит строки
горизонтально:

```text
Parquet file
├── row group 0: строки 1–3
│   ├── order_id column chunk → pages
│   ├── amount column chunk   → pages
│   └── ...
└── row group 1: строки 4–5
    ├── order_id column chunk → pages
    ├── amount column chunk   → pages
    └── ...
```

- **Row group** — горизонтальный блок строк.
- **Column chunk** — значения одной колонки внутри одного row group.
- **Page** — меньшая единица encoding и compression внутри column chunk.
- **Footer metadata** — схема и адреса блоков, которые reader читает перед нужными
  column chunks.

Число `3` выбрано только для наблюдаемого tiny-эксперимента: пять строк дают два row
groups. Это не рекомендация для production. Выбор размера по объёму и workload, а также
измерение pruning появятся в `12/04`.

### Физический и logical type

Parquet имеет небольшой набор физических представлений и logical annotations поверх
них. Аналитику важен смысл, который увидит reader:

```text
amount     → decimal128(12, 2)
ordered_at → timestamp[us, tz=UTC]
comment    → string nullable
```

`decimal128(12, 2)` означает максимум 12 значащих десятичных цифр, из которых две —
после точки. Артефакт принимает `1200.5` и сохраняет `1200.50`, но отвергает `1200.501`
вместо скрытого округления. `NaN` и `Infinity` тоже отвергаются: конструктор `Decimal`
может создать их, однако денежный контракт не считает их суммами.

Timestamp обязан закончиться `Z` или числовым UTC offset. Значение
`2026-05-01T13:00:00+03:00` нормализуется в тот же момент, что
`2026-05-01T10:00:00Z`. Naive-строка не получает придуманную timezone.

### Nullable — не правило для пустой CSV-строки

Parquet различает value и null. CSV содержит только токен, поэтому переход нужно задать
явно для каждой колонки:

```json
{
  "name": "comment",
  "type": "string",
  "nullable": true,
  "empty_as_null": true
}
```

У обязательного `user_id` `empty_as_null=false`: пустая строка является ошибкой, а не
допустимым identifier. Нельзя вывести эту политику только из `nullable` или из поведения
библиотеки по умолчанию.

### Compression и statistics — свойства блоков

Writer применяет ZSTD внутри Parquet column chunks. Это не то же самое, что положить
целый файл в ZIP: reader по-прежнему видит footer и может выбирать колонки.

Statistics вроде min, max и null count хранятся в metadata row groups, если writer их
создал. Некоторые движки используют их, чтобы пропустить блоки. Но наличие statistics
не доказывает ускорение конкретного запроса. Оно зависит от распределения, row-group
layout, фильтра и reader implementation. В этом уроке мы проверяем только факт metadata;
query plan и benchmark относятся к `12/04`.

### Размер tiny-файла ничего не доказывает

У пяти строк footer, schema и metadata могут стоить больше самих значений. Поэтому
маленький Parquet способен быть больше CSV. Формат выбирают ради типизированной
совместимости и аналитического workload, а compression сравнивают на репрезентативном
объёме. Один tiny-result нельзя превращать в production-обещание.

### Manifest связывает четыре независимых объекта

Поставляется не только `orders.parquet`:

```text
source bytes   ─┐
contract bytes ─┼→ conversion → verified Parquet bytes
writer policy  ─┘                    ↓
                              checksum-manifest
```

Manifest хранит SHA-256 source, contract и Parquet, PyArrow version, writer settings,
фактическую schema, row groups, compression и результаты checks. Он использует только
имена файлов, поэтому не раскрывает домашнюю директорию автора.

Parquet публикуется первым, manifest — последним как completion marker. Получатель всё
равно сверяет checksum: два соседних `os.replace()` не являются общей файловой
транзакцией. Ошибка данных или roundtrip до публикации сохраняет предыдущую пару.

## Соберите это

### Шаг 1. Увидьте потерянные типы

Запустите пример из директории урока:

```bash
uv run --locked python code/main.py
```

Первая часть читает CSV стандартным модулем и показывает:

```text
amount     → str
ordered_at → str
```

До PyArrow вручную преобразуйте один ряд:

```python
amount = Decimal(raw["amount"])
ordered_at = datetime.fromisoformat(
    raw["ordered_at"].replace("Z", "+00:00")
).astimezone(UTC)
```

Здесь важно не само количество строк кода, а момент принятия решения: тип появляется из
контракта, а не из расширения будущего файла.

### Шаг 2. Объявите schema до Table

`parquet_schema.json` версии `2.0.0` задаёт колонки списком, поэтому порядок является
частью договора. Артефакт преобразует его в Arrow schema:

```python
schema = pa.schema(
    [
        pa.field("order_id", pa.string(), nullable=False),
        pa.field("ordered_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("amount", pa.decimal128(12, 2), nullable=False),
    ]
)
```

До `pa.Table.from_pylist()` CSV проходит structural и semantic gates:

1. bytes не превышают объявленный предел и строго декодируются как UTF-8;
2. header точно совпадает по именам и порядку;
3. ширина каждой строки равна ширине schema;
4. непустые values приводятся с номером проблемной строки;
5. `empty_as_null`, domains и grain проверяются явно;
6. `max_rows` останавливает процесс, а не обрезает вход.

Ограничения честно отражают реализацию: учебный converter держит один bounded snapshot
в памяти. Большие потоки требуют batch/streaming writer, а не бесконечного увеличения
лимита.

### Шаг 3. Предскажите физическую metadata

До запуска запишите ожидания для пяти строк:

```text
schema amount      = decimal128(12, 2)
schema ordered_at  = timestamp[us, tz=UTC]
null comment       = 2
row groups         = 2: [3, 2]
compression        = ZSTD у каждого column chunk
statistics         = присутствует у каждого column chunk
grain              = unique order_id
```

Только после предсказания сравните вывод `code/main.py`.

## Используйте это

Запустите самостоятельный CLI из директории урока:

```bash
uv run --locked python outputs/parquet_converter.py \
  --input ../data/tiny/orders_typed.csv \
  --output delivery/orders.parquet \
  --schema ../data/parquet_schema.json \
  --manifest delivery/orders.manifest.json
```

Если `--manifest` не указан, создаётся
`delivery/orders.parquet.manifest.json`. Пределы bounded implementation можно уменьшить
для проверки или задать явно:

```bash
uv run --locked python outputs/parquet_converter.py \
  --input ../data/tiny/orders_typed.csv \
  --output delivery/orders.parquet \
  --schema ../data/parquet_schema.json \
  --max-rows 1000 \
  --max-bytes 1000000
```

Успех возвращает code `0` и печатает manifest. Contract/source error возвращает `2`,
roundtrip verification failure — `1`. Невалидный candidate не заменяет предыдущую
поставку.

### Прочитайте только нужные колонки

Колоночный интерфейс виден без benchmark:

```python
projection = pq.read_table(
    "delivery/orders.parquet",
    columns=["order_id", "amount"],
)
```

Reader получает таблицу только с двумя полями. Из этого ещё нельзя заключать, сколько
миллисекунд или байтов сэкономлено на конкретной машине. Здесь проверяется возможность
projection, а не production-speedup.

### Проверьте вторым движком

DuckDB читает поставку без повторного CSV parsing:

```sql
SELECT order_id, amount
FROM read_parquet('delivery/orders.parquet')
WHERE amount >= 900
ORDER BY order_id;
```

Это небольшой portability smoke test: decimal values и порядок результата совпадают.
Полный контракт обмена между PyArrow, pandas и DuckDB будет предметом `05/09`.

## Сломайте это

### Правдоподобный неверный decimal

Замените `1200.50` на `1200.501`. Silent rounding мог бы дать убедительную сумму, но
converter должен назвать строку и превышенный scale и не публиковать файл.

### Время без offset

Удалите `Z` из `2026-05-01T10:00:00Z`. Не разрешайте машине автора подставлять локальную
timezone: один и тот же CSV иначе обозначит разные моменты.

### Пустой обязательный identifier

Оставьте `user_id` пустым. `string` не означает, что `""` является допустимым ключом;
ошибка должна возникнуть до Arrow Table.

### Schema и domain drift

1. Поменяйте местами `order_id` и `user_id` в header.
2. Добавьте `USD`, не обновляя domain contract.
3. Повторите `order_id` в последней строке.
4. Укажите неизвестную contract version или duplicate JSON key.

Каждый дефект относится к разному слою: structure, domain, grain или configuration.

### Недоказанная полнота

Запустите converter с `--max-rows 4` для пяти строк. Правильное поведение — ошибка без
Parquet, а не «успешный» файл из первых четырёх заказов.

### Повреждение writer candidate

Behavioral test подменяет roundtrip check отрицательным результатом. Существующие
Parquet и manifest остаются прежними, а временный candidate удаляется.

## Проверьте это

Тесты проверяют наблюдаемое поведение, а не строки реализации:

- точные schema, field order и nullability;
- decimal values, scale, precision и конечность;
- timezone requirement и нормализацию numeric offset в UTC;
- null policy обязательных и nullable string fields;
- header width/order, domain и grain;
- row/byte limits без truncation;
- values/order/nulls после roundtrip;
- два row groups `[3, 2]`, ZSTD и statistics в metadata;
- чтение typed projection через DuckDB;
- SHA-256 source, contract и artifact без абсолютных путей;
- строгую contract version, unknown и duplicate keys;
- сохранение предыдущей поставки при source и verification failure;
- CLI happy path и различимый code `2` для contract failure.

Запустите:

```bash
uv run --locked python -m unittest discover -s tests -v
```

Для ручной проверки manifest:

```bash
uv run --locked python -c \
  'import json, pathlib; p=pathlib.Path("delivery/orders.manifest.json"); print(json.loads(p.read_text())["checks"])'
```

Наличие файла и code `0` недостаточны. Поставка валидна, когда все checks истинны и
получатель может заново вычислить checksum Parquet.

## Поставьте результат

`outputs/parquet_converter.py` — самостоятельный CLI для одного bounded UTF-8 CSV
snapshot. Ему нужны только input, schema contract и output path; notebook state,
локальная БД и secrets не требуются.

Поставка состоит из:

```text
orders.parquet
orders.manifest.json
```

Parquet несёт техническую schema и values. Manifest добавляет source/contract identity,
grain и domain contract, writer policy, observed metadata и checks. Получатель сначала
проверяет `summary.valid`, затем SHA-256 файла, а уже после читает данные.

Артефакт сознательно не решает соседние задачи:

- Arrow memory layout, pandas interchange и zero-copy — `05/09`;
- каталоги, partition keys и small-files problem — `05/10`;
- measured projection/predicate pushdown и выбор row-group layout — `12/04`;
- schema evolution множества файлов и table formats — за границей core-урока.

## Упражнения

1. Добавьте nullable `discount_amount: decimal128(12, 2)` и решите, означает ли пустой
   CSV token `null` или нулевую скидку. Зафиксируйте решение в contract и тесте.
2. Создайте копию fixture с `2026-05-01T13:00:00+03:00` и докажите, что Parquet хранит
   тот же UTC-момент, что исходное значение с `Z`.
3. Сравните ZSTD и Snappy на репрезентативно размноженном наборе. Отдельно запишите
   размер и время записи/чтения, но не объявляйте победителя по tiny-файлу.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| Parquet | «CSV, только сжатый» | Типизированный колоночный файловый формат с footer metadata |
| Row group | Отдельная таблица | Горизонтальный блок строк, содержащий column chunk для каждого поля |
| Column chunk | Вся колонка во всём dataset | Значения одной колонки внутри одного row group |
| Page | Строка файла | Меньший encoded/compressed блок внутри column chunk |
| Logical type | Python-класс | Семантическая аннотация поверх физического Parquet representation |
| Nullable | Пустая строка автоматически равна null | Разрешение отсутствующего value; mapping CSV-токена задаётся отдельно |
| Compression | ZIP всего файла | Codec, применяемый к data pages/column chunks |
| Statistics | Гарантия быстрого фильтра | Metadata, которую совместимый reader может использовать для skipping |
| Projection | Фильтр строк | Чтение выбранного набора колонок |
| Roundtrip | Файл открылся | Сравнение прочитанных schema, values, order и nulls с входной таблицей |
| Manifest | Копия Parquet | Проверяемая связь source, contract, writer policy и artifact checksum |

## Дополнительное чтение

- [RU · Yandex Cloud: форматы данных и алгоритмы сжатия](https://yandex.cloud/ru/docs/query/sources-and-sinks/formats) — сравните разделы `csv_with_names` и `parquet`, затем выпишите поддерживаемые codecs. Страница показывает, какие договоры становятся явной конфигурацией внешнего query engine.
- [RU · Microsoft Learn: формат Parquet в Azure Data Factory и Synapse](https://learn.microsoft.com/ru-ru/azure/data-factory/format-parquet) — прочитайте разделы про Parquet source, sink и physical schema. Это пример передачи того же формата между storage и промышленным ingestion workflow.
- [RU · Python: `decimal`](https://docs.python.org/ru/3/library/decimal.html#decimal.Decimal.is_finite) — повторите создание `Decimal`, специальные значения и `is_finite()`. Материал объясняет, почему денежный contract отдельно отвергает `NaN`, `Infinity` и лишний scale.
- [EN · PyArrow: Reading and Writing Parquet](https://arrow.apache.org/docs/python/parquet.html) — разберите single-file read/write, subset of columns, timestamp handling и compression. Это основной API-контракт урока и граница перед datasets.
- [EN · PyArrow: `write_table`](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.write_table.html) — изучите `row_group_size`, `version`, `compression` и `write_statistics`. Сопоставьте каждый параметр с полем writer contract, не включая экспериментальные options без задачи.
- [EN · PyArrow: `schema`](https://arrow.apache.org/docs/python/generated/pyarrow.schema.html) — прочитайте примеры `field(..., nullable=False)` и schema metadata. Это точное продолжение явных fields, которые converter строит до Table.
- [EN · Apache Parquet: File Format](https://parquet.apache.org/docs/file-format/) — проследите layout от magic bytes через column chunks до footer. Раздел нужен для причинной модели частичного чтения, а не для реализации собственного parser.
- [EN · Apache Parquet: Logical Types](https://parquet.apache.org/docs/file-format/types/logicaltypes/) — найдите Decimal и Timestamp и свяжите logical annotation с физическим representation. Обратите внимание на precision, scale и UTC semantics.
- [EN · Apache Parquet: Metadata](https://parquet.apache.org/docs/file-format/metadata/) — различите file metadata и page headers. Затем найдите в manifest урока только те observed properties, которые действительно прочитал `ParquetFile`.
- [EN · DuckDB: Reading and Writing Parquet](https://duckdb.org/docs/stable/data/parquet/overview) — выполните direct query и посмотрите раздел Partial Reading. Документация объясняет projection/filter pushdown, а измерение и query-plan evidence сознательно отложены до `12/04`.
