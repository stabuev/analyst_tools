# Git: история аналитического проекта

> Хорошая история хранит не каждое движение рук, а последовательность проверяемых решений.

**Тип:** Build  
**Треки:** Core  
**Пререквизиты:** 03 — Терминал и файловая система  
**Время:** ~75 минут  
**Результат:** создаёт репозиторий, делает атомарные commits и исключает данные через `.gitignore`

## Цели обучения

- Объяснять различия между working tree, index и последним commit.
- Выборочно собирать следующий snapshot и проверять его до сохранения.
- Делить аналитическую работу на небольшие commits с одной причиной изменения.
- Настраивать проектный `.gitignore` до появления локальных данных и окружения.
- Обнаруживать файл, который уже tracked, хотя теперь совпадает с ignore-правилом.
- Читать локальную историю без remote, веток и pull request.

## Проблема

Аналитический код часто развивается нелинейно. Вы одновременно меняете формулу метрики,
делаете пробную выгрузку, правите README и сохраняете локальный отчёт. Если затем выполнить
`git add .` и commit с сообщением `update`, история зафиксирует всё одним непрозрачным
пакетом.

Такой commit трудно проверить и почти невозможно отменить частично. Неясно, относится ли
изменение результата к формуле, данным или окружению. Ещё хуже, если вместе с кодом в
историю попала тяжёлая выгрузка или локальная конфигурация.

Git полезен не как резервное копирование папки. Он позволяет собрать следующий snapshot
осознанно: увидеть изменения, выбрать связанные файлы, проверить точное содержимое и
сохранить решение с понятным названием.

## Концепция

Для базовой работы достаточно модели из трёх состояний:

```text
working tree  -- git add -->  index  -- git commit -->  repository
     |                         |
     | git diff                | git diff --cached
     v                         v
изменения на диске       следующий snapshot
```

- **Working tree** — файлы, которые вы сейчас видите и редактируете.
- **Index** или staging area — подготовленная версия следующего commit.
- **Commit** — сохранённый snapshot index с автором, временем, сообщением и ссылкой на
  родительский commit.
- **HEAD** — ссылка на текущий commit.

`git add` означает не «добавить файл в Git навсегда», а «поместить текущее содержимое пути
в следующий snapshot». Если после `git add` снова изменить файл, в index останется старая
staged-версия, а в working tree появится более новая.

Команды сравнения отвечают на разные вопросы:

| Команда | Сравнение | Практический вопрос |
|---|---|---|
| `git status --short` | Сводка состояний | Что staged, unstaged и untracked? |
| `git diff` | Working tree против index | Что я изменил после последнего `git add`? |
| `git diff --cached` | Index против `HEAD` | Что точно войдёт в следующий commit? |
| `git show --stat HEAD` | Текущий commit против родителя | Что сохранил последний commit? |
| `git log --oneline` | Последовательность commits | Какие решения образуют историю? |

В коротком статусе левая колонка относится к index, правая — к working tree:

```text
 M report.py   # изменён только на диске
M  metric.py   # изменение staged
MM model.py    # staged, затем снова изменён
?? notes.md    # Git пока не отслеживает путь
```

## Соберите это

Создайте отдельный учебный репозиторий. Из корня курса перейдите в каталог урока:

```bash
cd phases/00-entry-and-tools/04-git-foundations
mkdir git-lab
cd git-lab
git init
```

Настройте автора только для учебного репозитория:

```bash
git config user.name "Course Student"
git config user.email "student@example.com"
```

Отсутствие `--global` важно: урок не меняет конфигурацию других проектов.

### Шаг 1: подготовьте правила до данных

Создайте `.gitignore`:

```gitignore
.venv/
__pycache__/
*.py[cod]
.env
data/raw/
outputs/local/
```

Создайте описание проекта:

```bash
printf '# Revenue check\n' > README.md
git status --short
```

Ожидаются два untracked-пути. Выберите их явно:

```bash
git add -- README.md .gitignore
git diff --cached
git commit -m "Initialize revenue project"
```

`--` отделяет параметры команды от путей. Это защищает от имени файла, начинающегося с
дефиса.

