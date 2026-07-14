# FastAPI как факультативный интерфейс

> API полезен только тогда, когда он показывает уже поставленный результат, а не становится единственным способом его получить.

**Тип:** Build
**Треки:** Delivery
**Пререквизиты:** `17-delivery/09-scheduled-runs`
**Время:** ~75 минут
**Результат:** вы добавляете read-only FastAPI endpoint поверх scheduled delivery package: Pydantic response models, OpenAPI schema, contract tests, validation errors и CLI fallback.

## Цели обучения

- Разделять shipped delivery package и optional HTTP-интерфейс к нему.
- Описывать response schemas через Pydantic models и проверять, что они попали в OpenAPI.
- Блокировать mutating routes, скрытые пересчеты, missing run history и server-only delivery.

## Проблема

После scheduled refresh из `17/09` появляется новый запрос: "Можно отдать результат через API, чтобы другой сервис забирал статус и историю запусков?". Это разумно, если API — тонкий read-only слой поверх поставленного package.

Опасность в другом: маленький endpoint быстро превращается в незаметный backend. В него добавляют `POST /refresh`, чтение секретов, сетевые запросы, запись freshness marker и ручную бизнес-логику. Тогда заказчик уже не может воспроизвести результат через report/workbook/CLI, а failure visibility из schedule исчезает за HTTP 200.

В этом уроке API получает жесткую границу:

- читает только файлы `scheduled-package/`;
- публикует только `GET` маршруты;
- описывает ответы через Pydantic models;
- отдает OpenAPI schema как контракт;
- возвращает понятные `404` и `422`;
- сохраняет CLI fallback как основной delivery path.

## Концепция

FastAPI package в уроке состоит из семи файлов.

| Файл | Роль |
|---|---|
| `api.py` | Read-only FastAPI app с `GET /health`, `/summary`, `/runs`, `/runs/{run_id}`, `/artifacts/manifest` |
| `api_data/` | Копия shipped schedule artifacts: run report, freshness, history, marker и manifests |
| `api_contract.json` | Машиночитаемая граница: allowed methods, response models, validation и fallback |
| `openapi_schema.json` | Сгенерированный FastAPI/OpenAPI contract |
| `api_contract_tests.json` | Явные ожидания для schema, runtime validation, read-only boundary и fallback |
| `api_audit.json` | Проверки upstream package, source markers, OpenAPI, runtime endpoints и no-mutation policy |
| `cli_fallback.md` | Команда, которая воспроизводит поставку без API |

Граница данных:

```text
scheduled delivery package
  -> copied api_data files
  -> FastAPI GET endpoints
  -> OpenAPI + contract tests + audit
```

API не запускает аналитику, не обновляет source truth и не заменяет schedule. Он просто делает уже поставленный результат удобным для чтения.

## Соберите это

Начните с минимального contract.

```python
contract = {
    "api_id": "trial-onboarding-delivery-read-only-api",
    "read_only_boundary": {
        "allowed_methods": ["GET"],
        "forbidden_methods": ["POST", "PUT", "PATCH", "DELETE"],
        "no_source_mutation": True,
        "no_background_jobs": True,
        "no_network_calls": True,
        "cli_fallback_required": True,
    },
    "routes": [
        {"path": "/health", "method": "GET", "response_model": "HealthResponse"},
        {"path": "/runs/{run_id}", "method": "GET", "response_model": "RunHistoryRow", "not_found_status": 404},
    ],
}
```

Минимальная модель ответа:

```python
from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(description="Scheduled delivery status.")
    freshness_state: str
    last_success_utc: str | None
```

Минимальный route:

```python
from fastapi import FastAPI

app = FastAPI(title="Delivery API")


@app.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    return HealthResponse(
        status="success",
        freshness_state="fresh",
        last_success_utc="2026-01-05T06:18:40Z",
    )
```

И сразу проверьте, что API не стал write path:

```python
forbidden = ["@app.post", "@app.put", "@app.patch", "@app.delete", ".write_text(", "requests.", "os.environ"]
assert not any(marker in source_text for marker in forbidden)
```

## Используйте это

Соберите пример:

```bash
uv run --locked python phases/17-delivery/10-fastapi/outputs/fastapi_delivery_endpoint.py \
  --write-example /tmp/fastapi-delivery-example \
  --output-dir /tmp/fastapi-delivery-package
```

Package:

```text
fastapi-delivery-api/
├── api.py
├── api_contract.json
├── openapi_schema.json
├── api_contract_tests.json
├── api_audit.json
├── api_manifest.json
├── cli_fallback.md
└── api_data/
    ├── schedule_run_report.json
    ├── schedule_freshness_report.json
    ├── run_history.csv
    ├── last_success_marker.json
    ├── scheduled_publish_manifest.json
    ├── delivery_cli_run_report.json
    ├── delivery_cli_publish_manifest.json
    └── delivery_freshness_report.json
```

Запустить API локально можно из папки package:

```bash
uv run --locked uvicorn api:app --app-dir /tmp/fastapi-delivery-package/fastapi-delivery-api
```

Проверить без браузера:

```python
from fastapi.testclient import TestClient
from api import app

client = TestClient(app)
assert client.get("/health").json()["freshness_state"] == "fresh"
assert client.get("/runs/not-a-real-run-id").status_code == 404
```

## Сломайте это

Проверьте failure modes.

1. Поменяйте route method в `api_contract.json` на `POST`. Builder должен вернуть `api_contract_block`.
2. Удалите `run_history.csv` из scheduled package. Builder должен вернуть `upstream_package_block`.
3. Поставьте `status = "data_quality_block"` в `schedule_run_report.json`. API не должен публиковать интерфейс как valid.
4. Добавьте в `api.py` `requests.get(...)` или `.write_text(...)`. Read-only source audit должен заблокировать package.
5. Запросите `/runs/not-a-real-run-id`. Runtime contract должен вернуть `404`.
6. Запросите `/runs?status=not-a-status`. FastAPI validation должен вернуть `422`.
7. Удалите `cli_fallback.md` или команду schedule. Audit должен показать, что API стал server-only surface.

## Проверьте это

Тесты урока проверяют:

- sample builder пишет `api.py`, `openapi_schema.json`, `api_contract_tests.json`, `api_audit.json`, `api_manifest.json`, `cli_fallback.md` и `api_data/`;
- default contract объявляет только `GET` маршруты и CLI fallback;
- generated source использует FastAPI decorators, Pydantic `BaseModel`, `response_model` и не содержит mutating/network/env patterns;
- OpenAPI содержит required paths и response schemas;
- runtime `TestClient` получает `200` для `/health`, `/summary`, `/runs`, `/artifacts/manifest`;
- unknown run id возвращает `404`, invalid query parameter возвращает `422`;
- bad contract, missing history и non-success upstream package блокируются;
- manifest хеширует API source, OpenAPI, audit и copied data files;
- CLI `--write-example` и `--fail-on-invalid` ведут себя предсказуемо;
- учебный `code/main.py` запускает весь happy path.

Запуск:

```bash
uv run --locked python -m unittest discover -s phases/17-delivery/10-fastapi/tests -v
```

## Поставьте результат

Именованный артефакт: `outputs/fastapi_delivery_endpoint.py`.

Для реального scheduled package:

```bash
uv run --locked python phases/17-delivery/10-fastapi/outputs/fastapi_delivery_endpoint.py \
  --scheduled-package-dir ./scheduled-delivery-package \
  --api-contract ./api_contract.json \
  --output-dir ./fastapi-delivery-package \
  --fail-on-invalid
```

Передавайте дальше весь `fastapi-delivery-api/`, а не только `api.py`. Без `openapi_schema.json`, `api_contract_tests.json`, `api_audit.json`, `api_manifest.json` и `cli_fallback.md` endpoint нельзя ревьюить как delivery artifact.

## Упражнения

1. Добавьте endpoint `/freshness` с отдельной `FreshnessResponse`, не дублируя логику `/health`.
2. Добавьте query parameter `freshness_state` для `/runs` и проверьте `422` для неизвестного значения.
3. Добавьте `x-delivery-artifact` metadata в OpenAPI schema и тест, который проверяет это поле.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Optional API | Новый основной продуктовый backend | Read-only интерфейс поверх уже поставленного delivery package |
| Response model | Украшение для Swagger UI | Pydantic schema, по которой FastAPI валидирует, документирует и фильтрует ответ |
| OpenAPI schema | Автоматическая страница документации | Машиночитаемый контракт HTTP API: paths, parameters, responses и schemas |
| Contract tests | Проверка "сервер стартует" | Проверки schema, validation, read-only boundary, runtime behavior и fallback |
| CLI fallback | Устаревший путь после появления API | Обязательный воспроизводимый способ получить package без HTTP-интерфейса |
| Read-only boundary | Отсутствие кнопки "сохранить" | Запрет mutating methods, source writes, background refresh, network calls и secret-dependent behavior |

## Дополнительное чтение

- [FastAPI: First Steps](https://fastapi.tiangolo.com/tutorial/first-steps/) - базовая структура `app = FastAPI()`, path operation decorators и автоматическая OpenAPI/Swagger документация.
- [FastAPI: Response Model - Return Type](https://fastapi.tiangolo.com/tutorial/response-model/) - как `response_model` валидирует, документирует и фильтрует ответы.
- [FastAPI: Path Parameters](https://fastapi.tiangolo.com/tutorial/path-params/) - типизация path parameters, automatic parsing, validation errors и документация параметров.
- [Pydantic: Models](https://docs.pydantic.dev/latest/concepts/models/) - `BaseModel`, validation, `model_dump`, schema и настройка `extra`.
- [OpenAPI Specification](https://spec.openapis.org/oas/latest.html) - зачем нужен language-agnostic HTTP API contract и какие объекты входят в schema.
