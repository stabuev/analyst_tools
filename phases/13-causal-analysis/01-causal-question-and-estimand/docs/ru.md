# Причинный вопрос и estimand

> До формулы эффекта нужно договориться, чьи два потенциальных сценария мы сравниваем.

**Тип:** Learn  
**Треки:** Decision, Product  
**Пререквизиты:** 10/11 — Протокол решения и коммуникация  
**Время:** ~75 минут  
**Результат:** переводит продуктовый вопрос в target trial-style causal spec: treatment,
contrast, outcome, time zero, population и ATE/ATT/LATE estimand, явно фиксируя
consistency, exchangeability, positivity и interference risks.

## Цели обучения

- Отличать описательный вопрос от causal question с counterfactual contrast.
- Определять treatment, comparator, time zero, target population и outcome window до
  анализа данных.
- Различать ATE, ATT и LATE по популяции усреднения, а не по выбранной библиотеке.
- Фиксировать causal assumptions как неподтвержденные требования дизайна.
- Не выдавать корректно оформленный estimand за уже identified и estimated effect.

## Проблема

Команда подписочного сервиса запустила assisted onboarding: специалист помогает
пользователю пройти первые шаги продукта. В сырых данных видно:

```text
received_assistance = true  -> activation_14d = 4 / 6
received_assistance = false -> activation_14d = 3 / 4
```

Наивная разница равна примерно `-8,3` процентного пункта. Значит ли это, что помощь
вредит?

Нет. Помощь чаще получали пользователи с высоким `friction_score`, плохим устройством,
сбоями приложения и низкой исходной активностью. Treatment выдавался неслучайно —
возникло **confounding by indication**. Сравнение наблюдаемых treated и untreated
отвечает на вопрос «чем различались две сложившиеся группы», но не на вопрос «что
случилось бы с одной и той же target population при двух стратегиях».

До regression, matching или propensity score нужно сформулировать объект оценки:

```text
population + treatment + comparator + time zero + outcome + horizon + effect measure
```

Если эта строка неоднозначна, более сложный estimator лишь даст точное число для
непонятного вопроса.

## Концепция

### Наблюдаемое сравнение не является counterfactual contrast

Для пользователя `i` мысленно существуют два потенциальных результата:

```text
Y_i(assisted)
Y_i(no_assistance)
```

В реальности наблюдается только один. Индивидуальный эффект:

```text
Y_i(assisted) - Y_i(no_assistance)
```

не наблюдается напрямую. Causal estimand усредняет такой contrast по объявленной
популяции.

В уроке бизнес решает, делать ли assisted onboarding стандартной опцией для eligible
high-friction users. Поэтому primary estimand:

```text
ATE = E[Y(assisted) - Y(no_assistance) | eligible_high_friction_users]
```

Outcome — `activation_14d`, effect measure — абсолютная разница рисков.

### ATE, ATT и LATE отвечают разным заказчикам

| Estimand | Где усредняется эффект | Рабочий смысл |
|---|---|---|
| ATE | В объявленной target population | Что было бы при применении стратегии ко всей eligible population |
| ATT | Среди фактически treated users | Каков средний эффект для тех, кто реально получил treatment |
| LATE | Среди compliers относительно instrument | Каков локальный эффект для пользователей, чье treatment меняется из-за instrument |

ATT не является «ATE после matching», а LATE не является «ATE с еще одной колонкой».
Смена estimand меняет популяцию и смысл решения.

### Time zero синхронизирует дизайн

В target trial entry, eligibility, treatment assignment и follow-up начинаются от одного
момента. В уроке:

```text
time zero = первый friction assessment после регистрации и до offer
```

Treatment:

```text
начать одну 30-минутную assisted session в течение 24 часов после time zero
```

Comparator:

```text
не начинать assisted session в течение тех же 24 часов
```

Если определить time zero после treatment start, treated user должен «дожить» до
получения treatment, а comparator может войти в анализ раньше. Это меняет eligibility и
создает временное смещение.

### Treatment должен иметь операционное определение

`received_assistance = true` недостаточно. Нужно знать:

- что считается началом treatment;
- какой допустим grace period;
- какие версии treatment считаются одной стратегией;
- считается ли offer без session treatment;
- что является comparator в том же временном окне.

В `target_trial_spec.json` offer без session не считается treatment. Это важно:
`offered_assistance` и `received_assistance` отвечают на разные причинные вопросы.

### Assumptions — не галочки «выполнено»

Первый урок фиксирует четыре требования:

1. **Consistency:** наблюдаемый outcome соответствует потенциальному outcome реально
   полученной, достаточно однозначной версии treatment.
2. **Exchangeability:** после обоснованного pre-treatment adjustment treated и
   comparator сравнимы по потенциальным outcomes.
3. **Positivity:** в нужных covariate strata возможны обе стратегии.
4. **Interference:** treatment одного пользователя не меняет outcome другого.

На этом этапе их статус — `untested`. Валидатор проверяет, что assumptions названы и
связаны с будущими evidence checks, но не может доказать их истинность.

### Target trial — спецификация вопроса, а не притворный эксперимент