### Шаг 2: сохраните расчёт отдельно

Создайте минимальную функцию:

```bash
mkdir -p src
cat > src/revenue.py <<'PY'
def paid_revenue(amounts: list[float]) -> float:
    return round(sum(amounts), 2)
PY
```

Проверьте изменение, подготовьте только код и снова проверьте index:

```bash
git status --short
git add -- src/revenue.py
git diff --cached
git commit -m "Add paid revenue calculation"
```

Commit атомарен не потому, что меняет один файл. У него одна причина: добавить расчёт
выручки. Если бы функция требовала теста и fixture, несколько файлов могли бы составлять
одно связанное изменение.

### Шаг 3: зафиксируйте предположение

```bash
mkdir -p docs
cat > docs/assumptions.md <<'MD'
# Assumptions

Amounts are already filtered to paid orders.
MD

git add -- docs/assumptions.md
git diff --cached
git commit -m "Document revenue assumptions"
```

История должна читаться как короткий рассказ:

```bash
git log --reverse --oneline --stat
git status --short
```

Последняя команда ничего не печатает, если tracked и untracked изменений нет.

### Шаг 4: проверьте ignore-контракт

Создайте локальную выгрузку:

```bash
mkdir -p data/raw
printf 'order_id,amount\n101,120\n' > data/raw/orders.csv
git status --short
```

Файл не должен появиться в статусе. Проверьте причину:

```bash
git check-ignore -v data/raw/orders.csv
```

Проектный `.gitignore` хранится в репозитории и распространяется между участниками. Личные
настройки редактора можно держать в глобальном ignore, а специфичные только для одного
клона правила — в `.git/info/exclude`.

## Используйте это

Вернитесь в каталог урока и запустите поставляемый аудитор:

```bash
cd ..
python3 outputs/git_history_check.py git-lab
```

Сохраните JSON для автоматической проверки:

```bash
python3 outputs/git_history_check.py \
  git-lab \
  --format json \
  --output git-history-report.json
```

CLI проверяет:

- существует ли минимум три commits;
- чисты ли working tree и index;
- отслеживается ли `.gitignore`;
- нет ли tracked-файлов, которые совпадают с ignore-правилами;
- не являются ли сообщения слишком короткими, общими или длиннее 72 символов;
- не меняет ли commit больше четырёх файлов.

Последний лимит — учебная эвристика для этого маленького проекта. В реальной работе один
атомарный commit может менять десятки связанных файлов, например код, тесты и миграцию.
Главный критерий — одна причина изменения и возможность проверить или отменить её
отдельно.

Запустите готовую демонстрацию:

```bash
python3 code/main.py
```

Она создаёт временный репозиторий, делает три commits и печатает отчёт аудитора.

## Сломайте это

### Измените файл после staging

Внутри `git-lab`:

```bash
printf '\n# First note\n' >> docs/assumptions.md
git add -- docs/assumptions.md
printf '\n# Newer note\n' >> docs/assumptions.md
git status --short
```

Статус покажет `MM`. Сравните две версии:

```bash
git diff
git diff --cached
```

Если следующий commit должен содержать обе строки, повторите `git add`. Если staged-версия
не готова, уберите её из index, не удаляя изменения на диске:

```bash
git restore --staged -- docs/assumptions.md
```

### Добавьте в ignore уже tracked-файл

`.gitignore` не влияет на tracked-файлы. Проверьте это в отдельном временном репозитории
рядом с `git-lab`:

```bash
cd ..
mkdir tracked-file-lab
cd tracked-file-lab
git init
git config user.name "Course Student"
git config user.email "student@example.com"
printf '# Tracked file lab\n' > README.md
touch .gitignore
git add -- README.md .gitignore
git commit -m "Initialize tracked file lab"
mkdir -p data/raw
printf 'order_id,amount\n101,120\n' > data/raw/orders.csv
git add -- data/raw/orders.csv
git commit -m "Add raw order sample"
printf 'data/raw/\n' >> .gitignore
git add -- .gitignore
git commit -m "Ignore raw data directory"
git ls-files -ci --exclude-standard
```

Команда всё ещё покажет `data/raw/orders.csv`. Чтобы перестать отслеживать файл в будущих
snapshots, оставив его на диске:

```bash
git rm --cached -- data/raw/orders.csv
git commit -m "Stop tracking raw order sample"
```

Старые commits по-прежнему содержат файл. Поэтому `.gitignore` не является защитой
секретов; полноценное реагирование на утечку рассматривается в уроке `00/06`.

### Подготовьте всё без просмотра

Создайте несвязанные изменения и выполните:

```bash
git add .
git status --short
git diff --cached --stat
```

`git add .` не ошибочен сам по себе, но скрывает решение о составе commit. Если index
собран слишком широко:

```bash
git restore --staged -- .
git add -- path/to/related-file
```

### Назовите commit словом `update`

Сообщение отвечает на вопрос «какое решение появилось?». `Update files` сообщает только
факт изменения, уже известный Git. Сравните:

```text
update
Add paid revenue calculation
Document cancellation rule
Exclude local extracts from Git
```

## Проверьте это

Запустите тесты урока:

```bash
python3 -m unittest discover \
  -s phases/00-entry-and-tools/04-git-foundations/tests \
  -p "test_*.py" -v
```

Тесты создают настоящие временные Git-репозитории и проверяют:

- успешный аудит трёх сфокусированных commits;
- отказ при незакоммиченном изменении;
- обнаружение tracked-файла после добавления ignore-правила;
- отказ для общего сообщения и слишком широкого учебного commit;
- полноту Markdown-отчёта.

Перед commit используйте короткий контрольный цикл:

```bash
git status --short
git diff
git diff --cached
git commit -m "Describe the decision"
git show --stat HEAD
```

Если `git diff --cached` пуст, следующий commit не содержит подготовленных изменений.
Если обычный `git diff` не пуст, часть работы останется вне commit — иногда намеренно,
иногда из-за забытого `git add`.

## Поставьте результат

Итог студента — локальный `git-lab` с тремя объяснимыми commits и tracked-файлом
`.gitignore`. Переиспользуемый артефакт урока — `outputs/git_history_check.py`, который
можно скопировать в onboarding-репозиторий или запускать перед сдачей учебной работы.

```bash
python3 outputs/git_history_check.py \
  path/to/project \
  --min-commits 3 \
  --max-files-per-commit 4
```

Manifest и команда использования находятся в `outputs/artifact.json`. Аудитор не
доказывает смысловую атомарность автоматически: он проверяет наблюдаемые признаки и
показывает историю для человеческого ревью.

## Упражнения

1. Добавьте тест для `paid_revenue` отдельным commit и объясните, почему код и тест можно
   было сохранить вместе.
2. Настройте исключение `outputs/local/`, создайте там отчёт и подтвердите правило через
   `git check-ignore -v`.
3. Расширьте CLI проверкой, что каждый commit имеет непустой body с причиной изменения,
   но сделайте правило опциональным.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| Working tree | Всё содержимое Git | Текущие файлы на диске |
| Index | Список отслеживаемых файлов | Подготовленный snapshot следующего commit |
| Commit | Архив изменённых строк | Snapshot index с метаданными и ссылкой на родителя |
| HEAD | Название основной ветки | Ссылка на текущий выбранный commit |
| Tracked | Файл существует в папке | Путь представлен в index и известен Git |
| `.gitignore` | Запрещает Git читать файл | Описывает намеренно untracked-пути |
| Атомарный commit | Commit с одним файлом | Одно связанное и независимо проверяемое изменение |

## Дополнительное чтение

- [Pro Git: Recording Changes to the Repository](https://git-scm.com/book/en/v2/Git-Basics-Recording-Changes-to-the-Repository) — пройдите жизненный цикл tracked-файла, staging и базовый контракт commit.
- [git-status documentation](https://git-scm.com/docs/git-status) — разберите две колонки short/porcelain status и различие index с working tree.
- [git-diff documentation](https://git-scm.com/docs/git-diff) — сравните обычный `git diff`, `git diff --cached` и `git diff HEAD`.
- [gitignore documentation](https://git-scm.com/docs/gitignore) — изучите источники ignore-правил и примечание о файлах, которые уже tracked.
