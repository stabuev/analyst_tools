# SQL или DataFrame: выбор инструмента

> Не выбирайте инструмент по размеру знакомого кода. Сначала зафиксируйте grain,
> движение данных и границу ответственности, затем подтвердите решение фактами запуска.

**Тип:** Case
**Треки:** Core
**Пререквизиты:** 04/12
**Время:** ~120 минут
**Результат:** собирает две проверенные SQL-витрины с revenue по отдельным валютам без
материализации полных результатов в Python и защищает границу DuckDB, Python и pandas.

## Цели обучения

После урока вы сможете:

- разложить аналитический pipeline на реляционные преобразования, orchestration и
  локальное исследование;
- выбрать границу между DuckDB SQL, Python и pandas по grain и движению данных, а не по
  личной привычке;
- собрать `order_mart` и `user_summary`, не выгружая полные результаты через
  `fetchall()` или `DataFrame`;
- отделить инварианты публикации от известных контрольных чисел tiny-набора;
- сохранить разрешённую неполноту как warnings, а нарушения ключей и сверок — как
  blockers;
- поставить получателю переносимый пакет с SQL, provenance, checksums и командой
  независимой проверки;
- сформулировать честную границу вывода: один успешный запуск не доказывает универсальное
  преимущество движка.

## Связь с предыдущими уроками

Это интеграционный финал SQL-фазы. Он не добавляет ещё один синтаксис JOIN или новый вид
агрегации, а собирает уже освоенные механизмы в одну поставку.

| Что понадобится | Где это уже было | Как используется здесь |
|---|---|---|
| Grain и ключ | 04/01 | `orders` и `order_mart` остаются на grain `order_id` |
| Типизированный `DECIMAL` и `NULL` | 04/02–04/03 | Денежная сверка не переводится во `float`, неполнота не маскируется |
| Условная агрегация | 04/04 | Paid revenue считается отдельно по валютам без удаления остальных заказов |
| Cardinality и unmatched keys | 04/05 | Позиции агрегируются до JOIN, неизвестный пользователь сохраняется |
| CTE и decomposition | 04/06 | SQL assets читаются как последовательность именованных отношений |
| Доказательства качества | 04/01–04/06 | Source- и mart-инварианты образуют publish gate |
| Оконный порядок и frames | 04/07–04/08 | Проверяются отдельными phase-exit сценариями, а не вставляются в mart без бизнес-вопроса |
| Временные границы | 04/09 | Business date строится после явного преобразования timezone |
| Когортная модель | 04/10 | Проверяется отдельным phase-exit сценарием; order mart не подменяет cohort grid |
| Явное соединение и параметры | 04/11 | Python связывает значения, а SQL остаётся отдельным доверенным asset |
| План и граница performance-вывода | 04/12 | Перед сборкой package студент подтверждает plan shape отдельным отчётом |

### Входной phase-exit: подтвердите четыре механизма

Финальная витрина не должна искусственно использовать окно или когорту только ради
демонстрации синтаксиса. Но без отдельной проверки её можно собрать, пропустив значительную
часть фазы. Работая из корня репозитория, подготовьте локальный каталог и создайте заметку:

```bash
mkdir -p work
# затем откройте в редакторе work/phase-04-exit-check.md
```

Для каждой проверки сначала запишите прогноз, затем выполните точечный тест и сохраните
наблюдаемое evidence. Одного слова `OK` недостаточно.

#### 1. Оконный порядок — `04/07`

До запуска ответьте:

- какая колонка делает последовательность заказов пользователя детерминированной;
- изменится ли `rank`, если тот же tie-breaker добавить в peer-order;
- чем `NULL` на границе partition отличается от неизвестного `amount`.

Затем выполните:

```bash
uv run --locked python -m unittest discover \
  -s phases/04-sql-and-duckdb/07-window-functions/tests \
  -k tie_breaker
uv run --locked python phases/04-sql-and-duckdb/07-window-functions/code/main.py
```

В заметке укажите конкретные строки или колонки, подтвердившие прогноз.

#### 2. Оконный frame — `04/08`

Для ключей `1, 1, 2, 4` вручную предскажите состав frame для `ROWS` и `RANGE` на строках
`A` и `D`. Затем выполните:

```bash
uv run --locked python -m unittest discover \
  -s phases/04-sql-and-duckdb/08-window-aggregates-and-frames/tests \
  -k frame
uv run --locked python \
  phases/04-sql-and-duckdb/08-window-aggregates-and-frames/code/main.py
```

Запишите, где различие вызвано peers, а где — разрывом значений. Отдельно назовите
знаменатель rolling average при неизвестном `amount`.

#### 3. Когортный горизонт — `04/10`

До запуска объясните, почему отсутствие событий в завершённом месяце должно дать нулевую
ячейку, а будущий месяц не должен появляться в grid. Затем выполните:

```bash
uv run --locked python -m unittest discover \
  -s phases/04-sql-and-duckdb/10-cohorts/tests \
  -k cutoff
uv run --locked python phases/04-sql-and-duckdb/10-cohorts/code/main.py
```

Сохраните grain ячейки, правило знаменателя и evidence наблюдаемого нуля.

#### 4. План запроса — `04/12`

Сначала предскажите число чтений источника в baseline и candidate. Затем выполните:

```bash
uv run --locked python phases/04-sql-and-duckdb/12-query-plans/outputs/plan_report.py \
  --events phases/04-sql-and-duckdb/data/tiny/events.csv \
  --event-name order_paid \
  --output work/phase-04-plan-report.json
```

В заметке укажите plan signal, подтверждающий устранение повторного чтения, и отдельно
напишите, почему один tiny timing не доказывает устойчивое ускорение.

Phase-exit завершён, если четыре раздела содержат прогноз, наблюдение и объяснение
механизма. Это учебная самопроверка, а не автоматическая сдача или сертификат.

Новая задача урока — **граница инструментов**. Она отвечает сразу на три вопроса:

1. где выполняются преобразования;
2. в какой момент данные покидают движок;
3. кто принимает решение о публикации и проверяет поставку.

Оптимизация больших production-систем, распределённое выполнение, object storage и
оркестраторы остаются за пределами урока.

## Проблема

Нужно выпустить две таблицы для продуктовой команды:

- `order_mart.csv`: одна строка на заказ;
- `user_summary.csv`: одна строка на пару пользователя и валюты заказа.

Источники связаны так:

```text
users (user_id)
          \
           orders (order_id) ─── order_items (order_id, product_id)
```

Внешне задача допускает несколько реализаций.

### Вариант A: всё сразу загрузить в pandas

```python
users = pd.read_csv(users_path)
orders = pd.read_csv(orders_path)
items = pd.read_csv(items_path)

order_mart = (
    orders
    .merge(items, on="order_id", how="left")
    .merge(users, on="user_id", how="left")
)
```

Код короткий, но в нём уже две скрытые проблемы:

- все три источника материализованы в памяти Python до сокращения grain;
- JOIN с товарными позициями размножает строку заказа и его `amount`.

DataFrame сам по себе не создаёт ошибку. Ошибка возникает из-за незаявленного grain и
необоснованного перемещения полного объёма в процесс Python.

### Вариант B: один SQL-текст внутри Python

```python
sql = f"""
SELECT ...
FROM read_csv('{orders_path}') ...
"""
rows = connection.execute(sql).fetchall()
```

Здесь реляционная работа попала в подходящий движок, но:

- пути смешаны со структурой SQL;
- SQL трудно запускать и ревьюить отдельно;
- `fetchall()` всё равно превращает полный результат в Python-объекты;
- непонятно, что считается publish blocker;
- получатель видит CSV, но не видит запрос и не может проверить его байты.

### Вариант C: граница назначена словами

Можно записать в README:

```text
SQL — для joins, Python — для orchestration, pandas — для анализа.
```

Это разумная гипотеза, но пока не решение. Она ничего не говорит о конкретном grain,
числе переданных строк, способе экспорта и проверках.

Нужен pipeline, в котором граница наблюдаема:

```text
CSV sources
    │
    │ read_csv + typing + joins + aggregation
    ▼
DuckDB temp relations
    │
    │ COPY ordered SELECT directly to files
    ▼
checked CSV package
    │
    │ optional local read of the required result only
    ▼
pandas at (user_id, currency) grain
```

## Концепция

### Инструмент выбирают для операции, а не для профессии

SQL, DuckDB, Python и pandas — не взаимоисключающие команды.

