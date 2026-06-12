# Окружения и зависимости с uv

> Воспроизводится не каталог `.venv`, а процедура, которая заново создаёт его из
> `pyproject.toml`, выбранного Python и зафиксированного `uv.lock`.

**Тип:** Build
**Треки:** Core
**Пререквизиты:** 01/01 — Версии Python и совместимость
**Время:** ~75 минут
**Результат:** создаёт окружение, добавляет зависимости и воспроизводит установку из
lock-файла

## Цели обучения

- Различать декларацию зависимостей, lockfile и установленное окружение.
- Создавать проектное окружение `.venv` через `uv`.
- Добавлять runtime- и development-зависимости командами `uv add`.
- Запускать код через `uv run` без ручного выбора Python.
- Проверять актуальность `uv.lock` и синхронизацию `.venv`.
- Удалять локальное окружение и восстанавливать его через `uv sync --locked`.
- Объяснять, почему `.venv` не хранится в Git, а `uv.lock` хранится.

## Проблема

В проекте появился импорт:

```python
import numpy as np
```

На машине автора `numpy` уже установлен, поэтому скрипт запускается. Коллега клонирует
репозиторий и получает:

```text
ModuleNotFoundError: No module named 'numpy'
```

Автор отвечает:

```bash
pip install numpy
```

Но эта команда не сообщает:

- какую версию установить;
- с каким Python она совместима;
- какие транзитивные зависимости были выбраны;
- где находится окружение;
- как повторить установку через месяц;
- какие пакеты нужны только для разработки;
- совпадает ли окружение с текущим кодом.

Архив `.venv` тоже не решает задачу. В нём есть абсолютные пути, platform-specific
binary-файлы и состояние конкретной машины. Каталог может не работать на другой ОС,
архитектуре или даже после перемещения проекта.

Нужна не копия окружения, а воспроизводимый контракт:

```text
requires-python + зависимости + lockfile
                 ↓
          синхронизация uv
                 ↓
              .venv
```

## Концепция

### Три состояния проекта

В uv-проекте полезно различать три уровня.

**Декларация** в `pyproject.toml` описывает допустимые требования:

```toml
[project]
requires-python = ">=3.11,<3.13"
dependencies = [
    "numpy>=2,<3",
]

[dependency-groups]
dev = [
    "pytest>=8",
]
```

Здесь указаны диапазоны, а не обязательно точные версии.

**Разрешение** в `uv.lock` содержит точные выбранные packages, versions, sources и условия
для поддерживаемых платформ и Python. `uv.lock`:

- создаётся и обновляется `uv`;
- является cross-platform lockfile;
- должен попадать в version control;
- не редактируется вручную.

**Установленное состояние** находится в `.venv`. Это локальный результат синхронизации:

- зависит от платформы и интерпретатора;
- может быть удалён и пересоздан;
- не должен попадать в Git;
- не является источником истины.

### Locking и syncing

**Locking** разрешает требования проекта в конкретный lockfile:

```bash
uv lock
```

**Syncing** устанавливает выбранный набор из lockfile в проектное окружение:

```bash
uv sync
```

Многие команды uv выполняют эти шаги автоматически. Например, `uv run` перед запуском
проверяет lockfile и окружение и при необходимости синхронизирует их.

Для проверки воспроизводимости автоматическое исправление иногда нежелательно. Используйте:

```bash
uv lock --check
uv sync --check --locked
```

Первая команда отвечает: соответствует ли `uv.lock` metadata проекта? Вторая: соответствует
ли `.venv` locked-проекту?

### `--locked` и `--frozen`

Эти опции не являются синонимами.

`--locked` требует, чтобы lockfile существовал и был актуален:

```bash
uv sync --locked
```

Если `pyproject.toml` изменён, а `uv.lock` нет, команда завершится ошибкой вместо
неявного обновления lockfile.

`--frozen` использует существующий lockfile без проверки его соответствия metadata:

```bash
uv sync --frozen
```

Это полезно в специальных workflows, но может скрыть рассинхронизацию. В учебном CI и
обычном восстановлении проекта используйте `--locked`.

### `uv add` управляет контрактом целиком

Команда:

```bash
uv add 'numpy>=2,<3'
```

