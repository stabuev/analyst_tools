# Приложение на Streamlit

> Хорошее аналитическое приложение не прячет новый расчет за красивым UI, а делает проверенные артефакты удобными для решения.

**Тип:** Build
**Треки:** Delivery
**Пререквизиты:** `17-delivery/05-interactive-plotly`
**Время:** ~90 минут
**Результат:** вы собираете Streamlit stakeholder app поверх проверенного Plotly appendix и проверяете app contract, filters, decision views, upstream warnings, download actions, redaction и отсутствие скрытого ad-hoc пересчета.

## Цели обучения

- Проектировать Streamlit app как delivery shell поверх precomputed artifacts.
- Разделять app contract, app data, generated `streamlit_app.py`, download bundle и app audit.
- Проверять filters/default state, upstream blockers, lineage hashes, public downloads и sensitive-field redaction.

## Проблема

После интерактивного Plotly appendix из `17/05` stakeholder просит не просто HTML-файл, а маленькое приложение:

- слева выбрать статусы метрик;
- быстро переключаться между summary, chart, evidence и downloads;
- видеть warning, если upstream appendix был собран с проблемами;
- скачать проверенный bundle для обсуждения;
- не получать сырой `user_email`, `token` или внутренние source paths в публичных данных.

Самый опасный наивный ответ - написать Streamlit app, который внутри заново читает source tables, пересчитывает метрики и строит график. UI будет выглядеть лучше, но delivery contract станет хуже: появится новая версия результата без manifest, без upstream audit и без понятной границы ответственности.

В этом уроке Streamlit используется иначе. Приложение читает только проверенные артефакты:

```text
17/05 Plotly appendix -> app_data/ -> streamlit_app.py -> download bundle
```

Если upstream bundle сломан, приложение не должно "спасать" его красивой оболочкой. Оно должно заблокировать delivery.

## Концепция

Streamlit app состоит из пяти слоев.

| Слой | Роль |
|---|---|
| `app_contract.json` | Фиксирует views, filters, downloads, quality gate, input policy и confidentiality policy |
| `app_data/` | Публичные precomputed CSV/JSON/SVG, которые можно показывать и скачивать |
| `streamlit_app.py` | UI shell: sidebar filters, decision views, chart, tables, warning/error states и download button |
| `download_manifest.json` + zip | Проверяемый download action с именами файлов, SHA-256 и размерами |
| `app_audit.json` + `app_manifest.json` | Готовность приложения и checksums inputs/outputs |

Ключевая граница: `streamlit_app.py` не ходит в сеть, не читает secrets, не делает SQL и не использует cache. Кеширование и freshness появятся в следующем уроке, а здесь важно зафиксировать чистую delivery boundary.

## Соберите это

Сначала опишите contract вручную:

```python
contract = {
    "required_views": ["decision_summary", "guardrail_explorer", "evidence_table", "downloads"],
    "status_filters": ["all", "ok", "watch", "breached"],
    "default_status_filter": ["breached", "watch"],
    "quality_gate_policy": {
        "block_on_invalid_upstream": True,
        "show_warnings": True,
        "empty_state_required": True,
    },
    "input_policy": {
        "precomputed_only": True,
        "forbid_ad_hoc_recompute": True,
    },
}
```

Теперь сделайте минимальную проверку фильтров:

```python
def build_filters_audit(metrics: list[dict[str, str]], contract: dict) -> dict:
    statuses = sorted({row["status"] for row in metrics if row.get("status")})
    allowed = contract["status_filters"]
    default = contract["default_status_filter"]
    missing = sorted(set(statuses) - set(allowed))
    invalid_default = sorted(set(default) - set(allowed))
    default_rows = sum(1 for row in metrics if row["status"] in default)
    return {
        "valid": not missing and not invalid_default and default_rows > 0,
        "status_values": statuses,
        "missing_status_filters": missing,
        "invalid_default_filter_values": invalid_default,
        "default_result_rows": default_rows,
    }
```

И отдельно проверьте redaction:

```python
import re

sensitive_field = re.compile(r"(email|phone|token|secret|password|user_id)", re.I)

def public_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    hidden = {column for row in rows for column in row if sensitive_field.search(column)}
    return [{column: value for column, value in row.items() if column not in hidden} for row in rows]
```

Так вы строите не "приложение ради приложения", а проверяемый wrapper: данные приходят из upstream appendix, чувствительные поля удаляются до `app_data`, а UI только показывает и скачивает готовое.

## Используйте это

Запустите артефакт урока:

```bash
uv run --locked python phases/17-delivery/06-streamlit/outputs/streamlit_stakeholder_app.py \
  --write-example /tmp/streamlit-example \
  --output-dir /tmp/streamlit-app \
  --fail-on-invalid
```

`--write-example` сначала собирает sample Plotly appendix из `17/05`, затем пишет Streamlit bundle:

```text
streamlit-app/
├── streamlit_app.py
├── app_contract.json
├── app_data/
│   ├── metric_summary.csv
│   ├── claim_evidence_matrix.csv
│   ├── plotly_figure_spec.json
│   ├── source_table_links.csv
│   ├── interaction_audit.json
│   ├── interaction_manifest.json
│   └── static-fallbacks/
│       └── metric_status.svg
├── filters_audit.json
├── download_manifest.json
├── downloads/
│   └── stakeholder_app_bundle.zip
├── app_audit.json
├── app_manifest.json
└── app_runbook.md
```

