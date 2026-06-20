# Популяция, выборка и механизм отбора

> Среднее по файлу отвечает только за файл; статистический вывод начинается с популяции и отбора.

**Тип:** Learn  
**Треки:** Product, ML  
**Пререквизиты:** 07/10 - Интеграционный quality gate  
**Время:** ~75 минут  
**Результат:** задает target population, sampling unit, sampling frame и
inclusion/response mechanisms для user-level метрики, проверяет coverage bias,
non-response, веса, дубликаты и неполные observation windows до расчета estimate.

## Цели обучения

- Отличать target population от файла, который лежит на диске.
- Называть sampling unit, sampling frame, inclusion mechanism и response mechanism.
- Проверять, что sample grain совпадает с единицей анализа.
- Находить coverage bias и segment-level non-response до расчета метрики.
- Понимать, когда веса являются частью estimator contract, а не украшением отчета.

## Проблема

Команда подписочного сервиса хочет оценить раннюю активацию и первую выручку по user-level
выгрузке. В файле `sample_observations.csv` есть шесть пользователей. Пять из них имеют
наблюдаемый outcome, трое активировались. Наивный вывод:

```text
activation_rate = 3 / 5 = 60%, все выглядит нормально.
```

Такой вывод пропускает главный вопрос: кого этот файл представляет?

В tiny-данных фазы 09 есть конечная синтетическая популяция из eligible пользователей.
Sampling frame не содержит одного low-end Android пользователя, а в sample один low-end
Android пользователь выбран, но outcome не наблюдается. Поэтому среднее по observed rows
уже не является нейтральным ответом на вопрос о target population.

Перед оценкой нужно выпустить audit:

```text
target population -> sampling frame -> selected sample -> respondents
```

Если на этом пути теряется сегмент, обычный confidence interval позже даст аккуратную
арифметику вокруг неправильной цели.

## Концепция

### Четыре объекта до метрики

| Объект | Вопрос | В уроке |
|---|---|---|
| Target population | О ком мы хотим сделать вывод? | eligible non-test registered users with complete seven-day window |
| Sampling unit | Что является единицей отбора и анализа? | `user_id` |
| Sampling frame | Через какой список пользователи вообще могли попасть в sample? | `activation_export` |
| Response mechanism | У кого после отбора реально наблюдаются outcome-поля? | `outcome_observed` и segment response rate |

Если эти объекты не названы, результат остается описательной статистикой файла.

### Sampling frame может быть уже target population

Coverage bias появляется, когда frame не покрывает target population. В уроке это видно
на low-end Android:

```text
eligible low-end users: U004, U006
frame low-end users:    U004
coverage rate:          50%
```

Это не доказывает, что activation занижена или завышена. Но это доказывает, что оценка по
frame требует ограничения или корректировки.

### Non-response не исправляется размером sample

В sample может быть выбран пользователь, но outcome не наблюдается. Если non-response
связан с сегментом или поведением пользователя, простое удаление пустых строк меняет
целевую популяцию. Поэтому audit считает response rate не только overall, но и по
сегментам.

### Веса принадлежат estimator, а не графику

Если inclusion probabilities различаются, один sampled user может представлять больше
пользователей target population, чем другой. В этом уроке аудитор только проверяет, что
`sample_weight ~= 1 / inclusion_probability`. Сами weighted estimators появятся в `09/03`.

## Соберите это

Откройте `code/main.py`. Минимальная ручная проверка делает ровно одну операцию: находит
eligible users, которых нет в sampling frame.

```python
def manual_missing_from_frame(population, frame):
    eligible_ids = {
        row["user_id"]
        for row in population
        if row["eligible_for_analysis"] == "true" and row["is_test_user"] == "false"
    }
    frame_ids = {row["user_id"] for row in frame}
    return sorted(eligible_ids - frame_ids)
```

Запустите:

```bash
uv run --locked python phases/09-applied-statistics/01-population-and-sample/code/main.py
```

Фрагмент результата:

```json
{
  "manual_missing_from_frame": ["U006"],
  "audit_valid": true,
  "warnings": [
    "frame_segment_coverage",
    "sample_segment_response",
    "unequal_inclusion_probabilities_declared"
  ]
}
```

`audit_valid=true` означает, что таблицы структурно пригодны: ключи, связи, вероятности,
веса и observation windows не сломаны. Warning-и означают другое: оценка по sample несет
методологический риск.

### Шаг 1: назовите target population

В `outputs/sampling_spec.json` target population задана до расчета:

```json
{
  "target_population": "Eligible non-test registered users with a complete seven-day observation window.",
  "sampling_unit": "user_id"
}
```

Если завтра продуктовая команда спросит про новых пользователей без полного окна,
спецификация должна измениться. Нельзя просто переиспользовать тот же denominator.

### Шаг 2: проверьте grain

Sample должен иметь одну строку на `user_id`. Дубликат не является маленькой технической
ошибкой: он меняет вероятность попадания пользователя в расчет.

### Шаг 3: проверьте relationship

Каждый user в sample должен существовать в sampling frame, а каждый user в frame - в
population. Иначе анализ смешивает разные списки пользователей.

### Шаг 4: проверьте probabilities и weights

Поля:

```text
inclusion_probability
response_probability
sample_weight
```

