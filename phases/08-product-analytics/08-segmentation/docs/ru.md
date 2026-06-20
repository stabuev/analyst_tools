# Сегментация без самообмана

> Сегмент не объясняет причину сам по себе. Хороший сегментный отчет заранее фиксирует разрезы, denominator, минимальный размер ячейки и честно отделяет описание от гипотезы.

**Тип:** Build  
**Треки:** product  
**Пререквизиты:** `08-product-analytics/07-monetization`  
**Время:** ~75 минут

## Цели обучения

- Заранее объявлять dimensions, периоды сравнения и minimum cell size.
- Считать segment activation rate на той же когорте, что и базовую метрику.
- Помечать exploratory-разрезы и не выдавать их за подтвержденные эффекты.
- Разделять падение общей метрики на within-segment effect и composition effect.
- Запрещать causal claims в сегментации без эксперимента или отдельного causal design.

## Проблема

После изменения onboarding команда видит, что D0 activation rate упал с `0.500000` до `0.333333`. Первое желание - открыть дашборд, накидать десятки breakdowns и найти виновника: platform, country, channel, app version, paywall variant, что угодно.

Так рождается опасная аналитика. Если смотреть много сегментов после факта, какой-нибудь разрез почти всегда будет выглядеть драматично. Маленькая ячейка даст rate `0%` или `100%`. Exploratory-находка станет слайдом "причина падения". Команда может откатить изменение из-за шума или, наоборот, проигнорировать реальную проблему в большом сегменте.

В этом уроке мы строим CLI-калькулятор сегментации для activation rate. Он делает пять вещей:

1. Берет сегменты только из спецификации.
2. Считает denominator по пользователям из тех же cohort periods.
3. Скрывает rates для маленьких ячеек.
4. Помечает exploratory-сегменты.
5. Разкладывает изменение общей метрики на изменение rates внутри platform и изменение состава platform-трафика.

## Концепция

Сегментация отвечает на вопрос "где именно изменилась метрика?", но не отвечает на вопрос "почему это случилось?". Чтобы не перепутать эти вопросы, у отчета должен быть контракт.

**Base metric не меняется.** Если базовая метрика - D0 activation rate, то сегментный rate считается так же: eligible users в когорте периода в denominator, пользователи с `feature_value_seen` в день регистрации в numerator. Нельзя в одном сегменте считать пользователей, в другом sessions, а в третьем события.

**Dimension объявлен заранее.** В спецификации есть `platform`, `acquisition_channel` и `country`. Первые два разреза predeclared: команда заранее решила, что они важны для решения. `country` exploratory: его можно смотреть, но нельзя использовать как доказательство.

**Minimum cell size защищает от красивого шума.** На tiny-данных threshold равен `1`, чтобы урок показывал все строки. В реальной задаче threshold будет намного выше. Если ячейка меньше threshold, калькулятор оставляет counts для прозрачности, но очищает `activation_rate` и `traffic_share`.

**Traffic share так же важен, как rate.** Общая метрика может падать не потому, что все сегменты стали хуже, а потому что выросла доля сегмента с низким baseline rate. Поэтому в отчете есть `traffic_share` и decomposition.

**Decomposition не является причинностью.** Для primary dimension `platform` калькулятор строит строки `decomposition`. Формула:

```text
within_segment_effect = comparison_share * (comparison_rate - baseline_rate)
composition_effect = (comparison_share - baseline_share) * baseline_rate
total_delta_contribution = within_segment_effect + composition_effect
```

В tiny-данных общий delta равен `-0.166667`. Android дает `-0.166667` within и `-0.083333` composition, web дает `+0.083333` composition. Это хороший повод проверить mobile onboarding, но не доказательство, что platform стала причиной падения.

## Соберите это

Артефакт урока находится в `outputs/segmentation_calculator.py`. Он использует только стандартную библиотеку Python и читает четыре входа:

- `data/tiny/users.csv` - пользователи, даты регистрации и пользовательские dimensions.
- `data/tiny/events.csv` - события из tracking plan.
- `02-event-model/outputs/tracking_plan.json` - допустимые event names и политика late events.
- `outputs/segmentation_spec.json` - контракт сегментации.

Запустите калькулятор из корня репозитория:

```bash
python3 phases/08-product-analytics/08-segmentation/outputs/segmentation_calculator.py \
  --users phases/08-product-analytics/data/tiny/users.csv \
  --events phases/08-product-analytics/data/tiny/events.csv \
  --tracking-plan phases/08-product-analytics/02-event-model/outputs/tracking_plan.json \
  --spec phases/08-product-analytics/08-segmentation/outputs/segmentation_spec.json \
  --output phases/08-product-analytics/08-segmentation/outputs/segments.csv \
  --report /tmp/segmentation-report.json
```

Калькулятор проверяет:

- наличие обязательных колонок в users/events;
- что `activation_event_name` есть в tracking plan;
- валидность timezone и cohort periods;
- что primary decomposition dimension является predeclared;
- отсутствие причинных claims в спецификации;
- уникальность `user_id` и `event_id`;
- что activation events имеют `user_id`, ссылаются на известных пользователей и не нарушают late-event policy.

Дубликаты `event_id` делают quality report невалидным, но таблица все равно строится с дедупликацией. Это полезный компромисс: аналитик видит метрику и одновременно не может отправить результат как чистый.

## Используйте это

Посмотрите на первые строки `outputs/segments.csv`:

```text
overall baseline:   eligible_users=4, activated_users=2, activation_rate=0.500000
overall comparison: eligible_users=3, activated_users=1, activation_rate=0.333333
```

