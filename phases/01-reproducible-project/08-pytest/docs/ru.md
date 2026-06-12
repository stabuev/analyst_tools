# Первые проверки с pytest

> Хороший тест фиксирует аналитический контракт: какие данные допустимы и какой
> наблюдаемый результат должен получить пользователь.

**Тип:** Build
**Треки:** Core
**Пререквизиты:** 01/07 — Единый стиль и Ruff
**Время:** ~75 минут
**Результат:** пишет behavioral test для ключевого аналитического преобразования

## Цели обучения

- Формулировать test как Arrange, Act, Assert.
- Проверять observable behavior, а не внутреннюю реализацию.
- Покрывать happy path, границы и invalid inputs.
- Использовать `pytest.approx` для float.
- Проверять exceptions через `pytest.raises`.
- Сокращать повторения fixtures и parametrization.
- Сохранять независимость tests от порядка запуска.
- Настраивать discovery и strict markers в `pyproject.toml`.

## Проблема

Функция считает conversion rate:

```python
conversion = purchases / views
```

На одном примере она возвращает ожидаемые `0.25`, и автор считает расчёт готовым. Но
неоговорёнными остаются вопросы:

- считаются события или уникальные пользователи;
- раздувают ли повторные события denominator;
- допустим ли purchase без view;
- что делать с пустой воронкой;
- как обрабатывать пустой `user_id`;
- как сравнивать `2 / 3` с float;
- сохранится ли behavior после refactoring.

Ручная проверка одного notebook output не удерживает эти решения. Behavioral tests
превращают их в исполняемый контракт.

## Концепция

### Test проверяет поведение

Function contract:

```python
result = calculate_conversion(events)
```

Observable behavior:

- `entrants` — число уникальных пользователей start event;
- `converters` — число уникальных пользователей conversion event;
- `conversion_rate` — converters / entrants;
- duplicates не меняют counts;
- invalid funnel вызывает `FunnelDataError`.

Test не должен без необходимости знать:

- используются ли внутри sets;
- как называются local variables;
- сколько helper functions вызвано;
- в каком порядке написаны private expressions.

Тогда implementation можно безопасно менять, пока contract сохраняется.

### Arrange, Act, Assert

```python
def test_calculates_conversion_for_unique_users():
    # Arrange
    events = [
        {"user_id": "u-1", "event": "view"},
        {"user_id": "u-1", "event": "purchase"},
    ]

    # Act
    result = calculate_conversion(events)

    # Assert
    assert result.entrants == 1
    assert result.converters == 1
    assert result.conversion_rate == 1.0
```

Комментарии не обязательны в каждом test. Важна структура: setup, одно действие,
проверяемые ожидания.

### Happy path недостаточен

Минимальный набор для аналитического преобразования:

| Класс | Вопрос |
|---|---|
| Positive | Работает ли обычный пример? |
| Boundary | Что происходит при 0%, 100%, одном пользователе? |
| Duplicate | Не раздувает ли повтор метрику? |
| Empty | Определён ли пустой denominator? |
| Invalid | Отклоняется ли нарушение data contract? |

Не нужно перебирать все числа. Выбирайте representatives классов поведения.

### Ordinary `assert` и introspection

pytest использует обычный Python:

```python
assert result.entrants == 3
```

При failure он показывает значения выражения. Не заменяйте ясный assert на:

```python
if result.entrants != 3:
    raise Exception("wrong")
```

Assert должен объяснять одно ожидание. Несколько связанных полей одного result допустимо
проверить в одном test, если вместе они описывают один behavior.

### Float требует tolerance

Плохо:

```python
assert result.conversion_rate == 0.6666666667
```

Лучше:

```python
assert result.conversion_rate == pytest.approx(2 / 3)
```

Для business threshold задайте tolerance осознанно:

```python
assert actual == pytest.approx(expected, rel=1e-6, abs=1e-9)
```

Не используйте чрезмерный tolerance, который пропустит реальный defect.

### Ожидаемые exceptions

