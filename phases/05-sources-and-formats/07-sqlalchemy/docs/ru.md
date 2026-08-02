# Подключение к БД через SQLAlchemy

> Успешный `execute()` доказывает только выполнение запроса. Полезный срез должен ещё
> доказать свою схему, полноту, grain и корректное освобождение соединения.

**Тип:** Build  
**Треки:** Core  
**Пререквизиты:** 05/06  
**Время:** ~90 минут  
**Результат:** создаёт проверяемую границу чтения из SQL-БД через SQLAlchemy: передаёт
значения отдельно от доверенного SQL, управляет Engine и Connection, проверяет source
schema, полноту JOIN и safety limit, grain результата и публикует только валидный
snapshot.

## Цели обучения

После урока вы сможете:

- объяснить роли DBAPI, dialect, driver, Engine, pool, Connection, statement и Result;
- определить владельца Engine и Connection и гарантированно вернуть connection в pool;
- выполнять доверенный SQL-asset через `text()` с отдельно переданными значениями;
- проверить отражённую схему таблиц до чтения;
- обнаружить строки, потерянные на JOIN, и недоказанную полноту из-за safety limit;
- проверить фактические result columns даже при пустом результате;
- передать коллеге самостоятельный snapshot без credentials и локальных путей.

## Связь с предыдущими уроками

В `04/11` вы уже выполняли параметризованный SQL через явную DuckDB connection. Там были
освоены три переносимых правила:

```text
структура SQL и значения передаются отдельно
владелец connection определяет её lifecycle
успешный запрос не заменяет проверку результата
```

В `04/05` вы видели, что `JOIN` способен изменить число строк и grain. В `05/06` только
валидный HTML-срез разрешалось публиковать. Эти механизмы готовы; повторно учить SQL
injection или grain с нуля не нужно.

Новое в этом уроке — граница с уже существующей внешней БД:

```text
database + DBAPI driver
→ SQLAlchemy dialect
→ долгоживущий Engine и его pool
→ краткоживущая Connection
→ trusted SQL + bound values
→ Result metadata и rows
→ schema / completeness / grain checks
→ snapshot
```

SQLite используется как маленькая воспроизводимая БД. SQLAlchemy показывает общий
интерфейс, но не делает все базы одинаковыми: URL, driver, типы, transactions и часть
reflection зависят от dialect.

## Проблема

Нужно прочитать заказы из БД, присоединить сегмент пользователя и передать результат
дальше. Первый вариант выглядит разумно:

```python
query = f"""
SELECT ...
FROM orders
JOIN users USING (user_id)
WHERE status = '{status}'
LIMIT {limit}
"""
rows = connection.execute(query).fetchall()
```

Даже если запрос вернул строки, остаются четыре независимые проблемы.

### Значение стало частью SQL

`status="paid' OR 1=1 --"` меняет синтаксис запроса. Нужно передавать value отдельно от
statement. Но проверять это поиском слова `paid` в compiled SQL нельзя: безопасное
значение может случайно совпасть с именем таблицы или столбца.

### `INNER JOIN` спрятал потерю

Если заказ ссылается на неизвестного пользователя, `INNER JOIN` просто удалит его.
Итоговые пять строк могут выглядеть правдоподобно, хотя в таблице заказов было шесть.

### `LIMIT` выдал префикс за полный срез

Условие `len(rows) <= limit` истинно почти всегда: сам SQL не вернёт больше limit. Оно не
отвечает на вопрос, существовала ли следующая строка.

### Пустой результат спрятал неверную схему

У нуля строк всё равно есть result metadata. Если код подставляет ожидаемые названия
колонок из JSON-контракта, он не проверяет результат, а повторяет собственное ожидание.

Нужна граница, которая делает эти ошибки видимыми до публикации.

## Концепция

### От Python к базе через несколько слоёв

