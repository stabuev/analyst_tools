# CLI для повторяемого запуска

> Хороший delivery CLI не просто запускает код, а обещает: какие входы использованы, что проверено, что опубликовано и какой сигнал получила автоматизация.

**Тип:** Build
**Треки:** Delivery
**Пререквизиты:** `17-delivery/07-caching-and-state`
**Время:** ~75 минут
**Результат:** вы оформляете delivery pipeline как CLI с явными input/output paths, `--check`, JSON report, publish manifest, staged publication и различимыми exit codes.

## Цели обучения

- Проектировать CLI как machine-readable operational contract, а не как удобный wrapper.
- Разделять check mode, publish mode, data-quality block, freshness warning и system error.
- Публиковать delivery package через staging directory, чтобы failed run не портил уже опубликованный output.

## Проблема

После Streamlit app, cache/state и freshness panel stakeholder просит простой способ пересобрать пакет:

```bash
python run_delivery.py ...
```

Опасность в том, что "простой скрипт" быстро становится неоперабельным:

- входы читаются из текущей директории и зависят от того, откуда запустили команду;
- `--check` на самом деле что-то публикует;
- stale data и missing file возвращают один и тот же non-zero code;
- при падении после половины копирования output directory выглядит почти готовым;
- stdout содержит красивый текст, но automation не знает, что делать.

В этом уроке CLI становится контрактом. Он не пересчитывает аналитику и не заменяет `17/07`; он оркестрирует проверенный cache/state package и добавляет безопасный operational boundary.

## Концепция

Delivery CLI состоит из пяти слоев.

| Слой | Роль |
|---|---|
| Explicit paths | `--app-dir`, `--cache-state-contract`, `--freshness-policy`, `--output-dir` |
| Check mode | Валидирует pipeline без публикации output directory |
| Exit-code policy | Разделяет success, data-quality block, freshness warning и system error |
| Staged publish | Сначала build во временную директорию, потом controlled replace output |
| Publish manifest | Фиксирует command, inputs, outputs, hashes, status и publish strategy |

В уроке exit codes такие:

| Статус | Код | Смысл |
|---|---:|---|
| `success` | 0 | Package опубликован или check прошел |
| `data_quality_block` | 10 | Upstream audit или delivery gate блокирует publish |
| `freshness_warning` | 20 | Stale-only case: можно диагностировать отдельно от data-quality failure |
| `system_error` | 30 | Missing path, output conflict или другая инфраструктурная ошибка |
| argparse usage error | 2 | Неверные CLI arguments до запуска логики |

Почему stale - не то же самое, что system error: старый пакет может быть технически собран и полезен для диагностики, но automation должна видеть его отдельно от missing file или broken app audit.

## Соберите это

Минимальный CLI contract можно описать словарем:

```python
EXIT_CODE_POLICY = {
    "success": 0,
    "data_quality_block": 10,
    "freshness_warning": 20,
    "system_error": 30,
    "usage_error": 2,
}

contract = {
    "required_arguments": ["--app-dir", "--freshness-policy", "--output-dir"],
    "supported_modes": ["check", "publish"],
    "path_policy": {"explicit_input_paths_required": True},
    "publish_policy": {
        "build_in_staging_directory": True,
        "atomic_replace_required": True,
        "publish_manifest_required": True,
        "no_partial_publish_on_block": True,
    },
    "exit_code_policy": EXIT_CODE_POLICY,
}
```

Теперь добавьте классификацию upstream audit:

```python
FRESHNESS_ONLY_BLOCKERS = {"freshness_report_is_not_stale"}

def classify(blocking_errors: list[str]) -> tuple[str, int]:
    blockers = set(blocking_errors)
    if not blockers:
        return "success", 0
    if blockers <= FRESHNESS_ONLY_BLOCKERS:
        return "freshness_warning", 20
    return "data_quality_block", 10
```

И отделите build от publish:

```python
from tempfile import TemporaryDirectory
import os

def publish(build_fn, output_dir):
    with TemporaryDirectory(prefix=".delivery-stage-") as tmp:
        staging_dir = Path(tmp) / "package"
        report = build_fn(staging_dir)
        if report["status"] != "success":
            return report
        os.replace(staging_dir, output_dir)
        report["published"] = True
        return report
```

Смысл не в том, что `os.replace` магически решает все проблемы production deploy. Смысл в учебной границе: пока checks не прошли, published output не трогается.

## Используйте это

Запустите артефакт урока:

```bash
uv run --locked python phases/17-delivery/08-cli/outputs/delivery_cli_runner.py \
  --write-example /tmp/delivery-cli-example \
  --output-dir /tmp/delivery-cli-package
```

`--write-example` создает sample inputs из `17/07`, затем CLI публикует package:

```text
delivery-cli-package/
├── cli_run_report.json
├── cli_publish_manifest.json
├── delivery_cli_contract.json
├── streamlit_app.py
├── cache_state_contract.json
├── freshness_policy.json
├── freshness_report.json
├── cache_state_audit.json
├── cache_state_manifest.json
└── ...
```

