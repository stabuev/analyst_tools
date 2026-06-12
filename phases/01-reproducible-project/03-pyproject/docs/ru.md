# pyproject.toml как контракт проекта

> `pyproject.toml` отвечает не на вопрос «что установлено у автора», а на вопрос
> «что представляет собой проект и какие правила нужны, чтобы с ним работать».

**Тип:** Build
**Треки:** Core
**Пререквизиты:** 01/02 — Окружения и зависимости с uv
**Время:** ~60 минут
**Результат:** описывает метаданные, зависимости и настройки инструментов в одном
manifest

## Цели обучения

- Читать `pyproject.toml` как набор контрактов, а не как случайный TOML-файл.
- Различать стандартные таблицы `[build-system]`, `[project]` и
  `[dependency-groups]`.
- Хранить настройки pytest, Ruff и других инструментов в их пространствах `[tool.*]`.
- Отделять runtime-зависимости от инструментов разработки.
- Объяснять разницу между manifest, lockfile и установленным окружением.
- Создавать консольные команды через `[project.scripts]`.
- Находить дубли, потерянные README, неверные entry points и секреты в URL.
- Проверять manifest автоматическим CLI-аудитом.

## Проблема

Небольшой аналитический проект часто начинается с нескольких несвязанных файлов:

```text
requirements.txt
requirements-dev.txt
pytest.ini
.ruff.toml
setup.cfg
README.md
analysis.py
```

Сами по себе отдельные файлы не являются ошибкой. Проблема возникает, когда никто уже не
понимает:

- где находится актуальный список runtime-зависимостей;
- какие пакеты нужны только автору;
- какой диапазон Python поддерживается;
- откуда pytest берёт тесты;
- почему локальный Ruff форматирует иначе, чем CI;
- является ли каталог вообще устанавливаемым Python-проектом;
- какой командой запускать анализ после установки.

В результате новый участник восстанавливает правила по косвенным признакам. CI использует
одни настройки, редактор — другие, а README описывает третьи.

`pyproject.toml` собирает основной контракт проекта в одном известном месте:

```toml
[project]
name = "analytics-lab"
version = "0.1.0"
description = "Воспроизводимый аналитический проект"
readme = "README.md"
requires-python = ">=3.11,<3.14"
dependencies = [
    "numpy>=2,<3",
]

[dependency-groups]
dev = [
    "pytest>=8",
    "ruff>=0.6",
]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
target-version = "py311"
```

Это не означает, что в один файл нужно переносить абсолютно всё. Код, документация,
lockfile и CI остаются отдельными артефактами. Manifest связывает их общими метаданными и
машиночитаемыми правилами.

## Концепция

### TOML — формат, а не схема

TOML задаёт синтаксис:

```toml
name = "analytics-lab"
enabled = true
ports = [8000, 8001]

[database]
host = "localhost"
```

Но сам TOML не знает, что означает `name` или `[database]`. Смысл таблиц
`pyproject.toml` задают Python packaging specifications и документация конкретных
инструментов.

Файл может быть синтаксически корректным, но семантически бесполезным:

```toml
[tools.ruff]
line-length = 100
```

Ruff читает `[tool.ruff]`, а не `[tools.ruff]`. TOML parser примет файл, но инструмент
проигнорирует опечатку.

### Четыре зоны ответственности

Удобная карта manifest:

| Таблица | Владелец схемы | Что описывает |
|---|---|---|
| `[build-system]` | packaging specification | Как собирать distribution |
| `[project]` | packaging specification | Метаданные и runtime-контракт |
| `[dependency-groups]` | dependency groups specification | Зависимости локальных workflows |
| `[tool.*]` | конкретный инструмент | Настройки pytest, Ruff и других tools |

Не каждому аналитическому репозиторию сразу нужен `[build-system]`. Если проект только
запускается через `uv run` и не собирается в wheel, можно начать с `[project]`. Когда код
станет устанавливаемым package, build backend должен быть указан явно.

### `[project]`: идентичность и runtime