| Слой | Что делает | Чего не обещает |
|---|---|---|
| DBAPI | Общий Python-интерфейс connection/cursor/execute | Одинаковый placeholder и поведение всех БД |
| Driver | Реализует DBAPI для конкретной БД | Самостоятельную модель pool и SQL abstraction |
| Dialect | Переводит SQLAlchemy API в особенности конкретной БД/driver | Идентичные типы и функции между dialects |
| Engine | Хранит конфигурацию, dialect и pool; выдаёт Connection | Не является одной открытой connection |
| Pool | Переиспользует DBAPI connections | Не отменяет лимиты и правила сервера |
| Connection | Даёт ограниченный контекст выполнения | Не должна жить бесконечно или закрываться случайным helper |
| Statement | Описывает доверенную структуру запроса | Не превращает identifier в value parameter |
| Result | Содержит metadata и поток строк | Не доказывает grain или полноту автоматически |

`create_engine()` обычно не открывает сетевое соединение сразу. Engine подключается
лениво, когда получает первую задачу. Поэтому «Engine создан» ещё не означает «БД
доступна».

### Engine должен быть долгоживущим

Engine — registry конфигурации и connection pool. В приложении его обычно создают один
раз для одной БД и переиспользуют:

```python
engine = create_engine(database_url)
try:
    first = read_orders(engine, ...)
    second = read_orders(engine, ...)
finally:
    engine.dispose()
```

Функция `read_orders()` принимает caller-owned Engine. Она может брать из него
Connection, но не вызывает `dispose()`: иначе один helper уничтожил бы pool, которым
ещё пользуется вызывающий код.

CLI устроен иначе. Он сам создаёт Engine для одного процесса, поэтому сам вызывает
`dispose()` в `finally`.

### Connection — заимствованный ограниченный ресурс

```python
with engine.connect() as connection:
    result = connection.execute(statement, parameters)
```

После блока SQLAlchemy закрывает объект Connection и возвращает нижележащую DBAPI
connection в pool. Если transaction была начата, но не завершена, закрытие выполняет
rollback. В уроке запрос только читает, однако lifecycle остаётся явным.

Для SQLite учебный CLI открывает файл через URI `mode=ro&uri=true`. Это дополнительная
защита на уровне driver: даже ошибочная команда записи получит `readonly database`.
Для серверной БД аналогичная гарантия достигается отдельной read-only ролью и правами;
SQLAlchemy не создаёт их автоматически.

### Доверенная структура и bound values

Запрос хранится в `outputs/order_slice.sql`:

```sql
WHERE orders.amount >= :min_amount
  AND (:status IS NULL OR orders.status = :status)
LIMIT :fetch_limit
```

Python передаёт словарь:

```python
parameters = {
    "min_amount": 900.0,
    "status": "paid",
    "fetch_limit": 101,
}
connection.execute(text(sql), parameters)
```

Имена `orders`, `status` и направление сортировки являются SQL structure. Обычный bind
parameter предназначен для values, а не для таблиц, колонок или `ASC`/`DESC`. Если
identifier действительно должен меняться, выберите его из заранее заданного allowlist
или соберите statement из доверенных SQLAlchemy objects.

Артефакт проверяет набор bind names и checksum SQL-asset. Он не пытается доказать
безопасность SQL поиском пользовательских строк: доверие к structure появляется из
reviewed asset, а безопасность values — из binding.

### Reflection — наблюдение, а не источник бизнес-смысла

`inspect(connection)` может получить:

- существование таблицы;
- имена, типы и nullability колонок;
- primary key и другие constraints, если dialect их отражает.

Reflection отвечает «что БД сообщает сейчас». Она не знает:

- означает ли строка один заказ;
- допустимы ли статусы;
- должен ли каждый заказ иметь пользователя;
- является ли пустой результат нормальным.

Эти ожидания задаёт `db_contract.json`. В уроке source contract требует таблицы
`orders`, `users`, необходимые колонки, primary keys и non-nullability. SQL type names
записываются в report, но не сравниваются буквально между dialects: `TEXT`, `VARCHAR` и
другие представления могут различаться.

### Result metadata существует даже без строк

SQLAlchemy сообщает колонки через `result.keys()`:

```python
cursor = connection.execute(statement, parameters)
actual_columns = list(cursor.keys())
rows = cursor.mappings().fetchmany(...)
```

`actual_columns` не зависит от `rows[0]`. Поэтому пустой срез может быть валидным по
политике `allow_empty=true`, но всё равно обязан иметь точные колонки и порядок.

