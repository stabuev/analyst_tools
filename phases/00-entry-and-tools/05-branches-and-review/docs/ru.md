# Ветки, pull request и ревью

> Pull request — это проверяемое предложение изменить base, а не уведомление о готовом
> решении.

**Тип:** Build
**Треки:** Core
**Пререквизиты:** 04 — Git: история аналитического проекта
**Время:** ~60 минут
**Результат:** проводит изменение через ветку и проверяет аналитический код коллеги

## Цели обучения

- Создавать feature-ветку от актуального base и объяснять модель указателей Git.
- Различать base, head и merge base.
- Проверять commits и diff будущего PR до публикации на GitHub.
- Писать описание PR с задачей, способом проверки и ограничениями.
- Проводить ревью аналитического изменения от бизнес-риска к строкам кода.
- Выбирать между comment, approve и request changes.

## Проблема

Локально можно проверить только собственное намерение. Автор знает, почему выбрал именно
этот знаменатель, какие строки исключил и какой notebook запускал перед commit. Коллега
видит только результат. Если изменение сразу попадает в `main`, скрытое предположение
становится частью общего расчёта без независимой проверки.

Ветка изолирует незавершённую работу, а pull request связывает три объекта:

1. задачу и мотивацию;
2. конкретный diff между base и head;
3. обсуждение, проверки и решение о merge.

Для аналитики code review особенно важен: синтаксически корректный SQL или Python может
удвоить выручку из-за many-to-many join, изменить популяцию метрики или использовать
будущие данные. Зелёный запуск ещё не доказывает корректность вывода.

## Концепция

Ветка Git — не отдельная копия проекта, а именованная ссылка на commit:

```text
                   feature/activation-check
                              |
A --- B --- C ----------------D
          |
         main
```

После `git switch -c feature/activation-check` обе ветки указывают на `C`. Новый commit
перемещает только feature-ветку к `D`.

В pull request:

- **base** — ветка, куда предлагается применить изменение;
- **head** — ветка с предлагаемыми commits;
- **merge base** — общий предок base и head;
- **diff** — изменение head относительно merge base.

Если `main` продвинулся после ответвления:

```text
          E --- F  main
         /
A --- B
         \
          C --- D  feature
```

`git diff main...feature` показывает изменения `B -> D`, то есть вклад feature-ветки.
Base-only commits `E` и `F` не становятся частью предложения.

Pull request существует на платформе GitHub, а не внутри локальной базы Git. Локально
можно подготовить тот же пакет: список commits, трёхточечный diff, описание и результаты
проверок. После push GitHub добавляет обсуждение, reviewers, статусы CI и решение о merge.

## Соберите это

Используйте учебный `git-lab` из предыдущего урока или создайте новый небольшой
репозиторий. В примере base называется `main`.

### Шаг 1: начните от base

Проверьте текущую ветку и чистоту дерева:

```bash
git switch main
git status --short
git log --oneline -3
```

Перед ответвлением working tree должен быть понятным. Незакоммиченные изменения могут
перейти в новую ветку и смешать две задачи.

Создайте ветку с назначением, а не именем автора:

```bash
git switch -c feature/activation-check
git branch --show-current
```

Хорошее имя помогает ответить, какое изменение находится в ветке:

```text
feature/activation-check
fix/order-join-cardinality
docs/metric-assumptions
```

### Шаг 2: внесите проверяемое изменение

Создайте функцию:

```bash
mkdir -p src tests
cat > src/activation.py <<'PY'
def activation_rate(activated: int, eligible: int) -> float:
    if eligible <= 0:
        raise ValueError("eligible must be positive")
    return activated / eligible
PY
```

Добавьте контрольный тест:

```bash
cat > tests/test_activation.py <<'PY'
from src.activation import activation_rate


def test_activation_rate() -> None:
    assert activation_rate(25, 100) == 0.25
PY
```

Запустите проверку и сохраните связанное изменение:

```bash
python3 -m pytest tests/test_activation.py
git add -- src/activation.py tests/test_activation.py
git diff --cached
git commit -m "Add activation rate validation"
```

Если `pytest` ещё не установлен в учебном окружении, выполните эквивалентный контрольный
пример через Python, но обязательно укажите реальную команду в описании PR:

```bash
python3 -c 'from src.activation import activation_rate; assert activation_rate(25, 100) == 0.25'
```

