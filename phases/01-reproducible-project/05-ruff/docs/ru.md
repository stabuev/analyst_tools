# Единый стиль и Ruff

> Автоформатирование убирает споры о представлении, а lint освобождает review для
> вопросов корректности и смысла.

**Тип:** Build
**Треки:** Core
**Пререквизиты:** 01/04 — От ноутбука к модулям и скриптам
**Время:** ~45 минут
**Результат:** настраивает lint и format и исправляет типовые дефекты автоматически

## Цели обучения

- Различать linting и formatting.
- Устанавливать Ruff как development dependency.
- Хранить policy в `pyproject.toml`.
- Выбирать явный стартовый набор rule families.
- Применять safe fixes и отдельно оценивать unsafe fixes.
- Использовать точечный `noqa` с кодом правила.
- Проверять lint и format отдельными командами.
- Включать одинаковый gate локально и в CI.

## Проблема

В review небольшого расчёта обсуждаются:

- порядок imports;
- одинарные или двойные кавычки;
- длина строк;
- лишние variables;
- неиспользуемые imports;
- устаревший синтаксис;
- ветка `if`, которую можно упростить.

Часть замечаний механическая. Они повторяются, зависят от вкуса reviewer и заслоняют
важные вопросы:

- верна ли формула;
- не потеряны ли данные;
- соответствует ли grain;
- покрыты ли edge cases.

Ruff объединяет быстрый linter и formatter, но они решают разные задачи:

```text
ruff check .          defects и правила
ruff format --check . представление кода
```

Успех одной команды не гарантирует успех другой.

## Концепция

### Linter ищет нарушения

Пример:

```python
import os

value = 42
```

`os` не используется. Pyflakes rule `F401` сообщит defect:

```text
os imported but unused
```

Другие категории урока:

| Prefix | Источник | Примеры |
|---|---|---|
| `E` | pycodestyle errors | Базовые style violations |
| `F` | Pyflakes | Undefined names, unused imports |
| `I` | isort | Порядок imports |
| `UP` | pyupgrade | Современный Python syntax |
| `B` | flake8-bugbear | Вероятные defects и design smells |
| `SIM` | flake8-simplify | Избыточные конструкции |

Formatter не найдёт undefined name. Linter не обязательно переформатирует весь файл.

### Formatter нормализует код

До:

```python
def add(a,b): return a+b
```

После:

```python
def add(a, b):
    return a + b
```

Команда изменения:

```bash
ruff format .
```

Команда проверки без изменения:

```bash
ruff format --check .
```

В CI нужна вторая: pipeline не должен молча править рабочее дерево.

### Project policy находится в `pyproject.toml`

Artifact использует:

```toml
[dependency-groups]
dev = [
    "ruff>=0.15,<0.16",
]

[tool.ruff]
target-version = "py311"
line-length = 100
extend-exclude = ["data"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
line-ending = "auto"
```

Editor, CLI и CI читают один contract.

### `target-version` влияет на анализ

Если project поддерживает Python 3.11:

```toml
target-version = "py311"
```

Ruff может рекомендовать syntax, допустимый в 3.11, но не должен переписывать код в
конструкции только для более новых versions.

Значение согласуйте с:

```toml
[project]
requires-python = ">=3.11"
```

### Явный `select` лучше случайного набора

`select = ["ALL"]` кажется строгим, но при upgrade новые правила включатся автоматически.
Проект может внезапно получить десятки violations без изменения собственной policy.

Для старта:

```toml
select = ["E", "F"]
```

Затем добавляйте categories отдельными commits:

```toml
select = ["E", "F", "I", "UP", "B", "SIM"]
```

Так review видит изменение правил и соответствующие fixes.

### Safe и unsafe fixes

```bash
ruff check --fix .
```

по умолчанию применяет fixes, классифицированные как safe.

```bash
ruff check --fix --unsafe-fixes .
```

разрешает transformations, которые могут изменить behavior или comments. Не запускайте
их вслепую на большом diff.

Надёжный порядок:

```bash
git status --short
ruff check --fix .
git diff
python3 -m unittest discover
```

### Suppression должна быть узкой

Плохо:

```python
# noqa
```

Лучше:

```python
import optional_runtime_hook  # noqa: F401
```

Код правила объясняет, что именно принято осознанно. Ещё лучше — удалить suppression,
если design можно исправить.

Global ignore:

```toml
[tool.ruff.lint]
ignore = ["F401"]
```

скрывает все unused imports и обычно слишком широк.

### Generated data и code — разные вещи

Ruff должен обходить:

- virtual environments;
- build artifacts;
- generated code, если он не контролируется вручную;
- каталоги данных.

Но не исключайте `tests` только потому, что там есть violations. Test code тоже является
поддерживаемым кодом.

## Соберите это

Откройте:

```text
outputs/ruff_project
```

### Шаг 1: установите Ruff

В собственном проекте:

```bash
uv add --dev "ruff>=0.15,<0.16"
```

Или одноразово:

```bash
uvx ruff --version
```

