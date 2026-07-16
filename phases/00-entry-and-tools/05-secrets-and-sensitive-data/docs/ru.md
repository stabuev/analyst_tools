# Секреты и безопасная работа с данными

> Безопасный проект хранит в Git контракт доступа к данным, но не сами доступы и не
> исходные чувствительные выгрузки.

**Тип:** Build
**Треки:** Core
**Пререквизиты:** 05 — Ветки, pull request и ревью
**Время:** ~60 минут
**Результат:** классифицирует чувствительные данные и использует переменные окружения без
утечек

## Цели обучения

- Различать секреты, персональные данные и другие чувствительные данные.
- Классифицировать данные до того, как выбрать место хранения и способ передачи.
- Документировать имена обязательных переменных через `.env.example`.
- Загружать обязательную конфигурацию из окружения без hardcoded fallback.
- Проверять, что `.env` и restricted extracts не отслеживаются Git.
- Реагировать на опубликованный секрет как на инцидент, а не как на опечатку.

## Проблема

Аналитический проект почти всегда соединяет код с чем-то, что нельзя публиковать:

- строкой подключения к хранилищу;
- API token;
- service account;
- выгрузкой пользователей;
- таблицей с внутренними финансовыми показателями;
- результатом исследования до публикации.

Одна ошибка смешивает два разных слоя:

```python
WAREHOUSE_DSN = "рабочее значение"
```

Теперь код нельзя безопасно показать коллеге, отправить в pull request или опубликовать.
Если значение попало в commit, последующее удаление строки из текущего файла не отменяет
предыдущую версию в истории Git.

Есть и менее очевидная ошибка: считать private repository универсальным разрешением на
хранение данных. Видимость репозитория снижает аудиторию, но не отвечает на вопросы:

- имел ли автор право копировать эти строки;
- нужен ли полный набор данных для задачи;
- кто отвечает за него;
- когда его удалить;
- попадёт ли он в clone, backup, CI log или артефакт.

Безопасность начинается не с regex-сканера, а с решения, что именно проекту разрешено
хранить.

## Концепция

### Секрет и чувствительные данные — не одно и то же

**Секрет** предоставляет доступ или подтверждает полномочия: password, token, private key,
connection string с credentials. После раскрытия секрет обычно нужно отозвать или
ротировать.

**Чувствительные данные** не обязательно предоставляют доступ, но их раскрытие может
навредить людям или организации: персональные идентификаторы, внутренние метрики, сырые
ответы исследования, коммерческие условия.

В этом уроке используется консервативная учебная классификация:

| Класс | Пример | Допустим в публичном Git |
|---|---|---|
| Public | Документация, синтетический sample | Да |
| Internal | Внутренний процесс без персональных данных | Нет |
| Confidential | Пользовательские строки, финансы, непубличные результаты | Нет |
| Restricted | Credentials, private keys, raw PII | Нет |

Названия классов в вашей организации могут отличаться. Важен не ярлык, а явное решение:
владелец, цель, доступ, срок хранения и допустимое место.

### Код хранит контракт, окружение — значение

Репозиторий должен сообщать, что приложению нужен `WAREHOUSE_DSN`, но не раскрывать его:

```text
# .env.example
WAREHOUSE_DSN=
ANALYTICS_API_TOKEN=
```

Python получает значение из окружения процесса:

```python
import os


def require_env(name: str) -> str:
    try:
        value = os.environ[name]
    except KeyError as error:
        raise RuntimeError(f"Required environment variable is missing: {name}") from error
    if not value:
        raise RuntimeError(f"Required environment variable is empty: {name}")
    return value
```

Отсутствие обязательного значения является ошибкой конфигурации. Hardcoded fallback вроде
`os.getenv("TOKEN", "рабочий-токен")` возвращает секрет в код и скрывает неверно
настроенное окружение.

`.env` — соглашение о локальном файле, а не встроенная возможность Python. Стандартная
библиотека не загружает его автоматически. Проект может использовать отдельную библиотеку
или launcher, но правило остаётся тем же: локальный файл не попадает в Git, а код работает
через environment variables.

### Ignore не отменяет историю