Теперь сравните platform:

```text
platform=android baseline:   eligible_users=2, activated_users=1, activation_rate=0.500000
platform=android comparison: eligible_users=1, activated_users=0, activation_rate=0.000000
platform=web comparison:     eligible_users=1, activated_users=1, activation_rate=1.000000
```

Если остановиться здесь, легко написать "android просел". Но decomposition показывает аккуратнее:

```text
android total_delta_contribution = -0.250000
web total_delta_contribution     =  0.083333
overall_delta                    = -0.166667
```

Такой вывод честнее:

> В comparison-периоде общий D0 activation rate ниже на `0.166667`. В разложении по platform основной отрицательный вклад дает android: часть связана с более низким rate внутри сегмента, часть - с изменением доли android в трафике. Это гипотеза для проверки mobile onboarding, а не причинное доказательство.

Запустите пример:

```bash
python3 phases/08-product-analytics/08-segmentation/code/main.py
```

Он печатает ручную проверку baseline/comparison, summary калькулятора, exploratory-строку `country=RU` и decomposition-строку `platform=android`.

## Сломайте это

Попробуйте три поломки.

1. Увеличьте `minimum_cell_size` до `2`. Строка `platform=web` в baseline сохранит `eligible_users=1`, но получит `is_reportable=false`, пустой `activation_rate` и пустой `traffic_share`.
2. Поставьте `primary_decomposition_dimension` в `country`. Калькулятор откажется строить таблицу, потому что `country` объявлен как exploratory.
3. Добавьте `"causal"` в `allowed_claim_types`. Quality report станет невалидным: этот артефакт разрешает descriptive и hypothesis claims, но не causal claims.

Обратите внимание на важную деталь: плохой вход не должен тихо давать красивый CSV. В продуктовой аналитике опаснее всего не ошибка, которая падает, а ошибка, которая выглядит как инсайт.

## Проверьте это

Запустите тесты урока:

```bash
cd phases/08-product-analytics/08-segmentation
python3 -m unittest discover -s tests -v
```

Тесты проверяют поведение, а не только наличие файлов:

- tiny-таблица имеет `22` строки и ожидаемые overall rates;
- `segments.csv` совпадает с расчетом;
- exploratory country-сегменты помечены отдельно от predeclared-разрезов;
- small cells не публикуют rate;
- дубликаты событий репортятся и дедуплицируются;
- late activation event, неизвестный user_id и пустой user_id ломают quality report;
- timezone `Europe/Moscow` управляет назначением пользователя в baseline/comparison;
- decomposition contributions суммируются в overall delta;
- CLI возвращает ненулевой код для невалидной спецификации.

## Поставьте результат

Готовый результат урока:

- `outputs/segmentation_spec.json` - контракт сегментации;
- `outputs/segmentation_calculator.py` - CLI-калькулятор;
- `outputs/segments.csv` - именованный артефакт с overall, segment_metric и decomposition rows;
- `outputs/artifact.json` - описание артефакта для индекса курса;
- `tests/test_main.py` - behavioral tests.

Перед handoff сформулируйте вывод в безопасной форме:

```text
Мы видим descriptive drop в D0 activation rate с 0.500000 до 0.333333.
В platform decomposition android дает отрицательный вклад, web - положительный.
Country-разрез exploratory и используется только для генерации гипотез.
Причинный вывод о platform/onboarding без эксперимента не делаем.
```

Это и есть "сегментация без самообмана": отчет помогает выбрать следующий проверяемый шаг, но не притворяется экспериментом.

## Упражнения

1. Добавьте в спецификацию еще один predeclared-разрез из `users.csv` и объясните, почему он заслуживает этого статуса.
2. Поднимите `minimum_cell_size` и проверьте, какие строки перестают быть reportable.
3. Измените `observation_end_date` на более раннюю дату и объясните, почему часть comparison-пользователей должна быть исключена.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Segment | "Сегмент объясняет причину изменения" | Разрез данных, который описывает, где метрика отличается или меняется |
| Predeclared dimension | "Любой breakdown одинаково надежен" | Разрез, объявленный до просмотра результата и привязанный к решению |
| Exploratory segment | "Раз нашли после факта, значит можно решать" | Разведочный разрез для гипотез, а не для доказательства эффекта |
| Minimum cell size | "Маленький сегмент можно показать с оговоркой" | Порог, ниже которого rate/share не публикуются как надежные значения |
| Composition effect | "Общая метрика меняется только из-за поведения" | Вклад изменения доли сегмента в общий delta |
| Within-segment effect | "Если общий rate упал, все сегменты стали хуже" | Вклад изменения rate внутри сегмента при сравнении периодов |

## Дополнительное чтение

- [Mixpanel Insights documentation](https://docs.mixpanel.com/docs/reports/insights) - посмотрите, как breakdowns используются для сравнения групп и почему сам интерфейс не заменяет контракт анализа.
- [Amplitude Event Segmentation documentation](https://amplitude.com/docs/analytics/charts/event-segmentation/event-segmentation-build) - полезно сопоставить наш `dimensions` contract с user-property segmentation в продуктовой аналитике.
- [Предыдущий урок про монетизацию](../../07-monetization/docs/ru.md) - повторите идею window completeness и denominator discipline перед сегментацией.
- [Дизайн фазы 08](../../../../docs/phase-08-design.md) - связывает metric tree, events, cohorts, retention, monetization и segmentation в один продуктовый цикл.
