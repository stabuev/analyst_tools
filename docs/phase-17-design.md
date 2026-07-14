# Проект фазы 17: Доставка аналитического результата

Канонический порядок, статусы, длительность и результаты уроков находятся в
[`../curriculum.json`](../curriculum.json). Этот документ фиксирует границы delivery-фазы,
единую задачу, роли инструментов и контракт итогового `stakeholder-delivery-package`.

## Результат фазы

Студент берет проверенный аналитический результат из любого маршрута и превращает его в
форму, которой действительно пользуется заказчик: короткая записка, workbook, отчет,
интерактивное приложение, повторяемый CLI-запуск, расписание обновлений и понятный handoff.
Фаза учит не "сделать красивую презентацию", а поставить результат как маленький продукт
с контрактом входных данных, проверками свежести, ограничениями, инструкцией перезапуска и
границами сопровождения.

Фаза держит раздельно семь слоев:

1. **Decision narrative:** что должен решить заказчик, какие варианты доступны и какая
   рекомендация следует из evidence.
2. **Format contract:** memo, XLSX, HTML/PDF/DOCX, interactive report, app, CLI или API
   выбираются по потребителю, а не по вкусу автора.
3. **Reproducibility:** каждый файл собирается из входного evidence package одной
   командой, с manifest, checksums и environment notes.
4. **Stakeholder ergonomics:** таблицы, фильтры, графики и приложение помогают принять
   решение без чтения исходного notebook.
5. **Freshness and state:** кеш, session state, расписание и stale-data warnings не дают
   пользователю принять решение по старым данным.
6. **Optional interfaces:** FastAPI и Docker показывают границу между аналитической
   поставкой и backend/DevOps, оставаясь факультативными.
7. **Support handoff:** итоговый пакет содержит owner, rerun instructions, known
   limitations, escalation path and retirement policy.

Фаза состоит из пяти блоков:

1. `17/01`-`17/02`: decision memo и workbook для табличной поставки.
2. `17/03`-`17/04`: reproducible Quarto report и multi-format delivery.
3. `17/05`-`17/07`: Plotly appendix, Streamlit app, caching/state/freshness.
4. `17/08`-`17/09`: CLI entrypoint и scheduled refresh workflow.
5. `17/10`-`17/12`: факультативные FastAPI/Docker interfaces и финальный handoff package.

Суммарная длительность - 960 минут, или 16 часов.

## Границы содержания

- **Не повтор анализа.** Статистика, эксперименты, causal, forecasting, AE и ML уже
  поставляют verified evidence. Здесь проверяется, что этот evidence честно доставлен
  потребителю без расширения claim.
- **Не BI-платформа.** DataLens/Tableau/Power BI не входят в обязательную фазу: курс
  фокусируется на portable artifacts в репозитории. Dashboard delivery может быть
  факультативом после курса.
- **Не frontend-курс.** Streamlit используется как быстрый аналитический интерфейс с
  ограниченным состоянием, а не как полноценное web-приложение.
- **Не backend-курс.** FastAPI нужен только для маленького read-only интерфейса к
  проверенному результату или скорингу. Auth, queues, distributed serving, observability
  платформы и SLA остаются вне фазы.
- **Не DevOps-курс.** Docker показывает reproducible packaging boundary. Kubernetes,
  registry governance, cloud deployment, secrets platform and infra-as-code не входят в
  обязательный маршрут.
- **Не презентационная полировка.** Визуальный стиль важен, но уроки оценивают decision
  clarity, traceability, freshness, reproducibility и supportability.
- **Не production ML monitoring.** Drift/stability уже были в фазе 16. Здесь проверяется
  delivery freshness и stale output, а не строится online monitoring platform.
- **Не секреты в артефактах.** Любые tokens, персональные данные и чувствительные поля
  должны быть исключены из workbook, report, app state, API responses, Docker context and
  logs.

## Роли инструментов

Новые зависимости не добавляются на этапе проектирования. Уже доступные `pandas`,
`openpyxl`, `plotly`, `pydantic`, `pytest` и стандартная библиотека закрывают часть
delivery contract. `XlsxWriter`, `streamlit`, `fastapi`/`uvicorn` и внешние инструменты
Quarto/Docker добавляются только в конкретных уроках, где нужен реальный API.