Минимальный практический контракт:

```toml
[project]
name = "analytics-lab"
version = "0.1.0"
description = "Расчёт продуктовых метрик"
readme = "README.md"
requires-python = ">=3.11,<3.14"
dependencies = []
```

Поля отвечают на разные вопросы:

- `name` — как проект идентифицируется в packaging ecosystem;
- `version` — версия distribution;
- `description` — короткое назначение;
- `readme` — файл подробного описания;
- `requires-python` — допустимые версии интерпретатора;
- `dependencies` — пакеты, необходимые установленному проекту во время работы.

Значение `readme` — не декоративная подпись. Если указано:

```toml
readme = "README.md"
```

файл должен существовать.

### Manifest не заменяет lockfile

Сравните:

```toml
dependencies = [
    "numpy>=2,<3",
]
```

и запись в `uv.lock`, где зафиксирована конкретная версия и полный граф. Их роли:

```text
pyproject.toml     допустимые требования и настройки
uv.lock            точное разрешение зависимостей
.venv              локально установленный результат
```

Правка диапазона в manifest требует пересчитать lockfile:

```bash
uv lock
```

CI может проверить, что автор не забыл это сделать:

```bash
uv lock --check
```

### Runtime и development dependencies

Runtime-зависимость нужна коду проекта:

```toml
[project]
dependencies = [
    "pandas>=2.2,<3",
]
```

Инструмент разработки нужен для создания или проверки кода:

```toml
[dependency-groups]
dev = [
    "pytest>=8",
    "ruff>=0.6",
]
```

Если библиотека используется только в тестах, она не должна принудительно устанавливаться
пользователю production-кода.

Неверное разделение:

```toml
[project]
dependencies = [
    "pandas>=2.2,<3",
    "pytest>=8",
    "ruff>=0.6",
]
```

Правило не абсолютно для каждого возможного проекта, но для курса действует простой
критерий:

> Если удаление пакета ломает рабочий код, это runtime. Если ломается только разработка,
> тестирование или linting, это development dependency.

### Dependency groups и optional dependencies — не одно и то же

Development group описывает локальный workflow:

```toml
[dependency-groups]
dev = ["pytest>=8"]
```

Optional dependency создаёт устанавливаемый extra для пользователей проекта:

```toml
[project.optional-dependencies]
excel = ["openpyxl>=3.1"]
```

Пользователь сможет запросить extra `excel`, а группа `dev` не становится частью metadata
собранного package. Не используйте extras только как старый обходной путь для dev tools,
если toolchain поддерживает dependency groups.

### `[tool.*]`: namespaced configuration

Каждый инструмент владеет своей вложенной таблицей:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
```

Наличие конфигурации ещё не устанавливает tool. Если `[tool.ruff]` есть, `ruff` всё равно
должен находиться в development dependencies.

И обратное: установленный Ruff без общей конфигурации может использовать разные defaults
на разных этапах workflow.

### Консольные команды

`[project.scripts]` создаёт entry points:

```toml
[project.scripts]
build-report = "analytics_lab.cli:main"
```

Левая часть — имя команды. Правая — импортируемый объект:

```text
module.submodule:function
```

Такой target:

```toml
build-report = "analysis.py"
```

не является Python entry point. Это имя файла, а не импортируемая функция.

### Static и dynamic metadata

Обычно metadata записывается прямо:

```toml
version = "0.1.0"
```

Если значение вычисляет build backend, поле объявляют динамическим:

```toml
dynamic = ["version"]
```

Не указывайте одно поле одновременно как статическое и dynamic. Для учебного проекта
начните со статической версии: она проще для чтения и диагностики.

### Секреты не становятся безопаснее внутри TOML

Так делать нельзя:

```toml
dependencies = [
    "private-lib @ https://login:password@example.org/private-lib.whl",
]
```

Файл попадает в Git, историю review, CI logs и локальные clones. Используйте механизм
аутентификации package index или переменные окружения, не inline credentials.

## Соберите это

Создайте каталог:

```bash
mkdir pyproject-lab
cd pyproject-lab
```

Инициализируйте manifest артефактом урока:

```bash
python3 ../outputs/pyproject_audit.py init . \
  --name pyproject-lab \
  --description "Учебный аналитический проект" \
  --requires-python ">=3.11,<3.14"
