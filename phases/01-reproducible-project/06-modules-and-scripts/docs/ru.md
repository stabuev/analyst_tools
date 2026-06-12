# От ноутбука к модулям и скриптам

> Notebook помогает найти расчёт. Module делает расчёт переиспользуемым, а CLI —
> запускаемым без ручного кликанья.

**Тип:** Build
**Треки:** Core
**Пререквизиты:** 01/05 — Воспроизводимые ноутбуки
**Время:** ~75 минут
**Результат:** выносит переиспользуемый расчёт из notebook в функцию и CLI

## Цели обучения

- Отличать исследовательский код от устойчивой расчётной логики.
- Проектировать функцию с явными inputs, output и ошибками.
- Создавать importable package в `src` layout.
- Отделять business logic от файлового ввода-вывода и CLI.
- Запускать package через `python -m`.
- Объявлять console script в `pyproject.toml`.
- Возвращать машинный JSON в stdout и ошибки в stderr.
- Проверять один расчёт через import и через command line.

## Проблема

В notebook появился полезный расчёт:

```python
rows = list(csv.DictReader(open("orders.csv")))
amounts = [float(row["amount"]) for row in rows]
print(sum(amounts) / len(amounts))
```

Он работает, но его трудно использовать:

- другой notebook копирует те же cells;
- pipeline не может вызвать расчёт стабильной командой;
- file I/O смешан с business logic;
- пустые данные приводят к случайному `ZeroDivisionError`;
- не проверяются columns, duplicates и отрицательные суммы;
- результат печатается для человека, но не имеет явной схемы;
- import файла может немедленно запустить чтение production data.

Копирование cells масштабирует не решение, а расхождения. Нужно выделить устойчивое ядро:

```python
summary = summarize_orders(orders)
```

Затем дать ему несколько адаптеров:

```text
Notebook ─┐
CLI ──────┼──> core function
Test ─────┘
```

## Концепция

### Функция — минимальная единица повторного использования

Хорошая аналитическая функция:

- получает значения или объекты явно;
- возвращает результат;
- не читает случайный global path;
- не зависит от state notebook;
- валидирует domain assumptions;
- не печатает вместо возврата значения.

Плохо:

```python
def calculate():
    rows = read_csv("/Users/me/orders.csv")
    print(rows["amount"].mean())
```

Лучше:

```python
def summarize_orders(orders):
    ...
    return {
        "orders": count,
        "revenue": revenue,
        "average_order_value": average,
    }
```

Загрузка CSV становится отдельной функцией. Notebook может передать данные из другого
источника, не меняя формулу.

### Module и package

**Module** — `.py`-файл с definitions и statements.

**Package** организует несколько modules в namespace:

```text
order_metrics/
├── __init__.py
├── __main__.py
├── cli.py
└── core.py
```

Responsibilities:

| Файл | Ответственность |
|---|---|
| `core.py` | Data contract и расчёт |
| `cli.py` | Arguments, files, JSON, exit codes |
| `__init__.py` | Публичное Python API |
| `__main__.py` | Запуск `python -m order_metrics` |

### Import не должен запускать workflow

При:

```python
import order_metrics
```

Python выполняет top-level statements package. Поэтому нельзя помещать туда:

```python
orders = load_orders(PRODUCTION_PATH)
print(summarize_orders(orders))
```

CLI запускается только через явную точку входа:

```python
if __name__ == "__main__":
    main()
```

Для package этот guard обычно находится в `__main__.py`.

### `src` layout

Структура artifact:

```text
order_metrics_project/
├── data/
│   └── orders.csv
├── pyproject.toml
└── src/
    └── order_metrics/
        ├── __init__.py
        ├── __main__.py
        ├── cli.py
        └── core.py
```

`src` layout не позволяет случайно импортировать package прямо из repository root как
незаявленный local path. При обычной разработке project устанавливается в environment.

В уроке для быстрого запуска без installation используется:

```bash
PYTHONPATH=.../src python3 -m order_metrics ...
```

Это демонстрационный fallback. В рабочем проекте используйте установленный package:

```bash
uv sync
uv run order-metrics data/orders.csv
```

### Business logic отдельно от transport

`core.py` не должен знать:

- вызван ли он из notebook;
- пришли ли данные из CLI;
- куда сохранить JSON;
- какой exit code вернуть.

Он работает с objects:

```python
orders = [Order("A", Decimal("10.00"))]
summary = summarize_orders(orders)
```

`cli.py` адаптирует внешний мир:

```text
argv -> Path -> CSV -> Order objects -> summary -> JSON -> stdout/file
```

Так core tests выполняются быстро и не требуют subprocess.

### Ошибка данных — часть API

Artifact вводит:

```python
class DataContractError(ValueError):
    ...
```

Она обозначает ожидаемую ошибку input:

- нет required column;
- пустой `order_id`;
- duplicate ID;
- amount не является числом;
- amount отрицательный или non-finite;
- input пуст.

CLI переводит domain error в:

```text
stderr + exit code 2
```

Неожиданный programming defect не нужно молча превращать в пустой отчёт.

### Почему `Decimal`

Денежные значения:

```text
0.1 + 0.2
```

не всегда точно представлены binary float. `Decimal` хранит decimal representation и
позволяет явно контролировать rounding policy.

Artifact не округляет average автоматически. В production contract нужно отдельно
определить:

- currency;
- scale;
- rounding mode;
- правило для refunds;
- timezone и grain заказа.

### CLI как стабильный интерфейс

Команда:

```bash
order-metrics data/orders.csv
```

должна иметь предсказуемые streams:

- stdout — machine-readable result;
- stderr — diagnostics;
- exit `0` — success;
- non-zero — failure.

JSON:

```json
{
  "orders": 3,
  "revenue": "300.00",
  "average_order_value": "100.00"
}
```

Money передаётся строкой, чтобы JSON consumer не потерял decimal precision.

### Console script

В `pyproject.toml`:

```toml
[project.scripts]
order-metrics = "order_metrics.cli:main"
```

После установки package tool создаёт executable wrapper. Target — importable function, а
не путь к файлу.

## Соберите это

Откройте artifact:

```text
outputs/order_metrics_project
```

### Шаг 1: вызовите core из Python

Из каталога урока:

```bash
PYTHONPATH=outputs/order_metrics_project/src python3 - <<'PY'
from decimal import Decimal
from order_metrics import Order, summarize_orders

summary = summarize_orders([
    Order("A", Decimal("10.00")),
    Order("B", Decimal("20.00")),
])
print(summary)
PY
```

Здесь нет CSV и argparse. Проверяется чистый расчёт.

### Шаг 2: запустите module как CLI

```bash
PYTHONPATH=outputs/order_metrics_project/src \
python3 -m order_metrics \
  outputs/order_metrics_project/data/orders.csv
```

Python найдёт `order_metrics/__main__.py`, а он вызовет `cli.main`.

### Шаг 3: сохраните output

```bash
PYTHONPATH=outputs/order_metrics_project/src \
python3 -m order_metrics \
  outputs/order_metrics_project/data/orders.csv \
  --output /tmp/order-summary.json
```

Проверьте:

```bash
python3 -m json.tool /tmp/order-summary.json
```

### Шаг 4: установите project

Из `outputs/order_metrics_project`:

```bash
uv sync
uv run order-metrics data/orders.csv
```

`pyproject.toml` использует Hatchling как build backend. После lock обязательно добавьте
созданный `uv.lock` в рабочий repository.

### Шаг 5: используйте функцию в notebook

После установки project:

```python
from order_metrics import load_orders, summarize_orders

orders = load_orders(project_root / "data" / "orders.csv")
summary = summarize_orders(orders)
summary
```

Notebook отвечает за explanation и visualization, а не содержит вторую копию formula.

## Используйте это

При переносе notebook-кода:

1. Найдите повторяемое преобразование.
2. Перечислите inputs и output.
3. Уберите чтение files из формулы.
4. Запишите domain validations.
5. Верните structured result.
6. Добавьте thin CLI adapter.
7. Импортируйте ту же функцию обратно в notebook.

