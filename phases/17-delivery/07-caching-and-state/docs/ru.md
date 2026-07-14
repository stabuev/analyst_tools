# Кеширование, состояние и свежесть приложения

> Кеш полезен только тогда, когда пользователь понимает, насколько свежий результат он видит и что именно сбросит старое состояние.

**Тип:** Case
**Треки:** Delivery
**Пререквизиты:** `17-delivery/06-streamlit`
**Время:** ~75 минут
**Результат:** вы добавляете к Streamlit stakeholder app проверяемый cache/state/freshness слой: `st.cache_data`, `st.cache_resource`, `st.session_state`, TTL policy, checksum invalidation, freshness report и stale-output gate.

## Цели обучения

- Разделять data cache, resource cache и session state по назначению и рискам.
- Делать свежесть входов частью delivery contract через tracked files, checksums, TTL и stale policy.
- Проверять, что stale inputs видны пользователю, cache можно вручную сбросить, а downloads не выглядят свежими при устаревших данных.

## Проблема

В `17/06` мы сделали Streamlit app поверх проверенных артефактов. Теперь stakeholder начал пользоваться приложением чаще: переключает фильтры, смотрит график, скачивает bundle, возвращается через час и ожидает, что UI не будет тормозить.

Наивное решение - добавить `@st.cache_data` ко всем загрузчикам и сохранить выбор фильтров в `st.session_state`. Приложение станет быстрее, но появятся новые delivery-риски:

- CSV перезаписали, путь тот же, а cache показывает старые строки;
- Plotly figure payload живет как общий ресурс, но проверяется как обычный data cache;
- stale package выглядит свежим, потому что download button активен;
- session state случайно хранит user-specific или sensitive данные;
- никто не знает, какие TTL и max entries действуют.

В delivery phase cache - это не микрооптимизация. Это контракт свежести и состояния.

## Концепция

В уроке появляется четыре файла поверх bundle из `17/06`.

| Файл | Роль |
|---|---|
| `cache_state_contract.json` | Какие cache functions разрешены, какие session keys существуют, как сбрасывается cache |
| `freshness_policy.json` | Snapshot time, checked time, TTL, max entries, tracked input files и stale gate |
| `freshness_report.json` | Текущий digest входов, возраст данных, stale reasons и per-file hashes |
| `cache_state_audit.json` | Проверки готовности cache/state/freshness слоя |

Слой приложения разделяет три механизма.

| Механизм | Для чего используется | Что нельзя делать |
|---|---|---|
| `st.cache_data` | Сериализуемые CSV/JSON загрузчики, которые зависят от path и checksum | Хранить secrets, читать сеть, скрывать recompute |
| `st.cache_resource` | Общий resource payload, например подготовленный Plotly figure spec | Мутировать общий объект без контроля и выдавать его за per-session data |
| `st.session_state` | Выбранные фильтры, active view, last input digest, manual refresh count | Хранить sensitive user fields или durable business state |

Главная идея: cache key должен зависеть не только от пути, но и от checksum входа.

```text
app_data/metric_summary.csv
  -> sha256 in freshness_report.json
  -> load_csv_cached(path, checksum)
  -> changed input changes cache key
```

## Соберите это

Сначала опишите tracked input inventory без Streamlit:

```python
import hashlib
import json
from pathlib import Path

tracked_files = ["app_contract.json", "app_data/metric_summary.csv"]

def file_row(root: Path, relative: str) -> dict:
    path = root / relative
    return {
        "path": relative,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "",
        "missing": not path.is_file(),
    }

def input_digest(root: Path) -> str:
    rows = [file_row(root, relative) for relative in tracked_files]
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

Теперь добавьте freshness rule:

```python
from datetime import datetime, timezone

def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)

def is_stale(source_snapshot_utc: str, checked_at_utc: str, max_age_seconds: int) -> bool:
    age = parse_utc(checked_at_utc) - parse_utc(source_snapshot_utc)
    return age.total_seconds() > max_age_seconds
```

И только после этого свяжите contract с generated app:

```python
@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS, max_entries=DATA_CACHE_MAX_ENTRIES)
def load_csv_cached(path_text: str, checksum: str) -> pd.DataFrame:
    return pd.read_csv(Path(path_text))

@st.cache_resource(ttl=RESOURCE_CACHE_TTL_SECONDS, max_entries=RESOURCE_CACHE_MAX_ENTRIES)
def load_figure_resource(path_text: str, checksum: str) -> dict:
    return {"payload": json.loads(Path(path_text).read_text()), "checksum": checksum}
```

Параметр `checksum` может не использоваться внутри функции. Он нужен Streamlit как часть cache key. Это нормально: его работа - инвалидация, а не чтение данных.

## Используйте это

Запустите артефакт урока:

```bash
uv run --locked python phases/17-delivery/07-caching-and-state/outputs/streamlit_cache_state_auditor.py \
  --write-example /tmp/cache-state-example \
  --output-dir /tmp/cache-state-app \
  --fail-on-invalid
```

`--write-example` сначала собирает sample Streamlit bundle из `17/06`, затем добавляет cache/state/freshness слой:

```text
cache-state-app/
├── streamlit_app.py
├── cache_state_contract.json
├── freshness_policy.json
├── freshness_report.json
├── cache_state_audit.json
├── cache_state_manifest.json
├── cache_state_runbook.md
├── app_contract.json
├── app_data/
│   ├── metric_summary.csv
│   ├── claim_evidence_matrix.csv
│   ├── plotly_figure_spec.json
│   ├── source_table_links.csv
│   ├── interaction_audit.json
│   └── interaction_manifest.json
└── downloads/
    └── stakeholder_app_bundle.zip