```

Если вы работаете из корня курса:

```bash
python3 phases/01-reproducible-project/03-pyproject/outputs/pyproject_audit.py \
  init /tmp/pyproject-lab \
  --name pyproject-lab \
  --description "Учебный аналитический проект" \
  --requires-python ">=3.11,<3.14"
```

Команда создаёт:

```text
pyproject-lab/
├── README.md
├── pyproject.toml
└── tests/
```

### Шаг 1: прочитайте manifest сверху вниз

Не начинайте с правки. Сначала ответьте:

1. Как называется проект?
2. Какой Python он поддерживает?
3. Какие зависимости нужны runtime?
4. Какие нужны разработчику?
5. Какие tools настроены?

Проверьте синтаксис стандартной библиотекой:

```bash
python3 -c 'import pathlib, tomllib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text()))'
```

### Шаг 2: добавьте реальную runtime-зависимость

Через uv:

```bash
uv add "pandas>=2.2,<3"
```

Не редактируйте одновременно manifest и lockfile вручную. `uv add` обновит проектный
контракт согласованно.

### Шаг 3: настройте команду проекта

Создайте package:

```text
src/
└── pyproject_lab/
    ├── __init__.py
    └── cli.py
```

В `cli.py`:

```python
def main() -> None:
    print("report is ready")
```

В manifest:

```toml
[project.scripts]
build-report = "pyproject_lab.cli:main"
```

Для устанавливаемого `src` layout потребуется build system. До его добавления воспринимайте
entry point как следующий слой контракта, а не обещание, что package уже собирается.

### Шаг 4: выполните аудит

```bash
python3 outputs/pyproject_audit.py check .
```

JSON-отчёт:

```bash
python3 outputs/pyproject_audit.py check . \
  --format json \
  --output pyproject-report.json
```

CLI проверяет:

- валидность TOML;
- обязательные metadata;
- существование README;
- дубли direct dependencies;
- попадание pytest и Ruff в runtime;
- пересечение runtime и dev groups;
- соответствие tool config и dev dependencies;
- формат console scripts;
- inline credentials в dependency URLs.

Он намеренно не пытается заменить packaging validator или конкретный tool. Это короткий
учебный quality gate для наиболее частых ошибок.

## Используйте это

Перед review manifest:

```bash
python3 outputs/pyproject_audit.py check .
uv lock --check
git diff -- pyproject.toml uv.lock
```

При чтении чужого проекта используйте порядок:

1. `[project]` — что это и что нужно runtime.
2. `[dependency-groups]` — какие workflows поддерживает команда.
3. `[tool.*]` — какие quality rules действуют.
4. `[build-system]` — как package собирается.
5. Lockfile — во что разрешились требования.

При добавлении нового инструмента изменяются минимум две части:

```toml
[dependency-groups]
dev = [
    "new-tool>=1",
]