### LEFT JOIN сохраняет доказательство потери

В SQL-asset используется:

```sql
FROM orders
LEFT JOIN users
    ON orders.user_id = users.user_id
```

Одна строка source `orders` остаётся одной строкой результата. Если matching user нет,
`segment` становится `NULL`. Контракт объявляет `segment` обязательным relationship
field, поэтому snapshot не публикуется.

Это не универсальное правило «всегда используйте LEFT JOIN». Здесь population задаёт
`orders`, и полнота заказов важнее удобства. В другой задаче population и допустимая
потеря могут быть иными — их нужно назвать до выбора JOIN.

### `max_rows + 1` различает срез и незаметный префикс

`max_rows` — safety limit памяти, а не бизнес-фильтр. Чтобы проверить полноту в его
границах, запрос просит одну дополнительную строку:

```text
нужно не больше 100 строк
запрашиваем LIMIT 101
получили 100 или меньше → результат целиком помещается в limit
получили 101          → существует продолжение, полнота не доказана
```

При переполнении report сохраняет первые `max_rows` строк для диагностики, но получает
`result_complete_within_limit=false` и не публикуется. Для действительно большого
результата нужны pagination, streaming или выгрузка внутри БД — это отдельный workflow.

### Контракт результата

`db_contract.json` версии `2.0.0` задаёт:

```text
source.tables       → требуемая физическая схема
query.bind_names    → интерфейс trusted SQL
result.columns      → точные имена и порядок
result.grain        → ключ уникальности
result.fields       → string/number и nullability
result.domains      → допустимые значения
relationship_fields→ поля, доказывающие успешный JOIN
allow_empty         → допустим ли нулевой срез
```

Неизвестная версия, неизвестные/duplicate JSON keys и внутренне противоречивые поля
останавливают запуск как configuration error.

## Соберите это

### Шаг 1. Увидьте DBAPI-механизм

Из директории урока запустите:

```bash
uv run --locked python code/main.py
```

Первая часть использует стандартный `sqlite3`:

```python
with sqlite3.connect("file:...?mode=ro", uri=True) as connection:
    cursor = connection.execute(
        "SELECT order_id, amount FROM orders WHERE amount >= ? ORDER BY order_id",
        (900,),
    )
```

Здесь видны четыре элемента, которые позже обобщит SQLAlchemy:

1. concrete driver `sqlite3`;
2. read-only connection;
3. driver-specific placeholder `?`;
4. отдельно переданный tuple values.

`cursor.description` показывает result columns до чтения первой строки.

### Шаг 2. Сопоставьте слои SQLAlchemy

Вторая часть примера создаёт read-only Engine и печатает:

```text
dialect = sqlite
driver  = pysqlite
pool    = имя фактической pool implementation
```

Затем один Engine используется для checked slice и ещё одного `SELECT 42`. Это
наблюдаемое доказательство ownership: `read_orders()` не уничтожила чужой Engine.

### Шаг 3. Предскажите checks

Для `status=paid` и `min_amount=900` до запуска запишите:

```text
order_id   = O2501, O2502, O2505
row_count  = 3
grain      = unique order_id
segment    = present for every order
truncated  = false при max_rows=100
```

Только после предсказания сравните результат программы.

## Используйте это

Запустите самостоятельный CLI:

```bash
uv run --locked python outputs/db_reader.py \
  --database ../data/tiny/analytics.sqlite \
  --contract ../data/db_contract.json \
  --status paid \
  --min-amount 900 \
  --max-rows 100 \
  --output delivery/orders_snapshot.json
```

Успешный snapshot содержит:

- dialect, driver и версию SQLAlchemy;
- file name, размер и SHA-256 SQLite fixture;
- точную копию контракта;
- trusted SQL, его SHA-256 и bind names;
- runtime parameters без database URL или password;
- отражённую source schema;
- фактические result columns и rows;
- checks, errors и summary.

Публикация атомарна: сначала полностью записывается соседний temporary file, затем
`os.replace()` заменяет target. Невалидный result не создаёт новый snapshot и не
перезаписывает предыдущий.

### Переиспользование функции

В приложении Engine создаёт владелец конфигурации:

