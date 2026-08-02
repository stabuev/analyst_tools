# Партиционирование наборов данных

## Цели обучения

После урока вы сможете:

- отличить filesystem partition от Parquet row group и SQL window partition;
- начать проектирование layout с representative workload, а не со списка колонок;
- вручную сравнить candidate layouts по filter coverage, числу partitions и перекосу;
- разделить partition filters и residual filters для конкретного запроса;
- записать выбранный Hive-partitioned dataset и восстановить ключи из путей;
- проверить schema, values, nulls, grain и workload results до публикации;
- сформулировать ограниченный вывод о fragment pruning без обещания ускорения.

Результат урока — CLI `verified-partitioned-dataset`. Он принимает типизированный
Parquet-файл и внешний layout contract, сравнивает объявленные варианты, строит выбранный
вариант во временном каталоге, проверяет его и только затем публикует единый пакет из
`data/` и `manifest.json`.

## Связь с предыдущим и следующим уроками

В 05/08 вы получили один проверенный Parquet-файл. В 05/09 прочитали его как Arrow Table
и научились отделять сохранность значений от metadata drift и поведения памяти. Здесь
таблица становится набором Parquet-файлов: часть значений переносится в структуру путей,
а потребитель собирает файлы обратно в один логический dataset.

Новый вопрос возникает только теперь:

```text
один проверенный Parquet
  → какие запросы будут читать dataset
  → какие candidate layouts им соответствуют
  → какой компромисс выбран
  → можно ли прочитать опубликованный пакет без изменения данных
```

В 05/11 этот пакет станет частью immutable версии устойчивого загрузчика. Там появятся
raw cache, run id и атомарный current pointer. Этот урок отвечает только за layout одной
версии и её приёмку.

В 12/04 вы вернётесь к теме производительности: прочитаете query plans, измерите
projection и predicate pushdown и разберёте row-group statistics. Здесь мы наблюдаем,
какие fragments PyArrow считает кандидатами, но не измеряем скорость и не называем
layout оптимальным для production.

## Проблема

Команда получила таблицу заказов и решила «ускорить всё» партиционированием. Кто-то
предлагает `order_id`, потому что это уникальный ключ. Кто-то — дату до дня. Третий
вариант — месяц и валюту, потому что отчёты обычно фильтруются по ним.

Все три варианта технически записываются:

```text
order_id=O2401/part-0.parquet
order_date=2026-05-01/currency=RUB/part-0.parquet
order_month=2026-05/currency=RUB/part-0.parquet
```

Но техническая допустимость не равна хорошему решению:

- `order_id` на пяти строках даёт пять partitions;
- day/currency тоже даёт по одной строке на partition;
- month/currency поддерживает заявленные фильтры, но редкая EUR-группа остаётся маленькой;
- month-only хранит все строки вместе и не помогает запросу только по валюте;
- ни один tiny-пример не сообщает размер будущих production-файлов.

Опасны два противоположных вывода:

1. «Чем больше ключей, тем лучше pruning» — игнорирует количество файлов и metadata
   overhead.
2. «На sample появился маленький файл, значит layout запрещён» — переносит пять учебных
   строк на неизвестный production volume.

Нужно сохранить решение, evidence и границы вывода, а не угадать универсальный ключ.

## Концепция

### Три разных значения слова partition

Студент уже встречал `PARTITION BY` в SQL window functions. Здесь слово означает другое.

| Механизм | Что разделяется | Когда существует |
|---|---|---|
| SQL window partition | строки логического результата запроса | во время вычисления окна |
| Dataset partition | файлы или каталоги по значениям ключей | в физическом layout dataset |
| Parquet row group | последовательность строк внутри одного файла | внутри Parquet metadata и bytes |

Dataset partition не является row group. Одна partition может содержать несколько
Parquet-файлов, а каждый файл — несколько row groups. И наоборот, маленький учебный
writer может создать один файл на каждую partition. Поэтому нельзя использовать
`partition_count`, `file_count` и `row_group_count` как синонимы.

### Hive-style layout

Hive-partitioned dataset кодирует имя поля и значение в сегментах пути:

```text
dataset/
└── order_month=2026-05/
    ├── currency=EUR/
    │   └── part-0.parquet
    └── currency=RUB/
        └── part-0.parquet
```

