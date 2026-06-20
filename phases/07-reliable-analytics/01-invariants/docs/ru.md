# Инварианты аналитического расчета

> Надежный расчет начинается с ответа на вопрос: что не имеет права измениться незаметно?

**Тип:** Build  
**Треки:** Core  
**Пререквизиты:** 06/11 - От наблюдения к аналитическому выводу  
**Время:** ~75 минут  
**Результат:** формулирует структурные и алгебраические инварианты расчета, превращает
их в исполняемый gate и сверяет итог независимым контрольным путем.

## Цели обучения

- Отличать пример ожидаемого результата от общего инварианта.
- Защищать grain, ключи, домены значений и арифметические связи.
- Разделять входные, промежуточные и выходные checks.
- Выполнять независимый контрольный расчет другим способом.
- Возвращать machine-readable report и ненулевой exit code при нарушении.

## Проблема

Ежедневный расчет paid revenue завершился без exception и показал `10 350.50 RUB`.
Число выглядит правдоподобно, но в batch повторно доставлен заказ `O001`. Обычная сумма
молча учитывает его дважды.

Проверка только конкретного ожидаемого числа тоже слаба:

```python
assert paid_revenue == 9150.50
```

Она привязана к одному fixture и не объясняет, какие свойства должны сохраняться на
следующем batch. Кроме того, обязательный production gate нельзя строить только на
`assert`: при запуске `python -O` такие statements не исполняются.

Нужен явный контракт:

```text
одна строка = один заказ
order_id уникален
status входит в согласованный домен
amount_rub неотрицателен и имеет денежную точность
paid revenue равен сумме paid-заказов
основной и контрольный расчеты совпадают
```

## Концепция

### Инвариант описывает свойство, а не снимок

Пример:

```text
paid_revenue = 9150.50
```

Инвариант:

```text
paid_revenue = sum(amount_rub for rows where status == "paid")
```

Первое утверждение верно только для одного набора. Второе должно быть верно для любого
допустимого batch.

### Три уровня проверок

| Уровень | Вопрос | Пример |
|---|---|---|
| Вход | Можно ли данным доверять до расчета? | ключи заполнены, status известен |
| Преобразование | Сохранился ли смысл между стадиями? | число строк после дедупликации ожидаемо |
| Выход | Согласуются ли итоговые числа? | сумма status counts равна order count |

Не каждое изменение числа является ошибкой. Order count между днями меняется. Но
соотношение:

```text
sum(status_counts.values()) == order_count
```

обязано сохраняться.

### Структурные и алгебраические инварианты

Структурные rules описывают форму:

- обязательные столбцы присутствуют;
- batch не пуст;
- `order_id` и `user_id` заполнены;
- `order_id` уникален;
- timestamp содержит timezone offset.

Алгебраические rules связывают числа:

```text
0 <= paid_order_count <= order_count
sum(status_counts) == order_count
paid_revenue(primary) == paid_revenue(control)
```

Структурная проверка выполняется раньше агрегатов. Нет смысла считать revenue после
неизвестного status или дубликата business key: правдоподобный output только замаскирует
нарушенный контракт.

### Независимый контрольный путь

Основной расчет урока использует pandas и сумму целых копеек. Контрольный расчет проходит
по строкам обычным Python-loop и складывает `Decimal`.

```text
primary: pandas -> integer kopecks -> group/filter
control: Python loop -> Decimal -> explicit condition
```

Это не абсолютная независимость: оба пути читают один вход и используют одно определение
`status=paid`. Но риск общей ошибки меньше, чем при повторном вызове одной функции.

Контроль особенно полезен для:

- выручки и балансов;
- знаменателей долей;
- row-count reconciliation;
- перехода между grain;
- результатов после JOIN;
- инкрементальной и полной сборки.

### Gate должен быть наблюдаемым

Каждый check получает стабильный `id`:

```json
{
  "id": "order_id_unique",
  "valid": false,
  "expected": "one row per order_id",
  "observed": 1,
  "sample": ["O001"]
}
```

Текст ошибки может измениться после обновления библиотеки. Стабильный идентификатор
позволяет тестам, CI и monitoring работать с семантикой check, а не парсить строку.

## Соберите это

Откройте `code/main.py`. Ручной control path считает четыре значения:

```python
def manual_control(rows):
    order_ids = [row["order_id"] for row in rows]
    paid_amounts = [
        Decimal(row["amount_rub"])
        for row in rows
        if row["status"].strip().lower() == "paid"
    ]
    return {
        "order_count": len(rows),
        "unique_order_count": len(set(order_ids)),
        "paid_order_count": len(paid_amounts),
        "paid_revenue_rub": f"{sum(paid_amounts, start=Decimal('0')):.2f}",
    }
```

Запустите:

```bash
uv run --locked python code/main.py
```

Для committed tiny ожидаются:

```text
order_count = 10
unique_order_count = 10
paid_order_count = 7
paid_revenue_rub = 9150.50
```

Теперь повторите первую строку `orders.csv`. Order count станет `11`, но unique count
останется `10`. Это и есть минимальный контрпример нарушенного grain.

### Шаг 1: объявите grain

До кода запишите:

```text
grain: одна строка на заказ
business key: order_id
```

Без этой фразы невозможно решить, является повторная строка дефектом или допустимой
историей состояний заказа.

### Шаг 2: перечислите домены

```text
status in {paid, refunded, cancelled, pending}
currency == RUB
amount_rub >= 0
fractional digits(amount_rub) <= 2
ordered_at is timezone-aware
```

Неизвестный status нельзя молча отнести к unpaid: это изменение бизнес-классификации.

### Шаг 3: добавьте reconciliation

Сравните pandas-агрегат с loop-контролем. Отдельно проверьте partition:

```python
sum(status_counts.values()) == order_count
```

Такой check обнаруживает потерянную или дважды учтенную категорию даже тогда, когда
итоговая revenue случайно не изменилась.

## Используйте это

Артефакт `outputs/invariant_gate.py` читает CSV и выпускает JSON report:

```bash
uv run --locked python outputs/invariant_gate.py \
  --input ../data/tiny/orders.csv \
  --output invariant-report.json
```

Успешный запуск возвращает exit code `0`. Нарушенный контракт возвращает `1`.
Ошибка использования, например отсутствующий файл, возвращает `2`.

Для учебного просмотра failed report без блокировки:

```bash
uv run --locked python outputs/invariant_gate.py \
  --input broken-orders.csv \
  --allow-failures
```

Gate проверяет:

1. обязательные столбцы и непустой batch;
2. заполненность ключей и уникальность `order_id`;
3. domain `status` и `currency`;
4. денежную точность и неотрицательность;
5. timezone-aware timestamps;
6. reconciliation количества строк, status partition и paid revenue.

Pandera в `07/05` сделает DataFrame schema компактнее и даст полный lazy error report.
Но бизнес-инварианты и независимый control path останутся отдельными checks.

## Сломайте это

Проверьте один дефект за раз:

1. Повторите `O001` - должен упасть `order_id_unique`.
2. Очистите `user_id` - должен упасть `keys_not_blank`.
3. Замените `paid` на `complete` - должен упасть `status_domain`.
4. Запишите `-1.00` - должен упасть `amount_domain`.
5. Запишите `1.001` - денежная точность должна быть отклонена.
6. Удалите `+03:00` из timestamp - должен упасть `timestamp_timezone`.
7. Удалите столбец `currency` - summary не должен вычисляться.

Важно: не объединяйте все дефекты в одном fixture. Иначе первый failure скрывает
следующие, а причина красного gate становится неоднозначной.

## Проверьте это

Behavioral tests проверяют observable contract:

- валидный tiny batch проходит;
- итог совпадает с независимым control summary;
- дубликат нарушает grain;
- пустой ключ и неизвестный status блокируют расчет;
- отрицательная сумма и лишний десятичный знак отклоняются;
- naive timestamp не принимается;
- missing column останавливает summary;
- CLI пишет тот же JSON в stdout и output file и возвращает ненулевой exit code.

```bash
uv run --locked python -m unittest discover -s tests
```

Тесты обращаются к checks по стабильному `id`, а не по позиции или полному тексту
сообщения.

## Поставьте результат

`outputs/invariant_gate.py` можно использовать до расчета витрины:

```bash
uv run --locked python outputs/invariant_gate.py \
  --input path/to/orders.csv \
  --output quality/invariant-report.json
```

Артефакт не исправляет данные и не удаляет дубликаты. Его задача - остановить pipeline,
показать нарушенное свойство и сохранить небольшой sample для диагностики.

В следующих уроках этот gate станет первым слоем общей системы:

```text
invariants -> stage tests -> generated cases -> schemas -> SQL checks
           -> regression -> monitoring -> atomic publication
```

## Упражнения

1. Добавьте инвариант `paid_revenue <= total_amount`.
2. Расширьте вход валютой `EUR` и сделайте allowed currencies параметром, не ослабляя
   денежную точность.
3. Добавьте проверку batch-window: все `ordered_at` должны попадать в объявленный
   интервал запуска.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Инвариант | Ожидаемое число для одного fixture | Свойство для всех допустимых входов |
| Grain | Количество строк | Смысл одной строки и ключ сущности |
| Domain check | Автоматическое исправление значений | Проверка допустимого множества |
| Reconciliation | Повторный вызов той же функции | Сверка связанных итогов или разных путей |
| Control calculation | Еще один production pipeline | Простой независимый расчет критичного числа |
| Quality gate | Отчет с warning | Проверка, которая блокирует дальнейший шаг |

## Дополнительное чтение

- [Python: assert statement](https://docs.python.org/3/reference/simple_stmts.html#the-assert-statement) - разберите, почему `assert` удаляется при оптимизации и не подходит как единственный production gate.
- [pytest: assertions](https://docs.pytest.org/en/stable/how-to/assert.html) - изучите introspection, сравнение структур и явную проверку exceptions в test suite.
- [AWS Deequ](https://github.com/awslabs/deequ) - посмотрите, как data quality constraints, metrics и verification suites масштабируют идею инвариантов на наборы данных.
- [dbt data tests](https://docs.getdbt.com/docs/build/data-tests) - сравните generic checks ключей и связей с custom business assertions для SQL-моделей.
