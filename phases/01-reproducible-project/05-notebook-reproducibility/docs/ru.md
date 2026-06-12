# Воспроизводимые ноутбуки

> Notebook воспроизводим не тогда, когда в нём виден результат, а когда новый kernel
> получает тот же результат при выполнении ячеек сверху вниз.

**Тип:** Build
**Треки:** Core
**Пререквизиты:** 01/04 — Jupyter, kernels и состояние
**Время:** ~60 минут
**Результат:** находит скрытое состояние и добивается успешного Restart and Run All

## Цели обучения

- Объяснять, почему сохранённые outputs не доказывают актуальность расчёта.
- Читать `execution_count` как следы kernel session.
- Находить использование variables до их определения.
- Убирать абсолютные локальные пути и неявные inputs.
- Выбирать политику хранения чистых или полностью выполненных notebooks.
- Выполнять notebook автоматически через `jupyter execute`.
- Проверять бизнес-результат assertions, а не визуальным впечатлением.
- Очищать outputs и execution metadata перед review.

## Проблема

Notebook показывает красивую таблицу и график. Автор отправляет его коллеге, но после
`Restart Kernel and Run All Cells` расчёт падает:

```text
NameError: name 'orders' is not defined
```

Причина обнаруживается позже:

1. Ячейка с загрузкой `orders` была удалена.
2. Variable осталась в памяти старого kernel.
3. Ячейка расчёта продолжала выполняться интерактивно.
4. Старый output сохранился в `.ipynb`.

Формат notebook хранит одновременно:

- исходный код;
- markdown;
- execution counts;
- outputs;
- metadata.

Код и output могут относиться к разным моментам времени. Поэтому открывшийся файл ещё не
является выполненной программой.

## Концепция

### Notebook — документ и программа одновременно

В обычном `.py` порядок очевиден:

```python
orders = [100, 200]
total = sum(orders)
print(total)
```

В Jupyter пользователь может выполнить нижнюю ячейку, затем верхнюю, затем снова нижнюю.
Визуальный порядок документа не совпадает с историей процесса.

Notebook становится проверяемым, когда команда принимает правило:

```text
Новый kernel + ячейки сверху вниз = успешный расчёт и проверенный вывод
```

### Что означает `execution_count`

Code cell может хранить:

```json
{
  "execution_count": 12,
  "cell_type": "code"
}
```

Это номер execution request в текущей kernel session. Он не означает:

- двенадцатую ячейку notebook;
- двенадцать секунд выполнения;
- двенадцатую версию кода;
- воспроизводимость результата.

Последовательность:

```text
[1] [4] [2]
```

показывает интерактивный порядок, отличающийся от документа.

После чистого Run All counts обычно возрастают сверху вниз. Для Git можно выбрать ещё
более строгую политику: хранить все counts как `null`, а outputs — пустыми.

### Две разумные политики хранения

**Чистый notebook:**

```json
"execution_count": null,
"outputs": []
```

Плюсы:

- компактные diffs;
- нет устаревших результатов;
- меньше случайно опубликованных данных;
- факт исполнения проверяется отдельно в CI.

**Полностью выполненный notebook:**

- все code cells выполнены сверху вниз;
- counts уникальны и возрастают;
- нет error outputs;
- outputs нужны читателю как deliverable.

Плюсы:

- результат виден без запуска;
- удобно для отчёта.

Минусы:

- noisy diffs;
- большие embedded images;
- риск устаревших или чувствительных outputs.

В курсе по умолчанию храним notebooks чистыми и отдельно доказываем execution.

### Скрытое состояние

Скрытое состояние возникает, когда результат зависит не от видимых предыдущих ячеек, а от
истории процесса:

```python
summary = calculate(orders)
```

Если `orders` не определён выше, notebook зависит от старой session.

Другие примеры:

- импорт выполнен в удалённой ячейке;
- current working directory менялся вручную;
- global option изменена в другой части session;
- random state уже продвинут;
- файл создан предыдущим экспериментом;
- функция была переопределена, но старая версия осталась в памяти.

Static analysis находит часть проблем, но окончательное доказательство — новый process.

### Inputs должны быть явными

Непереносимый код:

```python
orders = read_csv("/Users/alice/Desktop/orders.csv")
```

На другой машине такого пути нет. Лучше:

```python
from pathlib import Path

PROJECT_ROOT = Path.cwd()
orders_path = PROJECT_ROOT / "data" / "orders.csv"
```

Ещё надёжнее — передавать path или configuration как параметр. Для production data
источник может быть URI, таблица или data contract, но он всё равно должен быть видимым.

### Working directory — часть контракта

Относительный путь:

```python
Path("data/orders.csv")
```

зависит от `Path.cwd()`. Зафиксируйте ожидание:

```python
from pathlib import Path

root = Path.cwd()
assert (root / "pyproject.toml").is_file(), "Запустите notebook из корня проекта"
```

Не исправляйте проблему цепочкой случайных `os.chdir(...)` в разных cells.

### Randomness требует явного generator state

Невоспроизводимо:

```python
sample = random.sample(population, 100)
```

Явно:

```python
import random

rng = random.Random(42)
sample = rng.sample(population, 100)
```

Seed не делает статистический вывод автоматически корректным. Он лишь позволяет повторить
конкретную последовательность.

### Проверяйте вывод кодом

Markdown:

```markdown
Средний чек равен 100.
```

может разойтись с кодом. Свяжите вывод:

```python
assert summary["average_order_value"] == 100.0
```

Для float используйте tolerance:

```python
import math

assert math.isclose(actual, expected, rel_tol=1e-9)
```

Assertions превращают notebook из презентации в исполняемый аналитический контракт.

### Автоматическое выполнение

Команда:

```bash
jupyter execute analysis.ipynb
```

создаёт kernel и выполняет cells последовательно. Ненулевой exit code означает, что
notebook не прошёл quality gate.

Для более сложного управления используют `nbclient` или `nbconvert --execute`. Важно не
конкретное имя CLI, а свойства процесса:

- свежий kernel;
- ограниченный timeout;
- контролируемый working directory;
- ошибка останавливает pipeline;
- используется kernelspec проекта.

## Соберите это

Откройте артефакт:

```text
outputs/reproducible_analysis.ipynb
```

Он состоит из пяти ячеек:

1. Цель и происхождение данных.
2. Imports.
3. Явный input и его parsing.
4. Расчёт, assertions и result.
5. Вывод.

Notebook хранится чистым:

```text
execution_count = null
outputs = []
```

### Шаг 1: выполните новый process

```bash
cp outputs/reproducible_analysis.ipynb /tmp/reproducible_analysis.ipynb
jupyter execute /tmp/reproducible_analysis.ipynb
```

Копия защищает committed artifact от случайного изменения metadata конкретной машиной.

### Шаг 2: запустите аудит

```bash
python3 outputs/notebook_audit.py check \
  outputs/reproducible_analysis.ipynb
```

Проверяются:

- `nbformat = 4`;
- уникальные cell IDs;
- единый storage mode;
- отсутствие stored tracebacks;
- базовые признаки use-before-definition;
- абсолютные local paths;
- наличие kernelspec metadata.

### Шаг 3: очистите рабочую копию

```bash
python3 outputs/notebook_audit.py clean analysis.ipynb
```

Или сохраните отдельно:

```bash
python3 outputs/notebook_audit.py clean analysis.ipynb \
  --output analysis.clean.ipynb
```

Cleaner удаляет:

- `execution_count`;
- `outputs`;
- transient cell execution metadata.

Он не удаляет код и markdown.

### Шаг 4: проверьте diff

```bash
git diff --stat
git diff -- analysis.ipynb
```

Если изменение одной строки кода породило сотни строк base64 output, очистка не применена
или output действительно является частью deliverable.

## Используйте это

Рабочий цикл:

```text
Исследовать интерактивно
        ↓
Упорядочить cells сверху вниз
        ↓
Restart Kernel and Run All
        ↓
Добавить assertions
        ↓
Очистить notebook
        ↓
Автоматически выполнить копию
        ↓
Review compact diff
```

Перед pull request:

```bash
python3 outputs/notebook_audit.py clean notebooks/report.ipynb
jupyter execute notebooks/report.ipynb
python3 outputs/notebook_audit.py check notebooks/report.ipynb
git diff --check
```

Если `jupyter execute` сохраняет outputs в вашей конфигурации, выполняйте временную копию
или очищайте файл после успешного запуска.

Для review задайте четыре вопроса:

1. Откуда берутся inputs?
2. Может ли новый kernel выполнить cells сверху вниз?
3. Каким кодом проверен ключевой бизнес-вывод?
4. Не раскрывают ли outputs данные, paths или secrets?

## Сломайте это

### Используйте variable из старой session

В первой code cell:

```python
print(hidden_value)
```

Если variable была определена раньше интерактивно, cell может сработать до restart.
Аудит отметит возможный use-before-definition, а новый kernel даст `NameError`.

### Выполните cells в обратном порядке

Сохраните counts:

```text
[3] load
[2] calculate
[1] imports
```

Смешанный порядок — сигнал, что outputs нужно перестроить или удалить.

### Оставьте traceback в output

Даже если следующая cell сработала, сохранённый error output означает незавершённый
документ. Исправьте причину и выполните notebook заново.

### Добавьте absolute path

```python
path = "/Users/me/data.csv"
```

CLI отметит path. Перенесите input в project-relative configuration.

### Измените код, не обновив output

Поменяйте формулу, не выполняя cell. Старый output останется визуально убедительным.
Именно поэтому output не является доказательством.

## Проверьте это

Запустите восемь tests:

```bash
python3 -m unittest discover \
  -s phases/01-reproducible-project/05-notebook-reproducibility/tests \
  -p "test_*.py" -v
```

Они покрывают:

- чистый готовый artifact;
- mixed execution state;
- немонотонные counts;
- stored traceback;
- use-before-definition;
- absolute path;
- cleaning;
- duplicate cell IDs.

Запустите демонстрацию:

```bash
python3 phases/01-reproducible-project/05-notebook-reproducibility/code/main.py
```

И обязательную динамическую проверку:

```bash
jupyter execute \
  phases/01-reproducible-project/05-notebook-reproducibility/outputs/reproducible_analysis.ipynb
```

Static audit не заменяет execution: Python допускает динамические конструкции, которые
невозможно надёжно доказать только чтением AST.

## Поставьте результат

Результат урока:

```text
outputs/
├── artifact.json
├── notebook_audit.py
└── reproducible_analysis.ipynb
```

Definition of done:

- notebook выполняется новым kernel сверху вниз;
- input определён явно;
- ключевой вывод подтверждён assertion;
- нет локальных absolute paths;
- в Git хранится согласованное состояние;
- автоматическая команда возвращает exit code `0`.

В следующем уроке стабильный расчёт будет вынесен из notebook в importable function и
CLI. Notebook останется тонким слоем исследования и представления.

## Упражнения

1. Возьмите собственный notebook, очистите его, выполните временную копию новым kernel и
   классифицируйте каждую найденную зависимость от session state.
2. Замените два absolute paths на параметры, проверьте запуск из другого working directory
   и опишите контракт inputs.
3. Вынесите ключевой бизнес-вывод в assertion с разумным tolerance и создайте намеренно
   неверный input, который должен остановить execution.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| Hidden state | Скрытая ячейка | Состояние kernel, не создаваемое видимым top-down кодом |
| `execution_count` | Номер ячейки | Номер запроса в kernel session |
| Output | Гарантированно актуальный результат | Сохранённый результат прошлого execution |
| Restart | Повторный показ notebook | Новый kernel без variables старого процесса |
| Run All | Произвольный запуск cells | Последовательное выполнение документа |
| Clean notebook | Notebook без кода | Документ без stored counts и outputs |
| Cell ID | Execution count | Стабильный идентификатор cell в nbformat |
| Working directory | Каталог notebook | Текущий каталог kernel process |
| Assertion | Комментарий к результату | Исполняемая проверка предположения |
| Static audit | Полная замена execution | Быстрый поиск ограниченного класса дефектов |

## Дополнительное чтение

- [nbformat: The notebook file format](https://nbformat.readthedocs.io/en/latest/format_description.html) — изучите структуру cells, outputs, execution counts, IDs и metadata.
- [nbclient: Executing notebooks](https://nbclient.readthedocs.io/en/latest/client.html) — разберите программное выполнение, timeout и обработку ошибок.
- [Jupyter Notebook: Notebook documents](https://jupyter-notebook.readthedocs.io/en/stable/notebook.html) — свяжите document format с kernel session и пользовательским workflow.
- [Jupyter Security: Security in notebook documents](https://jupyter-server.readthedocs.io/en/latest/operators/security.html) — поймите trust model и риски сохранённого HTML/JavaScript output.