- **SQL** описывает отношение, которое должно получиться.
- **DuckDB** планирует и выполняет это отношение над файлами и таблицами.
- **Python** связывает пути, параметры, шаги, ошибки и файлы поставки.
- **pandas** удобен для интерактивной работы с уже выбранным табличным срезом.

У каждого инструмента есть пересекающиеся возможности. И DuckDB, и pandas умеют JOIN и
GROUP BY; и SQL, и Python могут управлять экспортом. Поэтому вопрос звучит не «кто это
умеет», а так:

> Где операция сохраняет самый ясный grain-контракт и требует наименьшего лишнего
> движения данных?

### Четыре измерения границы

#### 1. Grain

До каждой операции назовите единицу строки.

| Отношение | Grain |
|---|---|
| `users` | `user_id` |
| `orders` | `order_id` |
| `order_items` | `(order_id, product_id)` |
| `item_totals` | `order_id` |
| `order_mart` | `order_id` |
| `user_summary` | `(user_id, currency)` |

JOIN `orders` с сырыми `order_items` меняет число строк. Поэтому сначала нужен
`item_totals`, и только потом — JOIN на одинаковом `order_id`-grain.

#### 2. Движение данных

Каждая из следующих операций материализует результат по-разному:

```python
connection.execute(sql).fetchall()  # все строки становятся Python tuples
connection.execute(sql).df()        # все строки становятся pandas DataFrame
```

Если следующему шагу нужен файл, промежуточная материализация не даёт ценности. DuckDB
может записать результат запроса непосредственно:

```sql
COPY (
    SELECT *
    FROM user_summary
    ORDER BY user_id
) TO ? (FORMAT CSV, HEADER);
```

Python здесь передаёт путь и проверяет результат, но не держит витрину в списке словарей.

#### 3. Владение логикой

Разделение не должно дробить одну бизнес-формулу между языками.

| Ответственность | Владелец |
|---|---|
| Типы, timezone, нормализация | SQL asset |
| Предварительная агрегация и JOIN | SQL asset |
| Paid revenue и user summary | SQL asset |
| Пути и параметры | Python |
| Publish gate | Python над SQL checks |
| Экспорт, provenance, manifest | Python + DuckDB `COPY` |
| Локальный ad hoc срез | pandas после поставки |

Если часть paid revenue считается в SQL, а часть в цикле Python, сверять результат
сложнее. В проекте вся бизнес-агрегация остаётся в SQL.

#### 4. Поставка

CSV без контракта не отвечает на вопросы:

- из каких источников он собран;
- какой SQL использован;
- какой grain обещан;
- прошли ли проверки;
- изменились ли байты после публикации.

Поэтому package содержит не только две таблицы:

```text
delivery/
├── boundary_decision.json
├── manifest.json
├── order_mart.csv
├── sql/
│   ├── order_mart.sql
│   └── user_summary.sql
└── user_summary.csv
```

### Контрольное число и инвариант — не одно и то же

Для tiny-данных заранее известны:

```text
orders rows = 12
paid revenue by currency:
  EUR = 1625.00
  KZT = 500.00
  RUB = 2700.00
  USD = 180.00
unknown user orders = 1
```

Эти числа полезны как ручной oracle тестового набора. Но правило вида
`valid = rows == 12` делает builder непригодным для другого корректного файла. Складывать
четыре валютных результата в прежнее общее число `5005.00` нельзя: без курса и даты
конвертации это не одна аддитивная метрика.

Publish gate должен опираться на инварианты:

| Инвариант | Почему блокирует |
|---|---|
| Ключи источников уникальны и заполнены | Иначе не определён исходный grain |
| Каждая item-ссылка ведёт в orders | Иначе позиции будут молча потеряны |
| Строк `order_mart` столько же, сколько orders | Иначе JOIN потерял или размножил заказы |
| `order_id` уникален в mart | Иначе нарушен заявленный grain |
| Известные amount совпадают с item total | Иначе денежные факты противоречат друг другу |
| У каждого заказа заполнена валюта | Иначе денежный факт не относится к определённой единице |
| У оплаченного заказа заполнен amount | Иначе published paid revenue заведомо неполна |
| Paid revenue совпадает между marts по каждой валюте | Иначе смена grain изменила аддитивную метрику |

Такие правила работают и на 12, и на 100 000 заказах.

### Blocker и warning отвечают на разные вопросы

В tiny-наборе есть намеренная неполнота:

- заказ неизвестного пользователя;
- заказ без даты;
- два заказа, где amount нельзя сверить с items.

Удалять эти строки нельзя: это изменило бы population. Но и скрывать их нельзя.

```text
blocker  → пакет нельзя публиковать под заявленным контрактом
warning  → пакет можно публиковать, но неполнота видна получателю
```

В этом проекте unknown user, missing business date и непроверяемая сумма неоплаченного
заказа становятся warnings. Дубликат ключа, orphan item, известное расхождение суммы,
отсутствующая валюта или оплаченный заказ без amount блокируют поставку. Это продуктовая
политика именно этого проекта, а не универсальное правило.

### Точные деньги не становятся `float`

SQL хранит `amount` как `DECIMAL(18, 2)`. При переходе в manifest итог кодируется строкой:

```json
{
  "order_paid_revenue_by_currency": {
    "EUR": "1625.00",
    "KZT": "500.00",
    "RUB": "2700.00",
    "USD": "180.00"
  }
}
```

Так JSON не заставляет нас превращать десятичные числа в двоичный `float`, валюты не
смешиваются, а две агрегации сравниваются внутри DuckDB как `DECIMAL` по каждой валюте.

### Что действительно доказывают evidence

`boundary_decision.json` фиксирует:

- строки и байты каждого источника;
- строки двух marts;
- целевой handoff grain;
- факт, что builder не материализовал DataFrame;
- причины выбранной границы;
- ограничения вывода.

Это сильнее готовой фразы, но не является benchmark:

```text
наблюдалось на этом запуске:
  три отношения → две marts → прямой export

не доказано:
  DuckDB быстрее pandas на любом размере и любом workload
```

Если объём, формат или нагрузка изменятся, повторите `EXPLAIN ANALYZE` и измерения из
04/12 на репрезентативном профиле.

### Checksum проверяет байты, а не истину

SHA-256 позволяет получателю заметить, что файл отличается от записанного в manifest.
Он не доказывает:

- корректность бизнес-формулы;
- авторство пакета;
- отсутствие злонамеренной одновременной подмены файла и manifest.

Логика подтверждается behavioral tests и quality gate. Для аутентичности нужны подпись,
доверенный registry или защищённый канал — это вне текущего проекта.

### Переносимость manifest

Такой provenance непереносим:

```json
{"orders": {"path": "/Users/alice/project/data/orders.csv"}}
```

Абсолютный путь раскрывает локальную структуру и бессмысленен на машине получателя.
Пакет сохраняет только роль, basename, размер и SHA-256:

```json
{
  "orders": {
    "name": "orders.csv",
    "bytes": 645,
    "sha256": "..."
  }
}
```

Hash идентифицирует точные исходные байты, а роль объясняет их назначение.

## Соберите это

### Шаг 1. Сформулируйте решение до кода

Заполните таблицу для будущего pipeline:

| Операция | Входной grain | Выходной grain | Движок | Материализация |
|---|---|---|---|---|
| Типизация orders | `order_id` | `order_id` | DuckDB SQL | relation |
| Агрегация items | `(order_id, product_id)` | `order_id` | DuckDB SQL | relation |
| JOIN users/items | `order_id` | `order_id` | DuckDB SQL | relation |
| User summary | `order_id` | `(user_id, currency)` | DuckDB SQL | relation |
| Package metadata | файлы | manifest | Python | маленький dict |
| Ad hoc preview | `(user_id, currency)` | `(user_id, currency)` | pandas | checked summary |

Если вы не можете назвать grain, ещё рано выбирать API.

### Шаг 2. Изучите первый SQL asset

Откройте `outputs/order_mart.sql`. Проследите CTE снизу вверх:

1. `users`, `orders`, `items` типизируют и нормализуют источники;
2. `item_totals` меняет grain до `order_id`;
3. `LEFT JOIN` сохраняет все orders;
4. `amount_matches_items` различает `true`, `false` и неизвестность;
5. `paid_amount` сохраняет остальные статусы, но даёт аддитивную paid-метрику.

До запуска предскажите:

- почему `O1001` не размножится;
- почему `O1010` останется в mart;
- когда `amount_matches_items` будет `NULL`;
- почему `paid_amount` имеет денежный тип.

### Шаг 3. Изучите смену grain

`outputs/user_summary.sql` читает уже созданный `order_mart`, а не сырые файлы.

