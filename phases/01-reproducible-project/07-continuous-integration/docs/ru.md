# Автоматическая проверка в CI

> Quality gate полезен только тогда, когда чистая машина повторяет те же команды и
> действительно останавливает merge при ошибке.

**Тип:** Build
**Треки:** Core
**Пререквизиты:** 01/06 — Первые проверки с pytest
**Время:** ~60 минут
**Результат:** запускает lint и tests автоматически на каждом изменении

## Цели обучения

- Объяснять роль continuous integration в аналитическом проекте.
- Создавать GitHub Actions workflow для push и pull request.
- Устанавливать Python и uv на чистом runner.
- Восстанавливать environment через `uv sync --locked`.
- Запускать Ruff lint, format check и pytest как обязательные steps.
- Ограничивать `GITHUB_TOKEN` read-only permissions.
- Отменять устаревшие runs через concurrency.
- Отличать локальную ошибку от failure чистой среды.

## Проблема

Автор перед pull request выполняет:

```bash
ruff check .
pytest
```

и сообщает, что всё работает. После merge выясняется:

- formatter не проверялся;
- tests использовали package из глобального environment;
- lockfile был stale;
- notebook или source зависели от local file;
- colleague забыл одну из команд;
- CI step был помечен `continue-on-error`;
- workflow имел избыточные write permissions.

Локальная дисциплина важна, но она не является общей проверкой. CI запускает agreed
procedure на отдельной машине из repository state.

```text
push / pull request
        ↓
clean runner
        ↓
locked environment
        ↓
workflow audit
        ↓
Ruff lint
        ↓
Ruff format check
        ↓
pytest
        ↓
pass или blocked change
```

## Концепция

### Continuous integration — короткая обратная связь

CI не означает deployment. В этой фазе pipeline только проверяет изменение:

- project можно восстановить;
- declarative contracts согласованы;
- source проходит static checks;
- formatting воспроизводим;
- behavioral tests зелёные.

Чем быстрее gate, тем раньше author получает feedback.

### Workflow находится в repository

GitHub Actions читает:

```text
.github/workflows/*.yml
```

Workflow — versioned code. Он проходит review вместе с source и не должен жить только в
настройках одного пользователя.

Artifact:

```text
outputs/ci_project/.github/workflows/quality.yml
```

### Triggers определяют момент запуска

```yaml
on:
  push:
    branches:
      - main
  pull_request:
  workflow_dispatch:
```

- `push` проверяет состояние main после изменения;
- `pull_request` даёт feedback до merge;
- `workflow_dispatch` позволяет ручной run для диагностики.

Если оставить только push, broken change обнаружится слишком поздно.

### Runner — новая машина

```yaml
jobs:
  quality:
    runs-on: ubuntu-latest
```

Runner не знает packages из laptop автора. Именно это делает CI полезным.

Ограничьте зависший job:

```yaml
timeout-minutes: 10
```

Короткий quality gate не должен бесконечно ждать network или hung test.

### Setup actions

```yaml
- uses: actions/checkout@v6

- uses: actions/setup-python@v6
  with:
    python-version-file: .python-version
```

Checkout помещает repository в workspace. Setup Python читает тот же selector, который
используется локально.

Для uv:

```yaml
- uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
  with:
    version: "0.11.21"
    enable-cache: true
    cache-dependency-glob: uv.lock
```

Third-party action зафиксирован immutable commit SHA. Комментарий сохраняет читаемую
release version. Сам uv тоже имеет explicit version.

Official actions в beginner artifact закреплены major tags. Для stricter supply-chain
policy закрепите и их full SHAs, обновляя через отдельный reviewed change.

### Lockfile является quality gate

```yaml
- run: uv sync --locked --dev
```

`--locked` запрещает workflow неявно обновлять stale `uv.lock`. Если author изменил
`pyproject.toml`, но не lockfile, CI падает.

Это важнее, чем:

```yaml
- run: uv sync
```

который может исправить repository state только внутри временного runner и скрыть
незакоммиченный diff.

### CI повторяет локальные команды

```yaml
- run: uv run ruff check .
- run: uv run ruff format --check .
- run: uv run pytest
```