`.gitignore` определяет намеренно untracked-файлы. Если `.env` уже был добавлен в index или
commit, новое правило не перестаёт отслеживать его.

Проверяйте оба условия:

```bash
git check-ignore -v .env
git ls-files -- .env
```

Первая команда должна показать правило ignore. Вторая не должна вернуть путь.

### Предотвращение и реагирование — разные задачи

Secret scanner и push protection уменьшают вероятность публикации. Они не доказывают, что
секретов нет: неизвестный формат, закодированное значение или чувствительная таблица могут
не совпасть с шаблоном.

Если реальный секрет уже опубликован:

1. Не пересылайте значение в чат, issue или лог.
2. Отзовите или ротируйте его у провайдера.
3. Определите, где и как долго он был доступен.
4. Удалите значение из текущего кода и при необходимости из истории по согласованной
   процедуре.
5. Сообщите владельцу системы или security-команде согласно правилам организации.
6. Добавьте проверку, которая предотвращает повторение.

Переписывание Git history не заменяет отзыв: старое значение могло быть склонировано,
закешировано или записано в логи.

## Соберите это

Артефакт урока создаёт минимальный security-контракт аналитического проекта. Начните с
небольшого Git-репозитория:

```bash
mkdir secure-analytics-lab
cd secure-analytics-lab
git init
git branch -M main
```

Путь к CLI указан относительно каталога урока. Из корня репозитория курса:

```bash
python3 phases/00-entry-and-tools/05-secrets-and-sensitive-data/outputs/secure_project.py \
  init secure-analytics-lab \
  --owner analytics-team \
  --require WAREHOUSE_DSN \
  --require ANALYTICS_API_TOKEN
```

Команда создаёт четыре части шаблона:

```text
secure-analytics-lab/
├── .env.example
├── .gitignore
├── config/
│   └── security-policy.json
└── src/
    └── settings.py
```

### Шаг 1: проверьте env-контракт

```bash
cat secure-analytics-lab/.env.example
```

В файле должны быть только имена:

```text
WAREHOUSE_DSN=
ANALYTICS_API_TOKEN=
```

Не вставляйте туда рабочие значения, даже если репозиторий пока локальный.

### Шаг 2: разберите правила Git

Шаблон добавляет:

```gitignore
.env
.env.*
!.env.example
data/raw/
```

`.env.*` закрывает локальные варианты вроде `.env.dev`, а отрицательное правило оставляет
пример видимым. `data/raw/` используется в уроке как зона restricted extracts. Public
sample хранится отдельно в `data/sample/`.

Проверьте поведение Git:

```bash
cd secure-analytics-lab
touch .env
git check-ignore -v .env
git check-ignore -v .env.example || true
git status --short
```

`.env` должен быть ignored, а `.env.example` — доступен для commit.

### Шаг 3: изучите policy данных

Откройте `config/security-policy.json`:

```json
{
  "owner": "analytics-team",
  "required_environment": [
    "WAREHOUSE_DSN",
    "ANALYTICS_API_TOKEN"
  ],
  "data_assets": [
    {
      "path": "data/raw/",
      "classification": "restricted",
      "owner": "analytics-team",
      "retention_days": 7,
      "allowed_in_git": false
    },
    {
      "path": "data/sample/",
      "classification": "public",
      "owner": "analytics-team",
      "retention_days": 30,
      "allowed_in_git": true
    }
  ]
}
```

Policy фиксирует не данные, а решение о данных:

- где они появляются;
- к какому классу относятся;
- кто отвечает;
- сколько дней хранить локальную копию;
- допустимы ли они в Git.

Для реального проекта замените учебные пути и сроки правилами вашей организации.

### Шаг 4: загрузите конфигурацию без вывода значений

`src/settings.py` завершает запуск, если обязательной переменной нет. Задайте значение
через окружение или одобренный secret manager. Для локальной shell-сессии можно ввести его
без отображения на экране:

```bash
read -rs WAREHOUSE_DSN
export WAREHOUSE_DSN
printf '\n'
```

Проверяйте имена загруженных параметров, а не значения:

```bash
python3 -c \
  'from src.settings import load_settings; print(sorted(load_settings()))'
```

