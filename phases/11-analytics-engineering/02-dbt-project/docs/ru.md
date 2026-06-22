# Структура dbt-проекта

> dbt-проект - это не папка с SQL, а контракт: какие ресурсы существуют, где dbt их
> ищет, каким profile он подключается и какими командами это проверяется.

**Тип:** Build  
**Треки:** Data  
**Пререквизиты:** 11/01 - Слои и контракты аналитических данных  
**Время:** ~75 минут  
**Результат:** собирает минимальный dbt-проект с `dbt_project.yml`, profile contract,
каталогами models/tests/macros/snapshots и воспроизводимыми командами parse, compile и
debug.

## Цели обучения

- Объяснить, за что отвечает `dbt_project.yml`, а что должно оставаться в локальном
  `profiles.yml`.
- Собрать минимальную структуру dbt-проекта с `models/`, `tests/`, `macros/`,
  `snapshots/`, `seeds/` и layer-папками.
- Настроить локальный DuckDB profile без секретов и cloud-зависимостей.
- Проверить проект командами `dbt debug`, `dbt parse` и `dbt compile`.
- Выпустить machine-readable audit report для skeleton перед добавлением sources и marts.

## Проблема

После `11/01` у команды есть contract: raw, staging, intermediate и mart слои описаны как
граф ответственности. Но contract еще не dbt-проект. Частая ошибка - сразу создать
несколько `.sql` файлов и начать писать бизнес-логику:

```text
models/
  revenue.sql
  users.sql
  final.sql
```

Такой проект может даже запускаться, но он плохо передается коллеге:

```text
Какой profile нужен?
Где dbt ищет snapshots?
Какие папки являются частью контракта, а какие просто временные?
Как понять, что проект хотя бы парсится и компилируется?
```

В analytics engineering skeleton должен быть проверяемым раньше, чем в нем появится
сложная витрина. Иначе первая бизнес-ошибка смешается с ошибкой окружения.

## Концепция

### `dbt_project.yml` описывает проект, а не подключение

`dbt_project.yml` отвечает за top-level структуру:

```yaml
name: analytics_engineering_skeleton
profile: analytics_engineering_skeleton
model-paths: ["models"]
test-paths: ["tests"]
macro-paths: ["macros"]
snapshot-paths: ["snapshots"]
seed-paths: ["seeds"]
```

Это договор с parser: где искать models, tests, macros, snapshots и seeds. В этом файле
не должно быть паролей, токенов или персональных локальных путей к warehouse.

### `profiles.yml` - локальная граница подключения

Рабочий profile часто живет вне репозитория: в `~/.dbt/profiles.yml`, CI secret store или
временной папке. В уроке в репозитории лежит только `profiles.yml.example`:

```yaml
analytics_engineering_skeleton:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: "{{ env_var('DBT_DUCKDB_PATH', 'target/analytics.duckdb') }}"
      schema: analytics
      threads: 1
```

Для курса это важно: мы фиксируем форму подключения, но не коммитим секреты. DuckDB
позволяет проверить dbt локально без внешнего аккаунта.

### Resource directories - часть контракта

В skeleton уже есть папки:

```text
models/staging/
models/intermediate/
models/marts/
tests/
macros/
snapshots/
seeds/
```

Даже если часть папок пока почти пустая, они показывают будущую архитектуру фазы. В
следующих уроках туда попадут sources, refs, data tests, macros, snapshots и итоговый mart.

### Три команды проверяют разные границы

`dbt debug` проверяет profile, адаптер, подключение и локальную установку.

`dbt parse` проверяет, что dbt может прочитать проект, YAML и Jinja. Он не подключается к
warehouse для вычисления моделей.

`dbt compile` строит compiled SQL и проверяет, что Jinja/ref graph можно превратить в SQL
для выбранного adapter.

Эти команды не заменяют будущие `dbt run` и `dbt test`. Они дают дешевый quality gate:
skeleton рабочий, можно добавлять настоящие sources и модели.

## Соберите это

### Шаг 1: прочитайте skeleton

Откройте:

```text
outputs/dbt_project_skeleton/
```

Внутри лежит минимальный проект:

```text
dbt_project.yml
profiles.yml.example
commands.md
models/
tests/
macros/
snapshots/
seeds/
```

Сначала проверьте не SQL, а договор:

```text
project name == profile name
resource paths существуют как папки
profile target ведет в local duckdb
commands.md показывает debug, parse и compile
```

### Шаг 2: посмотрите smoke graph

В `models/` есть три маленькие модели:

```text
models/staging/stg_project_smoke.sql
models/intermediate/int_project_smoke.sql
models/marts/mart_project_smoke.sql
```

Они не решают бизнес-задачу. Их цель - доказать, что слой `staging -> intermediate ->
mart` уже выражается как dbt graph и компилируется.

### Шаг 3: проверьте структуру аудитором

Запустите из корня урока:

```bash
python outputs/dbt_project_auditor.py \
  --project outputs/dbt_project_skeleton \
  --output outputs/dbt_project_audit.json
```

Валидный static report должен содержать:

```json
{
  "valid": true,
  "summary": {
    "project_name": "analytics_engineering_skeleton",
    "profile_name": "analytics_engineering_skeleton"
  }
}
```

### Шаг 4: запустите настоящий dbt smoke check

Аудитор умеет сам создать временную копию проекта, положить туда `profiles.yml` и
запустить dbt-команды:

```bash
python outputs/dbt_project_auditor.py \
  --project outputs/dbt_project_skeleton \
  --output outputs/dbt_project_audit.json \
  --run-dbt
```

Он проверяет:

```text
dbt debug
dbt parse
dbt compile
```

Временная копия нужна, чтобы `target/`, `logs/` и DuckDB-файл не загрязняли учебный
каталог.

## Используйте это

С тем же skeleton можно работать вручную:

```bash
mkdir -p /tmp/analytics-dbt-profiles
cp outputs/dbt_project_skeleton/profiles.yml.example /tmp/analytics-dbt-profiles/profiles.yml
uv run --locked dbt debug --project-dir outputs/dbt_project_skeleton --profiles-dir /tmp/analytics-dbt-profiles
uv run --locked dbt parse --project-dir outputs/dbt_project_skeleton --profiles-dir /tmp/analytics-dbt-profiles
uv run --locked dbt compile --project-dir outputs/dbt_project_skeleton --profiles-dir /tmp/analytics-dbt-profiles
```

`code/main.py` показывает compact summary без живого dbt-прогона:

```bash
python code/main.py
```

Если static audit падает, сначала чините структуру. Если static audit проходит, а
`--run-dbt` падает, проблема почти всегда в профиле, adapter, Python environment или
локальном доступе к DuckDB.

## Сломайте это

### Profile name расходится с project config

Плохой вариант:

```yaml
profile: missing_profile
```

Аудитор должен провалить check:

```text
project_profile_exists
```

### Папка объявлена, но не существует

Если удалить `snapshots/`, dbt-проект может жить какое-то время, но contract уже лжет:

```text
snapshot-paths: ["snapshots"]
```

Аудитор должен провалить:

```text
resource_directories_exist
```

### В profile попали секретные поля

Плохой вариант:

```yaml
password: "{{ env_var('WAREHOUSE_PASSWORD') }}"
```

Даже если значение берется из env, skeleton этого урока должен оставаться локальным
DuckDB-контрактом без secret-like fields. Cloud credentials появятся только в реальном
проекте с отдельной политикой доступа.

### Команды не воспроизводят compile

Если `commands.md` содержит только `dbt debug`, проект проверяет подключение, но не
доказывает, что SQL/Jinja graph компилируется. Для skeleton этого мало.

## Проверьте это

Behavioral tests проверяют:

- валидный skeleton проходит static contract;
- обязательные файлы `dbt_project.yml`, `profiles.yml.example` и `commands.md` существуют;
- `profile` из `dbt_project.yml` есть в `profiles.yml.example`;
- resource directories существуют;
- `staging`, `intermediate` и `marts` имеют smoke SQL model;
- profile использует local DuckDB, schema и положительное число threads;
- profile не содержит secret-like fields;
- `commands.md` документирует `debug`, `parse` и `compile`;
- живой dbt smoke check проходит во временной копии проекта;
- CLI пишет audit JSON и возвращает non-zero для невалидного skeleton.

Запуск:

```bash
python -m unittest discover -s tests
```

## Поставьте результат

Итоговый артефакт:

```text
outputs/dbt_project_auditor.py
```

Он работает отдельно от текста урока:

```bash
python outputs/dbt_project_auditor.py \
  --project outputs/dbt_project_skeleton \
  --output outputs/dbt_project_audit.json \
  --run-dbt
```

Передайте вместе с ним:

```text
outputs/dbt_project_skeleton/
outputs/dbt_project_audit.json
```

Следующий урок заменит smoke graph настоящими `source()` и `ref()` для raw tables фазы 11.

## Упражнения

1. Добавьте папку `models/sandbox/`, но не добавляйте ее в `dbt_project.yml`. Объясните,
   почему dbt parser не обязан считать ее частью контракта проекта.
2. Измените `threads` в `profiles.yml.example` на `0` и проверьте, какой check падает.
3. Добавьте четвертую smoke-модель в `models/marts/`, затем запустите `dbt compile` и
   найдите compiled SQL во временной копии или локальном `target/`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| dbt project | Просто папка с SQL-файлами | Набор dbt resources, описанный `dbt_project.yml` и читаемый parser |
| `dbt_project.yml` | Место для credentials | Project config: имя, profile reference, пути ресурсов и project-level configs |
| Profile | Часть бизнес-логики модели | Локальная или CI-конфигурация подключения к data platform |
| Resource path | Косметическая структура папок | Договор, где dbt ищет models, tests, macros, snapshots и seeds |
| `dbt debug` | То же самое, что verbose logging | Команда проверки setup, profile, adapter и connection |
| `dbt parse` | Запуск моделей | Проверка project/YAML/Jinja и построение manifest без вычисления моделей |
| `dbt compile` | Полная сборка витрины | Превращение model SQL + Jinja + refs в compiled SQL |

## Дополнительное чтение

- [dbt: About dbt projects](https://docs.getdbt.com/docs/build/projects) — разберите top-level структуру проекта, resource types и связь skeleton с будущими sources, snapshots, tests и exposures.
- [dbt: DuckDB setup](https://docs.getdbt.com/docs/local/connect-data-platform/duckdb-setup) — разберите поля `type`, `path`, `schema` и `threads`, на которых держится локальный profile урока.
- [dbt: About dbt debug command](https://docs.getdbt.com/reference/commands/debug) — используйте как справочник по тому, что именно проверяет `dbt debug` и зачем нужен `--profiles-dir`.
- [dbt: About dbt parse command](https://docs.getdbt.com/reference/commands/parse) — посмотрите, почему parse ловит YAML/Jinja ошибки и строит manifest без подключения к warehouse.
- [dbt: About dbt compile command](https://docs.getdbt.com/reference/commands/compile) — сравните compile с будущими `run` и `test`: команда строит SQL, но не заменяет проверку данных.