В workflow нет особой «CI-версии» quality policy. Команды те же, что выполняет developer.

CI проверяет, но не форматирует:

```text
ruff format --check .
```

Если runner изменит files, изменения всё равно исчезнут после job. Исправлять source
нужно локально и отправлять reviewed diff.

### Failure обязан останавливать job

Shell step по умолчанию падает при non-zero exit code. Не добавляйте:

```yaml
continue-on-error: true
```

к обязательным checks. Иначе UI может показать warning, но broken contract не остановит
pipeline.

### Least privilege

Quality workflow только читает repository:

```yaml
permissions:
  contents: read
```

Не выдавайте write access «на всякий случай». Если позже появится publish job, отделите
его permissions и triggers от ordinary pull request validation.

Особенно осторожно обращайтесь с pull requests из forks: untrusted code не должен
получать secrets или privileged token.

### Concurrency отменяет устаревшие runs

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

После нового push предыдущий run той же ветки уже проверяет неактуальный commit.
Cancellation экономит runner minutes и ускоряет feedback.

### Cache — ускорение, не источник истины

Setup uv использует:

```yaml
enable-cache: true
cache-dependency-glob: uv.lock
```

Cache key меняется вместе с lockfile. Но workflow должен быть корректным и при cache miss.
Нельзя хранить только `.venv` без reproducible lock/sync procedure.

### Matrix нужна для реального диапазона support

Если project заявляет:

```toml
requires-python = ">=3.11,<3.14"
```

полезно тестировать 3.11, 3.12 и 3.13. Artifact ограничен Python 3.12:

```toml
requires-python = ">=3.12,<3.13"
```

поэтому один interpreter честно соответствует contract.

Не создавайте matrix из versions, которые project не обещает поддерживать.

## Соберите это

Откройте standalone sample:

```text
outputs/ci_project
```

Структура:

```text
ci_project/
├── .github/workflows/quality.yml
├── .python-version
├── pyproject.toml
├── uv.lock
├── src/ratio.py
├── tests/test_ratio.py
└── tools/workflow_audit.py
```

### Шаг 1: проверьте lockfile

```bash
cd outputs/ci_project
uv lock --check
```

Команда не должна изменять files.

### Шаг 2: восстановите environment

```bash
uv sync --locked --dev
```

Удаление `.venv` и повторный sync должны приводить к тому же locked graph.

### Шаг 3: проверьте сам workflow

```bash
uv run python tools/workflow_audit.py \
  .github/workflows/quality.yml
```

Аудитор структурно разбирает YAML и проверяет:

- required triggers;
- read-only permissions;
- concurrency cancellation;
- runner и timeout;
- setup actions;
- immutable setup-uv SHA;
- explicit uv version и cache;
- locked sync;
- порядок audit, lint, format и tests;
- отсутствие `continue-on-error`.

### Шаг 4: повторите CI локально

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Все commands должны завершиться status `0`.

### Шаг 5: перенесите workflow

В собственном project:

```bash
mkdir -p .github/workflows
cp path/to/quality.yml .github/workflows/quality.yml
```

Затем адаптируйте:

- Python selector;
- uv version;
- command paths;
- optional matrix;
- timeout.

Не копируйте workflow без чтения: он является executable supply-chain configuration.

## Используйте это

Перед push:

```bash
uv lock --check
uv sync --check --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

После push:

1. Откройте Actions или pull request checks.
2. Убедитесь, что запущен commit, который вы ожидаете.
3. При failure откройте первый упавший step.
4. Воспроизведите ту же command локально.
5. Исправьте code или contract и отправьте новый commit.

Не перезапускайте один и тот же deterministic failure много раз. Retry уместен только при
подтверждённой transient infrastructure error.

Branch protection может требовать успешный `quality` job до merge. Название job тогда
становится частью repository governance, поэтому не меняйте его случайно.

## Сломайте это

### Уберите `--locked`

```yaml
run: uv sync --dev
```

Workflow сможет разрешить новый graph, которого нет в committed lockfile. Аудитор
отклонит step.

### Добавьте write permissions

```yaml
permissions:
  contents: write
