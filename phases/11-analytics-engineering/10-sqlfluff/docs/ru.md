# SQLFluff и единый стиль

> Линтер не доказывает смысл SQL, но делает стиль, templating и review-поверхность одинаковыми для всей команды.

**Тип:** Build  
**Треки:** Data  
**Пререквизиты:** 11-analytics-engineering/09-documentation-and-lineage  
**Время:** ~60 минут  
**Результат:** настраиваете SQLFluff для DuckDB/dbt-проекта, исключаете generated artifacts и поставляете lint report, который отделяет style failures от semantic data tests.

## Цели обучения

- Настроить `.sqlfluff` для dbt-проекта с `dialect = duckdb` и `templater = dbt`.
- Объяснить, когда нужен dbt templater, а когда достаточно raw/jinja feedback.
- Исключить `target/`, `logs/`, `dbt_packages/` и локальные `*.duckdb` файлы.
- Исправить реальные style violations без отключения полезных правил.
- Поставить SQLFluff quality gate, который не подменяет `dbt test`.

## Проблема

В dbt-проекте уже есть sources, refs, tests, snapshots, docs и exposures. Но review все еще
может развалиться на мелочах:

- один аналитик пишет `SELECT *`, другой разворачивает все колонки;
- кто-то использует alias `orders`, `users`, `support`, а dialect считает часть таких слов
  keyword-like identifiers;
- длинные Jinja macro calls делают diff нечитаемым;
- CI линтит `target/compiled/` и ругается на сгенерированный SQL вместо исходников;
- команда спорит, «почему `sqlfluff lint` зеленый, а `dbt test` красный».

Единый стиль нужен не ради красоты. Он снижает стоимость ревью и делает SQL-проект
предсказуемым: где искать логику, как читать CTE, какие ошибки являются стилем, а какие
означают сломанный data contract.

## Концепция

SQLFluff состоит из трех практических решений:

| Решение | Что фиксирует | Ошибка, если не решить |
|---|---|---|
| Dialect | Синтаксис и reserved words конкретного SQL-движка | Линтер пропускает не тот SQL или ругается на допустимый синтаксис |
| Templater | Как раскрывать Jinja/dbt templates перед lint | `ref()`, `source()`, macros и `is_incremental()` проверяются не так, как в dbt |
| Ignore policy | Какие файлы не являются исходниками | CI линтит `target/`, логи, пакеты и локальные базы |

Для этого урока выбран строгий CI-gate:

```ini
[sqlfluff]
dialect = duckdb
templater = dbt
max_line_length = 120

[sqlfluff:templater:dbt]
project_dir = .
profiles_dir = .
profile = sqlfluff_project
target = dev
dbt_skip_compilation_error = False
```

`dbt_skip_compilation_error = False` важен: если dbt не может скомпилировать модель,
линтер не должен делать вид, что все хорошо. Но такой gate медленнее, поэтому для быстрых
plain SQL snippets в редакторе можно запускать raw templater отдельно.

## Соберите это

Сначала соберите минимальную проверку без SQLFluff. Это не полноценный парсер, а
контрольная мысль: style gate должен быть явным договором команды.

```python
from pathlib import Path
import re

sql = Path("outputs/sqlfluff_project/models/marts/mart_customer_revenue_health.sql").read_text()
bad_aliases = re.findall(r"\bas\s+(orders|users|support|lines)\b", sql, flags=re.I)
assert not bad_aliases
```

Такая проверка не понимает Jinja, CTE или dialect. Зато она показывает, что линтер
формализует не «мне не нравится», а конкретное правило, которое можно объяснить.

### Шаг 1. Объявите стиль как конфиг

Откройте:

```text
outputs/sqlfluff_project/.sqlfluff
outputs/sqlfluff_project/.sqlfluffignore
```

В конфиге должны быть только решения, которые команда действительно приняла. Не копируйте
весь default config: длинный конфиг быстро становится мусором и скрывает важное.

### Шаг 2. Проверьте исходники, а не generated artifacts

`.sqlfluffignore` исключает:

```text
target/
logs/
dbt_packages/
*.duckdb
```

Линтить нужно исходники:

```bash
cd outputs/sqlfluff_project
python -m sqlfluff lint models tests snapshots --format json
```

Если вы запускаете из корня репозитория через `uv`, используйте окружение курса:

```bash
cd phases/11-analytics-engineering/10-sqlfluff/outputs/sqlfluff_project
uv --project ../../../../.. run --locked python -m sqlfluff lint models tests snapshots --format json
```

### Шаг 3. Разделите style и semantics

SQLFluff отвечает на вопрос:

```text
Можно ли этот SQL единообразно читать, парсить и раскрывать как dbt template?
```

`dbt test` отвечает на другой вопрос:

```text
Сходятся ли ключи, связи, accepted values и бизнес-reconciliation?
```

Поэтому `commands.md` держит оба gate:

```bash
python -m sqlfluff lint models tests snapshots --format json
dbt test --select "test_type:data" --project-dir . --profiles-dir .
```

## Используйте это

