# Аудит набора данных

> До первого графика превратите требования visual question в проверяемое evidence о
> данных, не исправляя источник молча.

**Тип:** Case  
**Треки:** Core  
**Пререквизиты:** 06/01  
**Время:** ~90 минут  
**Результат:** проверяет пригодность versioned dataset для объявленного visual question:
исполняет контракт, различает дефект, допустимый экстремум и неполное наблюдение и
выпускает evidence-backed selection plan без изменения источника.

## Цели обучения

- Превращать readiness gates из visual question brief в наблюдаемые проверки.
- Исполнять объявленные key, type, domain, category, null и time-window constraints, а не
  дублировать их неявно в коде.
- Различать точную повторную доставку и конфликтующие строки одного business key.
- Отделять дефект источника от допустимого экстремума и ещё не наблюдавшегося outcome.
- Оценивать readiness для конкретного анализа, а не выдавать одну универсальную метку
  «данные чистые».
- Выпускать checksum-bound selection plan и decision log, не переписывая source bytes.

## Проблема

После 06/01 у команды есть visual question brief для семидневной активации. Он требует:

```text
population       = новые пользователи
analysis unit    = один пользователь и его семидневный outcome
metric           = activated users / users with a complete seven-day window
comparison       = cohort week до и после контрольной даты
readiness gates  = grain, дубликаты, окно, типы, знаменатель и сопоставимость сегментов
```

Файл `user_journeys.csv` открывается и содержит нужные столбцы. Это ещё не доказывает,
что он пригоден для вопроса. Правдоподобный график можно получить даже если:

- пустой ключ прошёл как обычная строка;
- две записи одного пользователя противоречат друг другу;
- `sessions_7d=-1` или `1.5` успешно преобразовались в число;
- неизвестный outcome неполного окна стал `false`;
- дата когорты не соответствует неделе регистрации;
- source изменился уже после аудита.

Опасна и обратная ошибка: один дефект делает «невалидным» весь dataset, хотя он не влияет
на текущую метрику. Невозможная длительность onboarding блокирует анализ распределения
onboarding, но не обязана запрещать activation, которая этого столбца не использует.

Задача аудитора — не почистить всё подряд, а сохранить evidence и ответить:

> Какие строки и поля разрешено использовать именно для объявленного вопроса, какие
> решения нужно применить и что по-прежнему блокирует интерпретацию?

## Концепция

### Четыре разных объекта нельзя смешивать

| Объект | Что он содержит | Чего он не доказывает |
|---|---|---|
| Data contract | ожидаемые поля, типы, grain и правила | что конкретный файл им соответствует |
| Observed profile | counts, строки-примеры и фактические нарушения | какое решение допустимо |
| Decision log | действие, scope, причина и evidence | что source bytes были изменены |
| Selection plan | правила построения аналитического view | что любой другой вопрос тоже готов |

Контракт версии 2 хранит исполняемые ограничения. Если `primary_key`, список категорий
или минимальное значение изменены в JSON, аудитор должен изменить поведение без правки
Python-кода. Иначе контракт служит документацией рядом с настоящими скрытыми правилами.

### Проверки образуют слои

```text
structure
-> key and duplicate class
-> physical type
-> domain and allowed values
-> conditional missingness
-> time range and cohort alignment
-> question-scoped readiness
```

Если обязательного столбца нет, зависимые type и domain checks не имеют входа. Их нельзя
показывать зелёными: аудит останавливается на ближайшей доказуемой границе.

### Одинаковый key не всегда означает одинаковую ошибку

Пусть `user_id=J018` встретился дважды.

1. **Exact duplicate delivery:** все поля совпадают. Можно принять явное решение оставить
   одну byte-equivalent запись и сохранить key в evidence.
2. **Key conflict:** хотя бы одно поле различается. Нельзя выбрать первую или последнюю
   строку без отдельного правила источника. Такой конфликт остаётся blocker.

Команда `drop_duplicates("user_id")` не различает эти случаи. Поэтому selection plan
разрешает удаление только exact duplicates, которые аудитор уже классифицировал на том же
checksum источника.

### Missingness определяется процессом наблюдения

Пустое значение не имеет одного универсального смысла:

| Поле и условие | Значение пропуска | Решение |
|---|---|---|
| `app_version` при `platform=web` | поле неприменимо | структурный пропуск допустим |
| `activated_7d` при `observed_days<7` | исход ещё неизвестен | исключить из знаменателя этой метрики |
| `activated_7d` при полном окне | потерян обязательный outcome | blocker activation |
| `country` | допустимое отсутствие атрибута | сохранить count и ограничение сегментации |
| обязательный `user_id` | неизвестна сущность строки | blocker любого анализа |

Аудитор не записывает `false` вместо неизвестного outcome. Он сохраняет исходную строку и
добавляет eligibility rule в selection plan.

### Invalid и extreme требуют разных доказательств

Контракт задаёт `onboarding_seconds >= 0`. Значение `-1` невозможно по предметному
смыслу и блокирует onboarding-distribution. Значение `3600` допустимо: оно может быть
реальным хвостом и должно остаться видимым для следующего урока о распределениях.

Порог «выглядит большим» не является domain rule. Верхнюю границу можно добавить только
если она следует из процесса измерения или согласованного контракта, а не из желания
сделать график аккуратнее.

### Readiness принадлежит вопросу

Артефакт рассчитывает два профиля:

- `activation_7d` использует key, cohort, platform, acquisition channel, observation
  window и boolean outcome;
- `onboarding_distribution` использует key, platform и неотрицательную длительность.

В committed tiny результат закономерно различается:

```text
activation_7d          -> ready_with_decisions
onboarding_distribution -> blocked
```

Первый статус разрешает применить зафиксированные решения об exact duplicate и неполных
окнах. Второй сохраняет отрицательную длительность blocker. Общий `valid=false` не
отменяет scoped readiness и не превращает его в разрешение игнорировать остальные
findings.

### Selection plan связан с source checksum

План содержит:

- SHA-256 исходного CSV;
- business key;
- evidence точных повторных доставок;
- eligibility rule конкретного вопроса;
- требуемые столбцы и их выходные типы;
- blocker и decision identifiers.

Если CSV изменился после аудита, следующий урок отклонит план. Это защищает от ситуации,
когда проверяли один файл, а график построили уже по другому.

## Соберите это

До pandas воспроизведите минимальный механизм стандартной библиотекой:

```bash
uv run --locked python code/main.py
```

Перед запуском предскажите отдельно:

1. есть ли пустой business key;
2. является ли повтор key точной доставкой или конфликтом;
3. какие окна исключаются только из activation;
4. какой defect относится только к onboarding-distribution.

Прозрачный пример группирует строки по `user_id`, сравнивает полные словари строк и не
смешивает два результата:

```text
activation_blockers
onboarding_distribution_blockers
```

Exact duplicate попадает в `activation_requires_decision`, а не автоматически исчезает.
Этот маленький механизм делает видимой классификацию, которую production-артефакт затем
применяет ко всему контракту.

## Используйте это

Запустите contract-driven CLI для вопроса activation:

```bash
uv run --locked python outputs/eda_audit.py \
  --input ../data/tiny/user_journeys.csv \
  --contract ../data/contract.json \
  --analysis activation_7d \
  --output audit.json
```

Код возврата `0` означает, что выбранный анализ имеет статус `ready` или
`ready_with_decisions`. Это не означает, что весь dataset идеален. Отчёт содержит:

```text
source and contract checksums
checks[] with status, severity, scopes and evidence
missingness
readiness by analysis profile
selection_plan
decision_log
```

Сравните другой вопрос:

```bash
uv run --locked python outputs/eda_audit.py \
  --input ../data/tiny/user_journeys.csv \
  --contract ../data/contract.json \
  --analysis onboarding_distribution \
  --output onboarding-audit.json
```

Здесь код `1`: отрицательная длительность остаётся blocker. Чтобы получить JSON для
разбора, не выдавая его за разрешение продолжать, добавьте `--report-only`. Ошибка чтения
входа, некорректный contract или неизвестный analysis profile возвращают код `2`.

Артефакт не пишет cleaned CSV. Его standalone API `prepare_analysis_frame` принимает
source и audit report, сверяет checksum и применяет только evidence-backed decisions.

## Сломайте это

1. Оставьте один пустой `user_id`. Он должен блокировать все профили, даже если такой
   пустой key встретился один раз.
2. Скопируйте строку и измените `activated_7d`. Key conflict нельзя назвать exact
   delivery или разрешить через `drop_duplicates`.
3. Запишите `sessions_7d=1.5` и `support_tickets_7d=-1`. Integer и domain checks должны
   сохранить номера строк.
4. Удалите `android` из `columns.platform.allowed` в копии контракта. Python-код не
   меняется, но Android становится contract violation.