При записи PyArrow не обязан дублировать `order_month` и `currency` внутри каждого
Parquet-файла. При чтении `HivePartitioning` восстанавливает их из `key=value` path.
Отсюда новый инвариант: проверять надо логический dataset после discovery, а не только
schema одного физического файла.

В контракте урока значения partition columns не могут быть `NULL`. Разные engines имеют
разные соглашения о специальном null-сегменте, поэтому версия 1 не делает такое поведение
скрытым default.

### Начните с workload

Partition key полезен не потому, что колонка «важная», а потому, что значение известно
до открытия файла и часто присутствует в фильтрах потребителя.

Layout contract объявляет три representative queries:

```text
monthly_orders          WHERE order_month = '2026-05'
currency_orders         WHERE currency = 'EUR'
monthly_currency_orders WHERE order_month = '2026-05' AND currency = 'EUR'
```

Representative не означает «все будущие SQL-запросы». Это минимальная зафиксированная
модель чтения, относительно которой можно объяснить решение.

### Partition filter и residual filter

Для candidate `partition_by=[order_month]` запрос по месяцу и валюте делится:

```text
partition filter = order_month
residual filter  = currency
```

Месяц может исключить каталоги до открытия файлов. Валюта всё равно применяется к
строкам внутри выбранных файлов.

Для `partition_by=[order_month, currency]` оба условия являются partition filters. Для
`partition_by=[order_id]` ни одно условие workload не помогает отобрать файл.

Важно: наличие partition filter не гарантирует, что число fragments уменьшится на любом
input. В учебном наборе присутствует только май 2026 года, поэтому фильтр по маю выбирает
оба файла. Это корректный результат, а не доказательство сломанного pruning.

### Четыре оси сравнения candidate layout

**1. Workload coverage.** Какие фильтры можно применить к путям, а какие останутся
residual?

**2. Cardinality и дробность.** Сколько уникальных комбинаций ключа получается? Отношение
`partition_count / row_count` не является production-метрикой, но на tiny-input хорошо
показывает вариант «одна partition на строку».

**3. Распределение строк.** Минимум, медиана и максимум обнаруживают skew. У
month/currency распределение `[1, 4]`: выбор поддерживает workload, но риск редкой EUR
partition должен остаться в отчёте.

**4. Эксплуатационный контекст.** Каков ожидаемый объём, частота записи, файловая система,
стоимость listing и возможности потребителей? Эти сведения нельзя вывести из пяти строк.

Артефакт автоматизирует evidence, но не выбирает ключ вместо аналитика. Поле `selected`
в contract — явное решение автора layout.

### Маленькая partition и маленький файл

Это связанные, но не одинаковые понятия. Partition — логическая группа значений; writer
может создать в ней один или много файлов. Размер файла зависит также от числа строк,
ширины schema, compression, batch size и политики записи.

Порог `small_partition_rows=2` в уроке — только видимая диагностическая линия на
tiny-input. Он не является рекомендацией в байтах. Manifest прямо сохраняет scope:

```text
row-count distribution on this input; not a production file-size target
```

Production-решение требует репрезентативного объёма и измерений. Урок не превращает
учебные две строки в отраслевой стандарт.

### Что именно доказывает fragment selection

PyArrow `dataset.get_fragments(filter=...)` сообщает, какие fragments могут участвовать
в scan с данным expression. Если для EUR выбран один fragment из двух, это evidence
file-level pruning для данного layout и данного фильтра.

Это не доказывает:

- ускорение запроса на реальном размере;
- число прочитанных row groups или pages;
- одинаковое поведение всех engines;
- оптимальность candidate относительно будущего workload;
- отсутствие затрат на listing и открытие файлов.

Поэтому отчёт использует поле `fragment_reduction_observed`, а не `query_faster`.

### Публикация как единая операция

Старый builder сначала переименовывал data directory, а затем проверял его и отдельно
писал manifest. При провале потребитель мог увидеть невалидный dataset.

Новый workflow:

```text
validate source and contract
  → analyze all candidates in memory
  → write selected candidate to unique staging/data
  → read it back and execute declared workload
  → calculate checksums
  → write staging/manifest.json
  → atomically rename the whole package
```

Итоговый каталог не появляется до успеха всех checks. Случайный старый каталог с похожим
именем staging не удаляется: временный путь уникален.

## Соберите это

### Шаг 1. Посчитайте candidates без PyArrow Dataset