Готовый артефакт запускает проверки на временной копии проекта, чтобы не оставлять
`target/`, `logs/` и `sqlfluff.duckdb` в исходниках:

```bash
uv run --locked python phases/11-analytics-engineering/10-sqlfluff/outputs/sqlfluff_quality_gate.py --run-sqlfluff
```

Ожидаемый компактный результат:

```json
{
  "sql_files": 22,
  "lint": {
    "files": 22,
    "violations": 0,
    "returncode": 0
  }
}
```

Артефакт также проверяет `outputs/bad_style_example.sql` raw templater-ом. Этот файл
намеренно плохой: uppercase keyword, неявный alias, тесный comparison и positional
`GROUP BY`. Он должен падать, иначе gate ничего не доказывает.

## Сломайте это

1. Замените в `.sqlfluff` `templater = dbt` на `templater = jinja`. Статический gate
   упадет: для CI dbt-проекта это уже другой уровень точности.
2. Удалите `logs/` из `.sqlfluffignore`. Gate упадет, потому что generated artifacts
   снова могут попасть в lint surface.
3. Переименуйте `user_rows` обратно в `users`. Статическая проверка поймает keyword-like
   alias раньше, чем команда начнет спорить о локальных исключениях.
4. Удалите `dbt test` из `commands.md`. Gate упадет, потому что style check не должен
   притворяться semantic quality gate.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/11-analytics-engineering/10-sqlfluff/tests
```

Тесты проверяют:

- `.sqlfluff` объявляет DuckDB dialect и dbt templater;
- profile использует локальный DuckDB без секретов;
- `.sqlfluffignore` исключает generated paths;
- live SQLFluff проходит на 22 SQL-файлах без нарушений;
- raw bad example действительно дает style violations;
- CLI пишет machine-readable report и возвращает non-zero для сломанного конфига.

## Поставьте результат

Итоговый артефакт:

```text
outputs/sqlfluff_quality_gate.py
outputs/sqlfluff_lint_report.json
outputs/sqlfluff_project/.sqlfluff
outputs/sqlfluff_project/.sqlfluffignore
```

Команда поставки:

```bash
uv run --locked python phases/11-analytics-engineering/10-sqlfluff/outputs/sqlfluff_quality_gate.py \
  --project phases/11-analytics-engineering/10-sqlfluff/outputs/sqlfluff_project \
  --bad-example phases/11-analytics-engineering/10-sqlfluff/outputs/bad_style_example.sql \
  --output phases/11-analytics-engineering/10-sqlfluff/outputs/sqlfluff_lint_report.json \
  --run-sqlfluff
```

Этот artifact можно перенести в другой dbt-проект: замените `EXPECTED_PROJECT_NAME`,
обновите `.sqlfluff`, `.sqlfluffignore` и список lint paths.

## Упражнения

1. Добавьте в `bad_style_example.sql` еще одно нарушение и проверьте, что raw templater
   возвращает новый code в report.
2. Временно удалите `max_line_length = 120`, запустите SQLFluff и сравните, какие длинные
   Jinja-строки теперь проходят незаметно.
3. Добавьте в `.sqlfluffignore` слишком широкий паттерн `models/` и расширьте аудитор так,
   чтобы он запрещал исключать исходные модели.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| SQLFluff dialect | «Любой SQL одинаковый» | Набор синтаксических правил и reserved words конкретного SQL-движка |
| Templater | «Это просто Jinja» | Механизм, который раскрывает template перед парсингом и lint rules |
| dbt templater | «Всегда лучший выбор» | Точный, но более медленный режим для CI/dbt-проектов с refs, sources и macros |
| `.sqlfluffignore` | «Можно исключить все шумное» | Контракт, который исключает generated artifacts, но не исходную бизнес-логику |
| Style violation | «SQL неправильный по данным» | Нарушение читаемости, форматирования, aliasing, casing или parseability |
| Semantic test failure | «Линтер это поймает» | Нарушение data contract, ключей, связей, reconciliation или бизнес-инвариантов |

## Дополнительное чтение

- [SQLFluff Default Configuration](https://docs.sqlfluff.com/en/stable/configuration/default_configuration.html) — почему проектный конфиг должен документировать только принятые командой решения, а не копировать все defaults.
- [SQLFluff dbt templater](https://docs.sqlfluff.com/en/stable/configuration/templating/dbt.html) — как выбрать между dbt templater для CI и более быстрым feedback для редактора.
- [SQLFluff Ignoring Errors & Files](https://docs.sqlfluff.com/en/stable/configuration/ignoring_configuration.html) — как работает `.sqlfluffignore` и почему опасно игнорировать parsing/templating errors.
- [SQLFluff Dialects Reference](https://docs.sqlfluff.com/en/stable/reference/dialects.html) — проверьте, что для DuckDB используется label `duckdb` и какие правила наследуются от PostgreSQL.
- [SQLFluff CLI Reference](https://docs.sqlfluff.com/en/stable/reference/cli.html) — команды `lint`, `fix`, `--dialect`, `--templater`, `--config` и JSON/report-friendly запуск.