согласованно обновляет:

1. `pyproject.toml`;
2. `uv.lock`;
3. `.venv`.

Для инструмента разработки:

```bash
uv add --dev 'pytest>=8'
```

Зависимость попадёт в development group, а не в runtime requirements проекта.

`uv pip install` предоставляет pip-compatible interface, но установка пакета напрямую в
окружение не заменяет `uv add`: декларация проекта и lockfile могут остаться без изменения.

### Activation необязательна

После:

```bash
uv sync
```

можно активировать окружение:

```bash
source .venv/bin/activate
```

Но для воспроизводимой команды часто яснее:

```bash
uv run python analysis.py
uv run pytest
```

`uv run` выбирает проектное окружение и снижает риск случайно использовать другой Python
из `PATH`.

## Соберите это

Продолжите проект `version-lab` из предыдущего урока или создайте новый:

```bash
mkdir uv-analytics-lab
cd uv-analytics-lab
uv init --bare --name uv-analytics-lab
```

Если `pyproject.toml` уже создан в уроке `01/01`, не запускайте `uv init` поверх него.
Проверьте контракт:

```bash
cat pyproject.toml
cat .python-version
```

Минимальный вариант:

```toml
[project]
name = "uv-analytics-lab"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = []
```

### Шаг 1: исключите локальное окружение

Добавьте в `.gitignore`:

```gitignore
.venv/
```

Проверьте:

```bash
git check-ignore -v .venv/ || true
```

До создания каталога некоторые варианты `git check-ignore` могут ничего не вывести.
После `uv sync` повторите проверку.

### Шаг 2: создайте окружение

```bash
uv sync
```

uv:

- выбирает Python, совместимый с `requires-python` и `.python-version`;
- создаёт `.venv`;
- создаёт или обновляет `uv.lock`;
- синхронизирует окружение.

Посмотрите структуру:

```bash
ls -la
uv run python -c 'import sys; print(sys.executable)'
```

Путь должен вести внутрь проекта:

```text
.../uv-analytics-lab/.venv/bin/python
```

### Шаг 3: добавьте runtime-зависимость

```bash
uv add 'numpy>=2,<3'
```

Проверьте metadata:

```bash
sed -n '1,120p' pyproject.toml
```

В `[project].dependencies` появится требование. Затем убедитесь, что импорт работает в
проектном окружении:

```bash
uv run python -c \
  'import numpy as np; print(np.__version__); print(np.array([1, 2, 3]).mean())'
```

Не фиксируйте результат `np.__version__` вручную в `pyproject.toml`: точное разрешение уже
записано в `uv.lock`.

### Шаг 4: добавьте development-зависимость

```bash
uv add --dev 'pytest>=8'
```

В современных uv-проектах dependency group выглядит так:

```toml
[dependency-groups]
dev = [
    "pytest>=8",
]
```

Runtime-пользователь проекта не обязан получать инструменты разработки. При обычном
`uv sync` группа `dev` синхронизируется по умолчанию; её можно исключить:

```bash
uv sync --no-dev
```

Для учебной разработки оставьте dev group установленной.

### Шаг 5: изучите lockfile без ручного редактирования

```bash
sed -n '1,160p' uv.lock
uv tree
```

Ищите:

- `requires-python`;
- direct dependency;
- транзитивные packages;
- source и version;
- различия по platform или Python markers.

Не меняйте строки `uv.lock` редактором. Изменение начинается с `uv add`, `uv remove`,
правки requirement в `pyproject.toml` или осознанной команды upgrade.

### Шаг 6: запустите проверки

```bash
uv lock --check
uv sync --check --locked
uv run --locked python -c 'import numpy'
```

Первая команда не должна менять lockfile. Вторая не должна устанавливать пакеты.
Последняя запрещает неявное обновление lockfile перед запуском.

## Используйте это

### Запускайте проект через `uv run`

Создайте `analysis.py`:

```python
import numpy as np


values = np.array([120.0, 75.0, 95.0])
print(values.mean())
```

Запустите:

```bash
uv run python analysis.py
```

Преимущества:

- команда привязана к проекту;
- нужное окружение выбирается автоматически;
- lockfile и dependencies проверяются до запуска;
- не требуется держать activation в голове.

