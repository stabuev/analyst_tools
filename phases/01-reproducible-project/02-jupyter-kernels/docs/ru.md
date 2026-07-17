# Jupyter, kernels и состояние

> Имя kernel в меню — подпись. Источник истины — Python-процесс, который показывает
> `sys.executable`.

**Тип:** Build
**Треки:** Core
**Пререквизиты:** 01/01 — Окружения и зависимости с uv
**Время:** ~60 минут
**Результат:** выбирает правильный kernel и диагностирует расхождение окружений

## Цели обучения

- Различать Jupyter frontend, server, kernelspec и kernel process.
- Объяснять, почему терминал и notebook могут видеть разные packages.
- Читать `kernel.json` и понимать роль `argv`.
- Регистрировать `ipykernel` из проектного окружения.
- Проверять runtime через `sys.executable`, `sys.prefix` и package metadata.
- Отличать имя kernel от фактического интерпретатора.
- Диагностировать устаревший kernelspec после перемещения или удаления `.venv`.
- Собирать переносимый отчёт о kernel environment.

## Проблема

В терминале проект работает:

```bash
uv run python -c "import pandas; print(pandas.__version__)"
```

В notebook та же строка падает:

```text
ModuleNotFoundError: No module named 'pandas'
```

Пользователь видит в меню:

```text
Python 3
```

и предполагает, что это тот же Python. Но на машине может быть несколько процессов:

```text
/usr/bin/python3
/opt/anaconda3/bin/python
/project/.venv/bin/python
```

Jupyter notebook не исполняет Python самостоятельно. Frontend отправляет код отдельному
kernel-процессу. Какой процесс будет запущен, определяет kernelspec.

Поэтому вопрос «какой kernel выбран?» нужно разложить:

1. Как называется kernelspec?
2. Какую команду содержит его `argv`?
3. Какой `sys.executable` реально работает внутри notebook?
4. Какому окружению соответствует `sys.prefix`?
5. Установлены ли там `ipykernel` и зависимости проекта?

## Концепция

### Четыре части Jupyter workflow

Упрощённая схема:

```text
Browser / JupyterLab
        ↓
Jupyter server
        ↓ выбирает kernelspec
kernel.json
        ↓ запускает argv
Python + ipykernel
```

**Frontend** показывает ячейки, отправляет команды и отображает outputs.

**Server** управляет файлами, sessions и связью с kernels.

**Kernelspec** — небольшой каталог с `kernel.json`, ресурсами и человекочитаемым именем.

**Kernel** — отдельный процесс, который хранит variables, imports и текущее состояние.

### Что находится в `kernel.json`

Типичный Python kernelspec:

```json
{
  "argv": [
    "/project/.venv/bin/python",
    "-m",
    "ipykernel_launcher",
    "-f",
    "{connection_file}"
  ],
  "display_name": "Python (analytics)",
  "language": "python"
}
```

Ключевые поля:

- `argv[0]` — команда запуска интерпретатора;
- `-m ipykernel_launcher` — модуль Python kernel;
- `{connection_file}` — placeholder для файла подключения;
- `display_name` — подпись в интерфейсе;
- `language` — язык kernel.

`display_name` можно назвать как угодно:

```json
"display_name": "Точно правильный Python"
```

Это не изменит `argv[0]`. Поэтому имя не является доказательством.

### Kernel environment и server environment могут различаться

JupyterLab может быть установлен глобально:

```bash
/opt/tools/bin/jupyter lab
```

а kernel запускаться из проекта:

```bash
/project/.venv/bin/python -m ipykernel_launcher
```

Это нормальная архитектура. Не нужно устанавливать весь JupyterLab в каждое окружение,
если server уже доступен. Но `ipykernel` и runtime dependencies должны быть установлены
там, где работает kernel.

### `sys.executable` — фактический бинарник

Выполните в notebook:

```python
import sys

print(sys.executable)
print(sys.prefix)
print(sys.base_prefix)
```

Интерпретация:

- `sys.executable` — путь к текущему Python;
- `sys.prefix` — prefix активного окружения;
- `sys.base_prefix` — base installation, из которой создано venv;
- если `sys.prefix != sys.base_prefix`, обычно активен virtual environment.

Переменная `VIRTUAL_ENV` полезна, но не обязательна для запущенного kernel. Kernel может
использовать `.venv`, даже если shell activation не выполнялась.

### Установка package должна использовать Python kernel

Команда:

```python
!pip install pandas
```