Запустите прозрачный пример:

```bash
uv run --locked python phases/05-sources-and-formats/10-partitioning/code/main.py
```

Он использует обычные словари, множества и `Counter`. Для каждого candidate вы увидите:

- число строк в каждой комбинации ключей;
- filter columns, совпавшие с partition keys;
- residual filters, которые всё равно применяются внутри файлов.

Сначала предскажите результат:

| Candidate | Partitions | Что поддерживает | Риск на sample |
|---|---:|---|---|
| month | 1 | month filters | currency остаётся residual |
| month_currency | 2 | весь объявленный workload | skew `[1, 4]` |
| day_currency | 5 | day/currency filters | одна строка на partition |
| order | 5 | lookup по order_id | не связан с workload |

Эта таблица является основанием решения. Вызов библиотеки только реализует выбранный
вариант.

### Шаг 2. Получите исходный Parquet

Повторите артефакт 05/08 в локальной папке:

```bash
mkdir -p work/05-partitioning
uv run --locked python \
  phases/05-sources-and-formats/08-parquet/outputs/parquet_converter.py \
  --input phases/05-sources-and-formats/data/tiny/orders_typed.csv \
  --schema phases/05-sources-and-formats/data/parquet_schema.json \
  --output work/05-partitioning/orders.parquet
```

### Шаг 3. Прочитайте layout contract

Откройте `phases/05-sources-and-formats/data/partition_layout_contract.json`.

Он содержит:

- точную schema, grain, row count и null counts источника;
- derivation `ordered_at → order_month/order_date` в UTC;
- четыре candidate layouts;
- поле `selected`, фиксирующее решение;
- representative workload;
- диагностический порог и явный запрет null partition values.

Parser не игнорирует неизвестные и повторные ключи. Новая версия контракта требует нового
осознанного parser, а не silent fallback.

### Шаг 4. Сравните candidates

Builder добавляет производные колонки и для каждого варианта считает:

```text
partition_count
partition_to_row_ratio
rows_per_partition: minimum / median / maximum
small_partition_count
one_partition_per_row
partition filters and residual filters per workload query
```

Ни один из этих показателей сам по себе не выбирает победителя. `selected` остаётся
decision record, а отчёт позволяет оспорить его предметно.

### Шаг 5. Запишите Hive dataset

Для выбранных полей строится явная partition schema:

```python
partition_schema = pa.schema([
    table.schema.field("order_month"),
    table.schema.field("currency"),
])

ds.write_dataset(
    table,
    staging_data,
    format="parquet",
    partitioning=ds.partitioning(partition_schema, flavor="hive"),
)
```

Запись идёт только в уникальный temporary sibling итогового package.

### Шаг 6. Проверьте логический dataset

После discovery выбранный dataset читается в исходном порядке колонок. Сравниваются:

- row count;
- имена и логические типы;
- все значения после canonical sort по grain;
- null counts;
- уникальность и обязательность grain;
- результаты каждого workload filter.

Checksums вычисляются для фактически записанных Parquet files. Только после этого
создаётся manifest и публикуется весь package.

## Используйте это

Запустите итоговый CLI из корня репозитория:

```bash
uv run --locked python \
  phases/05-sources-and-formats/10-partitioning/outputs/dataset_builder.py \
  --input work/05-partitioning/orders.parquet \
  --contract phases/05-sources-and-formats/data/partition_layout_contract.json \
  --output-dir work/05-partitioning/orders_dataset
```

Получится пакет:

```text
orders_dataset/
├── data/
│   └── order_month=2026-05/
│       ├── currency=EUR/part-0.parquet
│       └── currency=RUB/part-0.parquet
└── manifest.json
```

Сначала прочитайте `decision.candidates`, затем `decision.warnings`. В учебном результате
вы увидите warning о маленькой EUR partition. Он не делает semantic checks невалидными,
но обязан попасть в handoff.

В `workload` сравните два наблюдения:

- `currency_orders` выбирает один fragment из двух;
- `monthly_orders` выбирает оба, потому что sample содержит один месяц.

Оба запроса возвращают правильные строки. Только первый показывает фактическое сокращение
candidate fragments на этом input.

Manifest хранит только относительные package paths, SHA-256 source, contract и каждого
Parquet file, версии форматов и PyArrow. Локальные staging paths не должны утекать в
передаваемый результат.