Для CI используйте более строгий вариант:

```bash
uv run --locked python analysis.py
```

### Восстановите проект с нуля

Убедитесь, что все важные файлы сохранены:

```bash
git status --short
git ls-files -- pyproject.toml uv.lock .python-version .gitignore
```

Удалите только локальное окружение:

```bash
rm -rf .venv
```

В учебном каталоге это намеренный шаг. Не применяйте `rm -rf` к пути, который не
проверили через `pwd`.

Восстановите окружение:

```bash
uv sync --locked
uv run --locked python -c 'import numpy; print(numpy.__version__)'
```

Если команды проходят, `.venv` является производным артефактом, а репозиторий содержит
достаточный контракт восстановления.

### Проверьте артефактом урока

Из каталога урока:

```bash
python3 outputs/uv_project_check.py \
  path/to/uv-analytics-lab \
  --import numpy
```

Из корня курса:

```bash
python3 phases/01-reproducible-project/02-uv-environments/outputs/uv_project_check.py \
  uv-analytics-lab \
  --import numpy
```

CLI проверяет:

- наличие `uv`;
- `requires-python` и объявленные зависимости;
- структуру `uv.lock`;
- `uv lock --check`;
- `uv sync --check --locked`;
- правило `.gitignore` для `.venv`;
- smoke-import внутри locked-окружения без автоматической синхронизации.

Сохраните JSON:

```bash
python3 outputs/uv_project_check.py . \
  --import numpy \
  --format json \
  --output /tmp/uv-repro-check.json
```

Для полностью локальной диагностики с уже заполненным cache:

```bash
python3 outputs/uv_project_check.py . \
  --import numpy \
  --offline
```

Offline-режим не создаёт отсутствующие registry artifacts. Он доказывает только, что
нужные данные уже доступны локально.

### Обновляйте зависимости отдельно от обычной синхронизации

Существующий `uv.lock` сохраняет выбранные версии, даже если в registry появились новые:

```bash
uv sync
```

не является командой «обновить всё».

Осознанное обновление одного package:

```bash
uv lock --upgrade-package numpy
uv sync
```

Обновление всех разрешённых packages:

```bash
uv lock --upgrade
uv sync
```

Изменение lockfile должно проходить отдельный review: сравните версии, транзитивные
зависимости и результаты тестов.

## Сломайте это

### Измените `pyproject.toml`, но не lockfile

Добавьте requirement редактором:

```toml
dependencies = [
    "numpy>=2,<3",
    "pandas>=2",
]
```

Запустите:

```bash
uv lock --check
```

Команда должна завершиться ошибкой: декларация и разрешение расходятся.

Исправьте через:

```bash
uv lock
uv sync
```

Для обычной работы предпочтительнее `uv add pandas`, потому что команда выполняет все три
изменения согласованно.

### Удалите `uv.lock` и выполните обычный sync

Без lockfile:

```bash
uv sync
```

создаст новое разрешение на основе доступных сейчас package versions. Оно может отличаться
от окружения коллеги или вчерашнего CI.

Lockfile должен храниться в Git:

```bash
git add uv.lock
git commit -m "Lock project dependencies"
```

### Установите пакет только в окружение

```bash
uv pip install rich
```

Пакет может импортироваться локально, но не стать частью project metadata и lockfile.
После удаления `.venv` он исчезнет.

Для зависимости проекта:

```bash
uv add rich
```

Для одноразового инструмента рассмотрите `uvx`, но не маскируйте им runtime requirement
проекта.

### Запустите Python мимо проекта

```bash
python analysis.py
```

Команда использует первый `python` из `PATH`. Если `.venv` не активна, импорт может
случайно сработать из глобальной установки или завершиться ошибкой.

Сравните:

```bash
python -c 'import sys; print(sys.executable)'
uv run python -c 'import sys; print(sys.executable)'
```

Воспроизводимая инструкция должна явно выбирать проектное окружение.

### Сохраните `.venv` в Git

Проверьте:

```bash
git status --short .venv
git check-ignore -v .venv/
```

Если файлы видны как untracked, исправьте `.gitignore`. Если они уже tracked:

```bash
git rm -r --cached .venv
```