Target trial-style contract полезен, потому что заставляет явно назвать:

```text
eligibility
treatment strategies
assignment procedure
time zero
follow-up
outcomes
causal contrast
analysis unit
```

В нашем наборе `assignment_type = observational_nonrandomized`. Мы не переименовываем
наблюдательные данные в эксперимент. Напротив, target trial показывает, какой
гипотетический эксперимент мы хотели бы эмулировать и где потребуются identification
assumptions.

## Соберите это

Ручная часть урока находится в `code/main.py`. Сначала она строит target population без
causal library:

```python
def manual_target_population():
    return sorted(
        user_id
        for user_id, user in users.items()
        if user["is_test_user"] == "false"
        and user["eligible_for_program"] == "true"
        and int(baseline[user_id]["friction_score"]) >= 50
    )
```

Это дает десять пользователей:

```text
U001-U007, U010-U012
```

`U008` и `U009` не проходят friction threshold, `U999` является test user.

### Шаг 1: напишите causal question одним предложением

Используйте форму:

```text
Как изменился бы OUTCOME в HORIZON у POPULATION,
если бы все следовали TREATMENT,
по сравнению со сценарием COMPARATOR?
```

Для урока:

```text
Как изменилась бы 14-дневная активация eligible high-friction users,
если бы каждый получил assisted onboarding в течение 24 часов после time zero,
по сравнению со сценарием без такой помощи?
```

### Шаг 2: отделите treatment от offer

В данных есть:

```text
offered_assistance
received_assistance
offered_at
started_at
```

Primary treatment определяется через `received_assistance` и `started_at`. Пользователь
`U005` получил offer, но не начал session; для primary contrast он относится к
`no_assistance_within_24h`.

### Шаг 3: объявите target population

`outputs/target_trial_spec.json` хранит criteria как ссылки на таблицу и поле:

```json
[
  {"table": "users", "field": "is_test_user", "operator": "==", "value": false},
  {"table": "users", "field": "eligible_for_program", "operator": "==", "value": true},
  {
    "table": "pre_treatment_behavior",
    "field": "friction_score",
    "operator": ">=",
    "value": 50
  }
]
```

В eligibility нельзя добавить `onboarding_completed_48h`: это post-treatment mediator.
Нельзя молча оставить только `telemetry_complete_30d = true`: это меняет population
через post-treatment selection.

### Шаг 4: выберите estimand

В `outputs/estimand.json`:

```json
{
  "estimand_type": "ATE",
  "population_scope": "eligible_population",
  "outcome_id": "activation_14d",
  "time_horizon_days": 14,
  "effect_measure": "risk_difference"
}
```

Если заменить scope на `treated_population`, это станет ATT. Если выбрать LATE, нужно
назвать instrument и population `compliers`.

### Шаг 5: оставьте identification незавершенной

Корректный статус первого урока:

```text
claim_status = design_ready_for_identification
identification_status = not_yet_identified
estimator_status = not_selected
```

Это не скромность ради скромности. DAG и adjustment set появятся в следующих уроках.
Сейчас еще нельзя утверждать, что observed data идентифицируют ATE.

Запустите прозрачный пример:

```bash
uv run --locked python phases/13-causal-analysis/01-causal-question-and-estimand/code/main.py
```

Результат содержит:

```json
{
  "target_population_count": 10,
  "treated_users": 6,
  "comparator_users": 4,
  "identification_status": "not_yet_identified",
  "audit_valid": true,
  "warnings": ["observational_assignment_requires_identification"]
}
```

## Используйте это

Артефакт урока — CLI `causal_question_validator.py`. Он проверяет три контракта:

- `causal_question.json` — бизнес-вопрос и допустимый claim status;
- `target_trial_spec.json` — population, time zero, treatment, comparator, follow-up и
  outcomes;
- `estimand.json` — ATE/ATT/LATE, population scope, effect measure и assumptions.

Запуск из корня урока:

```bash
uv run --locked python outputs/causal_question_validator.py \
  --question outputs/causal_question.json \
  --target-trial outputs/target_trial_spec.json \
  --estimand outputs/estimand.json \
  --data-contract ../data/contract.json \
  --data-root ../data/tiny \
  --output outputs/causal_question_audit.json
```

CLI проверяет:

- согласованность ID между question, target trial и estimand;
- существование таблиц и полей в data contract;
- отсутствие post-treatment полей в eligibility и baseline covariates;
- две операционные treatment strategies, treatment versions и grace period;
- соответствие ATE/ATT/LATE объявленной population;
- наличие четырех causal assumptions;
- treatment start после time zero;
- достаточный follow-up для primary и secondary outcomes;
- отсутствие effect claim до identification.

Успешный запуск возвращает `0`, blocking failure — `1`, ошибка чтения контракта — `2`.
Warning `observational_assignment_requires_identification` остается намеренно: хороший
question contract еще не делает observational comparison причинным.

## Сломайте это

### Подмените ATE на ATT только названием

Оставьте `estimand_type = ATE`, но поменяйте:

```json
"population_scope": "treated_population"
```

Падает `estimand_population_alignment`. Нельзя обещать эффект для всей eligible
population, усреднив его только по treated users.