вызывает первый `pip` из shell `PATH`, который может принадлежать другому Python.

Более явно:

```python
import sys
!{sys.executable} -m pip install pandas
```

Но в воспроизводимом проекте dependencies лучше добавлять из терминала:

```bash
uv add pandas
uv sync --locked
```

После изменения окружения перезапустите kernel. Уже работающий процесс не обязан увидеть
все изменения корректно.

### Регистрация kernel из проектного окружения

Добавьте `ipykernel` как development dependency:

```bash
uv add --dev ipykernel
```

Зарегистрируйте kernel именно проектным Python:

```bash
uv run python -m ipykernel install \
  --user \
  --name analyst-tools \
  --display-name "Python (analyst-tools)"
```

Здесь:

- `--name` — стабильный внутренний идентификатор kernelspec;
- `--display-name` — подпись в интерфейсе;
- Python перед `-m ipykernel` определяет записанный executable.

Посмотрите registrations:

```bash
jupyter kernelspec list
jupyter kernelspec list --json
```

### Kernelspec может устареть

Если `.venv` удалили и создали заново в том же месте, путь часто продолжит работать.
Если проект переместили:

```text
/old/path/project/.venv/bin/python
```

останется в kernelspec и kernel не запустится.

Удалите старую регистрацию:

```bash
jupyter kernelspec uninstall analyst-tools
```

Затем установите её заново проектным Python. Не редактируйте случайный глобальный
`kernel.json`, не выяснив его scope.

### Состояние живёт в процессе

Kernel хранит:

- variables;
- imports;
- current working directory;
- random generator state;
- monkey patches и изменённые options;
- открытые connections.

Изменение kernel меняет и окружение, и состояние. Restart уничтожает process state, но не
переписывает notebook outputs.

В этом уроке мы диагностируем процесс. В следующем проверим, можно ли выполнить notebook
сверху вниз после полного restart.

## Соберите это

Откройте:

```text
outputs/kernel_diagnostic.ipynb
```

Выберите kernel проекта и выполните:

```text
Restart Kernel and Run All Cells
```

Первая code cell собирает:

```python
diagnostic = {
    "executable": str(Path(sys.executable).resolve()),
    "prefix": str(Path(sys.prefix).resolve()),
    "base_prefix": str(Path(sys.base_prefix).resolve()),
    "python_version": platform.python_version(),
    "ipykernel_version": package_version("ipykernel"),
    "cwd": str(Path.cwd().resolve()),
    "virtual_environment": os.environ.get("VIRTUAL_ENV"),
}
```

Не ограничивайтесь визуальным чтением. Укажите ожидаемый prefix:

```python
expected_prefix = "/absolute/path/to/project/.venv"
```

Вторая cell превратит предположение в assert.

### Шаг 1: найдите kernelspec

```bash
jupyter kernelspec list --json
```

В результате найдите `resource_dir` выбранного kernel:

```json
{
  "resource_dir": "/home/user/.local/share/jupyter/kernels/analyst-tools"
}
```

### Шаг 2: проверьте его CLI

```bash
python3 outputs/kernel_diagnostic.py check \
  /home/user/.local/share/jupyter/kernels/analyst-tools/kernel.json \
  --expected-prefix /absolute/path/to/project/.venv
```

CLI сравнивает текущий Python, kernelspec и expected prefix. Чтобы сравнение отражало
kernel runtime, запускайте CLI тем же Python:

```bash
/absolute/path/to/project/.venv/bin/python \
  outputs/kernel_diagnostic.py check /path/to/kernel.json \
  --expected-prefix /absolute/path/to/project/.venv
```

### Шаг 3: зафиксируйте доказательство

В issue или review достаточно приложить:

```text
Running Python: /project/.venv/bin/python
Environment prefix: /project/.venv
ipykernel: 6.x
Kernelspec argv[0]: /project/.venv/bin/python
Result: MATCH
```

Не публикуйте полный environment dump: в переменных могут находиться secrets.

## Используйте это

Если import работает в терминале, но не в notebook:

1. Выполните `sys.executable` внутри notebook.
2. Выполните `uv run python -c "import sys; print(sys.executable)"` в терминале.
3. Сравните пути после `Path(...).resolve()`.
4. Проверьте `ipykernel` и нужный package через тот же executable.
5. Перерегистрируйте kernelspec, если `argv[0]` устарел.
6. Перезапустите kernel.

Проверка package:

```python
import importlib.metadata

print(importlib.metadata.version("pandas"))
```