Безопасная проверка без публикации:

```bash
uv run --locked python phases/17-delivery/08-cli/outputs/delivery_cli_runner.py \
  --write-example /tmp/delivery-cli-example \
  --output-dir /tmp/delivery-cli-package \
  --check \
  --report /tmp/delivery-cli-check.json
```

Для реального входа:

```bash
uv run --locked python phases/17-delivery/08-cli/outputs/delivery_cli_runner.py \
  --app-dir /path/to/cache-state-app \
  --cache-state-contract /path/to/cache_state_contract.json \
  --freshness-policy /path/to/freshness_policy.json \
  --cli-contract /path/to/delivery_cli_contract.json \
  --output-dir /path/to/published-delivery
```

Если package stale-only и вы сознательно хотите опубликовать диагностический stale output:

```bash
uv run --locked python phases/17-delivery/08-cli/outputs/delivery_cli_runner.py \
  --app-dir /path/to/cache-state-app \
  --output-dir /path/to/published-delivery \
  --checked-at 2026-01-01T02:00:00Z \
  --allow-freshness-warning
```

Команда вернет exit code `20`, а manifest сохранит `status = "freshness_warning"`.

## Сломайте это

Проверьте failure modes.

1. Запустите без `--app-dir` и без `--write-example`. CLI должен вернуть JSON system error без traceback.
2. Укажите несуществующий `--app-dir`. Это system error, а не data-quality block.
3. Запустите `--check`. Output directory не должен появиться.
4. Сделайте upstream `app_audit.json` invalid. CLI должен вернуть `data_quality_block` и не публиковать package.
5. Сделайте stale-only run. CLI должен вернуть `freshness_warning`; публикация разрешена только с `--allow-freshness-warning`.
6. Попробуйте записать в существующий output directory без `--overwrite`. Existing package должен остаться нетронутым.
7. Повторите с `--overwrite` и valid staging build. Старый output заменяется только после успешного build.
8. Уберите `publish_manifest_required` из CLI contract. Run report должен показать invalid operational contract.

## Проверьте это

Тесты урока проверяют:

- happy path публикует package с CLI report, publish manifest, contract и cache/state outputs;
- `--check` не создает output directory;
- contract объявляет explicit paths, check/publish modes, atomic publish и exit codes;
- source использует `argparse`, `TemporaryDirectory` и `os.replace`;
- publish manifest хранит input/output hashes и atomic strategy;
- existing output не перезаписывается без `--overwrite`;
- data-quality block не заменяет уже опубликованный output;
- stale-only run возвращает exit code `20` и публикуется только при явном флаге;
- missing input path дает system error без traceback;
- `--help` документирует рабочие аргументы;
- учебный `code/main.py` запускает check и publish режимы.

Запуск:

```bash
uv run --locked python -m unittest discover -s phases/17-delivery/08-cli/tests -v
```

## Поставьте результат

Именованный артефакт: `outputs/delivery_cli_runner.py`.

Минимальный production-like сценарий:

```bash
uv run --locked python phases/17-delivery/08-cli/outputs/delivery_cli_runner.py \
  --app-dir ./cache-state-app \
  --cache-state-contract ./cache_state_contract.json \
  --freshness-policy ./freshness_policy.json \
  --cli-contract ./delivery_cli_contract.json \
  --output-dir ./published-delivery \
  --report ./delivery-run-report.json
```

Передавайте дальше `published-delivery/` вместе с `cli_publish_manifest.json` и `cli_run_report.json`. Один только stdout не является handoff artifact.

## Упражнения

1. Добавьте режим `--dry-run`, который печатает план публикации, но не запускает upstream builder.
2. Добавьте `--require-clean-output`, который блокирует publish, если output directory уже существует даже с `--overwrite`.
3. Расширьте `cli_publish_manifest.json` полем `previous_manifest_sha256` для chained publication history.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| CLI contract | Просто набор аргументов | Машиночитаемое обещание режимов, путей, exit codes, reports и publish behavior |
| Check mode | Быстрый smoke test | Полная валидация без изменения published output |
| Exit code policy | Техническая мелочь shell | Интерфейс для scheduler, CI и wrapper scripts |
| Staged publish | Лишняя копия файлов | Защита от partial output при failed run |
| Publish manifest | Лог выполнения | Проверяемый manifest inputs/outputs/hashes/status/publish strategy |
| System error | Любой non-zero exit | Инфраструктурная проблема, отличная от data-quality и freshness status |

## Дополнительное чтение

- [Python `argparse`](https://docs.python.org/3/library/argparse.html) — как задавать аргументы, help text, invalid arguments и стандартное поведение parser exit.
- [Python `tempfile`](https://docs.python.org/3/library/tempfile.html) — временные директории для staging build без загрязнения published output.
- [Python `os.replace`](https://docs.python.org/3/library/os.html#os.replace) — атомарная замена path на уровне OS API; читайте вместе с ограничениями вашей файловой системы.
- [Python `pathlib`](https://docs.python.org/3/library/pathlib.html) — объектная работа с путями, которую легче тестировать и сериализовать в manifests.