```sql
SELECT
    user_id,
    currency,
    count(*) AS order_count,
    count(*) FILTER (WHERE is_paid) AS paid_order_count,
    sum(paid_amount) AS paid_revenue,
    ...
FROM order_mart
GROUP BY user_id, currency;
```

Здесь допустимо агрегировать paid revenue, потому что в `order_mart` одна строка на
заказ, а `currency` остаётся частью нового grain. Если исходным отношением был сырой JOIN
с items, сумма могла бы умножиться; если убрать валюту из `GROUP BY`, несопоставимые
денежные единицы сложатся в правдоподобное, но бессмысленное число.

### Шаг 4. Запустите полный пример

```bash
uv run --locked python code/main.py
```

Пример:

1. создаёт временный package;
2. вызывает builder;
3. проверяет package как получатель;
4. только затем читает `user_summary.csv` в pandas;
5. печатает три строки preview.

В build-части pandas не участвует.

### Шаг 5. Найдите прямой export

В `outputs/sql_mart_builder.py` найдите два `COPY`:

```sql
COPY (SELECT * FROM order_mart ORDER BY order_id)
TO ? (FORMAT CSV, HEADER);
```

Здесь важны три детали:

- `SELECT` выполняется движком;
- `ORDER BY` делает порядок строк детерминированным;
- путь передаётся параметром, а не вставляется в SQL через f-string.

### Шаг 6. Разберите publish gate

Builder сначала вычисляет source checks и mart checks. Только если blockers пусты, он
создаёт output directory. Поэтому провал не оставляет каталог, похожий на готовую
поставку.

Tiny-значение `12` и четыре валютных revenue проверяются тестом, но отсутствуют в
условии `valid`. Найдите это различие в коде.

## Используйте это

### Соберите пакет из tiny-данных

Из каталога урока выполните:

```bash
uv run --locked python outputs/sql_mart_builder.py build \
  --users ../data/tiny/users.csv \
  --orders ../data/tiny/orders.csv \
  --items ../data/tiny/order_items.csv \
  --output-dir delivery
```

Команда отказывается переиспользовать существующий `delivery/`. Это защищает от
случайного смешивания старых и новых файлов. Для повторного запуска укажите новый каталог
или осознанно удалите прежний после проверки.

### Прочитайте quality report

В `manifest.json` найдите:

```json
{
  "quality": {
    "blockers": [],
    "warnings": [
      "unknown_user_orders=1",
      "missing_business_dates=1",
      "amount_item_unchecked=2"
    ],
    "valid": true
  }
}
```

Ответьте:

1. почему каждый warning не удаляет строку;
2. какая downstream-метрика чувствительна к missing date;
3. можно ли считать amount reconciliation полной.

### Защитите границу инструментов

Откройте `boundary_decision.json` и сформулируйте решение без слов «удобнее» и «я
привык». Используйте шаблон:

```text
На этом запуске вход состоял из ... строк и ... байтов.
Реляционные операции изменили grain ... → ... → ...
Полные marts были экспортированы DuckDB напрямую, поэтому ...
Python отвечал за ...
pandas допустим после ... при условии ...
Этот evidence не доказывает ...
```

Хорошее обоснование содержит и решение, и границу его применимости.

### Проверьте пакет как получатель

```bash
uv run --locked python outputs/sql_mart_builder.py verify \
  --package-dir delivery
```

Проверяющая сторона:

- читает только package;
- отвергает абсолютные пути и `..` в inventory;
- сверяет размер и SHA-256 каждого артефакта;
- проверяет точный состав файлов;
- требует успешный quality gate.

Исходные CSV не входят в delivery. Их hashes — provenance, а не копия источника.

### Передайте в pandas только нужный результат

Для локального вопроса по пользователям в RUB:

```python
import pandas as pd

summary = pd.read_csv(
    "delivery/user_summary.csv",
    dtype={"user_id": "string", "currency": "string"},
)
top_rub_users = (
    summary.loc[summary["currency"].eq("RUB")]
    .nlargest(5, "paid_revenue")
)
```

Не загружайте заново users, orders и items и не повторяйте в pandas уже проверенные JOIN
и GROUP BY. Иначе появится вторая реализация одной бизнес-логики.

## Сломайте это

Каждый эксперимент делайте на копии входа или package.