Проверка provenance импортированного модуля:

```python
import pandas

print(pandas.__file__)
```

Путь должен находиться в ожидаемом environment, а не в случайном global site-packages.

## Сломайте это

### Переименуйте только display name

Назовите системный kernelspec:

```text
Python (project)
```

Диагностический notebook всё равно покажет системный `sys.executable`. Это демонстрирует,
почему UI label недостаточно.

### Удалите проектную `.venv`

Старый kernelspec продолжит ссылаться на несуществующий executable. Jupyter может
показывать kernel в списке, но не сможет запустить его.

Восстановите environment:

```bash
uv sync --locked
```

и при необходимости перерегистрируйте kernel.

### Установите package не тем pip

```bash
pip install example-package
```

Затем проверьте:

```bash
which pip
pip --version
```

Сравните Python из пути `pip --version` с `sys.executable` notebook.

### Уберите `{connection_file}`

Kernelspec без placeholder не получает параметры подключения от server. CLI отметит
контракт `connection-file` как ошибочный.

### Ожидайте environment только по текущему каталогу

Notebook может лежать в `/project`, но kernel работать из Anaconda. Расположение `.ipynb`
не выбирает интерпретатор автоматически.

## Проверьте это

Запустите семь тестов:

```bash
python3 -m unittest discover \
  -s phases/01-reproducible-project/02-jupyter-kernels/tests \
  -p "test_*.py" -v
```

Они проверяют:

- совпадающий executable;
- ложное красивое display name;
- отсутствие `ipykernel`;
- неверный expected prefix;
- отсутствие connection placeholder;
- загрузку kernelspec из каталога;
- наличие runtime evidence в notebook.

Запустите демонстрацию:

```bash
python3 phases/01-reproducible-project/02-jupyter-kernels/code/main.py
```

Проверьте реальный локальный kernelspec:

```bash
python3 phases/01-reproducible-project/02-jupyter-kernels/outputs/kernel_diagnostic.py \
  check /path/to/kernel.json
```

## Поставьте результат

Результат урока:

```text
outputs/
├── artifact.json
├── kernel_diagnostic.ipynb
└── kernel_diagnostic.py
```

Notebook даёт evidence изнутри процесса. CLI связывает его с declarative kernelspec.
Вместе они отвечают:

```text
Какой Python работает?
Какое окружение он использует?
Есть ли там ipykernel?
Совпадает ли он с kernel.json?
```

В следующем уроке kernel будет перезапущен, а notebook проверен как последовательная
программа: без скрытых variables и случайного порядка ячеек.

## Упражнения

1. Зарегистрируйте два kernel из разных окружений с похожими display names и докажите их
   различие через `sys.executable`.
2. Переместите тестовый проект, найдите stale path в kernelspec и восстановите регистрацию
   без ручной установки packages в notebook.
3. Дополните диагностику версиями трёх direct dependencies и путями их модулей, не
   выводя переменные окружения и secrets.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| Jupyter frontend | Python runtime | Интерфейс для редактирования и отправки запросов |
| Kernel | Файл notebook | Отдельный процесс исполнения кода |
| Kernelspec | Само окружение | Декларация команды запуска kernel |
| `display_name` | Проверенный путь Python | Человекочитаемая подпись |
| `argv` | Аргументы текущей ячейки | Команда запуска kernel process |
| `sys.executable` | Команда `python` из shell | Фактический бинарник текущего процесса |
| `sys.prefix` | Текущий каталог | Prefix активного Python environment |
| `ipykernel` | Полный JupyterLab | Python-реализация Jupyter kernel |
| Connection file | Notebook на диске | Runtime-файл параметров связи server и kernel |
| Restart | Очистка outputs | Завершение process state и запуск нового kernel |

## Дополнительное чтение

- [Jupyter Client: Kernels](https://jupyter-client.readthedocs.io/en/stable/kernels.html) — изучите lifecycle kernel process, connection files и структуру kernelspec.
- [IPython: Installing the IPython kernel](https://ipython.readthedocs.io/en/stable/install/kernel_install.html) — разберите регистрацию kernels для нескольких environments.
- [Jupyter Documentation: Architecture](https://docs.jupyter.org/en/latest/projects/architecture/content-architecture.html) — свяжите notebook document, server, protocol и kernels в общей архитектуре.
- [Jupyter Notebook: Troubleshooting](https://jupyter-notebook.readthedocs.io/en/stable/troubleshooting.html) — используйте официальный checklist для PATH, kernels и package conflicts.
