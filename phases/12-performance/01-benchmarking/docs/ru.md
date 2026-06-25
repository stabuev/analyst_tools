# Корректный benchmarking

> Сначала докажите, что сравниваете один и тот же результат, и только потом обсуждайте секунды.

**Тип:** Build
**Треки:** Data, ML
**Пререквизиты:** `07-reliable-analytics/10-quality-gates`
**Время:** ~75 минут
**Результат:** строит воспроизводимый benchmark harness: фиксирует вход, версии, warm-up,
повторы, cache policy, equivalence gate и интерпретирует разброс измерений без ложной
точности.

## Цели обучения

- Зафиксировать benchmark scenario до запуска измерений.
- Отделить подготовку данных от измеряемого участка.
- Проверить эквивалентность результата до тайминга.
- Выполнить warm-up и несколько measured runs.
- Сохранить raw measurements, summary и environment report.

## Проблема

Команда готовит weekly customer revenue health mart. Прозрачная Python-реализация уже
правильно считает выручку по неделям, но на большем extract начинает тормозить.
Появляется кандидат на замену: другой порядок вычислений, другая библиотека или другой
engine.

Опасный путь выглядит так:

```text
old.py: 1.40 s
new.py: 0.45 s
new is 3x faster
```

Такой вывод еще не говорит почти ничего. Возможно, новая версия:

- читает другой вход;
- пропускает refunds;
- считает не тот grain;
- получила warm cache, а baseline запускался cold;
- измерялась один раз;
- включает setup только в одной ветке;
- быстрее на `tiny`, но хуже на рабочем размере.

В performance-фазе число без контракта считается непоставленным результатом.

## Концепция

Benchmark scenario - это договор о том, что именно сравнивается. Минимальный scenario
фиксирует:

1. бизнес-вопрос;
2. pipeline и версию логики;
3. профиль данных и размер;
4. реализации или engines;
5. timing scope;
6. warm-up и количество measured runs;
7. timer;
8. cache policy;
9. equivalence checks;
10. selection rule и ограничения.

Главная идея простая: benchmark является аналитическим артефактом. У него есть grain,
контракт результата, проверка качества, сырые наблюдения и ограниченная интерпретация.

### Порядок доверия

```text
scenario -> prepared input -> reference output -> candidate output
         -> equivalence gate -> warm-up -> repeated measurements
         -> raw runs -> summary -> ограниченный вывод
```

Если equivalence gate не прошел, измерения не запускаются. Это не техническая придирка:
быстрая неправильная витрина не является вариантом решения.

## Соберите это

В уроке используется маленький pipeline: из строк заказов собрать недельную выручку.
Reference-реализация нарочито прозрачная, candidate-реализация написана иначе, но должна
вернуть тот же нормализованный output.

### Шаг 1. Сгенерируйте фиксированный вход

```python
lines = generate_order_lines(rows=5_000, seed=42)
```

Seed и размер являются частью scenario. Генерация выполняется до timed section, потому что
вопрос урока - скорость расчета на уже подготовленных in-memory строках.

### Шаг 2. Постройте reference

```python
reference = reference_weekly_revenue(lines)
```

Reference проверяет grain `order_id, line_number`, считает `paid` как положительную
выручку, `refunded` как отрицательную часть net revenue и группирует по `week_start`.

### Шаг 3. Постройте candidate

```python
candidate = candidate_weekly_revenue(lines)
```

Candidate использует другой порядок: сначала выделяет недели, затем фильтрует строки
каждой недели. Это не обязательно быстрее. Важно, что harness умеет сравнить две ветки.

### Шаг 4. Введите equivalence gate

```python
equivalence = compare_outputs(reference, candidate)
if not equivalence["passed"]:
    raise BenchmarkError("equivalence gate failed before timing")
```

Сравнение нормализует порядок строк и типы, считает checksum обеих версий и сохраняет
первые расхождения. Пока gate не зеленый, секундомер молчит.

### Шаг 5. Измерьте несколько повторов

```python
runs = measure_seconds(
    lambda: candidate_weekly_revenue(lines),
    implementation="python_candidate",
    repeat=5,
    warmup=1,
)
```

Warm-up не попадает в raw runs. Он нужен, чтобы первый measured run меньше зависел от
ленивой инициализации, кэшей и одноразовых накладных расходов.

## Используйте это

Запустите демонстрационный пример:

```bash
uv run --locked python phases/12-performance/01-benchmarking/code/main.py
```

Запустите артефакт как CLI:

```bash
uv run --locked python phases/12-performance/01-benchmarking/outputs/benchmark_harness.py \
  --rows 5000 \
  --repeat 5 \
  --seed 42 \
  --output-dir /tmp/benchmark-package
```