```python
engine = create_engine(database_url_from_secret_store)
try:
    result = read_orders(engine, contract_path, status="paid")
finally:
    engine.dispose()
```

Не записывайте URL с password в lesson, command history, JSON report или Git. Учебный CLI
сознательно принимает только путь к локальному SQLite fixture; подключение production
dialect требует установленного driver, отдельной конфигурации TLS/timeouts и read-only
учётной записи.

## Сломайте это

### Потеря на JOIN

Добавьте в копию БД заказ с `user_id`, которого нет в `users`. Строка останется в
result, но `segment=None` провалит `relationships_complete`.

### Неполный срез

```bash
uv run --locked python outputs/db_reader.py \
  --database ../data/tiny/analytics.sqlite \
  --max-rows 2 \
  --output delivery/must-not-exist.json
```

Reader запросит три строки, вернёт код `1`, покажет первые две для диагностики и не
создаст output.

### Неверный пустой результат

Поменяйте ожидаемые columns в копии контракта и запросите несуществующий status. Ноль
rows не спасёт ошибочный contract: `result.keys()` всё равно покажет реальные колонки.

### Другие failure modes

1. Удалите обязательную таблицу или колонку в копии БД.
2. Измените primary key в contract.
3. Повторите `status` как grain — несколько `paid` должны нарушить уникальность.
4. Запишите неизвестный status в попавшую в срез строку.
5. Удалите `:fetch_limit` из копии SQL-asset.
6. Передайте `NaN` как `min_amount` или ноль как `max_rows`.
7. Попробуйте `INSERT` через read-only SQLite Engine.

Для каждой поломки назовите слой: configuration, source schema, query interface,
relationship, result contract или completeness.

## Проверьте это

```bash
uv run --locked python -m unittest discover -s tests
```

30 behavioral tests проверяют:

- happy path, фильтры и детерминированный порядок;
- empty result с фактическими metadata;
- injection payload и значение, совпадающее с identifier;
- точный набор bind names;
- обнаружение строки `max_rows + 1`;
- реальное применение contract grain;
- сохранение orphan order через LEFT JOIN;
- source schema, PK и nullability;
- типы, domains и empty policy результата;
- строгую schema JSON-контракта;
- ownership Engine и возврат Connection в pool;
- запрет записи read-only SQLite driver;
- отсутствие создания missing database;
- provenance без абсолютных путей;
- atomic publish и сохранность предыдущего snapshot;
- коды CLI для valid и incomplete result.

Тест с injection payload доказывает узкое поведение: конкретное значение осталось
значением. Он не доказывает безопасность произвольного SQL, прав доступа или всей БД.

## Поставьте результат

Именованный артефакт — `outputs/db_reader.py`; его reviewed query —
`outputs/order_slice.sql`. Для handoff передайте:

1. оба файла артефакта;
2. `db_contract.json`;
3. `orders_snapshot.json`;
4. способ получить Engine без раскрытия credentials;
5. версию locked-окружения и решение о допустимом `max_rows`.

Получатель snapshot может проверить SQL, parameters, source schema, rows и причины
отказа без исходного рабочего каталога. SHA-256 SQLite fixture полезен для учебного
файла; для живой серверной БД checksum всего источника обычно невозможен, и provenance
должен опираться на database snapshot/time, query и параметры.

В следующем уроке результат чтения станет входом в новый вопрос: как сохранить
типизированную таблицу переносимым колоночным файлом. SQLAlchemy Result сам по себе не
является форматом хранения; эту границу закроет Parquet.

## Границы урока

Мы сознательно не добавляем:

- ORM, `Session`, declarative models и relationships;
- INSERT/UPDATE/DELETE и migrations;
- async Engine;
- pool sizing, reconnect policies и server-side cursors;
- production drivers, TLS и secret manager;
- универсальный запуск произвольного SQL;
- автоматический retry запроса, который может изменить данные.

Эти темы требуют отдельных задач. Здесь достаточно надёжно прочитать один ограниченный
аналитический срез и не выдать правдоподобную неполноту за готовые данные.

## Упражнения

1. Добавьте два bound values для диапазона `ordered_at`; сначала назовите семантику обеих
   границ интервала.
