# Постановка ML-задачи

> ML начинается не с модели, а с договора: какую строку мы скорим, какой будущий outcome
> считаем target и какую бизнес-ошибку хотим уменьшить.

**Тип:** Case  
**Треки:** ML  
**Пререквизиты:** `09-applied-statistics/10-robust-methods`  
**Время:** ~75 минут  
**Результат:** вы формулируете supervised ML-задачу через business decision, prediction
unit, target horizon, prediction time, positive/negative class, allowed feature sources и
no-causal-claim boundary.

## Цели обучения

- Перевести расплывчатое «предсказать churn» в machine-readable `problem_spec.json`.
- Зафиксировать prediction unit, prediction time и target horizon до split и modeling.
- Отличить allowed feature sources от post-prediction leakage и target leakage.
- Назвать positive/negative class и проверить, что обе реально присутствуют в eligible
  population.
- Выпустить readiness report, который разрешает проектировать split, но не делает causal
  claim о retention offer.

## Проблема

Команда поддержки подписочного сервиса может отправить ограниченное число retention offers.
За 7 дней до окончания trial нужно понять, кого стоит разобрать вручную: пользователей с
высоким риском churn или всех подряд.

Самый опасный вариант - сразу собрать «все колонки про пользователя», обучить
classification model и радоваться ROC AUC. Такая модель может отвечать на другой вопрос:

- строка данных - не момент скоринга, а просто `user_id`;
- target «churn» не имеет horizon и может быть известен уже после решения;
- positive class есть, а negative class не описан;
- features включают future cancellation events или outcome retention offer;
- threshold выбирается на test, потому что так лучше выглядит отчет;
- model card обещает, что offer «снижает churn», хотя модель только ранжирует риск.

В этом уроке вы еще не обучаете модель. Вы строите gate, который отвечает на более ранний
вопрос: можно ли эту задачу вообще отдавать в modeling.

## Концепция

Supervised ML problem framing держится на шести слоях.

| Слой | Вопрос | Что ломается без него |
|---|---|---|
| Business decision | Какое действие будет принято по score? | Оптимизируется красивая метрика, а не ошибка решения. |
| Prediction unit | Что значит одна строка? | Один пользователь попадает в разные роли или моменты времени. |
| Prediction time | Когда score должен быть доступен? | Features подсматривают события из будущего. |
| Target horizon | После какого окна target считается известным? | Label смешивает уже случившийся churn и незавершенное окно. |
| Class semantics | Что такое positive и negative class? | Accuracy выглядит хорошо, но модель не ловит нужный риск. |
| Claim boundary | Что model score не доказывает? | Predictive model превращают в causal claim о действии. |

Для фазы 15 задача такая:

```text
За 7 дней до окончания trial оценить риск churn в следующие 14 дней
для eligible users, чтобы команда поддержки могла выбрать до 3 retention offers в день.
```

Prediction row - не просто `user_id`, а `snapshot_id`: один пользователь в конкретный
`prediction_time`. Target `churn_14d` измеряется после полного 14-дневного окна. Feature
source допустим только если он известен до `prediction_time`.

Это не causal задача. Если пользователь с высоким score получил offer и не ушел, модель не
доказывает, что offer его спас. Она только говорит: «до действия он выглядел рискованным».

## Соберите это

Начните с ручного контроля grain. Если prediction unit объявлен как `snapshot_id`, ключ
должен быть уникальным, а `user_id + prediction_time` не должен размножать одну строку.

```python
from collections import Counter

keys = [row["snapshot_id"] for row in snapshots]
duplicates = [key for key, count in Counter(keys).items() if count > 1]
assert duplicates == []
```

Теперь проверьте, что target действительно появляется после prediction time и полного
horizon:

```python
from datetime import timedelta

horizon_days = 14
prediction_time = parse_timestamp(snapshot["prediction_time"])
label_observed_at = parse_timestamp(label["label_observed_at"])
assert label_observed_at >= prediction_time + timedelta(days=horizon_days)
```

Последний ручной контроль - feature availability. Source можно использовать в модели
только если он доступен до scoring moment:

```python
allowed_timings = {
    "known_before_prediction_time",
    "lookback_before_prediction_time",
}
assert source["timing"] in allowed_timings
assert source["allowed"] == "true"
```

Эти проверки не делают модель лучше. Они защищают следующий этап от бессмысленного
baseline: если target или features определены нечестно, любой score будет подозрительным.

## Используйте это

Урок поставляет CLI `ml-problem-spec-validator`. Запустите его из корня урока:

```bash
python outputs/ml_problem_spec_validator.py \
  --spec ../data/tiny/problem_spec.json \
  --snapshots ../data/tiny/ml_scoring_snapshots.csv \
  --labels ../data/tiny/ml_labels.csv \
  --feature-sources ../data/tiny/feature_source_inventory.csv \
  --output outputs/ml_problem_readiness_report.json
```

Отчет содержит:

- `valid`: можно ли переходить к split design;
- `checks`: machine-readable проверки с `id`, `severity`, `observed`, `expected` и
  sample ошибок;
- `summary.eligible_prediction_rows`: сколько строк попало в eligible population;
- `summary.positive_labels` и `summary.negative_labels`: проверка class semantics;
- `summary.blocking_errors`: ошибки, которые запрещают modeling;
- `summary.warnings`: ограничения, которые нужно пронести дальше.