| Инструмент | Задача в фазе | Что сознательно не покрывается |
|---|---|---|
| Markdown / pathlib / json / hashlib | Decision memo, manifests, checksums, rerun instructions | CMS и knowledge base workflow |
| pandas / openpyxl / XlsxWriter | XLSX workbook, formatted tables, validation sheets, workbook audit | Excel как ручная аналитическая среда |
| Quarto | Executable report with Python, HTML/PDF/DOCX outputs, embedded resources | Полная publishing platform и сложные templates |
| Plotly | Interactive figure bundle, hover/filter decisions, HTML appendix | Dash как отдельный web-framework |
| Streamlit | Stakeholder app, filters, tables, charts, download actions | Frontend architecture, auth, multi-user backend |
| `st.cache_data` / `st.cache_resource` / session state | Freshness, rerun cost, model/resource reuse, per-session selections | Distributed cache and persistent user storage |
| argparse | Reproducible CLI entrypoint with explicit inputs/outputs | Full command framework или shell automation course |
| GitHub Actions schedule / cron semantics | Scheduled refresh contract, freshness report, failure notification mock | Production scheduler, Airflow, cloud orchestration |
| FastAPI / Pydantic | Optional read-only endpoint with request/response schemas and OpenAPI docs | Auth, async infra, model serving platform |
| Docker | Optional local container image with minimal context and no secrets | Kubernetes, registry, cloud deploy |
| pytest | Behavioral checks for generated files, freshness, links, schemas and handoff | Load testing and browser automation suite |

Проверенные 6 июля 2026 года официальные ориентиры:

- [XlsxWriter documentation](https://xlsxwriter.readthedocs.io/) - создание XLSX,
  formatting, charts, validation, conditional formatting, tables, images and memory mode.
- [Quarto with Python](https://quarto.org/docs/computations/python.html) - executable
  Python blocks inside Markdown and `quarto render` to HTML/PDF/DOCX.
- [Quarto HTML basics](https://quarto.org/docs/output-formats/html-basics.html),
  [PDF basics](https://quarto.org/docs/output-formats/pdf-basics.html) and
  [Word basics](https://quarto.org/docs/output-formats/ms-word.html) - output formats,
  embedded resources, PDF prerequisites and DOCX options.
- [Plotly Python](https://plotly.com/python/) - interactive publication-quality graphs and
  figure reference.
- [Streamlit API reference](https://docs.streamlit.io/develop/api-reference),
  [caching](https://docs.streamlit.io/develop/concepts/architecture/caching) and
  [session state](https://docs.streamlit.io/develop/concepts/architecture/session-state) -
  display API, rerun model, cache decorators and per-session state.
- [Python argparse](https://docs.python.org/3/library/argparse.html) - standard-library
  command-line parser with generated help and invalid-argument errors.
- [GitHub Actions scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) -
  `schedule` event, cron syntax, UTC/default-branch constraints and minimum interval.
- [FastAPI](https://fastapi.tiangolo.com/) - Pydantic/OpenAPI based API with automatic
  interactive documentation.
- [Docker containers](https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-a-container/) -
  containers as isolated, portable, self-contained processes.

## Единая задача и данные

Фаза использует общий вымышленный подписочный сервис, но не привязана только к ML. Входом
является один из upstream evidence packages:

- product/experiment decision package из фаз 08-10;
- analytics engineering mart package из фаз 11-12;
- causal или forecast package из фаз 13-14;
- `ml-baseline-package` или `tabular-ml-interpretation-package` из фаз 15-16.

Учебная delivery-задача: "подготовить регулярный пакет для руководителя поддержки и
продукта: кого удерживать на этой неделе, почему, с каким бюджетом, какими рисками и как
перезапустить расчет".

Общий входной contract:

| Поле | Смысл |
|---|---|
| `package_id` | Стабильный идентификатор upstream evidence package |
| `decision_id` | Бизнес-решение, для которого поставляется результат |
| `audience` | Основной потребитель: executive, analyst, support lead, engineer |
| `decision_options` | Допустимые действия, включая no-action |
| `primary_recommendation` | Рекомендация, ограниченная evidence |
| `metric_tables` | Табличные outputs с grain, keys and freshness |
| `figures` | Static or interactive figure specs |
| `methodology` | Короткое описание метода, assumptions and limitations |
| `quality_gates` | Статусы проверок, warnings and blockers |
| `rerun_command` | Команда воспроизводимого запуска |
| `freshness_policy` | Как понять, что результат устарел |
| `confidentiality_policy` | Что можно показывать в артефактах |

Профили:

- `tiny`: десятки строк для ручной проверки memo logic, workbook formulas, Quarto output,
  Plotly figure spec, Streamlit filters, CLI manifest and freshness warnings.
- `sample`: детерминированная локальная генерация сотен/тысяч rows для workbook size,
  app responsiveness, scheduled refresh and optional API responses.
- Дефектные fixtures: missing methodology, stale input, mismatched workbook totals, broken
  report links, hidden PII column, non-deterministic output timestamp, stale Streamlit
  cache, session-state leakage between filters, schedule run without freshness manifest,
  API response outside schema, Docker context with forbidden secret file.

## Контракт delivery spec

Каждый урок опирается на machine-readable spec:

```text
delivery_id
upstream_package_id
audience
decision_owner
decision_needed_by
decision_options
recommendation_policy
claim_boundary
input_artifacts
metric_grain
quality_gate_policy
confidentiality_policy
format_targets
workbook_policy
report_policy
interactive_policy
app_policy
cache_policy
state_policy
cli_policy
schedule_policy
api_policy
container_policy
handoff_policy
freshness_policy
support_policy
retirement_policy
rerun_instructions
known_limitations
```

Spec запрещает "просто отправить notebook". Любой delivery artifact должен отвечать:
кто потребитель, какое решение, какие данные, насколько свежо, как пересобрать, что
нельзя утверждать и куда идти при поломке.

## Контракт отдельных методов

### Analytical memo

- Memo начинается с решения и рекомендации, а не с истории вычислений.
- Каждый claim ссылается на evidence artifact and quality gate.
- Limitations and non-actions идут рядом с рекомендацией, а не в приложении мелким
  шрифтом.
- Executive summary не должен расширять causal/ML/forecast claim шире upstream package.

### XLSX workbook

- Workbook имеет явные листы: summary, data dictionary, tables, checks, methodology.
- Формулы и totals сверяются с source CSV/Parquet before shipping.
- Formatting помогает scanning: frozen panes, filters, number formats, comments and
  validation lists.
- Hidden sheets, manual edits and stale exported values должны быть обнаружены audit.

### Quarto and document formats

- Report пересобирается командой из clean inputs and locked environment.
- HTML может быть self-contained when stakeholder needs file transfer.
- PDF/DOCX formats проверяются как отдельные targets, потому что layout and references
  break differently.
- Rendering failure blocks delivery, not silently falls back to stale output.

### Plotly interactive appendix

- Interactive figure отвечает на конкретный decision question and preserves grain.
- Hover, filters and facets показывают enough context without exposing sensitive rows.
- Static fallback or data table существует для потребителей без JavaScript.
- Figure JSON/HTML сохраняется with checksum and source table references.

### Streamlit app

- App starts from precomputed verified artifacts, not hidden ad-hoc recomputation.
- Filters, download buttons and decision views map to audience tasks.
- Empty states, stale inputs and quality blockers are visible.
- App does not persist secrets or sensitive user choices in exported artifacts.

### Caching and state

- Expensive pure data computations use data cache with TTL/freshness policy.
- Resources such as model or connection are separated from serializable data cache.
- Session state is per-user interaction state, not a substitute for durable storage.
- Cache invalidation has tests for changed input checksum and stale timestamps.

### CLI

- CLI accepts explicit input/output paths and writes a manifest.
- `--check`, `--dry-run` or equivalent mode validates inputs without publishing.
- Exit codes distinguish success, data quality block, freshness warning and system error.
- Help text is part of the support contract.

### Scheduled runs

- Schedule definition includes timezone/UTC interpretation, expected cadence and owner.
- Each run writes freshness report, manifest and last-success marker.
- Missing input, failed quality gate or unchanged stale output is visible to the owner.
- Schedule does not mutate source truth or publish partial outputs.

### FastAPI optional interface

- API is read-only for shipped results or deterministic scoring demo.
- Request/response schemas are typed with Pydantic and documented via OpenAPI.
- Invalid inputs return clear validation errors.
- API never becomes the only delivery path: report/workbook/CLI remain reproducible.

### Docker optional package

- Dockerfile pins runtime expectations and uses minimal build context.
- `.dockerignore` excludes data dumps, secrets, caches and local credentials.
- Container run command produces the same manifest as local CLI.
- Image build is a reproducibility exercise, not a cloud deployment claim.

### Handoff and support

- Final package names owner, backup owner, rerun command, cadence, known limitations and
  escalation path.
- Changelog explains what changed since previous delivery.
- Support policy includes "when to retire this artifact".
- The decision status is explicit: `ship_now`, `ship_with_warnings`,
  `blocked_by_quality_gate`, `needs_methodology_review`, `stale_input`, `owner_handoff_only`.

## Интеграционный мини-проект

`17/12` собирает поставку:

```text
stakeholder-delivery-package/
├── input/
│   ├── upstream-package-manifest.json
│   ├── delivery-spec.json
│   ├── evidence-index.csv
│   └── quality-gate-summary.json
├── memo/
│   ├── executive-memo.md
│   └── claim-evidence-matrix.csv
├── workbook/
│   ├── stakeholder-workbook.xlsx
│   └── workbook-audit.json
├── report/
│   ├── report.qmd
│   ├── report.html
│   ├── report.pdf
│   ├── report.docx
│   └── render-report.json
├── interactive/
│   ├── plotly-figures.json
│   ├── interactive-appendix.html
│   └── static-fallbacks/
├── app/
│   ├── streamlit_app.py
│   ├── app-state-contract.json
│   └── freshness-panel.json
├── automation/
│   ├── delivery_cli.py
│   ├── schedule.yml
│   ├── run-history.csv
│   └── freshness-report.json
├── optional-api/
│   ├── api.py
│   ├── openapi-schema.json
│   └── api-contract-tests.json
├── optional-container/
│   ├── Dockerfile
│   ├── dockerignore-audit.json
│   └── container-run-report.json
├── handoff/
│   ├── runbook.md
│   ├── support-policy.md
│   ├── changelog.md
│   └── stakeholder-email.md
└── manifest.json
```

Пакет обязан:

- ссылаться на upstream evidence package and checksum manifest;
- сохранять claim boundaries, limitations and quality gates;
- выпускать at least two consumer formats: memo/workbook/report and one interactive view;
- иметь CLI rerun path and freshness report;
- показывать cache/state policy for any app surface;
- включать optional API/Docker only when their contracts pass, without making them
  mandatory for non-ML routes;
- проверять absence of secrets/sensitive columns in public artifacts;
- фиксировать decision status одним из разрешенных значений;
- выпускать SHA-256 manifest всех входных и generated файлов.

## Проверяемость

- Memo tests проверяют claim-evidence links, limitations, decision options and no
  overclaim relative to upstream package.
- Workbook tests сверяют totals, sheet inventory, formulas, hidden/manual sheets,
  data dictionary and freshness markers.
- Quarto tests проверяют executable render, changed-input rebuild, broken links,
  missing figures and format-specific outputs.
- Plotly tests проверяют figure schema, source table references, sensitive-field redaction
  and static fallback.
- Streamlit tests проверяют app contract, filter behavior, empty states, stale warnings
  and download artifacts.
- Cache/state tests проверяют input checksum invalidation, TTL policy, resource/data
  separation and no cross-session leakage in persisted outputs.
- CLI tests проверяют arguments, help, manifest, exit codes, `--check` mode and atomic
  publish behavior.
- Schedule tests проверяют cron metadata, default-branch/UTC assumptions, run history,
  last-success marker and failure visibility.
- FastAPI tests проверяют OpenAPI schema, Pydantic validation, read-only behavior and
  reproducible CLI fallback.
- Docker tests проверяют build context audit, `.dockerignore`, no-secret policy and
  manifest equivalence with local CLI.
- Final package tests проверяют tree structure, checksums, handoff docs, owner/support
  policy, decision status and rerun instructions.