## Сломайте это

### Сценарий 1. Выберите `order_id`

Поменяйте `selected` на `order`. Строгий contract отклонит решение: ни один фильтр
объявленного workload не содержит `order_id`. Даже до записи видно, что layout отвечает
другой задаче.

### Сценарий 2. Добавьте неизвестный partition key

Опечатка `order_mont` не должна молча создать странный каталог. Parser завершится с
ошибкой контракта и кодом CLI 2.

### Сценарий 3. Разрешите NULL в currency

Версия 1 требует `allow_null_partition_values=false`. Если source contract и данные
содержат null partition tuple, dataset не записывается. Политику специального null path
нельзя получать случайно от версии engine.

### Сценарий 4. Измените decimal schema

Приведите `amount` к `decimal128(13, 2)`. Значения могут остаться визуально теми же, но
source отклоняется до создания staging dataset.

### Сценарий 5. Повторите команду в существующий output

Builder не угадывает `append`, `overwrite` или `delete_matching`. Существующий package
остаётся без изменений, а запуск завершается ошибкой контракта.

### Сценарий 6. Сломайте проверку после записи

Если read-back или workload result отличается, временный package удаляется, итоговый
каталог не появляется. Это важнее красивого `summary.valid=false` рядом с уже
опубликованными ошибочными файлами.

### Сценарий 7. Примите отсутствие reduction за дефект

Фильтр `order_month=2026-05` выбирает все fragments текущего sample. Результат семантически
корректен. Для демонстрации month pruning нужен вход с несколькими месяцами, но добавлять
искусственные строки ради зелёного флага нельзя.

## Проверьте это

Запустите behavioral tests:

```bash
uv run --locked python -m unittest discover \
  -s phases/05-sources-and-formats/10-partitioning/tests -v
```

Тесты проверяют:

- четыре candidate layouts и их workload coverage;
- честный warning и ограничение sample diagnostic;
- Hive paths и восстановление partition columns;
- полный semantic roundtrip, а не только row count;
- точные результаты трёх workload filters;
- checksums и отсутствие абсолютных путей;
- строгую contract schema, версии и duplicate JSON keys;
- ошибки derived columns, partition keys и selected candidate;
- missing, oversized и повреждённый Parquet;
- schema drift, row-count drift, duplicate grain и null partition tuple;
- сохранность существующего output и чужого похожего staging path;
- cleanup после failed verification;
- коды CLI и запрет colliding paths.

Ключевой инвариант публикации:

```text
output package exists
  only if
source contract valid
AND selected decision valid for declared workload
AND dataset semantic roundtrip valid
AND all workload results match
AND files and manifest completed
```

Warning о размере partition не входит в semantic Boolean: на пяти строках невозможно
проверить production file-size target.

## Поставьте результат

Артефакт `verified-partitioned-dataset` передаётся как единый каталог. Получателю не
нужны исходная рабочая директория или незавершённый staging path.

Короткий handoff:

```text
Selected layout: order_month/currency.
Decision basis: three declared workload filters and four compared candidates.
Semantic roundtrip: schema, values, nulls and order_id grain preserved.
Observed fragment reduction: EUR filters only on this one-month sample.
Warning: one sample partition has one row; production file-size target not measured.
Integrity: source, contract and every Parquet file identified by SHA-256.
Publication: data and manifest appeared as one verified package.
```

Не пишите «запросы ускорились»: здесь нет benchmark и query plan. Не пишите «small files
устранены»: риск обнаружен, но production volume неизвестен.

## Упражнения

1. **Обязательное.** Для каждого candidate объясните, какие filters становятся
   partition filters, а какие residual. Не запускайте builder до прогноза.
2. **Обязательное.** Создайте копию контракта с `selected=month`. Сначала исправьте
   workload так, чтобы решение было допустимым, затем сравните candidate report.
3. **Перенос.** Добавьте к собственной таблице несколько месяцев и повторите
   `monthly_orders`. Объясните изменение `selected_fragments`, не сравнивая время.
4. **Диагностика.** Добавьте новый workload filter по `user_id`. Решите, должен ли он
   менять layout или остаться residual, и обоснуйте цену high cardinality.
5. **Граница.** Предложите production evidence для выбора file-size target: ожидаемый
   дневной объём, compression ratio, cadence записи и тип хранилища.

