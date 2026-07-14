# Запуски по расписанию и freshness report

> Расписание не делает поставку надежной само по себе: надежность появляется, когда каждый запуск оставляет проверяемый след.

**Тип:** Case
**Треки:** Delivery
**Пререквизиты:** `17-delivery/08-cli`
**Время:** ~75 минут
**Результат:** вы проектируете scheduled refresh поверх delivery CLI: cron metadata, UTC/timezone assumptions, run history, last-success marker, schedule freshness report и failure notification mock.

## Цели обучения

- Отличать cron trigger от полноценного delivery schedule contract.
- Хранить историю попыток, fresh success marker и freshness report так, чтобы stale или failed run был виден владельцу.
- Проверять, что scheduled run вызывает CLI с явными paths и не публикует partial output при failures.

## Проблема

После CLI из `17/08` заказчик хочет: "пусть пакет обновляется каждый понедельник утром". Это звучит как одна строка cron:

```yaml
on:
  schedule:
    - cron: "17 6 * * 1"
```

Но строка cron не отвечает на вопросы, которые появятся в первую же неделю:

- это 06:17 в UTC или в локальном времени команды;
- кто владелец, если запуск упал;
- как понять, когда был последний свежий успешный package;
- что делать, если CLI вернул `freshness_warning`, а не `success`;
- можно ли перезаписать старый published output после failed quality gate;
- где увидеть историю попыток, если workflow UI недоступен.

В этом уроке schedule становится delivery artifact. Он не заменяет production scheduler и не обещает SLA. Он фиксирует, как автоматизация вызывает уже проверенный CLI, какие operational файлы остаются после каждой попытки и какой сигнал получает владелец.

## Концепция

Scheduled delivery состоит из шести файлов.

| Файл | Роль |
|---|---|
| `schedule_contract.json` | Owner, cron, UTC assumptions, GitHub Actions caveats, required CLI args и failure policy |
| `schedule_workflow.yml` | GitHub Actions style workflow: `schedule`, `workflow_dispatch`, явный вызов CLI |
| `run_history.csv` | Ledger всех attempts: run id, status, exit code, freshness state, notification flag |
| `last_success_marker.json` | Последний свежий успешный publish, а не просто последняя попытка |
| `schedule_freshness_report.json` | Возраст last success, next expected run, delivery freshness и scheduler caveats |
| `failure_notification_mock.json` | Кого уведомить, с каким severity, reason codes и next manual action |

Главная граница: schedule не пересчитывает аналитику сам. Он вызывает CLI из `17/08` и переиспользует его status/exit code/report.

```text
schedule trigger
  -> scheduled_delivery_workflow
  -> delivery_cli_runner.py
  -> cache/state package from 17/07
  -> scheduled run history + freshness + notification
```

Exit codes наследуют смысл CLI:

| Статус | Код | Что делает schedule |
|---|---:|---|
| `success` | 0 | Публикует fresh package и обновляет `last_success_marker.json` |
| `schedule_contract_block` | 2 | Блокирует запуск до CLI: неверный cron, timezone или policy |
| `data_quality_block` | 10 | Пишет diagnostics, не перезаписывает previous published output |
| `freshness_warning` | 20 | Показывает stale state; publish разрешен только явным opt-in |
| `system_error` | 30 | Missing path или инфраструктурная ошибка, notification обязательна |

`last_success_marker.json` обновляется только для fresh `success`. Stale warning может быть полезен для диагностики, но он не должен маскировать отсутствие свежей поставки.

## Соберите это

Минимальный schedule contract:

```python
contract = {
    "schedule_id": "trial-onboarding-weekly-delivery-refresh",
    "owner": {"primary": "support_lead", "backup": "product_analytics"},
    "cron": "17 6 * * 1",
    "timezone": "UTC",
    "expected_cadence_minutes": 10080,
    "github_actions_constraints": {
        "schedule_uses_utc": True,
        "default_branch_required": True,
        "minimum_interval_minutes": 5,
        "workflow_dispatch_enabled": True,
        "high_load_delay_visible": True,
    },
    "run_policy": {
        "write_run_history": True,
        "write_freshness_report": True,
        "write_last_success_marker": True,
        "write_failure_notification_mock": True,
        "no_source_mutation": True,
        "no_partial_publish_on_failure": True,
    },
}
```

Теперь отделите attempt от success:

```python
def update_last_success(status, published, marker_path, payload):
    if status == "success" and published:
        write_json(marker_path, payload)
```

А failure visibility сделайте отдельным artifact, а не строкой в логе:

```python
notification = {
    "should_notify": status != "success",
    "recipient": contract["owner"]["primary"],
    "status": status,
    "reason_codes": blocking_errors,
    "run_report_path": "schedule_run_report.json",
    "next_manual_action": "rerun workflow_dispatch after fixing inputs",
}
```

## Используйте это

Запустите артефакт урока:

```bash
uv run --locked python phases/17-delivery/09-scheduled-runs/outputs/scheduled_delivery_workflow.py \
  --write-example /tmp/scheduled-delivery-example \
  --output-dir /tmp/scheduled-delivery-package
```

В результате появится package:

```text
scheduled-delivery-package/
├── schedule_contract.json
├── schedule_workflow.yml
├── run_history.csv
├── schedule_run_report.json
├── schedule_freshness_report.json
├── last_success_marker.json
├── failure_notification_mock.json
├── scheduled_publish_manifest.json
├── reports/
│   └── latest_cli_run_report.json
└── published-delivery/
    ├── cli_run_report.json
    ├── cli_publish_manifest.json
    ├── freshness_report.json
    └── ...
```