```

Quality checks не нуждаются в записи. Верните `contents: read`.

### Используйте third-party action по moving tag

```yaml
uses: astral-sh/setup-uv@v8
```

Tag читаем, но может указывать на другой commit. Artifact требует reviewed SHA.

### Разрешите test failure

```yaml
- run: uv run pytest
  continue-on-error: true
```

Gate становится декоративным. Аудитор пометит commands section как failed.

### Поменяйте порядок

Если tests идут до sync или formatter запускается после publish, pipeline не выражает
правильную dependency sequence. В quality job сначала создаётся environment, затем
проверяется workflow, потом source и behavior.

### Сломайте source

```python
def ratio(part, total):
    return 0.5
```

Локальный pytest и GitHub Actions должны упасть одинаково.

## Проверьте это

Запустите восемь tests урока:

```bash
python3 -m unittest discover \
  -s phases/01-reproducible-project/07-continuous-integration/tests \
  -p "test_*.py" -v
```

Покрыты:

- valid workflow;
- обязательный pull request trigger;
- запрет write permissions;
- immutable setup-uv pin;
- запрет `continue-on-error`;
- обязательный locked sync;
- актуальность `uv.lock`;
- behavioral tests sample project.

Запустите демонстрацию:

```bash
python3 phases/01-reproducible-project/07-continuous-integration/code/main.py
```

Полный локальный эквивалент:

```bash
cd phases/01-reproducible-project/07-continuous-integration/outputs/ci_project
uv sync --locked --dev
uv run python tools/workflow_audit.py .github/workflows/quality.yml
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Поставьте результат

Итоговый artifact фазы:

```text
reproducible project
├── Python version contract
├── pyproject.toml
├── uv.lock
├── importable source
├── Ruff policy
├── pytest behavioral suite
└── GitHub Actions quality gate
```

Definition of done:

- clone восстанавливается через locked sync;
- workflow запускается на pull request и main;
- token read-only;
- stale runs отменяются;
- lint, format и tests обязательны;
- local commands совпадают с CI;
- job зелёный на чистом runner.

Фаза 01 завершает базовую инженерную оболочку курса. В фазе 02 начнутся численные
вычисления с NumPy, но они уже будут жить в versioned, linted и tested project.

## Упражнения

1. Расширьте project contract до Python 3.11–3.13 и добавьте matrix, не дублируя quality
   commands в трёх jobs.
2. Добавьте notebook execution как отдельный step после pytest и ограничьте его timeout.
3. Зафиксируйте official actions по full commit SHAs и опишите процедуру безопасного
   обновления pins.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| CI | Deployment | Автоматическая интеграционная проверка changes |
| Workflow | Один shell script | YAML-описание triggers, jobs и permissions |
| Job | Одна command | Набор steps на runner |
| Step | Отдельная machine | Action или shell command внутри job |
| Runner | Production server | Временная среда выполнения job |
| Trigger | Manual button only | Event, запускающий workflow |
| Quality gate | Warning report | Обязательные checks с failure status |
| Locked sync | Обновление dependencies | Восстановление environment без изменения lockfile |
| Action pin | Версия Python | Ссылка на release tag или immutable action commit |
| Permissions | Права автора PR | Возможности `GITHUB_TOKEN` workflow |
| Concurrency | Parallel tests | Группировка runs и cancellation policy |
| Cache | Lockfile | Ускоряющая копия, не источник воспроизводимости |

## Дополнительное чтение

- [GitHub Docs: Building and testing Python](https://docs.github.com/en/actions/tutorials/build-and-test-code/python) — изучите официальный Python workflow, setup-python и pytest examples.
- [GitHub Docs: Workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax) — используйте как справочник по triggers, permissions, jobs, steps, timeout и concurrency.
- [GitHub Docs: Automatic token authentication](https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication) — разберите `GITHUB_TOKEN` и принцип минимальных permissions.
- [uv Docs: GitHub Actions integration](https://docs.astral.sh/uv/guides/integration/github/) — изучите setup-uv, version pinning, cache и locked sync в официальном workflow.