```python
with pytest.raises(FunnelDataError, match="no entrants"):
    calculate_conversion([])
```

Проверяются:

- тип domain error;
- полезная часть сообщения;
- факт, что invalid input не превращён в правдоподобный output.

`try/except: pass` может пропустить ситуацию, когда exception вообще не возник.

### Parametrization

Одна формула, несколько representative cases:

```python
@pytest.mark.parametrize(
    ("entrants", "converters", "expected"),
    [
        (1, 0, 0.0),
        (1, 1, 1.0),
        (4, 1, 0.25),
    ],
)
def test_conversion_boundaries(entrants, converters, expected):
    ...
```

Каждый row становится отдельным test case и отдельно отображается в report.

Не помещайте в одну parametrization несвязанные behaviors только ради уменьшения строк.

### Fixtures предоставляют setup

```python
@pytest.fixture
def basic_events():
    return [...]
```

Test запрашивает fixture по имени:

```python
def test_duplicate_events_do_not_inflate_counts(basic_events):
    ...
```

Fixture должна предоставлять понятный baseline, а не скрывать половину scenario.
Изменяемые значения лучше создавать заново для каждого test.

### Tests независимы

Нельзя:

```text
test_01_create_file
test_02_read_file_created_above
```

Pytest не обещает business dependency по порядку names. Каждый test сам создаёт resources
или использует fixture:

```python
def test_export(tmp_path):
    output = tmp_path / "report.json"
```

### Test configuration

Artifact:

```toml
[dependency-groups]
dev = [
    "pytest>=7.4,<10",
]

[tool.pytest.ini_options]
addopts = "-q --strict-markers"
testpaths = ["tests"]
pythonpath = ["src"]
```

`testpaths` ограничивает discovery. `pythonpath` делает учебный `src` importable без
installation. В production project предпочтительно тестировать установленный package.

`--strict-markers` не позволяет опечатке в custom marker тихо превратить selection в
непредсказуемое поведение.

## Соберите это

Откройте:

```text
outputs/pytest_project
```

Структура:

```text
pytest_project/
├── pyproject.toml
├── src/
│   └── funnel.py
└── tests/
    └── test_funnel.py
```

### Шаг 1: запустите suite

```bash
python3 -m pytest outputs/pytest_project -v
```

Или из установленного project environment:

```bash
uv run pytest
```

Использование `python -m pytest` явно связывает pytest с выбранным Python.

### Шаг 2: прочитайте названия tests

Названия отвечают на business questions:

```text
test_calculates_conversion_for_unique_users
test_duplicate_events_do_not_inflate_counts
test_conversion_boundaries
test_rejects_conversion_without_start_event
test_rejects_empty_funnel
test_rejects_incomplete_event
```

Если имя звучит как implementation detail, test может быть слишком связан с кодом.

### Шаг 3: сломайте формулу

Временно замените:

```python
conversion_rate=len(converters) / len(entrants)
```

на:

```python
conversion_rate=0.5
```

Запустите suite. Должны упасть несколько meaningful cases, а failure report показать
ожидание и actual.

### Шаг 4: запустите общий gate

```bash
python3 outputs/pytest_gate.py outputs/pytest_project
```

Gate проверяет config и запускает настоящий pytest. Non-zero exit code блокирует следующий
этап pipeline.

### Шаг 5: выполните конкретный test

```bash
python3 -m pytest \
  outputs/pytest_project/tests/test_funnel.py::test_rejects_empty_funnel \
  -v
```

Targeted run ускоряет разработку, но перед commit нужен весь suite.

## Используйте это

Для новой аналитической функции начните с таблицы:

| Scenario | Input | Expected |
|---|---|---|
| Typical | 3 entrants, 2 converters | 2/3 |
| Duplicate | Повтор view и purchase | Counts не меняются |
| Lower bound | 1 entrant, 0 converters | 0.0 |
| Upper bound | 1 entrant, 1 converter | 1.0 |
| Empty | Нет entrants | Domain error |
| Broken contract | Purchase без view | Domain error |