Не используйте `env`, `printenv` без имени переменной и `print(settings)` для диагностики:
их вывод может попасть в terminal history, CI log или сообщение об ошибке.

### Шаг 5: сохраните только безопасную часть

Создайте синтетический sample:

```bash
mkdir -p data/sample
printf 'order_id,amount\n101,120\n' > data/sample/orders.csv
```

Проверьте staging:

```bash
git add .gitignore .env.example config src data/sample
git diff --cached --name-only
git diff --cached
git commit -m "Add secure project configuration"
```

В staged diff не должно быть `.env`, raw extracts и рабочих значений.

## Используйте это

Запустите аудит из каталога урока:

```bash
python3 outputs/secure_project.py check path/to/project
```

Или из корня курса:

```bash
python3 phases/00-entry-and-tools/05-secrets-and-sensitive-data/outputs/secure_project.py \
  check secure-analytics-lab
```

CLI проверяет:

- `.env`, `.env.local` и `data/raw/` действительно ignored;
- `.env.example` не скрыт;
- policy содержит владельца, обязательные переменные, классы и retention;
- non-public asset не разрешён в Git;
- secret-bearing filenames не находятся среди tracked-файлов;
- required environment names присутствуют в `.env.example` без значений;
- tracked code, config и notebook-файлы не содержат нескольких явных credential
  patterns.

Сохраните машиночитаемый отчёт:

```bash
python3 outputs/secure_project.py check path/to/project \
  --format json \
  --output /tmp/security-check.json
```

При находке инструмент выводит только путь, номер строки и название правила:

```text
src/job.py:12 — hardcoded-credential
```

Совпавшее значение не включается в report. Это важно: security tool не должен сам
распространять секрет через stdout.

### Классифицируйте новый источник до выгрузки

Перед `SELECT ... INTO`, экспортом CSV или скачиванием notebook-результата ответьте:

1. Какие поля действительно нужны?
2. Есть ли прямые или косвенные идентификаторы?
3. Можно ли агрегировать, обезличить или синтезировать sample?
4. Кто владелец источника и кто разрешил использование?
5. Где будет храниться результат?
6. Когда локальная копия должна быть удалена?

Добавьте решение в `data_assets` до появления файла. Policy не заменяет ACL и
организационные процессы, но делает предположение видимым в review.

### Разделяйте sample и production extract

Хороший `data/sample/orders.csv`:

- синтетический или подтверждённо обезличенный;
- минимальный;
- покрывает нужные edge cases;
- не восстанавливается обратно в пользователей;
- имеет понятное происхождение.

Первые десять строк production-таблицы не становятся безопасным sample только из-за
маленького размера.

## Сломайте это

Используйте только учебные значения и синтетические данные.

### Принудительно добавьте `.env`

```bash
printf 'WAREHOUSE_DSN=local-demo-value\n' > .env
git add -f .env
git commit -m "Accidentally track local env"
python3 path/to/secure_project.py check .
```

Проверка `tracked-sensitive` завершится ошибкой, хотя правило `.gitignore` существует.
Уберите файл из tracking, сохранив локальную копию:

```bash
git rm --cached .env
git commit -m "Stop tracking local environment"
```

Если вместо учебного значения был реальный credential, сначала отзовите или ротируйте
его. Одного нового commit недостаточно.

### Зашейте credential в Python

```python
API_TOKEN = "local-demo-value-that-must-not-be-used"
```

После commit проверка `hardcoded-secrets` укажет файл и строку, но не повторит значение.
Замените литерал на `require_env("API_TOKEN")`.

Regex-проверка намеренно ограничена. Она может дать false positive и не найдёт каждый
секрет. Используйте её как локальный guardrail вместе с review и push protection.

### Добавьте restricted extract через `-f`

```bash
mkdir -p data/raw
printf 'customer_id,segment\n1,example\n' > data/raw/customers.csv
git add -f data/raw/customers.csv
git commit -m "Accidentally add restricted extract"
python3 path/to/secure_project.py check .
```

Проверка `data-policy` сопоставит tracked path с policy. Формат CSV и синтетическое
содержимое в упражнении не меняют правила: путь объявлен restricted.

### Заполните `.env.example`

```text
WAREHOUSE_DSN=local-demo-value
```