Для воспроизводимого team workflow dependency должна быть в project contract и lockfile.

### Шаг 2: проверьте lint

```bash
cd outputs/ruff_project
uv run ruff check .
```

Одноразовый эквивалент:

```bash
uvx ruff check .
```

### Шаг 3: проверьте format

```bash
uv run ruff format --check .
```

Если есть diff:

```bash
uv run ruff format .
git diff
```

### Шаг 4: запустите объединённый gate

Из каталога урока:

```bash
python3 outputs/ruff_gate.py outputs/ruff_project
```

CLI проверяет:

- Ruff в `dependency-groups.dev`;
- явные rule families;
- `target-version`;
- formatter config;
- настоящий `ruff check`;
- настоящий `ruff format --check`.

Если Ruff не установлен как command, CLI использует зафиксированный запуск через `uvx`.

## Используйте это

Локальный цикл:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
git diff
```

Первые две команды исправляют. Последние две проверяют итог.

Перед commit:

```bash
uv run ruff check .
uv run ruff format --check .
```

Editor может запускать fix/format on save, но terminal commands остаются общим контрактом.
Нельзя считать локальную plugin configuration источником истины.

При внедрении Ruff в существующий repository:

1. Зафиксируйте version range.
2. Добавьте минимальные `E` и `F`.
3. Исправьте baseline.
4. Добавляйте `I`, `UP`, `B`, `SIM` отдельно.
5. Не смешивайте массовое форматирование с business change.

## Сломайте это

### Добавьте unused import

```python
import os
```

Проверка:

```bash
ruff check .
```

должна показать `F401`. Safe fix удалит import:

```bash
ruff check --fix .
```

### Сломайте formatting

```python
def add(a,b): return a+b
```

```bash
ruff format --check .
```

вернёт non-zero status. Исправьте:

```bash
ruff format .
```

### Удалите Ruff из dev group

Конфигурация останется, но новый участник не сможет воспроизвести toolchain через
`uv sync`. Artifact gate отметит contract failure.

### Замените rules на `ALL`

Quality gate урока отклонит policy, потому что upgrade перестанет быть контролируемым.

### Спрячьте ошибку blanket `noqa`

Ruff замолчит, но review потеряет объяснение. Используйте rule-specific suppression и
зафиксируйте причину рядом.

## Проверьте это

Запустите шесть tests с настоящим Ruff:

```bash
python3 -m unittest discover \
  -s phases/01-reproducible-project/05-ruff/tests \
  -p "test_*.py" -v
```

Покрыты:

- чистый project;
- unused import и `F401`;
- safe fix;
- format failure и repair;
- неполная configuration;
- отсутствующий executable.

Запустите демонстрацию:

```bash
python3 phases/01-reproducible-project/05-ruff/code/main.py
```

Ожидаемый результат:

```text
configuration PASS
lint          PASS
format        PASS
```

## Поставьте результат

Результат урока:

```text
outputs/
├── artifact.json
├── ruff_gate.py
└── ruff_project/
    ├── pyproject.toml
    ├── src/reporting.py
    └── tests/test_reporting.py
```

Definition of done:

```bash
ruff check .
ruff format --check .
```

обе команды завершаются status `0` без локальных editor exceptions.

В следующем уроке pytest проверит behavior расчёта. Ruff снижает количество очевидных
defects, но не доказывает правильность business logic.

## Упражнения

1. Добавьте category `C4` или `RUF`, изучите каждое новое нарушение и зафиксируйте
   осознанное изменение policy.
2. Создайте один обоснованный `noqa: CODE`, затем проверьте, можно ли устранить suppression
   refactoring.
3. Выполните массовое форматирование отдельным commit и сравните читаемость следующего
   functional diff.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| Linter | Formatter | Static checker правил и вероятных defects |
| Formatter | Проверка business logic | Детерминированное представление source code |
| Rule code | Номер строки | Идентификатор класса violation |
| Rule prefix | Один конкретный defect | Группа правил, например `F` |
| Safe fix | Абсолютная математическая гарантия | Fix, предназначенный сохранять behavior |
| Unsafe fix | Обязательно неправильный fix | Transformation с возможным изменением behavior |
| `noqa` | Исправление defect | Подавление diagnostic |
| `target-version` | Текущий Python автора | Минимальный syntax target анализа |
| Format check | Форматирование files | Проверка, нужен ли formatting diff |
| Quality gate | Автоматическое исправление CI | Набор команд, возвращающих status |

## Дополнительное чтение

- [Ruff overview](https://docs.astral.sh/ruff/) — изучите возможности linter, formatter, cache и project configuration.
- [The Ruff Linter](https://docs.astral.sh/ruff/linter/) — разберите rule selection, safe/unsafe fixes, suppressions и exit codes.
- [The Ruff Formatter](https://docs.astral.sh/ruff/formatter/) — уточните совместимость, format options и поведение `--check`.
- [Configuring Ruff](https://docs.astral.sh/ruff/configuration/) — изучите discovery `pyproject.toml`, hierarchy и полный набор settings.