должны быть числовыми, probabilities лежат в `(0, 1]`, а вес для этого урока должен
совпадать с inverse inclusion probability.

### Шаг 5: отделите errors от warnings

Дубликат `user_id` - blocking error. Coverage gap - warning, но методологически важный.
Он не ломает файл, но ломает наивную интерпретацию.

## Используйте это

Артефакт урока:

```bash
uv run --locked python phases/09-applied-statistics/01-population-and-sample/outputs/sampling_frame_auditor.py \
  --population phases/09-applied-statistics/data/tiny/population_users.csv \
  --frame phases/09-applied-statistics/data/tiny/sampling_frame.csv \
  --sample phases/09-applied-statistics/data/tiny/sample_observations.csv \
  --segments phases/09-applied-statistics/data/tiny/segment_reference.csv \
  --spec phases/09-applied-statistics/01-population-and-sample/outputs/sampling_spec.json \
  --output sampling-audit.json
```

Report содержит stable check ids:

```text
sampling_spec_required_fields
sampling_unit_supported
population_key_unique
frame_key_unique
sample_key_unique
frame_users_exist_in_population
sample_users_exist_in_frame
frame_probabilities_in_domain
sample_probabilities_in_domain
sample_weights_match_inclusion_probability
sample_complete_observation_windows
frame_segment_coverage
sample_segment_response
unequal_inclusion_probabilities_declared
```

CLI возвращает `0`, если нет blocking errors. Warning-и остаются в JSON и должны попасть в
следующие уроки как limitations.

## Сломайте это

Попробуйте три мутации.

1. Продублируйте строку `U001` в `sample_observations.csv`.

Ожидаемый сбой:

```text
sample_key_unique
```

2. Замените `user_id` одной sample-строки на `U404`.

Ожидаемый сбой:

```text
sample_users_exist_in_frame
```

3. Поставьте `observed_days=3` для selected user.

Ожидаемый сбой:

```text
sample_complete_observation_windows
```

Во всех трех случаях проблема не статистическая, а контрактная: интервал или bootstrap
нельзя честно строить поверх неверной единицы анализа.

## Проверьте это

Запустите tests урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/09-applied-statistics/01-population-and-sample/tests -v
```

Tests проверяют:

- tiny audit структурно валиден, но содержит три warning-рискa;
- `U006` найден как eligible user вне frame;
- segment-level response warning не скрывается хорошим overall response rate;
- дубликат sample user ломает grain;
- sample user вне frame ломает relationship;
- неполное окно наблюдения блокирует оценку;
- неверная probability или weight становятся blocking error;
- CLI пишет JSON report и возвращает ненулевой код только при blocking errors.

## Поставьте результат

Именованный артефакт:

```text
outputs/sampling_frame_auditor.py
```

Его можно использовать вне урока для любого user-level extract, если подготовить:

```text
population table
sampling frame table
sample observations table
segment reference table
sampling spec
```

Минимальный handoff для следующего аналитика:

```text
Структурных ошибок нет.
Estimation risks:
- frame_segment_coverage: low-end Android undercoverage
- sample_segment_response: Android response below threshold
- unequal_inclusion_probabilities_declared: weights required before population estimate
```

Это не финальный статистический вывод. Это разрешение перейти к распределениям,
estimators, bias/variance и intervals без скрытого подменивания популяции.

## Упражнения

1. Добавьте в `segment_reference.csv` сегмент по `acquisition_channel` и расширьте
   `segment_columns` в spec. Какие новые warnings появились?
2. Сделайте `U006` доступным в `sampling_frame.csv`. Как изменится coverage warning?
3. Удалите `sample_weight` или сделайте его равным `1` для всех строк. Почему это должно
   блокировать будущий weighted estimator?

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Target population | Все строки в файле | Группа, о которой мы хотим делать вывод |
| Sampling unit | Любая строка таблицы | Объект, который отбирается и должен быть независимой единицей анализа |
| Sampling frame | То же самое, что population | Список или механизм, через который units могли попасть в sample |
| Coverage bias | Ошибка только маленьких samples | Смещение из-за несовпадения target population и frame |
| Non-response | Просто пропуски, которые можно удалить | Отсутствие outcome после отбора, потенциально связанное с unit или сегментом |
| Sample weight | Косметическая колонка | Часть estimator contract при unequal inclusion probabilities |

## Дополнительное чтение

- [AAPOR: Standard Definitions](https://aapor.org/standards-and-ethics/standard-definitions/) — прочитайте background о coverage, measurement и nonresponse effects; это хорошая рамка для отделения sampling error от других ошибок.
- [Jae Kwang Kim: Statistics in Survey Sampling](https://arxiv.org/abs/2401.07625) — используйте как первичный обзор survey sampling, inclusion probabilities, weights и nonresponse adjustment перед уроками `09/03`-`09/04`.
- [NIST/SEMATECH e-Handbook: Comparisons based on data from one process](https://www.itl.nist.gov/div898/handbook/prc/section2/prc2.htm) — посмотрите различие parametric и non-parametric procedures и роль assumptions перед распределениями и интервалами.
- [NumPy: Random Generator](https://numpy.org/doc/stable/reference/random/generator.html) — вспомните воспроизводимый `Generator`; он понадобится для repeated sampling simulation и bootstrap в следующих уроках.