Проверка без публикации delivery package:

```bash
uv run --locked python phases/17-delivery/09-scheduled-runs/outputs/scheduled_delivery_workflow.py \
  --write-example /tmp/scheduled-delivery-example \
  --output-dir /tmp/scheduled-delivery-check \
  --check
```

Stale attempt:

```bash
uv run --locked python phases/17-delivery/09-scheduled-runs/outputs/scheduled_delivery_workflow.py \
  --write-example /tmp/scheduled-delivery-example \
  --output-dir /tmp/scheduled-delivery-stale \
  --checked-at 2026-01-05T08:30:00Z
```

Команда вернет `freshness_warning`, запишет `run_history.csv`, `schedule_freshness_report.json` и `failure_notification_mock.json`, но не обновит `last_success_marker.json`.

## Сломайте это

Проверьте failure modes.

1. Поставьте `timezone = "Europe/Moscow"` в `schedule_contract.json`. Contract должен блокировать запуск: cron интерпретируется в UTC.
2. Используйте cron `*/1 * * * *`. GitHub Actions schedule не должен обещать интервал меньше 5 минут.
3. Используйте `0 6 * * 1`. Contract подсветит top-of-hour risk, потому что такие запуски чаще попадают в пиковую нагрузку.
4. Уберите `workflow_dispatch`. У владельца пропадет ручной recovery path.
5. Испортите upstream `app_audit.json`. Schedule должен сохранить previous published output и не обновить last-success marker.
6. Запустите stale-only attempt без `--allow-freshness-warning`. Он должен уведомить владельца и не публиковать package.
7. Запустите stale-only attempt с `--allow-freshness-warning`. Published output может появиться, но last-success marker все равно не обновляется.
8. Измените source input во время scheduled run. Тест должен поймать мутацию source tree.

## Проверьте это

Тесты урока проверяют:

- happy path пишет schedule contract, workflow YAML, run history, freshness report, last-success marker, notification mock, manifest и published delivery package;
- contract объявляет owner, UTC cron, GitHub Actions caveats, history, marker и notification policy;
- generated workflow содержит `schedule`, `workflow_dispatch` и явный вызов CLI с input/output/report paths;
- run history фиксирует status, exit code, freshness state и paths к CLI report/manifest;
- last-success marker обновляется только fresh success, а failed/stale attempts пишутся в history;
- stale run без opt-in уведомляет владельца и не публикует output;
- data-quality block сохраняет предыдущий published package;
- invalid schedule contract блокирует запуск до CLI;
- manifest хеширует inputs и generated outputs;
- source input tree не мутируется scheduled workflow;
- учебный `code/main.py` запускает success и stale сценарии.

Запуск:

```bash
uv run --locked python -m unittest discover -s phases/17-delivery/09-scheduled-runs/tests -v
```

## Поставьте результат

Именованный артефакт: `outputs/scheduled_delivery_workflow.py`.

Для реального package из `17/08`:

```bash
uv run --locked python phases/17-delivery/09-scheduled-runs/outputs/scheduled_delivery_workflow.py \
  --app-dir ./cache-state-app \
  --cache-state-contract ./cache_state_contract.json \
  --freshness-policy ./freshness_policy.json \
  --cli-contract ./delivery_cli_contract.json \
  --schedule-contract ./schedule_contract.json \
  --output-dir ./scheduled-delivery-package
```

Передавайте дальше не только `schedule_workflow.yml`, но и `run_history.csv`, `last_success_marker.json`, `schedule_freshness_report.json` и `failure_notification_mock.json`. Они объясняют, что произошло после запуска.

## Упражнения

1. Добавьте поле `missed_run_policy`, которое отличает delayed run от completely missed run.
2. Расширьте `run_history.csv` колонкой `previous_manifest_sha256` и проверьте chain history.
3. Добавьте два owner-а с разными каналами уведомлений: бизнес-владелец для stale warnings, инженерный владелец для system errors.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Schedule contract | Одна cron-строка | Машиночитаемый договор: когда, в каком timezone, кто owner, какие outputs и как видны failures |
| Run history | Лог stdout | Табличный ledger attempts со статусами, exit codes, freshness state и ссылками на reports |
| Last-success marker | Последний запуск scheduler-а | Последний свежий успешный publish, который можно использовать для оценки отставания |
| Freshness report | Проверка "файл существует" | Отчет о возрасте данных, last success, next expected run и caveats scheduler-а |
| Notification mock | Production alerting | Проверяемый учебный artifact: кому, почему и с каким next action сообщить о failure |
| Workflow dispatch | Ручной запуск "на всякий случай" | Recovery path, когда scheduled run задержался, был пропущен или input починили после failure |

## Дополнительное чтение

- [GitHub Actions: events that trigger workflows, `schedule`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) - ограничения scheduled workflows: UTC, default branch, minimum interval, возможные задержки и manual recovery через `workflow_dispatch`.
- [GitHub Actions workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax-for-github-actions) - структура `on`, `jobs`, `steps`, permissions и concurrency для воспроизводимого workflow file.
- [Python `datetime`](https://docs.python.org/3/library/datetime.html) - разбор timezone-aware timestamps и расчет возраста last-success/freshness windows.
- [Python `csv`](https://docs.python.org/3/library/csv.html) - запись переносимого `run_history.csv`, который читается без pandas и внешних зависимостей.
