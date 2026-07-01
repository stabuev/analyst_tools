# Rolling и expanding windows

> Оконный признак для даты прогноза должен смотреть назад, а не случайно заглядывать в
> текущую цель или будущие наблюдения.

- **Тип:** Build
- **Треки:** Decision
- **Пререквизиты:** `14-time-series/02-resampling`
- **Время:** ~75 минут
- **Результат:** вы строите lag, rolling и expanding features только из прошлого,
  фиксируете `lag`, `min_periods`, alignment и проверяете temporal leakage.

## Цели обучения

- Объяснить разницу между `rolling(value)` и `shift(1).rolling(value)`.
- Построить `lag_1`, rolling mean и expanding mean для каждого сегмента отдельно.
- Отделить warmup rows от настоящих ошибок данных.
- Выпустить leakage audit, где для каждого признака указаны source dates и latest source
  date.

## Проблема

После `14/02` у нас есть регулярный daily ряд `active_subscriptions`. Для baseline и
будущих моделей хочется добавить признаки: вчерашнее значение, среднее за 3 дня, среднее
за 7 дней, expanding mean.

Опасность в том, что оконные признаки выглядят безобидно:

```python
df["rolling_7"] = df.groupby("segment_id")["value"].rolling(7).mean()
```

Но для строки `2026-03-09` такой расчет включает само значение `2026-03-09`. Если эта
строка будет использоваться для обучения или backtest-прогноза на `2026-03-09`, признак
уже знает target. Модель станет выглядеть умнее, чем она будет в момент реального
forecast origin.

Урок строит feature builder, который требует `lag >= 1`, запрещает centered windows и
показывает, какие даты вошли в каждый признак.

## Концепция

Для forecast feature есть две даты:

| Дата | Смысл |
|---|---|
| `feature_date` | Дата, для которой строка признаков будет использована. |
| `source_date` | Историческая дата, значение которой попало в признак. |

Leakage-free правило простое:

```text
latest(source_date) < feature_date
```

Если признак для `2026-03-09` использует rolling-7 с `lag=1`, источники должны быть:

```text
2026-03-02, 2026-03-03, 2026-03-04, 2026-03-05,
2026-03-06, 2026-03-07, 2026-03-08
```

Текущее значение `2026-03-09` не входит в окно. Поэтому `rolling_7_mean_lag1` для
segment `all` равен:

```text
(998 + 1007 + 1016 + 1025 + 1034 + 1003 + 1012) / 7 = 1013.571429
```

Первые дни ряда не имеют достаточной истории для всех обязательных признаков. Это не
ошибка данных, а warmup. Такие строки нужно выпускать в output, но ставить
`include_in_training=false`, чтобы training window не сдвигался молча.

## Соберите это

Сначала реализуйте ручной rolling-3 для одного сегмента. Ключевой шаг - выбрать даты
строго до `feature_date`.

```python
from datetime import date, timedelta

values = {
    date(2026, 3, 2): 998,
    date(2026, 3, 3): 1007,
    date(2026, 3, 4): 1016,
    date(2026, 3, 5): 1025,
}

feature_date = date(2026, 3, 5)
lag = 1
window = 3
end_date = feature_date - timedelta(days=lag)
source_dates = [end_date - timedelta(days=offset) for offset in reversed(range(window))]
rolling_3 = sum(values[day] for day in source_dates) / window

assert source_dates == [date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)]
assert rolling_3 == 1007
```

Если заменить `lag = 0`, в окно попадет `2026-03-05`, то есть текущая цель. Если
включить centered window, окно может взять будущие даты. Оба случая должны блокироваться
до расчета.

Expanding mean устроен похожим образом: для даты `t` он берет все полные наблюдения до
`t - lag`, а не весь ряд до конца файла.

## Используйте это

Готовый артефакт:

```text
outputs/window_feature_builder.py
```

Запуск из корня урока:

```bash
python outputs/window_feature_builder.py \
  --series ../02-resampling/outputs/daily_resampled.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --spec ../data/tiny/window_feature_spec.json \
  --output-dir outputs
```

CLI пишет три файла:

- `outputs/window_features.csv` - строки признаков с `lag_1`, rolling и expanding
  features;
- `outputs/leakage_audit.csv` - source dates для каждого признака и каждой feature date;
- `outputs/window_feature_report.json` - blocking errors, warnings и summary.

В baseline `tiny` отчет валиден, но содержит два предупреждения:

```json
{
  "valid": true,
  "warnings": [
    "warmup_rows_excluded_from_training",
    "partial_source_rows_excluded_from_training"
  ]
}
```

Это ожидаемо: первые семь complete rows не имеют полного rolling-7 history, а partial row
`2026-03-17` видна в output, но не входит в training.

В pandas рабочий расчет должен сохранять тот же порядок: сначала `shift(1)`, потом
`rolling`.