Затем переносите rows в tests.

Полезные команды:

```bash
pytest -q
pytest -v
pytest -k duplicate
pytest tests/test_funnel.py::test_rejects_empty_funnel
pytest --collect-only -q
```

Перед review:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Ruff проверяет source quality, pytest — behavior.

## Сломайте это

### Удалите test на duplicates

Измените implementation с sets на list counting. Happy path может пройти, а repeated
events раздуют conversion. Верните regression test.

### Сравните float строкой

```python
assert str(result.conversion_rate) == "0.6667"
```

Test начинает проверять formatting, а не numeric behavior.

### Сделайте tests зависимыми

Пусть один test меняет global fixture, а другой ожидает изменение. Запуск второго отдельно
сломается. Возвращайте новый object из fixture.

### Ловите слишком общий exception

```python
with pytest.raises(Exception):
    calculate_conversion([])
```

Test пройдёт и при programming defect вроде `AttributeError`. Проверяйте domain type.

### Проверяйте private implementation

Если test требует, чтобы внутри обязательно был `set`, безопасный refactoring в другую
структуру сломает suite без изменения behavior.

## Проверьте это

Внешние tests урока:

```bash
python3 -m unittest discover \
  -s phases/01-reproducible-project/08-pytest/tests \
  -p "test_*.py" -v
```

Они подтверждают:

- успешный behavioral suite;
- падение при сломанной формуле;
- strict marker contract;
- ошибку отсутствующего pytest;
- сбор всех parametrized cases;
- использование fixture, parametrize, approx и raises.

Сам artifact содержит восемь собранных cases:

```bash
python3 -m pytest \
  phases/01-reproducible-project/08-pytest/outputs/pytest_project \
  -v
```

## Поставьте результат

Результат урока:

```text
outputs/
├── artifact.json
├── pytest_gate.py
└── pytest_project/
    ├── pyproject.toml
    ├── src/funnel.py
    └── tests/test_funnel.py
```

Definition of done:

- normal scenario проверен;
- boundaries проверены;
- invalid inputs дают domain errors;
- duplicate behavior зафиксирован;
- float сравнивается с tolerance;
- tests независимы;
- `pytest` возвращает status `0`.

В следующем уроке Ruff и pytest будут запускаться автоматически на каждом pull request.

## Упражнения

1. Добавьте промежуточный step `add_to_cart` и tests, которые проверяют последовательную
   трёхшаговую воронку.
2. Добавьте property: converters никогда не больше entrants, и создайте invalid dataset,
   нарушающий это правило.
3. Напишите test CLI или CSV adapter через `tmp_path`, оставив core tests быстрыми и
   независимыми от filesystem.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| Behavioral test | Проверка внутренних строк | Проверка observable contract |
| Happy path | Достаточное покрытие | Обычный успешный scenario |
| Boundary | Только большое число | Граница области допустимых inputs |
| Regression test | Повторный ручной запуск | Test, фиксирующий ранее найденный defect |
| Assertion | Print для debugging | Исполняемое ожидание |
| `pytest.approx` | Округление result | Сравнение с tolerance |
| `pytest.raises` | Игнорирование ошибки | Проверка ожидаемого exception |
| Fixture | Shared mutable global | Управляемый setup test |
| Parametrization | Один test с loop | Несколько отдельно reported cases |
| Test isolation | Отдельный файл | Независимость от порядка и состояния других tests |
| Discovery | Импорт всех `.py` | Правила поиска test modules и functions |

## Дополнительное чтение

- [pytest: Get Started](https://docs.pytest.org/en/stable/getting-started.html) — изучите discovery, assertions, exceptions, approximate comparisons и `tmp_path`.
- [pytest: Assertions](https://docs.pytest.org/en/stable/how-to/assert.html) — разберите introspection, `approx` и точные проверки exceptions.
- [pytest: Fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html) — изучите dependency injection, scopes и cleanup resources.
- [pytest: Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html) — свяжите project layout, imports, environments и test organization.