Compaction, bucketing, cloud catalog maintenance и benchmark query plans сознательно не
являются упражнениями этого урока.

## Ключевые термины

- **Dataset partition** — логическая группа данных, часто представленная каталогами по
  значениям partition keys.
- **SQL window partition** — группа строк для вычисления оконной функции; не filesystem
  layout.
- **Parquet row group** — блок строк внутри одного Parquet-файла.
- **Hive partitioning** — соглашение о путях вида `key=value`.
- **Partition key** — поле, значение которого кодируется в layout и может участвовать в
  раннем выборе файлов.
- **Candidate layout** — рассматриваемый набор partition keys до принятия решения.
- **Representative workload** — объявленный набор характерных фильтров потребителей.
- **Partition filter** — условие по partition key, применимое к file paths.
- **Residual filter** — условие, которое остаётся применить к строкам выбранных файлов.
- **Fragment** — сканируемая часть Arrow Dataset, в этом уроке Parquet file fragment.
- **Fragment pruning** — исключение неподходящих fragments по filter expression.
- **Cardinality** — число уникальных значений или комбинаций ключа.
- **Skew** — неравномерное распределение строк между partitions.
- **Small-file problem** — overhead множества файлов, а не просто «мало строк».
- **Staging package** — уникальный временный каталог до завершения проверок.
- **Atomic publish** — появление data и manifest как одного завершённого package.

## Дополнительное чтение

Материалы идут от русскоязычных ограничений выбора к точному API PyArrow и поведению
других engines.

1. [RU: Когда следует секционировать таблицы — Microsoft Learn](https://learn.microsoft.com/ru-ru/azure/databricks/tables/partitions) — прочитайте разделы о размере таблицы, cardinality и минимальном размере partition; особенно важно предупреждение, что рекомендации конкретной платформы нельзя автоматически переносить на обычный Hive/Parquet layout.
2. [RU: Чанки — YTsaurus](https://ytsaurus.tech/docs/ru/user-guide/storage/chunks) — изучите раздел «Размер чанков»: он объясняет metadata и I/O overhead большого числа мелких физических частей, не смешивая их с бизнес-grain.
3. [RU: Пользовательский ключ партиционирования — ClickHouse](https://clickhouse.com/docs/ru/engines/table-engines/mergetree-family/custom-partitioning-key) — сопоставьте рекомендацию не делать чрезмерно детальные partitions с candidate `order_id`; помните, что MergeTree parts не тождественны Parquet files урока.
4. [EN: Tabular Datasets — Apache Arrow](https://arrow.apache.org/docs/python/dataset.html) — прочитайте `Writing Datasets`, `Writing Partitioned Data` и фильтрацию Dataset; это основной концептуальный контракт используемого API.
5. [EN: `pyarrow.dataset.write_dataset` — Apache Arrow](https://arrow.apache.org/docs/python/generated/pyarrow.dataset.write_dataset.html) — сверьте `partitioning`, `basename_template`, `max_partitions` и особенно варианты `existing_data_behavior`; урок сознательно не выбирает append/overwrite автоматически.
6. [EN: `HivePartitioning` — Apache Arrow](https://arrow.apache.org/docs/python/generated/pyarrow.dataset.HivePartitioning.html) — изучите parsing `key=value`, schema и null fallback, чтобы понять восстановление виртуальных partition columns из путей.
7. [EN: Hive Partitioning — DuckDB](https://duckdb.org/docs/current/data/partitioning/hive_partitioning) — посмотрите чтение partition columns и filter pushdown другим engine; используйте как interoperability context, а не benchmark.
8. [EN: Optimize Data — Amazon Athena](https://docs.aws.amazon.com/athena/latest/ug/performance-tuning-data-optimization-techniques.html) — прочитайте `Pick partition keys` и `Avoid having too many files`: источник связывает workload, слишком много partitions и стоимость file listing в object storage.
9. [EN: Introduction to partitioned tables — BigQuery](https://cloud.google.com/bigquery/docs/partitioned-tables) — сравните column partitioning, pruning и платформенные ограничения с файловым Hive layout; различия не позволяют копировать настройки один к одному.
10. [EN: Parquet configurations](https://parquet.apache.org/docs/file-format/configurations/) — вернитесь к различию file, row group и page; материал готовит к измеряемому pushdown в 12/04, не расширяя текущую практику.