```python
import pandas as pd

df = pd.read_csv("daily_resampled.csv")
df = df.sort_values(["segment_id", "observed_date"])

df["value_lag_1"] = df.groupby("segment_id")["value"].shift(1)
df["rolling_3_mean_lag1"] = (
    df.groupby("segment_id")["value"]
    .transform(lambda series: series.shift(1).rolling(window=3, min_periods=3).mean())
)
```

Но pandas не знает, что `include_in_training=false` означает partial period, а
`center=True` запрещен для forecast features. Поэтому рядом с кодом нужен spec и audit.

## Сломайте это

Проверьте пять поломок.

1. Поставьте `lag: 0` у `value_lag_1` в `window_feature_spec.json`. Check
   `feature_rules_are_past_only` должен стать blocking error.
2. Поставьте `center: true` у `rolling_3_mean_lag1`. Это тоже blocking error, потому что
   centered window может смотреть вперед.
3. Удалите строку `android/2026-03-05` из `daily_resampled.csv`. Check
   `complete_history_has_no_missing_dates` должен упасть.
4. Скопируйте строку `all/2026-03-02`. Check `source_segment_date_unique` должен найти
   дубликат grain.
5. Удалите колонку `delta_active`. Check `source_columns_present` должен остановить
   feature build до расчета.

Строгий режим:

```bash
python outputs/window_feature_builder.py \
  --series ../02-resampling/outputs/daily_resampled.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --spec ../data/tiny/window_feature_spec.json \
  --fail-on-warning
```

Он вернет non-zero exit code из-за warmup и partial rows. Это полезно, если downstream
pipeline не должен продолжать без явного review feature coverage.

## Проверьте это

Тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/14-time-series/03-rolling/tests -v
```

Они проверяют:

- воспроизводимость `window_feature_spec.json`;
- ручные значения `rolling_3_mean_lag1` и `rolling_7_mean_lag1`;
- первый training row после полного required history;
- исключение warmup и partial rows из training;
- блокировку `lag=0`, `center=true`, missing complete date, duplicate date и missing
  input column;
- CLI output и режим `--fail-on-warning`.

Критерий интерпретации: если `summary.blocking_errors` не пустой, feature table нельзя
использовать. Если есть warnings, feature table можно продолжить только с явным
пониманием, какие строки не попали в training и почему.

## Поставьте результат

Итоговый артефакт:

```text
outputs/window_feature_builder.py
```

Он принимает проверенный daily ряд из `14/02`, forecast scenario и
`window_feature_spec.json`, затем выпускает feature table и leakage audit. `code/main.py`
пересобирает committed outputs:

```bash
uv run --locked python phases/14-time-series/03-rolling/code/main.py
```

Следующие уроки используют эти признаки как диагностический слой: для trend/seasonality,
temporal leakage и baseline. Ограничение: этот урок не выбирает модель и не доказывает
точность прогноза. Он только делает временные признаки пригодными для честного
backtesting.

## Упражнения

1. Добавьте `rolling_5_mean_lag1` в `window_feature_spec.json` и объясните, с какой даты
   строки смогут входить в training, если этот признак станет required.
2. Сделайте `delta_lag_7` и проверьте, почему он появляется позже, чем `delta_lag_1`.
3. Добавьте nullable optional-признак и измените policy так, чтобы он не блокировал
   `feature_complete`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Lag feature | Это любое соседнее значение. | Значение источника на фиксированное число периодов раньше feature date. |
| Rolling window | Среднее по текущей окрестности даты. | Окно фиксированной длины; для forecast feature оно должно быть сдвинуто в прошлое. |
| Expanding window | Среднее по всему файлу. | Накопительный расчет только по доступной истории до cutoff или feature date. |
| `min_periods` | Косметический параметр pandas. | Минимальное число прошлых наблюдений, без которого признак считается неполным. |
| Warmup rows | Их можно удалить без следа. | Начальные строки без достаточной истории; они должны быть видимы и исключены из training. |
| Centered window | Удобный способ сгладить ряд. | Для forecasting feature это потенциальная temporal leakage, потому что окно может включить будущее. |
| Leakage audit | Лишний лог. | Доказательство, что source dates каждого признака строго раньше feature date. |

## Дополнительное чтение

- [pandas: Windowing operations](https://pandas.pydata.org/docs/user_guide/window.html) — разберите rolling, expanding и `min_periods`; после урока особенно важны границы окна и поведение на начальных строках.
- [pandas: Time series / date functionality](https://pandas.pydata.org/docs/user_guide/timeseries.html) — повторите indexing, shifting и time-aware operations, которые нужны для безопасного feature alignment.
- [Forecasting: Principles and Practice, Time series cross-validation](https://otexts.com/fpp3/tscv.html) — посмотрите, почему признаки и validation должны уважать forecast origin.
- [scikit-learn: Common pitfalls and recommended practices](https://scikit-learn.org/stable/common_pitfalls.html) — прочитайте раздел про data leakage; идея та же, даже если этот урок еще не строит ML-модель.