### Добавьте mediator в eligibility

Добавьте criterion:

```json
{
  "table": "outcomes",
  "field": "onboarding_completed_48h",
  "operator": "==",
  "value": true
}
```

Падает `target_population_contract`: поле имеет timing `post_treatment`.

### Сдвиньте treatment до time zero

Для `U001` замените `started_at` на:

```text
2026-07-01T09:55:00+03:00
```

При `time_zero = 10:00` падает `time_zero_treatment_followup_order`.

### Объявите LATE без instrument

Поменяйте:

```json
"estimand_type": "LATE",
"population_scope": "compliers"
```

Без `instrument` валидатор блокирует spec. Encouragement станет предметом отдельного
quasi-experimental design, а не декоративным именем estimand.

### Разрешите causal claim раньше времени

Поменяйте statuses на `identified` и `estimated`. Падает
`claim_status_is_pre_identification`: урок 13/01 фиксирует вопрос, но еще не строит DAG,
не выбирает adjustment set и не оценивает effect.

## Проверьте это

Behavioral suite запускается так:

```bash
uv run --locked python -m unittest \
  phases/13-causal-analysis/01-causal-question-and-estimand/tests/test_main.py
```

Проверки покрывают:

- десять пользователей target population, шесть treated и четыре comparator;
- byte-reproducible генерацию `tiny`;
- согласованность question/trial/estimand IDs;
- запрет post-treatment eligibility;
- обязательные treatment versions;
- ATE/ATT/LATE population semantics;
- consistency, exchangeability, positivity и interference assumptions;
- treatment timing и follow-up;
- grain `user_id`;
- запрет premature causal claim;
- CLI exit codes и report output.

Контрольная интерпретация:

```text
valid = true
```

означает «вопрос и estimand внутренне согласованы и данные соответствуют временному
контракту». Это не означает:

```text
effect identified
assumptions proven
treatment beneficial
estimator selected
```

## Поставьте результат

Переиспользуемый артефакт:

```text
outputs/causal_question_validator.py
```

Его можно применить к другому observational study, если подготовить:

```text
causal_question.json
target_trial_spec.json
estimand.json
data/contract.json
data profile
```

Для передачи вместе с артефактом используйте:

```text
outputs/causal_question.json
outputs/target_trial_spec.json
outputs/estimand.json
outputs/causal_question_audit.json
```

Следующий урок добавит causal DAG и identification map. Там появится вопрос не только
«что хотим оценить», но и «какие paths нужно закрыть, чтобы observational data могли
идентифицировать этот estimand».

## Упражнения

1. Переформулируйте primary estimand как ATT и обновите question, population scope и
   notation без внутренних противоречий.
2. Добавьте outcome `cancelled_subscription_30d` и сформулируйте effect measure с
   направлением риска.
3. Опишите отдельный LATE для `capacity_lottery_v1`: назовите instrument, compliers,
   treatment, outcome и ограничения переноса локального эффекта на всю population.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Causal question | Любой вопрос со словом «влияет» | Counterfactual contrast treatment и comparator для population, outcome и horizon |
| Estimand | Метод расчета коэффициента | Формально определенный объект оценки до выбора estimator |
| Estimator | То же самое, что estimand | Процедура вычисления estimate для заданного estimand |
| ATE | Среднее среди treated | Средний treatment effect в target population |
| ATT | ATE после фильтра | Средний effect среди фактически treated population |
| LATE | Более надежный ATE | Локальный effect для compliers относительно валидного instrument |
| Time zero | Дата выгрузки | Общий момент eligibility, strategy assignment и начала follow-up |
| Consistency | Treatment записан boolean | Наблюдаемый outcome соответствует достаточно однозначной полученной стратегии |
| Exchangeability | В группах одинаковый размер | После корректного conditioning treatment не связан с potential outcomes |
| Positivity | Propensity score не равен среднему | В релевантных strata возможны обе treatment strategies |
| Interference | Нет дубликатов пользователей | Treatment одного unit не меняет outcome другого unit |

## Дополнительное чтение

- [Hernán и Robins: Causal Inference — What If](https://miguelhernan.org/whatifbook) — прочитайте главы о potential outcomes, target trials, exchangeability и positivity;
  они дают основную понятийную рамку фазы.
- [Hernán и Robins: Using Big Data to Emulate a Target Trial](https://pmc.ncbi.nlm.nih.gov/articles/PMC4832051/) — разберите, как явная спецификация eligibility, treatment strategies, time zero и
  follow-up предотвращает типовые design biases в observational research.
- [ICH E9(R1): Estimands and Sensitivity Analysis](https://database.ich.org/sites/default/files/E9-R1_Step4_Guideline_2019_1203.pdf) — используйте framework treatment, population, variable, intercurrent events и
  population-level summary как строгую проверку полноты estimand.
- [DoWhy: Estimating Causal Effects](https://www.pywhy.org/dowhy/main/user_guide/causal_tasks/estimating_causal_effects/index.html) — обратите внимание на разделение model, identify, estimate и refute; библиотека
  начинается после явного causal question и не создает assumptions автоматически.