Проверка import:

```bash
PYTHONPATH=src python3 -c \
  "import order_metrics; print(order_metrics.__all__)"
```

Проверка CLI:

```bash
PYTHONPATH=src python3 -m order_metrics data/orders.csv
echo $?
```

Проверка error path:

```bash
PYTHONPATH=src python3 -m order_metrics missing.csv
echo $?
```

Последняя команда должна вернуть non-zero status.

## Сломайте это

### Добавьте file I/O в `summarize_orders`

Функцию станет нельзя проверить objects in memory. Верните I/O в adapter.

### Запустите CLI при import

Если `main()` вызывается без guard, test import завершится `SystemExit` или попробует
прочитать argv тестового процесса.

### Верните JSON money как float

Consumer может получить binary approximation. Согласуйте contract: строки decimal или
целое число minor units.

### Проглотите ошибочную строку

Если invalid amount пропустить молча, revenue будет правдоподобной, но неверной.
Fail fast лучше скрытой потери данных.

### Назовите module как стандартную библиотеку

Файл `csv.py` рядом со script может затенить `csv` из Python. `src` layout и осмысленный
package namespace снижают риск.

## Проверьте это

Запустите восемь behavioral tests:

```bash
python3 -m unittest discover \
  -s phases/01-reproducible-project/06-modules-and-scripts/tests \
  -p "test_*.py" -v
```

Покрыты:

- корректный parse и summary;
- duplicate ID;
- invalid, negative и non-finite amount;
- empty input;
- missing columns;
- core без file I/O;
- успешный CLI JSON;
- non-zero status ошибочного CLI.

Запустите демонстрацию:

```bash
python3 phases/01-reproducible-project/06-modules-and-scripts/code/main.py
```

Проверьте compilation:

```bash
python3 -m compileall \
  phases/01-reproducible-project/06-modules-and-scripts/outputs/order_metrics_project/src
```

## Поставьте результат

Результат урока — небольшой устанавливаемый project:

```text
input CSV
   ↓
load_orders
   ↓
Order objects
   ↓
summarize_orders
   ↓
structured result
   ↓
CLI JSON / notebook visualization / test assertion
```

Единая business logic вызывается тремя способами, но существует в одном месте.

В следующем уроке Ruff зафиксирует единый style и найдёт defects в modules до запуска
tests.

## Упражнения

1. Добавьте поле `currency`, запретите смешение currencies в одном summary и покройте
   ошибку test.
2. Добавьте CLI option `--min-amount`, не помещая parsing arguments в `core.py`.
3. Импортируйте package в чистый notebook, постройте presentation table и докажите, что
   formula не скопирована обратно в cell.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| Module | Любой каталог | Python-файл с definitions и statements |
| Package | Архив для публикации | Namespace из modules, обычно каталог |
| Importable API | CLI command | Functions и types, доступные через import |
| Core logic | Весь script | Domain calculation без transport concerns |
| Adapter | Копия formula | Преобразование внешнего interface к core API |
| `src` layout | Обязательная сложность | Layout, отделяющий source package от repository root |
| `__main__.py` | Главная business logic | Entry point для `python -m package` |
| Console script | Путь к `.py` | Устанавливаемая команда с target `module:function` |
| stdout | Любые сообщения | Основной output успешной CLI-команды |
| stderr | Только traceback | Diagnostic channel |
| Exit code | Число строк result | Машинный статус success или failure |

## Дополнительное чтение

- [Python Tutorial: Modules](https://docs.python.org/3/tutorial/modules.html) — изучите module namespace, import, packages и выполнение через `__main__`.
- [Python Library: argparse](https://docs.python.org/3/library/argparse.html) — разберите parser, positional/optional arguments и error handling CLI.
- [PyPA: src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) — поймите, как layout влияет на imports и installed project.
- [PyPA: Creating and packaging command-line tools](https://packaging.python.org/en/latest/guides/creating-command-line-tools/) — свяжите console scripts с `pyproject.toml` и installation.