### 1. Размножьте ключ orders

Добавьте вторую строку с существующим `order_id`. Ожидайте:

```text
publish blocked: duplicate_order_ids=1
```

Output directory не должен появиться.

### 2. Создайте orphan item

Добавьте item с `order_id`, которого нет в orders. Даже если итоговая order mart
выглядит прежней, поставка должна остановиться: позиция иначе была бы молча потеряна.

### 3. Измените известную сумму позиции

Поменяйте `unit_price` у позиции оплаченного заказа. Ожидайте blocker
`amount_item_mismatches`, а не автоматическое предпочтение одной из двух сумм.

### 4. Верните `fetchall()`

Замените прямой `COPY` получением всех rows в Python. Объясните:

- какой новый объект появился в памяти;
- нужен ли он следующему шагу;
- чем подтвердить последствия на representative profile.

Не заявляйте memory improvement только по tiny-файлу.

### 5. Уберите `ORDER BY` из export

Повторите сборку и сравните bytes. Даже если текущая версия случайно вернула одинаковый
порядок, SQL-контракт без `ORDER BY` его не обещает.

### 6. Подмените поставленный CSV

Допишите строку в `order_mart.csv` и запустите `verify`. Проверка должна сообщить и
изменившийся размер, и checksum mismatch.

### 7. Подмените путь в manifest

Укажите `../outside.csv`. Проверяющая сторона должна отвергнуть path traversal до чтения
файла.

## Проверьте это

Запустите behavioral suite:

```bash
uv run --locked python -m unittest discover -s tests
```

Тесты проверяют наблюдаемое поведение, а не строки реализации:

- ручные tiny-controls и точный decimal revenue отдельно по валютам;
- сохранение order grain и предварительную агрегацию items;
- warnings для разрешённой неполноты;
- user summary на новом grain;
- корректный короткий вход с другими rows и revenue;
- blockers для duplicate key, orphan item и amount mismatch;
- отсутствие абсолютных путей в manifest;
- наличие SQL и boundary decision в package;
- детерминированность файлов;
- независимую проверку и обнаружение tampering;
- отказ от path traversal, undeclared file и переиспользования output directory;
- успешные CLI `build` и `verify`;
- понятную CLI-ошибку при отсутствующем источнике.

Важно: тест с тремя заказами доказывает, что builder не выучил числа tiny-набора.
Tiny-controls остаются отдельным oracle.

Проверьте стиль:

```bash
uv run --locked ruff check code/main.py outputs/sql_mart_builder.py tests/test_main.py
uv run --locked ruff format --check \
  code/main.py outputs/sql_mart_builder.py tests/test_main.py
```

## Поставьте результат

Перед handoff выполните приёмку со стороны получателя:

```bash
uv run --locked python outputs/sql_mart_builder.py verify \
  --package-dir delivery
```

Затем передайте весь каталог, а не только CSV:

```text
delivery/
├── boundary_decision.json    # решение, evidence и ограничения
├── manifest.json             # quality, provenance, inventory, checksums
├── order_mart.csv            # grain: order_id
├── sql/
│   ├── order_mart.sql        # точное реляционное преобразование
│   └── user_summary.sql      # точная смена grain
└── user_summary.csv          # grain: (user_id, currency)
```

Минимальное сообщение получателю:

```text
Пакет собран DuckDB <version> в timezone Europe/Moscow.
Quality gate прошёл; warnings перечислены в manifest.
Полные marts записаны DuckDB напрямую, без DataFrame в build.
Команда verify сверяет пять файлов с inventory.
SHA-256 подтверждает идентичность байтов, но не авторство.
```

Не называйте package «production-ready» только потому, что тесты tiny-набора зелёные.
Для production ещё потребуются политика доступа, наблюдаемость, representative load test,
версионирование схемы и согласованный канал публикации.

`work/phase-04-exit-check.md` и `work/phase-04-plan-report.json` остаются учебным evidence
освоения фазы. Не добавляйте их в delivery package: получателю витрин нужны только
заявленные данные, SQL, provenance и проверки поставки.

## Упражнения

1. Сгенерируйте `sample`-профиль, соберите package и сравните rows/bytes в
   `boundary_decision.json`. Не коммитьте сгенерированные данные.
2. Добавьте `monthly_revenue.sql`. Сначала объявите grain и только затем включите файл в
   inventory и verifier.