2. Добавьте allowlist сортировки `order_id` / `amount`. Покажите, почему имя колонки не
   является обычным value parameter.
3. Измените `allow_empty` на `false` для workflow, где пустой срез означает сбой, и
   добавьте тест.
4. Спроектируйте конфигурацию PostgreSQL Engine без credentials в коде. Не подключайтесь
   к живой БД: перечислите driver, secret source, TLS, connect timeout и read-only role.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение в уроке |
|---|---|---|
| DBAPI | Одна библиотека для всех БД | Стандарт интерфейса, реализуемый конкретным driver |
| Driver | Сама база данных | Python-реализация протокола доступа к конкретной БД |
| Dialect | Синоним driver | Адаптер SQLAlchemy к особенностям DB и DBAPI |
| Engine | Открытая connection | Долгоживущий registry конфигурации, dialect и pool |
| Pool | Кеш строк запроса | Менеджер переиспользуемых DBAPI connections |
| Connection | Глобальный singleton | Временно заимствованный контекст выполнения |
| Bound value | Экранированная f-string | Значение, переданное отдельно от SQL structure |
| Identifier | Любой текстовый parameter | Имя SQL-объекта, являющееся частью structure |
| Reflection | Бизнес-контракт | Наблюдаемая metadata, сообщённая текущим dialect |
| Result metadata | Первая строка | Имена колонок, доступные даже при нуле rows |
| Safety limit | Доказательство полноты | Ограничитель; полнота требует проверки дополнительной строки |
| Relationship check | Наличие JOIN в SQL | Проверка, что требуемые связи действительно нашлись |

## Дополнительное чтение

- [RU · Python `sqlite3`: placeholders](https://docs.python.org/ru/3/library/sqlite3.html#how-to-use-placeholders-to-bind-values-in-sql-queries) — прочитайте подраздел о binding values и сравните qmark/named placeholders с DBAPI baseline урока; операции записи и adapters пока пропустите.
- [RU · Postgres Pro: транзакции](https://postgrespro.ru/docs/postgresql/current/tutorial-transactions) — разберите `BEGIN`, `COMMIT`, `ROLLBACK` и атомарность, чтобы понимать transaction, которую Connection может начать даже если текущий workflow только читает.
- [RU · Microsoft Learn: настройка параметров](https://learn.microsoft.com/ru-ru/sql/connect/ado-net/configure-parameters?view=sql-server-ver17) — сопоставьте разделы о parameter markers и type inference с переносимой границей structure/value; синтаксис ADO.NET не копируйте в Python.
- [EN · SQLAlchemy: Establishing Connectivity](https://docs.sqlalchemy.org/en/20/tutorial/engine.html) — прочитайте весь короткий раздел про URL, dialect, DBAPI и lazy Engine; это обязательное продолжение центральной модели урока.
- [EN · SQLAlchemy: Transactions and the DBAPI](https://docs.sqlalchemy.org/en/20/tutorial/dbapi_transactions.html) — разберите `engine.connect()`, context manager, autobegin и Result mappings; write-сценарии оставьте на будущее.
- [EN · SQLAlchemy: Engine disposal](https://docs.sqlalchemy.org/en/20/core/connections.html#engine-disposal) — прочитайте различие между возвратом Connection в pool и `Engine.dispose()`; сопоставьте его с caller-owned функцией и owned CLI.
- [EN · SQLAlchemy: Reflection](https://docs.sqlalchemy.org/en/20/core/reflection.html) — изучите `inspect()`, `get_columns()` и `get_pk_constraint()` и отметьте dialect-specific ограничения reflected metadata.
- [EN · SQLAlchemy SQLite URI connections](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#uri-connections) — разберите, почему `mode=ro` относится к SQLite URI, а `uri=true` должен находиться в SQLAlchemy URL query string.
- [EN · PEP 249: Python Database API 2.0](https://peps.python.org/pep-0249/) — прочитайте `paramstyle`, Connection objects и Cursor `description`; это первичный контракт под слоем SQLAlchemy.
- [EN · OWASP: SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html) — изучите prepared statements и allow-list validation и отделите binding values от безопасной работы с identifiers и privileges.