### Шаг 3: соберите локальный diff PR

Сначала посмотрите commits, которых нет в base:

```bash
git log --oneline main..HEAD
```

Затем изучите изменение относительно общего предка:

```bash
git diff --stat main...HEAD
git diff main...HEAD
```

Проверяйте именно тот range, который будет показан reviewer. Обычный `git diff` здесь
ничего не покажет, если working tree чист, потому что он сравнивает диск с index, а не две
ветки.

### Шаг 4: напишите описание предложения

Черновик body не обязан входить в feature-ветку. Создайте его во временном каталоге:

```bash
cat > /tmp/activation-pr.md <<'MD'
## Что изменено

Добавлен расчет activation rate с явной проверкой положительного знаменателя.

## Проверка

Запущен контрольный пример: 25 активированных из 100 дают 0.25.

## Решения и ограничения

Функция ожидает уже подготовленные количества на согласованной популяции.
Она не определяет окно активации и не исправляет grain исходных событий.
MD
```

Хорошее описание экономит время reviewer и ограничивает вывод. Оно не пересказывает имена
файлов, которые уже видны в diff.

### Шаг 5: подготовьте публикацию

Для реального GitHub-репозитория:

```bash
git push -u origin feature/activation-check
```

После push откройте PR в интерфейсе GitHub, выберите `main` как base и
`feature/activation-check` как compare/head. Вставьте подготовленный body. Если установлен
GitHub CLI, эквивалентная команда:

```bash
gh pr create \
  --base main \
  --head feature/activation-check \
  --title "Add activation rate validation" \
  --body-file /tmp/activation-pr.md
```

`gh` не является обязательной зависимостью урока. Локальный сценарий и артефакт работают
без сети и GitHub-аутентификации.

## Используйте это

Артефакт `outputs/pr_review_packet.py` собирает локальный пакет будущего PR:

```bash
python3 outputs/pr_review_packet.py \
  path/to/project \
  --base main \
  --body /tmp/activation-pr.md
```

Он проверяет:

- head является отдельной именованной веткой;
- у base и head есть merge base;
- в head есть предлагаемые commits и изменённые файлы;
- working tree чист;
- описание содержит заполненные разделы «Что изменено», «Проверка» и
  «Решения и ограничения».

Отчёт показывает commits, список файлов и чек-лист ревью. Для Python добавляются вопросы
о граничных случаях и скрытом состоянии, для SQL — о grain, ключах, NULL и размножении
строк, для данных — о необходимости хранения и чувствительных полях.

Сохраните пакет:

```bash
python3 outputs/pr_review_packet.py \
  path/to/project \
  --base main \
  --body /tmp/activation-pr.md \
  --output /tmp/activation-review.md
```

Запустите готовую демонстрацию:

```bash
python3 code/main.py
```

### Проведите ревью

Начинайте не с первой строки diff, а с цели:

1. Какое решение должно стать возможным после merge?
2. Соответствует ли diff заявленному scope?
3. Как доказана корректность?
4. Какие предположения и ограничения останутся после merge?

Затем просмотрите каждый изменённый файл и запустите проверки локально. Для аналитического
изменения приоритет вопросов обычно такой:

| Приоритет | Что проверять |
|---|---|
| Correctness | Формула, фильтры, знаменатель, временное окно |
| Data model | Grain, ключи, cardinality, дубликаты, NULL |
| Leakage | Будущая информация, признаки после целевого события |
| Verification | Контрольный расчёт, тесты, инварианты, сравнение с baseline |
| Reproducibility | Зависимости, входы, команды запуска, отсутствие скрытого state |
| Communication | Ограничения вывода и последствия для решения |

Комментарий reviewer должен содержать наблюдение, последствие и ожидаемое действие:

```text
После JOIN одна строка заказа повторяется для каждого статуса доставки, поэтому SUM(amount)
завышает выручку. Нужен тест cardinality и агрегация статусов до grain order_id перед JOIN.
```

Фраза «кажется, join неправильный» не объясняет риск и плохо помогает автору исправить
изменение.

## Сломайте это

### Создайте ветку не от того base

Проверьте граф:

```bash
git log --graph --decorate --oneline --all
git merge-base main HEAD
```

Если ветка создана от устаревшей или другой линии разработки, PR может содержать чужие
commits. Перед публикацией сравните `git log main..HEAD` и список файлов.

### Перепутайте `..` и `...`