Сгенерированный `streamlit_app.py` использует обычные Streamlit primitives:

- `st.set_page_config` для страницы;
- `st.sidebar.multiselect` для status filters;
- `st.sidebar.radio` для decision views;
- `st.plotly_chart` для Plotly figure spec;
- `st.dataframe` для metrics, evidence и source links;
- `st.warning`, `st.error`, `st.stop` для quality states;
- `st.download_button` для checked zip bundle.

Локальный запуск приложения:

```bash
cd /tmp/streamlit-app
uv run --locked streamlit run streamlit_app.py
```

Если app audit готов, CLI вернет:

```json
{
  "valid": true,
  "readiness_status": "ready",
  "blocking_errors": []
}
```

## Сломайте это

Проверьте failure modes, которые в реальной работе часто пропускают.

1. Сделайте upstream `interaction_audit.json` invalid. App audit должен заблокировать delivery, а UI должен иметь `st.error` и `st.stop`.
2. Удалите view `downloads` из `app_contract.json`. Download action является частью stakeholder task, поэтому contract invalid.
3. Удалите `breached` из `status_filters`. Даже если sample data маленький, приложение больше не покрывает все возможные статусные состояния.
4. Поставьте `default_status_filter = ["archived"]`. Дефолтный экран станет пустым или неверным, filters audit должен заблокировать bundle.
5. Измените source table после сборки Plotly appendix. Hash из `source_table_links.csv` больше не совпадет, значит Streamlit app не имеет права молча читать изменившуюся таблицу.
6. Добавьте `requests.get(...)`, `st.secrets[...]` или `@st.cache_data` в generated app. Для 17/06 это forbidden runtime pattern: сеть, secrets и cache появятся только когда будут явно описаны freshness rules.
7. Добавьте `user_email` в source metric table. App data и zip не должны содержать ни значения, ни имя колонки. Даже публичная копия upstream audit должна хранить только счетчик redacted fields.

## Проверьте это

Тесты урока проверяют:

- happy path пишет app source, contract, app data, audits, manifests, runbook и download bundle;
- generated `streamlit_app.py` содержит обязательные API-маркеры и компилируется;
- app source не использует SQL/network/secrets/cache;
- filters audit покрывает source statuses и непустой default state;
- zip совпадает с `download_manifest.json`;
- sanitized source links не раскрывают временные пути и несут source hashes;
- invalid upstream audit, missing appendix file, stale source hash, missing views/downloads и неверные filters блокируют delivery;
- sensitive source columns редактируются из app data, zip и публичного upstream audit;
- CLI возвращает exit code `2` при `--fail-on-invalid`;
- manifest содержит Streamlit version, renderer boundary и hashes.

Запуск:

```bash
uv run --locked python -m unittest discover -s phases/17-delivery/06-streamlit/tests -v
```

## Поставьте результат

Именованный артефакт: `outputs/streamlit_stakeholder_app.py`.

Для реального Plotly appendix:

```bash
uv run --locked python phases/17-delivery/06-streamlit/outputs/streamlit_stakeholder_app.py \
  --interactive-dir /path/to/interactive-appendix \
  --app-contract /path/to/app_contract.json \
  --output-dir /path/to/streamlit-app \
  --fail-on-invalid
```

Передавайте дальше весь `streamlit-app/`, а не только `streamlit_app.py`. Сам файл приложения без `app_data`, contract, audits, manifests и zip не является delivery artifact.

## Упражнения

1. Добавьте view `owner_review`, который показывает только метрики конкретного owner, и расширьте app contract.
2. Добавьте warning, если `download_manifest.json` содержит файл больше заданного лимита.
3. Сделайте отдельный public audit sanitizer для `interaction_manifest.json`, если в будущем upstream manifest начнет хранить чувствительные имена колонок.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Streamlit delivery shell | Приложение, которое само считает аналитику | UI поверх precomputed artifacts, contract, audits и manifests |
| App contract | README для пользователя | Машиночитаемое описание обязательных views, filters, downloads и quality policies |
| Quality gate | Текст warning в интерфейсе | Проверка, которая может заблокировать app delivery до решения stakeholder |
| Download action | Кнопка для удобства | Проверяемая часть delivery contract с manifest, hashes и public-only contents |
| Public audit | Полная копия внутреннего audit | Санитизированная копия, сохраняющая проверочный смысл без раскрытия sensitive field names |

## Дополнительное чтение

- [Streamlit API reference](https://docs.streamlit.io/develop/api-reference) — карта основных primitives, которые используются в generated `streamlit_app.py`.
- [Streamlit Session State](https://docs.streamlit.io/develop/concepts/architecture/session-state) — прочитайте как подготовку к следующему уроку про state, cache и freshness, но не используйте state для скрытого пересчета в 17/06.
- [Streamlit `st.plotly_chart`](https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart) — параметры отображения Plotly figure в приложении и ограничения interactive chart handoff.
- [Streamlit `st.download_button`](https://docs.streamlit.io/develop/api-reference/widgets/st.download_button) — как устроена download action и почему файл должен быть подготовлен и проверен заранее.
