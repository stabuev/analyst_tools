# CPU и memory profiling

> Profiler нужен, чтобы найти горячую зону, а не чтобы объявить победителя по одной секунде.

**Тип:** Build
**Треки:** Data, ML
**Пререквизиты:** `12-performance/01-benchmarking`
**Время:** ~75 минут
**Результат:** профилирует один аналитический pipeline по wall time, CPU и памяти,
отделяет Python overhead, native allocations, IO и algorithmic hot spots и выпускает
actionable profile report.

## Цели обучения

- Запустить CPU profile на конкретном участке pipeline, а не на всей подготовке данных.
- Сравнить wall time и process time без ложного вывода о speedup.
- Собрать traced Python memory profile через `tracemalloc`.
- Объяснить ограничения `cProfile` и `tracemalloc`.
- Выпустить report с top functions, top allocations, memory budget и интерпретацией.

## Проблема

После корректного benchmark из прошлого урока команда видит: weekly revenue pipeline
медленнее, чем нужно. Следующий соблазн - переписать первую попавшуюся функцию или
сразу поменять engine.

Так performance-задача быстро становится лотереей:

```text
pipeline slow -> переписали parse_money -> стало неясно
pipeline slow -> включили multiprocessing -> память выросла
pipeline slow -> заменили библиотеку -> результат поменялся
```

Нужен другой артефакт: profile report. Он не доказывает стабильное ускорение. Он
показывает, куда смотреть: Python call overhead, алгоритмический hot spot, traced
allocation, возможное IO-ожидание или native work, который стандартный Python profiler
видит только косвенно.

## Концепция

Профилирование отвечает на вопрос "что происходило внутри одного запуска?". Benchmark
отвечает на вопрос "как стабильно ведут себя реализации при честном сравнении?". Эти
инструменты связаны, но не заменяют друг друга.

Минимальный profile report фиксирует:

1. scenario и timing scope;
2. environment;
3. контракт результата;
4. wall time и process time;
5. CPU profile;
6. memory profile;
7. findings с ограничениями;
8. рекомендацию, какую гипотезу проверять benchmark'ом.

### Wall time и process time

`time.perf_counter()` измеряет elapsed wall-clock time. В него попадает ожидание диска,
сети, sleep, scheduler и внешних систем.

`time.process_time()` измеряет CPU time текущего процесса. Если wall time заметно больше
process time, pipeline мог ждать IO или внешний engine. Если значения близки, задача
похожа на CPU-bound участок, но это не доказательство без дополнительного контекста.

### CPU profile

`cProfile` собирает deterministic profiling statistics по Python calls: сколько раз
вызвана функция, сколько времени она провела внутри себя и сколько cumulative time прошло
вместе с вложенными вызовами.

Большой cumulative time говорит: "начни ревью отсюда". Он не говорит автоматически:
"перепиши именно эту строку". Иногда функция наверху только оборачивает дорогие
дочерние вызовы.

### Memory profile

`tracemalloc` показывает Python allocations, которые видит интерпретатор: строки, списки,
словари, промежуточные объекты. Это полезно для аналитического Python-кода, но не равно
full process RSS. Native allocations внутри C/Rust/Java libraries, memory mapping и
внешние engines могут быть видны плохо или не видны вовсе.

## Соберите это

В уроке профилируется тот же тип задачи: недельная витрина выручки из строк заказов.
Генерация входа выполняется до профилируемого участка, чтобы report говорил о pipeline,
а не о synthetic data setup.

### Шаг 1. Зафиксируйте вход

```python
lines = generate_order_lines(rows=5_000, seed=42)
```

`rows` и `seed` входят в scenario. Если вход поменялся, profile report уже относится к
другому запуску.

### Шаг 2. Определите профилируемый участок

```python
result, timings = run_once(profiled_pipeline, lines)
```

`run_once` делает ровно один запуск pipeline, измеряет `wall_seconds` и
`process_seconds`, затем проверяет контракт результата. Это осознанно не benchmark:
здесь нет warm-up и повторов, потому что цель - собрать внутренний след выполнения.

### Шаг 3. Оберните участок в `cProfile`

```python
profiler = cProfile.Profile()
profiler.enable()
result, timings = run_once(profiled_pipeline, lines)
profiler.disable()
```

После запуска `pstats.Stats` сортирует функции по `cumulative_seconds`. В report
попадают `primitive_calls`, `total_calls`, `internal_seconds`, `cumulative_seconds` и
доля internal time.

### Шаг 4. Включите `tracemalloc`

```python
tracemalloc.start()
result, timings = run_once(profiled_pipeline, lines)
current_bytes, peak_bytes = tracemalloc.get_traced_memory()
snapshot = tracemalloc.take_snapshot()
tracemalloc.stop()
```

Snapshot агрегируется по строкам исходного кода. Это помогает увидеть, где создаются
самые крупные Python objects, но в отчете обязательно остается warning про native
allocations и RSS.

### Шаг 5. Сформируйте findings

```python
findings = classify_profile(
    cpu=cpu_profile,
    memory=memory_profile,
    memory_budget_mb=16.0,
)
```

Findings не должны звучать как "оптимизируй X". Хороший finding говорит: "X имеет самый
большой cumulative time", "peak traced memory близок к budget", "строка Y создала больше
всего traced allocations". Дальше нужна гипотеза и benchmark из `12/01`.