`env-example` должен завершиться ошибкой. Пример документирует имя, а не переносит
локальную конфигурацию между людьми.

### Выведите конфигурацию в лог

Даже корректно полученный через environment variable секрет можно раскрыть позже:

```python
settings = load_settings()
print(settings)
```

Логируйте факт конфигурации или список имён:

```python
print("Configured:", sorted(settings))
```

Наличие секрета и его значение — разные данные.

## Проверьте это

Запустите тесты урока:

```bash
python3 -m unittest discover \
  -s phases/00-entry-and-tools/05-secrets-and-sensitive-data/tests \
  -p "test_*.py" -v
```

Семь сценариев создают настоящие временные Git-репозитории и проверяют:

- готовый шаблон;
- различие `.env` и `.env.example`;
- уже tracked `.env`;
- hardcoded credential без вывода значения;
- restricted extract, добавленный через `git add -f`;
- пропущенную обязательную переменную в env-контракте;
- заполненную лишнюю переменную, не объявленную в policy.

Запустите демонстрацию:

```bash
python3 phases/00-entry-and-tools/05-secrets-and-sensitive-data/code/main.py
```

Перед pull request выполните:

```bash
git status --short
git diff --cached
git ls-files -- .env '.env.*' 'data/raw/**'
python3 phases/00-entry-and-tools/05-secrets-and-sensitive-data/outputs/secure_project.py \
  check .
```

Пустой вывод `git ls-files` подтверждает отсутствие этих путей среди tracked-файлов, но
не проверяет всю историю и внешние логи.

## Поставьте результат

Результат урока — не локальный `.env`, а переиспользуемый безопасный контракт:

- `.env.example` перечисляет обязательные имена;
- `src/settings.py` fail fast загружает значения из окружения;
- `.gitignore` закрывает локальные секреты и raw extracts;
- `config/security-policy.json` классифицирует зоны данных;
- `secure_project.py check` даёт воспроизводимую проверку перед review.

Manifest артефакта находится в `outputs/artifact.json`. CLI использует только стандартную
библиотеку Python и Git, поэтому может быть перенесён в другой аналитический проект.

Для production-систем environment variables часто являются только интерфейсом доставки:
источником значения должен быть одобренный secret manager, CI secret storage или
оркестратор. Не превращайте `.env` в командное хранилище, пересылаемое в мессенджере.

## Упражнения

1. Добавьте в policy `data/interim/` с классом `confidential` и докажите, что tracked-файл
   из этой директории блокирует проверку.
2. Добавьте обязательную переменную `REPORT_BUCKET` одновременно в policy,
   `.env.example` и `src/settings.py`, затем удалите её из одного места и исследуйте
   failure.
3. Создайте синтетический sample с edge cases для будущего расчёта и письменно объясните,
   почему он относится к `public`, не ссылаясь только на размер файла.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| Secret | Любые непубличные данные | Значение, которое предоставляет доступ или полномочие |
| Sensitive data | Только пароль | Данные, раскрытие которых может причинить вред |
| `.env.example` | Копия рабочего `.env` | Версионируемый список имён без рабочих значений |
| Environment variable | Надёжное хранилище секрета | Способ передать значение процессу |
| `.gitignore` | Удаление файла из Git | Правила для намеренно untracked-путей |
| Rotation | Переименование переменной | Выпуск нового секрета и прекращение действия старого |
| Data minimization | Удаление части строк после анализа | Получение и хранение только необходимого минимума |
| Push protection | Доказательство отсутствия секретов | Превентивная блокировка известных credential patterns |

## Дополнительное чтение

- [Python Docs: os.environ и os.getenv](https://docs.python.org/3/library/os.html#os.environ) — изучите mapping окружения и различие обязательного доступа и default-значения.
- [Git: gitignore documentation](https://git-scm.com/docs/gitignore) — разберите источники правил и почему уже tracked-файлы не затрагиваются.
- [GitHub Docs: Push protection](https://docs.github.com/en/code-security/concepts/secret-security/push-protection) — посмотрите, где GitHub блокирует известные hardcoded credentials до публикации.
- [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html) — углубите жизненный цикл секрета: создание, доступ, rotation, audit и уничтожение.
