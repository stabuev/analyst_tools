# Docker как факультативная упаковка

> Docker полезен как локальная упаковка только тогда, когда он не скрывает контракт поставки, секреты и различия между локальным и контейнерным запуском.

**Тип:** Build
**Треки:** Delivery
**Пререквизиты:** `17-delivery/10-fastapi`
**Время:** ~75 минут
**Результат:** вы собираете Docker packaging audit: Dockerfile, `.dockerignore`, context report, run manifest и проверку equivalence с локальным FastAPI package.

## Цели обучения

- Проектировать Docker build context как явный allow-list, а не как случайный снимок репозитория.
- Проверять `.dockerignore`, no-secret policy, non-root runtime и отсутствие широкого `COPY . .`.
- Доказывать, что container package показывает тот же `api_manifest.json`, что и локальная поставка.

## Проблема

В прошлом уроке мы сделали optional read-only FastAPI поверх уже поставленного результата. Это удобно для локальной демонстрации: можно открыть `/health`, `/summary`, `/runs`, отдать клиенту OpenAPI schema. Но как только появляется API, возникает следующий соблазн: "давайте завернем это в Docker и будем считать, что доставка готова к production".

Это опасный скачок. Docker-образ может стать хорошей упаковкой, но он не исправляет плохой delivery contract. Если в build context случайно попали `.env`, raw dumps, `.venv`, caches или весь репозиторий через `COPY . .`, контейнер делает поставку менее проверяемой, а не более надежной.

В этом уроке Docker остается факультативной локальной упаковкой. Мы не требуем реальный Docker daemon для тестов курса. Вместо этого строим проверяемый Docker package:

- `Dockerfile` с pinned runtime и non-root user;
- `.dockerignore`, который отсекает секреты, caches, raw/heavy data и generated metadata;
- `docker_build_context_report.json`, который показывает, что реально вошло бы в build context;
- `docker_run_manifest.json`, который фиксирует local `docker build` / `docker run` команды;
- `docker_audit.json`, который блокирует упаковку, если upstream FastAPI package или контейнерный контракт сломан.

Главная мысль: контейнер — это wrapper поверх known-good delivery package, а не замена проверки результата.

## Концепция

Docker build получает на вход build context. По умолчанию легко отправить слишком много: весь репозиторий, локальные артефакты, временные данные, credentials. Поэтому проектирование начинается не с "какую команду написать", а с вопроса: какие файлы вообще имеют право войти в context?

В нашем контракте context минимален:

```text
Dockerfile
.dockerignore
app/
```

В `app/` попадает allow-list из FastAPI package:

```text
api.py
api_contract.json
openapi_schema.json
api_contract_tests.json
api_audit.json
api_manifest.json
cli_fallback.md
api_data/
```

Все audit metadata Docker-урока остаются рядом в package, но `.dockerignore` исключает их из image build. Это полезное различие: reviewer видит отчеты, но runtime image не раздувается служебными файлами урока.

`Dockerfile` фиксирует runtime:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY app/ /app/
RUN python -m pip install --no-cache-dir \
    "fastapi>=0.139.0,<0.140" \
    "uvicorn>=0.50.1,<0.51"
USER appuser
EXPOSE 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

Здесь важны не сами строки как магия, а контракт:

- base image pinned, а не `python:latest`;
- `COPY app/ /app/`, а не широкий `COPY . .`;
- runtime user не root;
- команда запуска явно ведет к тому же `api.py`;
- runtime не требует secrets из env.

Manifest equivalence связывает контейнер с локальной поставкой: `app/api_manifest.json` внутри package должен иметь тот же SHA-256, что и исходный `api_manifest.json` из FastAPI package. Если хеш другой, Docker package уже не является прозрачной упаковкой результата.

## Соберите это

Артефакт урока лежит в `outputs/docker_packaging_audit.py`. Он умеет сгенерировать пример входов, собрать FastAPI package из урока 17/10 и затем создать Docker packaging audit.

Запуск happy path:

```bash
python phases/17-delivery/11-docker/outputs/docker_packaging_audit.py \
  --write-example /tmp/docker-delivery-example \
  --output-dir /tmp/docker-delivery-package
```

Внутри output появится директория:

```text
docker-delivery-package/
├── Dockerfile
├── .dockerignore
├── app/
├── container_contract.json
├── docker_contract_tests.json
├── docker_build_context_report.json
├── docker_run_manifest.json
├── docker_audit.json
├── docker_manifest.json
└── docker_runbook.md
```

Ключевые проверки находятся в `docker_audit.json`:

- upstream FastAPI package valid до контейнеризации;
- container contract требует local-only boundary;
- Dockerfile использует pinned slim runtime, `USER appuser` и uvicorn `CMD`;
- Dockerfile не содержит `COPY . .`, root runtime user, token/secret args;
- `.dockerignore` закрывает секреты, caches, raw/heavy data;
- build context содержит только `Dockerfile`, `.dockerignore`, `app/`;
- run manifest сохраняет тот же `api_manifest.json` hash.

Если нужно использовать свой FastAPI package:

```bash
python phases/17-delivery/11-docker/outputs/docker_packaging_audit.py \
  --api-package-dir /path/to/fastapi-delivery-api \
  --container-contract /path/to/container_contract.json \
  --output-dir /tmp/docker-delivery-package \
  --fail-on-invalid
```

`--fail-on-invalid` полезен для CI: invalid upstream package вернет код `10`, invalid container contract — код `2`, системная ошибка — код `30`.

## Используйте это

Открой `docker_run_manifest.json`. Там есть команды, которые можно выполнить локально при наличии Docker:

```bash
docker build --pull --tag trial-onboarding-delivery-api:local .
docker run --rm -p 8000:8000 trial-onboarding-delivery-api:local
```

После запуска API должен отвечать так же, как локальный FastAPI package:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/artifacts/manifest
```

Но даже без Docker daemon можно проверить смысл упаковки:

1. `docker_build_context_report.json` показывает included/excluded файлы.
2. `docker_run_manifest.json` показывает ожидаемый хеш `/app/api_manifest.json`.
3. `docker_audit.json` объясняет, почему package valid или invalid.

Это важная привычка: сначала доказать contract, потом запускать инфраструктуру.

## Сломайте это

Сломай upstream package:

```bash
rm /tmp/docker-delivery-example/fastapi-package/fastapi-delivery-api/api_manifest.json
```

Теперь запуск с `--fail-on-invalid` должен завершиться upstream block:

```bash
python phases/17-delivery/11-docker/outputs/docker_packaging_audit.py \
  --api-package-dir /tmp/docker-delivery-example/fastapi-package/fastapi-delivery-api \
  --container-contract /tmp/docker-delivery-example/container_contract.json \
  --output-dir /tmp/docker-delivery-broken \
  --fail-on-invalid
```

Сломай container contract:

```json
{
  "base_image": "python:latest",
  "image_claim_boundary": {
    "no_registry_push": false
  }
}
```

Audit должен показать:

- `base_image_must_pin_python_3_12_slim`;
- `image_boundary_no_registry_push_required`.

Сломай Dockerfile mentally: если бы там было `COPY . .`, builder отправил бы слишком много. В нашем артефакте это ловит `dockerfile_has_no_broad_copy_root_user_or_secret_patterns`.

Добавь рядом с source API package файл `.env` или `secret.key`. Правильное поведение: audit покажет их в `source_forbidden_candidates`, но не скопирует в `app/` и не включит в `forbidden_included_paths`.

## Проверьте это

Запусти тесты урока:

```bash
python -m unittest phases/17-delivery/11-docker/tests/test_main.py
```

Тесты проверяют:

- package пишет все обязательные файлы;
- default contract требует local-only runtime и no-registry-push boundary;
- Dockerfile использует `python:3.12-slim`, `USER appuser`, uvicorn `CMD`;
- `.dockerignore` закрывает secrets/caches/raw data;
- context report минимален и не содержит forbidden paths;
- `.env` и `secret.key` не копируются из source package;
- local `api_manifest.json` hash совпадает с packaged `/app/api_manifest.json`;
- invalid upstream FastAPI package блокирует Docker package;
- CLI возвращает правильный non-zero code при `--fail-on-invalid`.

Полный курс проверяется стандартным набором команд проекта:

```bash
python scripts/validate_course.py
python scripts/render_curriculum.py --check
python scripts/render_outputs.py --check
python scripts/render_site.py --check
python -m unittest discover -s tests
python scripts/run_lesson_tests.py
```

## Поставьте результат

Перед handoff отдавай не "Dockerfile где-то лежит", а проверяемый package:

```text
docker-delivery-package/
  Dockerfile
  .dockerignore
  docker_build_context_report.json
  docker_run_manifest.json
  docker_audit.json
  docker_manifest.json
```

В комментарии к поставке напиши:

- Docker package local-only;
- registry push и cloud deployment не заявлены;
- build context минимален;
- runtime не требует secrets;
- manifest equivalence с FastAPI package проверен;
- основной delivery path остается CLI/report/API package из предыдущих уроков.

Docker здесь делает результат удобнее запускать, но не отменяет дисциплину поставки: сначала проверенный артефакт, потом упаковка.

## Упражнения

1. Добавьте в `container_contract.json` отдельное поле `required_healthcheck_path` и тест, который проверяет, что Dockerfile `HEALTHCHECK` использует именно этот path.
2. Расширьте `.dockerignore` политикой для локальных notebook outputs и проверьте, что `*.ipynb_checkpoints/` не попадает в context.
3. Добавьте второй run profile для другого порта, но сохраните проверку manifest equivalence и local-only boundary.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Build context | "Docker видит весь компьютер" | Набор файлов, который клиент отправляет builder; его нужно сужать через context root и `.dockerignore`. |
| `.dockerignore` | "Просто ускоряет сборку" | Контракт исключения секретов, caches, raw/heavy data и generated metadata из build context. |
| `COPY app/ /app/` | "То же самое, что `COPY . .`, только короче" | Allow-list runtime-файлов; широкий copy может утащить лишние данные и credentials. |
| Non-root user | "Нужен только для production Kubernetes" | Базовая runtime-граница: приложение не должно запускаться от root без причины даже локально. |
| Manifest equivalence | "Если контейнер стартует, значит результат тот же" | Проверка, что manifest внутри container package имеет тот же SHA-256, что локальный delivery manifest. |

## Дополнительное чтение

- [Dockerfile overview](https://docs.docker.com/build/concepts/dockerfile/) — официальное описание Dockerfile и базовых инструкций `FROM`, `RUN`, `WORKDIR`, `COPY`, `CMD`.
- [Dockerfile reference](https://docs.docker.com/reference/dockerfile/) — детали `USER`, `WORKDIR`, `EXPOSE`, `HEALTHCHECK` и других инструкций.
- [Build context and .dockerignore](https://docs.docker.com/build/concepts/context/#dockerignore-files) — как Docker выбирает build context и применяет `.dockerignore`.
- [Build secrets](https://docs.docker.com/build/building/secrets/) — почему secrets не должны попадать в image через `COPY`, `ARG` или `ENV`.