В baseline `tiny` отчет валиден, но содержит warning:

```json
{
  "valid": true,
  "warnings": ["class_imbalance_expected"],
  "eligible_prediction_rows": 12,
  "positive_labels": 4,
  "negative_labels": 8
}
```

Это хороший результат для первого урока. Tiny profile уже содержит три будущих
prediction-date блока для split design, но imbalance не блокирует постановку задачи и
заранее запрещает делать accuracy основной метрикой.

## Сломайте это

Проверьте пять поломок.

1. Скопируйте первую строку `ml_scoring_snapshots.csv`. Check
   `prediction_unit_is_snapshot` должен найти duplicate `snapshot_id`.
2. Поставьте `label_observed_at = 2026-05-12T12:00:00+03:00` для `S001`. Check
   `target_has_horizon_and_classes` должен заблокировать target: horizon еще не
   завершился.
3. Добавьте `cancellation_events_after_prediction` в `allowed_feature_sources`. Check
   `feature_sources_available_before_prediction` должен поймать post-prediction leakage.
4. Поменяйте `threshold_policy.selection_data` на `test`. Check
   `evaluation_policies_predeclared` должен упасть: test не выбирает threshold.
5. Замените `model_card_policy.claim_boundary` на «offer will reduce churn». Check
   `no_causal_claim_boundary` должен заблокировать causal wording.

Строгий режим возвращает non-zero exit code даже при warnings:

```bash
python outputs/ml_problem_spec_validator.py \
  --spec ../data/tiny/problem_spec.json \
  --snapshots ../data/tiny/ml_scoring_snapshots.csv \
  --labels ../data/tiny/ml_labels.csv \
  --feature-sources ../data/tiny/feature_source_inventory.csv \
  --fail-on-warning
```

Он пригодится, если pipeline не должен продолжать без review imbalance.

## Проверьте это

Behavioral tests запускаются так:

```bash
uv run --locked python -m unittest discover \
  -s phases/15-applied-machine-learning/01-problem-framing/tests -v
```

Они проверяют:

- валидный tiny-profile и warning про imbalance;
- воспроизводимость `data/generate_data.py --check`;
- запуск `code/main.py` и запись readiness report;
- дубликат prediction unit;
- label до окончания horizon;
- отсутствие negative class;
- post-prediction feature source в allowed list;
- threshold selection на test;
- causal overclaim в model-card policy;
- unknown label snapshot;
- отсутствие обеих target classes;
- CLI exit codes и `--fail-on-warning`.

Интерпретация:

```text
valid = true
```

означает, что problem framing согласован и можно проектировать split. Это не означает,
что модель обучена, baseline побежден, threshold выбран или retention offer доказал
эффект.

## Поставьте результат

Итоговый артефакт:

```text
outputs/ml_problem_spec_validator.py
```

Он принимает `problem_spec.json`, scoring snapshots, labels и feature-source inventory и
возвращает JSON-аудит готовности ML-постановки.

`code/main.py` запускает валидатор на committed `tiny` профиле и обновляет:

```text
outputs/ml_problem_readiness_report.json
```

Следующий урок использует этот problem contract как вход для train/validation/test split
manifest: split уже не будет выбирать target, horizon или prediction unit заново.

## Упражнения

1. Переформулируйте задачу для paid subscribers вместо trial users: что изменится в
   prediction unit, eligibility и target horizon?
2. Добавьте source `last_seen_after_prediction` и опишите, почему он должен быть
   forbidden даже если сильно улучшает validation score.
3. Измените business budget с 3 до 1 offer в день и объясните, почему это меняет
   threshold policy сильнее, чем ROC AUC.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Prediction unit | Это всегда пользователь. | Одна строка, для которой в конкретный момент строится prediction. |
| Prediction time | Дата выгрузки данных. | Момент, в который score должен быть доступен и после которого features запрещены. |
| Target horizon | Просто поле `churned`. | Будущее окно, после которого label можно считать наблюденным. |
| Positive class | Класс с большим числом строк. | Событие, риск которого модель должна обнаружить для решения. |
| Negative class | Все остальное без описания. | Бизнес-смысл отсутствия positive event внутри target horizon. |
| Feature availability | Колонка есть в таблице. | Источник известен до prediction time и не содержит target или action outcome. |
| Leakage | Только явный target в features. | Любая информация, недоступная в scoring moment или выбранная с подсмотром evaluation data. |
| Threshold policy | Берем 0.5 по умолчанию. | Предварительное правило перевода score в действие с учетом budget/cost. |
| No-causal-claim boundary | Юридическая оговорка. | Запрет выдавать predictive score за эффект intervention. |

## Дополнительное чтение

- [scikit-learn: Common pitfalls and recommended practices](https://scikit-learn.org/stable/common_pitfalls.html) — прочитайте разделы про inconsistent preprocessing и data leakage; они объясняют, почему split и feature availability нужно фиксировать до fit.
- [scikit-learn: Model selection and evaluation](https://scikit-learn.org/stable/model_selection.html) — используйте разделы про metrics/scoring и decision threshold как ориентир для следующих уроков о metric policy и threshold selection.
- [Model Cards for Model Reporting](https://arxiv.org/abs/1810.03993) — посмотрите, как intended use, evaluation conditions, limitations и subgroup performance превращают модель из notebook score в ответственный артефакт.