[tool.new-tool]
setting = "value"
```

Потом обновляется lockfile. Это делает diff объяснимым: инструмент установлен и его
поведение зафиксировано.

## Сломайте это

### Удалите README

```bash
rm README.md
python3 outputs/pyproject_audit.py check .
```

Manifest ссылается на отсутствующий файл. Исправление — вернуть документ или изменить
metadata на реальный target.

### Продублируйте dependency

```toml
dependencies = [
    "my_package>=1",
    "my-package<3",
]
```

Имена нормализуются: `_`, `-` и `.` не делают их разными packages. Объедините constraints
в одно requirement.

### Перенесите pytest в runtime

```toml
[project]
dependencies = ["pytest>=8"]
```

Аудит покажет misplaced development tool. Верните его в `dependency-groups.dev`.

### Настройте tool, но не установите его

Оставьте `[tool.ruff]`, удалив Ruff из dev group. Конфигурация существует, но workflow
невозможно воспроизвести.

### Сделайте опечатку в имени таблицы

```toml
[tools.ruff]
line-length = 100
```

TOML останется валидным. Запустите сам инструмент:

```bash
uv run ruff check .
```

Manifest-аудит не может знать схемы всех tools; поведение обязан подтверждать tool.

### Сломайте TOML

```toml
dependencies = [
    "numpy>=2"
```

Parser должен завершиться ошибкой до любых смысловых проверок.

## Проверьте это

Запустите семь поведенческих тестов:

```bash
python3 -m unittest discover \
  -s phases/01-reproducible-project/03-pyproject/tests \
  -p "test_*.py" -v
```

Тесты проверяют:

- создание валидного manifest и экранирование кавычек;
- отсутствующий README;
- нормализацию имён и дубли dependencies;
- pytest в runtime;
- tool config без соответствующей dev dependency;
- пересечение runtime и dev group;
- неверный target console script.

Запустите демонстрацию:

```bash
python3 phases/01-reproducible-project/03-pyproject/code/main.py
```

Ожидаемый итог:

```text
Result: valid contract
```

## Поставьте результат

Результат урока — manifest, который можно объяснить по строкам:

```text
project identity  -> [project]
runtime contract  -> project.dependencies
local workflows   -> [dependency-groups]
tool behavior     -> [tool.*]
exact resolution  -> uv.lock
```

Артефакт:

```text
outputs/pyproject_audit.py
```

Команда quality gate:

```bash
python3 outputs/pyproject_audit.py check . && uv lock --check
```

В следующем уроке этот контракт будет связан с Jupyter kernel: одного имени окружения
недостаточно, нужно доказать, какой Python фактически исполняет notebook.

## Упражнения

1. Возьмите существующий аналитический репозиторий и классифицируйте каждую зависимость как
   runtime, development или optional. Обоснуйте спорные случаи.
2. Добавьте `[project.scripts]` для функции `main`, установите проект и вызовите команду без
   прямого обращения к `.py`-файлу.
3. Намеренно рассинхронизируйте `pyproject.toml` и `uv.lock`, покажите разницу между
   semantic audit и `uv lock --check`, затем исправьте оба контракта.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| Manifest | Список установленных пакетов | Декларация metadata, requirements и configuration |
| `[project]` | Настройки любого инструмента | Стандартизованные metadata Python-проекта |
| Runtime dependency | Всё, что установлено в `.venv` | Requirement рабочего кода проекта |
| Dependency group | Публичный extra package | Набор зависимостей локального workflow |
| Optional dependency | Dev tool | Устанавливаемая пользователем дополнительная возможность |
| `[tool.*]` | Единая универсальная схема | Namespaced config со схемой конкретного tool |
| Entry point | Путь к Python-файлу | Ссылка `module:function` на импортируемый объект |
| Lockfile | Замена manifest | Точное разрешение требований manifest |
| Static metadata | Значение, которое нельзя менять | Значение, записанное прямо в manifest |
| Dynamic metadata | Любая переменная TOML | Поле, значение которого предоставляет build backend |

## Дополнительное чтение

- [Python Packaging User Guide: Writing your pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) — разберите назначение `[build-system]`, `[project]` и `[tool]` на официальных примерах.
- [PyPA specification: pyproject.toml](https://packaging.python.org/en/latest/specifications/pyproject-toml/) — используйте как нормативную схему project metadata и entry points.
- [PyPA specification: Dependency Groups](https://packaging.python.org/en/latest/specifications/dependency-groups/) — уточните, как dev groups отличаются от published extras.
- [PEP 735: Dependency Groups in pyproject.toml](https://peps.python.org/pep-0735/) — изучите мотивацию, ограничения и принятый дизайн dependency groups.
- [uv Docs: Configuration files](https://docs.astral.sh/uv/concepts/configuration-files/) — проверьте, какие настройки uv читает из `pyproject.toml` и `uv.toml`.