## Используйте это

Запустите демонстрационный пример:

```bash
uv run --locked python phases/12-performance/02-profiling/code/main.py
```

Запустите артефакт как CLI:

```bash
uv run --locked python phases/12-performance/02-profiling/outputs/profiling_report.py \
  --rows 5000 \
  --seed 42 \
  --top-n 8 \
  --memory-budget-mb 16 \
  --output /tmp/profile-report.json
```

CLI печатает JSON report в stdout и, если указан `--output`, сохраняет тот же report в
файл. В report есть:

- `scenario` - что профилировали;
- `environment` - версия Python и платформа;
- `result_contract` - grain, output rows и ключевые totals;
- `timings` - wall/process time одного запуска;
- `cpu_profile` - top Python functions;
- `memory_profile` - peak traced memory и top allocation lines;
- `findings` - actionable классификация;
- `interpretation` - явное напоминание, что это не benchmark claim.

## Сломайте это

### Профилируйте setup вместе с pipeline

Если включить генерацию данных внутрь profiler scope, верхние функции могут показать
работу random generator и создание fixtures. Это честный профиль, но другого вопроса.
Timing scope должен сказать, что именно попало в измерение.

### Используйте profiler как benchmark

```text
profiled run: 0.18 s
optimized profiled run: 0.12 s
speedup: 1.5x
```

Такой вывод слабый: profiler добавляет overhead, запуск один, warm-up отсутствует,
окружение может шуметь. После оптимизации вернитесь к benchmark harness из `12/01`.

### Примите `tracemalloc` за RSS

Если `tracemalloc` показывает 8 MB, это не значит, что процесс занимал только 8 MB.
Pandas, NumPy, DuckDB, Arrow и другие native-backed инструменты могут выделять память
вне Python allocator. Для production memory budget нужен отдельный RSS/process-level
monitoring.

### Игнорируйте контракт результата

Профиль неправильного результата не помогает. В уроке `validate_result` проверяет
обязательные колонки, уникальный grain и базовые инварианты.

## Проверьте это

Точечная проверка урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/12-performance/02-profiling/tests \
  -v
```

Что проверяют тесты:

- генерация входа воспроизводима;
- output имеет уникальный grain `week_start, platform`;
- duplicate source grain блокируется;
- report содержит CPU, memory, timings и environment;
- interpretation явно запрещает speedup claim по profile run;
- memory budget может перейти в severity `block`;
- broken pipeline останавливается на result contract;
- CLI пишет JSON и не печатает traceback на invalid input.

Полная проверка курса:

```bash
uv run --locked python scripts/validate_course.py
uv run --locked python scripts/run_lesson_tests.py
```

## Поставьте результат

Именованный артефакт урока:

```text
outputs/profiling_report.py
```

Его можно переиспользовать как шаблон для performance-разбора:

```bash
python outputs/profiling_report.py \
  --rows 5000 \
  --top-n 8 \
  --memory-budget-mb 16 \
  --output /tmp/profile-report.json
```

Перед передачей результата приложите JSON report и короткую интерпретацию:

```text
Finding: profiled_pipeline has the largest cumulative time.
Evidence: cProfile cumulative_seconds=...
Memory: peak traced memory within 16 MB budget.
Limit: tracemalloc is Python allocations, not full RSS.
Next step: formulate one optimization hypothesis and validate it with benchmark harness.
```

## Упражнения

1. Увеличьте `rows` в 10 раз и сравните, меняется ли top CPU function.
2. Добавьте искусственный `time.sleep()` в pipeline и объясните разницу между wall time и
   process time.
3. Замените `set` пользователей на список и найдите, как изменились top allocations.
4. Добавьте finding для подозрительно большой разницы `wall_seconds - process_seconds`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Profile report | "Это benchmark результата" | Отчет о внутреннем поведении одного запуска с ограниченной интерпретацией |
| Wall time | "Чистое время CPU" | Elapsed time с ожиданиями IO, scheduler и внешних систем |
| Process time | "Полное пользовательское ожидание" | CPU time процесса без sleep и части ожиданий |
| Cumulative time | "Время только этой функции" | Время функции вместе с вложенными вызовами |
| Internal time | "Вся стоимость ветки вызовов" | Время, проведенное непосредственно в функции |
| Traced memory | "Полный RSS процесса" | Python allocations, видимые `tracemalloc` |
| Native allocation | "То же самое, что Python object" | Память, выделенная библиотекой или runtime вне обычного Python object accounting |

## Дополнительное чтение

- [Python `profile` and `cProfile`](https://docs.python.org/3/library/profile.html) - официальный раздел про deterministic profiling, поля `pstats` и смысл internal / cumulative time.
- [Python `tracemalloc`](https://docs.python.org/3/library/tracemalloc.html) - как включать tracing, читать snapshots и почему это именно traced Python allocations.
- [Python `time.process_time`](https://docs.python.org/3/library/time.html#time.process_time) - короткая спецификация CPU-времени процесса и отличие от elapsed timers.
- [Python `resource`](https://docs.python.org/3/library/resource.html) - Unix-интерфейс, который полезно изучить дальше для process-level limits и RSS-like сигналов.