5. Заполните outcome при `observed_days=2`. Conditional null policy должна заблокировать
   activation.
6. Измените один byte CSV после выпуска `audit.json`. `prepare_analysis_frame` должен
   отвергнуть старый selection plan по checksum.

Ни одна поломка не должна приводить к автоматической перезаписи source. Исправление или
исключение — отдельное решение с владельцем и evidence.

## Проверьте это

Behavioral tests проверяют не только committed fixture, но и правдоподобные ложные
зелёные результаты:

- blank key и conflicting duplicate блокируют анализ;
- exact duplicate отделён от конфликта;
- integer и non-negative constraints действительно влияют на status;
- allowed categories читаются из contract;
- incomplete window исключается без переписывания outcome;
- activation и onboarding получают разные readiness;
- selection plan создаёт 22 уникальные строки полного окна;
- изменившийся source отклоняется по checksum;
- CLI exit code следует выбранному analysis profile.

```bash
uv run --locked python -m unittest discover -s tests
uv run --locked python ../data/generate_data.py --check
```

После этого передайте evidence следующему уроку:

```bash
uv run --locked python ../03-matplotlib-oo/outputs/figure_factory.py \
  --input ../data/tiny/user_journeys.csv \
  --audit audit.json \
  --output-dir figure-output
```

Figure factory больше не выполняет скрытый `drop_duplicates`: она принимает только тот
source, для которого выпущен audit report, и сохраняет readiness и decision ids в
manifest фигуры.

## Поставьте результат

`outputs/eda_audit.py` — самостоятельный question-scoped аудитор. Он принимает внешний
CSV и contract, выпускает JSON с evidence, scoped readiness, decision log и
checksum-bound selection plan.

Артефакт полезен:

- как data-readiness evidence рядом с visual question brief;
- как gate перед воспроизводимой фигурой;
- в review, где нужно отличить exact duplicate от key conflict;
- при смене вопроса, когда один dataset получает разные readiness statuses;
- в финальном EDA-package вместе с исходным checksum и manifest.

## Упражнения

1. **Закрепление.** Добавьте в копию CSV пустой `platform` и неизвестный `desktop`.
   Предскажите разные finding ids и только затем запустите аудитор.
2. **Перенос.** Для вопроса о распределении времени ответа поддержки сформулируйте
   contract: одна строка на ticket, незакрытые обращения не имеют final duration, а
   отрицательная длительность невозможна. Назовите readiness gates без кода.
3. **Неоднозначность.** Две строки одного `ticket_id` имеют разные `status`. Запишите,
   какое дополнительное source rule нужно получить, прежде чем выбирать строку.
4. **Новая граница.** Добавьте analysis profile для `sessions_7d`, не меняя Python-код.
   Проверьте, что дробное или отрицательное значение блокирует именно новый профиль.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| Data contract | Список названий столбцов | Исполняемые ожидания о структуре, grain, типах и правилах |
| Observed profile | Автоматический вывод | Evidence о конкретной версии данных без решения за аналитика |
| Exact duplicate | Любой повтор key | Повторная строка, совпадающая по всем полям |
| Key conflict | Строка, которую можно удалить первой | Один key с различающимися значениями и неизвестной canonical policy |
| Structural missingness | Случайно потерянное значение | Поле неприменимо при объявленном условии |
| Observation window | Диапазон оси | Период, нужный для полного наблюдения outcome |
| Scoped readiness | Общая чистота dataset | Пригодность конкретных полей и строк для объявленного вопроса |
| Selection plan | Очищенный файл | Проверяемые правила построения view, связанные с checksum источника |
| Decision log | Технический лог | Решение, scope, причина и evidence, которые можно пересмотреть |

## Дополнительное чтение

- [pandas: Working with missing data](https://pandas.pydata.org/docs/user_guide/missing_data.html) — разберите nullable dtypes и сопоставьте технический `NA` с conditional null policies урока.
- [pandas: Duplicate Labels](https://pandas.pydata.org/docs/user_guide/duplicates.html) — изучите последствия повторяющихся index labels и отдельно зафиксируйте, почему это не заменяет проверку business key и сравнение полных строк.
- [NIST: Exploratory Data Analysis](https://www.itl.nist.gov/div898/handbook/eda/eda.htm) — сопоставьте проверку предпосылок и структуры данных с последующими графическими методами, не превращая EDA в автоматическую очистку.