Не удаляйте local environment без необходимости; команда выше прекращает tracking в
следующем commit.

### Используйте `--frozen` для сокрытия stale lock

После ручной правки `pyproject.toml`:

```bash
uv sync --frozen
```

может применить старый lockfile без проверки metadata. Это не исправление.

Для quality gate:

```bash
uv sync --locked
```

## Проверьте это

Запустите тесты урока:

```bash
python3 -m unittest discover \
  -s phases/01-reproducible-project/02-uv-environments/tests \
  -p "test_*.py" -v
```

Семь тестов используют настоящий `uv` и полностью локальную editable-зависимость:

- locked и synced проект со smoke-import;
- stale lockfile без неявного обновления;
- актуальный lock при отсутствующей `.venv`;
- восстановление удалённой `.venv` через `uv sync --locked`;
- отсутствие `.venv` в `.gitignore`;
- неработающий smoke-import;
- отсутствующий `uv.lock`.

Тесты запускаются с отдельным временным `UV_CACHE_DIR` и `--offline`, поэтому не изменяют
пользовательский cache и не требуют registry.

Запустите демонстрацию:

```bash
python3 phases/01-reproducible-project/02-uv-environments/code/main.py
```

Перед pull request:

```bash
uv lock --check
uv sync --check --locked
uv run --locked pytest
git status --short
git diff -- pyproject.toml uv.lock
```

Review должен видеть изменение requirements и соответствующий diff lockfile.

## Поставьте результат

Результат урока:

```text
project/
├── .gitignore
├── .python-version
├── .venv/          # локально, не в Git
├── pyproject.toml  # требования
└── uv.lock         # точное разрешение, в Git
```

Команда восстановления:

```bash
uv sync --locked
```

Команда запуска:

```bash
uv run --locked python analysis.py
```

Проверка:

```bash
python3 outputs/uv_project_check.py . --import numpy
```

Manifest находится в `outputs/artifact.json`. CLI не обновляет lockfile и не ремонтирует
окружение во время проверки: любой drift остаётся видимым.

В следующем уроке мы разберём `pyproject.toml` целиком: metadata, dependencies,
dependency groups и tool configuration. Здесь он использовался только как часть
воспроизводимого uv workflow.

## Упражнения

1. Добавьте runtime-зависимость с разумным диапазоном и dev-зависимость, сравните две
   части `pyproject.toml` и diff `uv.lock`.
2. Удалите `.venv`, восстановите её через `uv sync --locked` и докажите совпадение версии
   direct dependency до и после удаления.
3. Создайте stale lockfile ручной правкой requirement, покажите отказ `uv lock --check`,
   затем исправьте контракт через `uv lock` и объясните diff.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| Virtual environment | Копия всего проекта | Изолированное установленное состояние Python packages |
| `.venv` | Источник воспроизводимости | Локальный производный каталог |
| Requirement | Точная установленная версия | Допустимый диапазон или источник зависимости |
| Lockfile | Ещё один requirements list | Точное разрешение полного графа |
| Direct dependency | Любой package в lockfile | Requirement, объявленный самим проектом |
| Transitive dependency | Неважный внутренний package | Зависимость direct dependency |
| Locking | Установка packages | Разрешение requirements в lockfile |
| Syncing | Обновление metadata | Приведение окружения к lockfile |
| `--locked` | Запрет использовать lockfile | Запрет неявно менять stale lockfile |
| `--frozen` | Более строгий `--locked` | Использование lockfile без проверки metadata |
| `uv run` | Только сокращение activation | Запуск команды в проверенном project environment |

## Дополнительное чтение

- [uv Docs: Working on projects](https://docs.astral.sh/uv/guides/projects/) — пройдите официальный workflow от `uv init` и `uv add` до `uv run`.
- [uv Docs: Locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/) — разберите `--locked`, `--frozen`, exact sync и правила upgrade.
- [uv Docs: Managing dependencies](https://docs.astral.sh/uv/concepts/projects/dependencies/) — изучите runtime requirements, development groups, extras и alternative sources.
- [uv Docs: Structure and files](https://docs.astral.sh/uv/concepts/projects/layout/) — уточните роли `.python-version`, `.venv`, `pyproject.toml` и `uv.lock`.