3. Сравните прямой CSV export и Parquet на sample-профиле по размеру, времени чтения и
   сохранению типов. Не делайте универсальный вывод по одному запуску.
4. Добавьте необязательный аргумент verify с путями к исходным CSV, чтобы получатель мог
   сверить provenance hashes, не копируя raw data в package.
5. Сформулируйте альтернативную границу для интерактивного ноутбука с 200 строками.
   Назовите, какое evidence делает pandas разумным выбором именно там.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение в уроке |
|---|---|---|
| Tool boundary | «Любимая библиотека автора» | Место смены движка, представления данных и владельца ответственности |
| Materialization | Любое выполнение SQL | Создание конкретного набора данных в памяти или файле |
| Grain | Число строк | Бизнес-смысл одной строки и ключ, который её идентифицирует |
| Mart | Любой экспорт | Таблица с заявленным назначением, population, grain и checks |
| Orchestration | Бизнес-формулы на Python | Управление параметрами, шагами, ошибками и поставкой |
| Publish gate | `assert rows == 12` | Data-independent инварианты, разрешающие или блокирующие выпуск |
| Blocker | Любой `NULL` | Нарушение, несовместимое с заявленным контрактом |
| Warning | Ошибка, которую забыли исправить | Разрешённая неполнота, явно переданная получателю |
| Provenance | Абсолютный путь автора | Идентификатор роли и точных входных байтов |
| Manifest | Текстовый README | Машиночитаемый inventory, quality report и checksums |
| Checksum | Доказательство верной логики | Отпечаток байтов для обнаружения изменения |
| Boundary of claim | Оговорка для красоты | Явное описание того, чего evidence не доказывает |

## Дополнительное чтение

- [Яндекс Образование: зачем аналитику знать SQL](https://education.yandex.ru/knowledge/sql-zachem-analitiku-nuzhno-znat-yazik-strukturirovannikh-zaprosov) — начните с русскоязычного обзора роли SQL: сопоставьте перечисленные задачи с реляционной частью проекта и отметьте, какие обязанности остаются за Python.
- [Postgres Pro: команда COPY](https://postgrespro.ru/docs/postgresql/current/sql-copy) — разберите русскоязычное описание `COPY (query) TO` и различие серверного файла и клиентского потока; затем сравните контракт с локальным embedded DuckDB.
- [Microsoft Learn: Get-FileHash](https://learn.microsoft.com/ru-ru/powershell/module/microsoft.powershell.utility/get-filehash) — разберите русскоязычное объяснение хэша файла и пример SHA-256; зафиксируйте границу: digest обнаруживает изменение байтов, но не заменяет quality checks и подпись.
- [DuckDB: Python API](https://duckdb.org/docs/stable/clients/python/overview) — проследите способы чтения, выполнения и выгрузки результата; отдельно отметьте вызовы, которые материализуют pandas DataFrame.
- [DuckDB: Relational API](https://duckdb.org/docs/stable/clients/python/relational_api) — изучите ленивое relation и методы, запускающие выполнение; используйте страницу, чтобы точнее говорить о вычислении и материализации.
- [DuckDB: CSV Import and Export](https://duckdb.org/docs/stable/data/csv/overview) — сопоставьте параметры `read_csv` и `COPY ... TO` с двумя SQL assets проекта и проверьте, какие настройки CSV объявлены явно.
- [DuckDB: Performance Guide](https://duckdb.org/docs/stable/guides/performance/overview.html) — прочитайте рекомендации как направления измерения, а не обещание скорости; повторяйте выводы только на representative workload.
- [pandas: Comparison with SQL](https://pandas.pydata.org/docs/getting_started/comparison/comparison_with_sql.html) — сравните эквивалентные SELECT, GROUP BY и JOIN и объясните, почему одинаковая выразительность ещё не определяет правильную границу движков.
- [pandas: Scaling to Large Datasets](https://pandas.pydata.org/docs/user_guide/scale.html) — свяжите memory usage, выбор колонок, chunking и другие библиотеки с решением не материализовывать полные marts без необходимости.
- [Frictionless Data: Data Package specification](https://specs.frictionlessdata.io/data-package/) — рассмотрите первичную спецификацию package metadata и сравните её resources-модель с минимальным учебным manifest; не заявляйте совместимость без реализации всех требований.