```

Готовый CLI возвращает:

```json
{
  "valid": true,
  "readiness_status": "ready",
  "blocking_errors": []
}
```

Сгенерированное приложение показывает freshness panel в sidebar: возраст входов, короткий digest, счетчик manual refreshes и stale warning. Кнопка `Refresh cached data` вызывает `.clear()` у data и resource loaders. Если `freshness_report.json` stale, приложение показывает ошибку и отключает download.

Локальный запуск:

```bash
cd /tmp/cache-state-app
uv run --locked streamlit run streamlit_app.py
```

## Сломайте это

Проверьте типовые failure modes.

1. Перезапишите `app_data/metric_summary.csv` после сборки. `freshness_report_matches_current_input_checksums` должен стать invalid.
2. Поставьте `checked_at_utc` на два часа позже snapshot при `max_input_age_seconds = 3600`. Package должен стать stale.
3. Удалите `load_figure_resource` из `cache_state_contract.json`. Contract больше не разделяет data cache и resource cache.
4. Замените decorator у resource loader на `st.cache_data`. Это выглядит похоже, но меняет семантику общего ресурса.
5. Удалите `manual_refresh_count` из session keys. UI потеряет проверяемый marker ручного сброса.
6. Добавьте session key `user_email`. Даже если значение не записывается, contract допускает чувствительное состояние.
7. Уберите `load_csv_cached.clear()` из app source. Кнопка refresh больше не сбрасывает все data loaders.
8. Уберите checksum из вызова `load_csv_cached`. Path останется тем же, и кеш может пережить изменение файла.
9. Добавьте `persist="disk"` или `st.secrets`. Для этого delivery package запрещены disk-persisted cache и secrets.
10. Сделайте upstream `app_audit.json` invalid. Cache/state layer не должен "лечить" сломанное приложение.

## Проверьте это

Тесты урока проверяют:

- happy path пишет enhanced app, cache/state contract, freshness policy/report, audit, manifest и runbook;
- generated app содержит `@st.cache_data`, `@st.cache_resource`, `st.session_state`, `.clear()` и stale-download marker;
- cache contract разделяет CSV/JSON data loaders, figure resource loader и per-session keys;
- freshness report пересчитывается из текущих SHA-256 tracked files;
- изменение входного CSV после сборки блокирует digest check;
- stale timestamps, нулевой TTL и TTL больше freshness window блокируют policy;
- missing/wrong resource cache, missing/sensitive session key и отсутствие checksum invalidation блокируют delivery;
- forbidden runtime patterns вроде secrets, network, SQL recompute и disk-persisted cache запрещены;
- CLI возвращает exit code `2` при `--fail-on-invalid`.

Запуск:

```bash
uv run --locked python -m unittest discover -s phases/17-delivery/07-caching-and-state/tests -v
```

## Поставьте результат

Именованный артефакт: `outputs/streamlit_cache_state_auditor.py`.

Для реального Streamlit app bundle из `17/06`:

```bash
uv run --locked python phases/17-delivery/07-caching-and-state/outputs/streamlit_cache_state_auditor.py \
  --app-dir /path/to/streamlit-app \
  --cache-state-contract /path/to/cache_state_contract.json \
  --freshness-policy /path/to/freshness_policy.json \
  --output-dir /path/to/cache-state-app \
  --fail-on-invalid
```

Передавайте дальше весь `cache-state-app/`, а не только `streamlit_app.py`. Freshness policy, report, manifest и audit являются частью delivery artifact.

## Упражнения

1. Добавьте tracked file `app_data/source_table_links.csv` в отдельный freshness group с более строгим TTL и расширьте audit.
2. Добавьте в `freshness_report.json` поле `last_success_utc`, не смешивая его с `checked_at_utc`.
3. Сделайте warning, если `manual_refresh_count` слишком большой: это может быть сигналом, что пользователь пытается исправить stale package кнопкой, а не пересборкой.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Data cache | Любой быстрый cache в приложении | Cache для сериализуемых данных с TTL, max entries и checksum input |
| Resource cache | Более быстрый data cache | Cache для общего ресурса, который может жить между rerun и требует отдельной политики мутации |
| Session state | Хранилище данных приложения | Per-session UI state, не durable storage и не место для sensitive data |
| Freshness policy | Текст в README | Машиночитаемый contract для возраста входов, TTL, tracked files и stale gate |
| Checksum invalidation | Замена TTL | Дополнительный cache key, который реагирует на изменение содержимого входа |
| Stale output | Ошибка рендера | Артефакт, который может открываться, но не должен выглядеть готовым к свежему решению |

## Дополнительное чтение

- [Streamlit caching overview](https://docs.streamlit.io/develop/concepts/architecture/caching) — базовая модель `st.cache_data` и `st.cache_resource`, rerun cost и типичные ошибки кеширования.
- [Streamlit `st.cache_data`](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data) — параметры `ttl`, `max_entries`, hashing и очистка data cache.
- [Streamlit `st.cache_resource`](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_resource) — когда кешировать общий resource и зачем нужна `validate`.
- [Streamlit Session State](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state) — per-session storage, widget keys и callbacks; читайте с вопросом "что нельзя хранить".
- [Streamlit architecture: Session State](https://docs.streamlit.io/develop/concepts/architecture/session-state) — концептуальная модель state между rerun и границы применения в multi-user app.
