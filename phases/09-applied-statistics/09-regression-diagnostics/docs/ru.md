# Диагностика регрессии

> Regression summary без diagnostics - это витрина без проверки фундамента.

**Тип:** Build  
**Треки:** Product, ML  
**Пререквизиты:** `09-applied-statistics/08-linear-regression`  
**Время:** ~75 минут  
**Результат:** проверяет residual patterns, heteroscedasticity, leverage, influence,
multicollinearity, non-linearity и specification risks, превращая diagnostics в
machine-readable flags и ограничения отчета.

## Цели обучения

- Читать residuals, fitted values, leverage и Cook's distance.
- Проверять condition number и VIF для multicollinearity.
- Не запускать формальные тесты там, где sample слишком мал.
- Выпускать diagnostic flags вместо текстового summary.
- Строить компактную diagnostic figure для handoff.

## Проблема

В `09/08` OLS runner выдал coefficient table. Но коэффициент с p-value не отвечает на
вопрос:

```text
Можно ли доверять assumptions, от которых зависит этот inference?
```

Если residuals имеют pattern, errors heteroscedastic, predictors collinear, а одна строка
имеет огромный influence, coefficient interval становится хрупким. Поэтому следующий шаг -
не новый вывод, а диагностика.

## Концепция

### Residuals

```text
residual_i = y_i - fitted_i
```

Среднее residuals в OLS с intercept должно быть почти ноль. Но нулевое среднее не
доказывает правильную спецификацию.

### Leverage и influence

Leverage показывает необычность строки в `X`. Cook's distance показывает, насколько строка
влияет на fitted coefficients.

### Multicollinearity

Condition number и VIF отвечают на вопрос, не объясняют ли predictors друг друга настолько
сильно, что coefficients становятся нестабильными.

## Соберите это

Из `09/08` model report возьмите:

```python
X = report["design_matrix"]["rows"]
y = report["design_matrix"]["outcome"]
```

Fit:

```python
result = sm.OLS(y, X, hasconst=True).fit()
influence = OLSInfluence(result)
```

Diagnostics:

```python
residuals = result.resid
leverage = influence.hat_matrix_diag
cooks = influence.cooks_distance[0]
```

## Используйте это

Запустите артефакт:

```bash
uv run --locked python phases/09-applied-statistics/09-regression-diagnostics/outputs/regression_diagnostics_checker.py \
  --model-report phases/09-applied-statistics/08-linear-regression/outputs/model_report.json \
  --spec phases/09-applied-statistics/09-regression-diagnostics/outputs/diagnostic_spec.json \
  --output-report phases/09-applied-statistics/09-regression-diagnostics/outputs/diagnostics.json \
  --output-figure phases/09-applied-statistics/09-regression-diagnostics/outputs/regression_diagnostics.png
```

Короткий пример:

```bash
uv run --locked python phases/09-applied-statistics/09-regression-diagnostics/code/main.py
```

Report содержит `warning_flags`, diagnostics по residuals, VIF, leverage, Cook distance,
normality и heteroscedasticity.

## Сломайте это

1. Передайте `model_report.json` с `valid = false`.

Ожидаемый check:

```text
source_model_report_valid
```

2. Снизьте `condition_number_max`.

Ожидаемый warning:

```text
condition_number_below_threshold
```

3. Уменьшите `min_n_for_heteroscedasticity_test` и посмотрите, почему формальный тест на
tiny sample все равно не стоит превращать в решение.

## Проверьте это

Запустите tests:

```bash
uv run --locked python -m unittest discover \
  -s phases/09-applied-statistics/09-regression-diagnostics/tests -v
```

Tests проверяют:

- machine-readable diagnostics keys;
- residual mean near zero;
- skipped normality/Breusch-Pagan tests на tiny sample;
- VIF/condition number;
- influence thresholds;
- committed JSON и PNG.

## Поставьте результат

Артефакт урока - `outputs/regression_diagnostics_checker.py`. Он выпускает:

- `outputs/diagnostics.json` - flags, diagnostics и limitations;
- `outputs/regression_diagnostics.png` - residual/fitted и influence panels.

Этот результат нужен финальному `09/10`: statistical evidence package должен передавать не
только coefficients, но и риски модели.

## Упражнения

1. Снизьте Cook threshold и посмотрите, какие строки становятся influential.
2. Добавьте почти дублирующий predictor и проверьте VIF.
3. Расширьте diagnostic figure QQ-plot панелью.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Residual | Ошибка исходных данных | `observed - fitted` после модели |
| Leverage | Большой residual | Необычная позиция строки в predictor space |
| Cook's distance | p-value строки | Influence наблюдения на fitted model |
| VIF | Качество модели | Диагностика multicollinearity predictors |
| Diagnostic flag | Автоматический фикс | Machine-readable ограничение для отчета |

## Дополнительное чтение

- [statsmodels: Regression Diagnostics](https://www.statsmodels.org/stable/diagnostic.html) - обзор heteroscedasticity, non-linearity, multicollinearity, normality и influence checks.
- [statsmodels: Breusch-Pagan](https://www.statsmodels.org/stable/generated/statsmodels.stats.diagnostic.het_breuschpagan.html) - официальный API heteroscedasticity test и его null hypothesis.
- [statsmodels: OLSInfluence](https://www.statsmodels.org/stable/generated/statsmodels.stats.outliers_influence.OLSInfluence.html) - leverage, Cook's distance и другие influence measures.
- [statsmodels: variance_inflation_factor](https://www.statsmodels.org/stable/generated/statsmodels.stats.outliers_influence.variance_inflation_factor.html) - VIF как диагностика collinearity.