CLI печатает JSON report и, если указан `--output-dir`, пишет reusable package:

```text
benchmark-package/
├── benchmark-plan.json
├── equivalence/
│   └── output-checks.json
├── measurements/
│   ├── environment.json
│   ├── raw-runs.csv
│   └── summary.csv
└── report.json
```

`raw-runs.csv` хранит каждое измерение отдельно. `summary.csv` хранит `min`, `median`,
`max` и `mean` по реализации. Вывод о speedup берется из summary, но не заменяет raw
measurements.

## Сломайте это

### Уберите equivalence gate

Если candidate забывает refunds, он может стать быстрее. Это не performance improvement,
а изменение бизнес-логики. В уроке такая поломка приводит к `BenchmarkError` до тайминга.

### Сравните разные timing scope

Нечестно измерять baseline вместе с генерацией входа, а candidate - на готовом списке.
Такой benchmark отвечает на другой вопрос. Scope должен явно сказать, включены ли чтение,
парсинг, конвертация, расчет и запись.

### Сделайте один запуск

Один запуск легко ловит cold start, соседний процесс или случайный скачок. Минимум три
measured runs в этом уроке - технический gate, а не статистическая гарантия.

### Оставьте только лучшее время

Лучший запуск показывает нижнюю границу в конкретной среде, но скрывает обычное поведение.
Для аналитического решения обычно полезнее медиана и raw distribution.

### Зафиксируйте speedup в unit test

```python
assert speedup > 2
```

Такой тест зависит от машины. Behavioral tests должны проверять структуру benchmark,
эквивалентность, наличие raw runs и отсутствие traceback на invalid input.

## Проверьте это

Точечная проверка урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/12-performance/01-benchmarking/tests \
  -v
```

Что проверяют тесты:

- генерация входа воспроизводима;
- reference и candidate дают одинаковый normalized output;
- duplicate grain блокируется;
- scenario требует equivalence checks и минимум три measured runs;
- broken candidate не доходит до timing;
- report содержит raw runs, summary и environment;
- CLI пишет reusable package;
- invalid input возвращает код ошибки без traceback.

## Поставьте результат

Артефакт урока - `outputs/benchmark_harness.py`. Его можно использовать вне текста урока:

```bash
cd phases/12-performance/01-benchmarking
uv run --locked python outputs/benchmark_harness.py \
  --rows 20000 \
  --repeat 7 \
  --seed 2026 \
  --output-dir /tmp/weekly-revenue-benchmark
```

Передайте заказчику или коллегам не только `speedup`, а весь package:

- `benchmark-plan.json` объясняет scenario;
- `output-checks.json` доказывает, что результат совпал;
- `raw-runs.csv` показывает все измерения;
- `summary.csv` показывает устойчивую сводку;
- `environment.json` фиксирует среду;
- `report.json` связывает все вместе.

Такой артефакт еще не выбирает pandas, DuckDB или Polars. Он задает стандарт доказательства,
который понадобится всем следующим урокам фазы.

## Упражнения

1. Увеличьте `--rows` в 10 раз и сравните, как меняется разброс raw runs.
2. Напишите broken candidate, который игнорирует `refunded`, и убедитесь, что timing не
   запускается.
3. Добавьте в package отдельный `scenario.md`, где человеческим языком описан timing
   scope и ограничения вывода.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Benchmark scenario | «Команда, которая выводит секунды» | Полный контракт сравнения: вход, scope, повторы, checks, среда и правило вывода |
| Timing scope | «Размер данных» | Граница работы, которая входит в измеряемый участок |
| Equivalence gate | «Лишняя проверка перед speedup» | Блокирующая сверка, что implementations возвращают один и тот же результат |
| Warm-up | «Подгонка под лучший результат» | Неизмеряемый предварительный запуск перед raw measurements |
| Raw runs | «Шум, который можно удалить» | Все отдельные наблюдения времени, нужные для честной интерпретации |
| Median runtime | «Абсолютная скорость программы» | Устойчивая сводка конкретного scenario в конкретной среде |

## Дополнительное чтение

- [Python `timeit`](https://docs.python.org/3/library/timeit.html) — стандартный модуль для повторяемых измерений и важные предупреждения о шуме benchmark.
- [Python `time.perf_counter`](https://docs.python.org/3/library/time.html#time.perf_counter) — монотонный высокоточный таймер, который подходит для wall-clock измерений коротких участков.
- [Python `statistics.median`](https://docs.python.org/3/library/statistics.html#statistics.median) — медиана как простая устойчивая сводка raw measurements.
- [pyperf documentation](https://pyperf.readthedocs.io/en/latest/) — практический инструмент для более строгих Python benchmarks, calibration и metadata.