```bash
git diff main..HEAD
git diff main...HEAD
```

Двухточечная форма сравнивает tips веток. Трёхточечная сравнивает merge base с head и
лучше соответствует вопросу «что предлагает эта ветка?». Если base продвинулся отдельно,
результаты различаются.

### Оставьте незакоммиченный файл

```bash
printf 'draft\n' > local-note.txt
python3 outputs/pr_review_packet.py \
  . --base main --body /tmp/activation-pr.md
```

Аудитор остановит готовность пакета: reviewer не увидит незакоммиченное изменение в PR.
Удалите черновик или осознанно сохраните его в отдельном commit.

### Заполните PR фразой «всё работает»

Такое описание не сообщает команду, данные и ожидаемый результат. Укажите воспроизводимую
проверку и её границы:

```text
python3 -m pytest tests/test_activation.py
Контрольный пример: activated=25, eligible=100, result=0.25.
Не проверяет построение eligible population из событий.
```

### Одобрите только по зелёному CI

CI проверяет формализованные условия. Если тест не проверяет many-to-many join, зелёный
статус не обнаружит завышенную сумму. Reviewer обязан сопоставить методологию, diff и
реальные failure modes.

## Проверьте это

Запустите тесты урока:

```bash
python3 -m unittest discover \
  -s phases/00-entry-and-tools/05-branches-and-review/tests \
  -p "test_*.py" -v
```

Тесты создают настоящие временные Git-репозитории и проверяют:

- готовую feature-ветку с заполненным PR body;
- корректность `base...head`, когда base продвинулся отдельно;
- отказ при пропущенных разделах описания;
- отказ при грязном working tree;
- профильные вопросы ревью для SQL-файла.

Перед публикацией PR выполните:

```bash
git status --short
git log --oneline main..HEAD
git diff --stat main...HEAD
git diff main...HEAD
python3 outputs/pr_review_packet.py \
  . --base main --body /tmp/activation-pr.md
```

После review выберите одно решение:

- **Comment** — вопрос или необязательное улучшение.
- **Approve** — изменение можно безопасно объединить.
- **Request changes** — найден дефект или отсутствующая обязательная проверка, без которой
  merge небезопасен.

## Поставьте результат

Результат урока — feature-ветка, заполненное описание PR и выполненный аналитический
review checklist. Переиспользуемый артефакт `outputs/pr_review_packet.py` позволяет
подготовить этот пакет до push и не зависит от GitHub API.

```bash
python3 outputs/pr_review_packet.py \
  path/to/project \
  --base main \
  --head HEAD \
  --body /tmp/pull-request.md \
  --format markdown
```

Manifest и команда запуска находятся в `outputs/artifact.json`. CLI проверяет структуру
предложения, но не заменяет reviewer: смысловую корректность формулы, SQL или вывода нельзя
надёжно определить только по именам файлов и status checks.

## Упражнения

1. Добавьте второй commit, исправляющий нулевой знаменатель, и убедитесь, что пакет PR
   показывает оба commits в правильном порядке.
2. Создайте SQL-файл с join и письменно проведите ревью по grain, cardinality и NULL.
3. Расширьте CLI проверкой максимального размера diff, но сделайте порог настраиваемым и
   объясните, почему число строк не определяет качество PR.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| Ветка | Копия репозитория | Именованная перемещаемая ссылка на commit |
| Base | Ветка автора | Ветка, куда предлагается применить изменение |
| Head | Главная ветка | Ветка, содержащая предлагаемые commits |
| Merge base | Последний commit в base | Общий предок сравниваемых линий истории |
| Pull request | Команда Git | Объект платформы для предложения и обсуждения diff |
| Review | Проверка форматирования | Независимая оценка корректности, риска и проверяемости |
| Request changes | Негативная оценка автора | Решение не объединять изменение до исправления блокирующего риска |

## Дополнительное чтение

- [GitHub Docs: Creating a pull request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request) — разберите роли base и head, draft PR и способы публикации.
- [GitHub Docs: Reviewing proposed changes](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/reviewing-proposed-changes-in-a-pull-request) — изучите порядок file-by-file review, pending comments и итоговые решения.
- [GitHub Docs: About branches](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-branches) — углубите модель веток и связь изменений с default branch.
- [git-diff documentation](https://git-scm.com/docs/git-diff) — сравните двухточечные и трёхточечные формы и роль merge base.
