# Линейная регрессия для вывода

> Regression coefficient - это условная association в модели, а не автоматический эффект.

**Тип:** Build  
**Треки:** Product, ML  
**Пререквизиты:** `09-applied-statistics/07-correlation`  
**Время:** ~90 минут  
**Результат:** строит design matrix, оценивает OLS coefficients, standard errors и
confidence intervals для user-level outcome, интерпретирует коэффициенты при контролях и
отделяет inference от prediction и causality.

## Цели обучения

- Собирать design matrix из machine-readable model spec.
- Считать OLS coefficients вручную через least squares.
- Сравнивать ручные coefficients со `statsmodels.OLS`.
- Читать standard errors, t-values, p-values и coefficient intervals.
- Формулировать regression claim как conditional association, не causal effect.

## Проблема

Корреляция из `09/07` показала, что `sessions_7d` и `activated_7d` сильно связаны. Но
корреляция не умеет ответить:

```text
Как onboarding duration связан с sessions, если activation уже включен в модель?
```

Для этого нужна линейная модель:

```text
sessions_7d = beta_0 + beta_1 * onboarding_seconds_centered + beta_2 * activated_7d + error
```

Важно: это не прогнозная ML-модель и не causal design. Здесь regression нужна как
инструмент вывода о коэффициентах и assumptions.

## Концепция

### Design matrix

Каждая строка - пользователь. Каждый столбец - term:

```text
const
onboarding_seconds_per_100_centered
activated_7d
```

Center/scale нужен, чтобы коэффициент onboarding читался как изменение sessions на 100
секунд относительно центра `520`.

### OLS

OLS оценивает:

```text
beta_hat = argmin sum((y_i - x_i beta)^2)
```

Ручной путь в уроке - `np.linalg.lstsq`. Production inference path - `statsmodels.OLS`,
потому что он дает standard errors, t-values, p-values и confidence intervals.

### Интерпретация

Коэффициент при onboarding:

```text
при фиксированном activated_7d в этой линейной модели onboarding duration conditionally
associated with sessions_7d.
```

Он не означает, что замедление onboarding причинно меняет sessions.

## Соберите это

Сначала соберите `X`:

```python
const = 1.0
onboarding = (onboarding_seconds - 520.0) / 100.0
activated = 1.0 if activated_7d else 0.0
```

И `y`:

```python
y = sessions_7d
```

Затем:

```python
beta, *_ = np.linalg.lstsq(X, y, rcond=None)
```

После этого сравните с:

```python
result = statsmodels.api.OLS(y, X, hasconst=True).fit()
```

## Используйте это

Запустите артефакт:

```bash
uv run --locked python phases/09-applied-statistics/08-linear-regression/outputs/ols_inference_runner.py \
  --sample phases/09-applied-statistics/data/tiny/sample_observations.csv \
  --spec phases/09-applied-statistics/08-linear-regression/outputs/model_spec.json \
  --output-coefficients phases/09-applied-statistics/08-linear-regression/outputs/coefficients.csv \
  --output-report phases/09-applied-statistics/08-linear-regression/outputs/model_report.json
```

Короткий пример:

```bash
uv run --locked python phases/09-applied-statistics/08-linear-regression/code/main.py
```

Report содержит design matrix, coefficient table, claim type и limitations.

## Сломайте это

1. Замените `candidate_claim` на causal wording.

Ожидаемый check:

```text
causal_wording_forbidden
```

2. Переименуйте колонку onboarding в несуществующую.

Ожидаемый check:

```text
model_columns_present
```

3. Добавьте лишние collinear terms.

Ожидаемый check:

```text
design_matrix_full_rank
```

## Проверьте это

Запустите tests:

```bash
uv run --locked python -m unittest discover \
  -s phases/09-applied-statistics/08-linear-regression/tests -v
```

Tests проверяют:

- design matrix columns и residual df;
- manual coefficients совпадают со statsmodels;
- coefficient table содержит standard errors и intervals;
- activation control является явным term;
- causal wording блокируется;
- committed CSV/JSON совпадают с runner output.

## Поставьте результат

Артефакт урока - `outputs/ols_inference_runner.py`. Он выпускает:

- `outputs/coefficients.csv` - coefficient table;
- `outputs/model_report.json` - design matrix, checks, limitations и claim type.

Следующий урок `09/09` возьмет этот report и проверит diagnostics: residual patterns,
heteroscedasticity, leverage, influence и multicollinearity.

## Упражнения

1. Уберите `activated_7d` из terms и сравните коэффициент onboarding.
2. Измените scale onboarding с `100` на `1` и объясните, почему coefficient меняет единицы.
3. Добавьте `support_tickets_7d` как control и проверьте rank/residual df.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Design matrix | Автоматически созданный DataFrame | Числовая матрица terms, которую реально видит OLS |
| Coefficient | Причинный эффект | Условная association при assumptions модели |
| Standard error | Ошибка данных | Uncertainty оценки coefficient |
| Residual df | Число строк | `n - number_of_parameters` |
| Inference | Prediction | Вывод о coefficient/uncertainty, а не оценка качества прогнозов |

## Дополнительное чтение

- [statsmodels: Linear Regression](https://www.statsmodels.org/stable/regression.html) - OLS/WLS/GLS и структура result table.
- [statsmodels: OLS](https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.OLS.html) - аргументы `endog`, `exog`, `hasconst` и fit workflow.
- [statsmodels: RegressionResults](https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.RegressionResults.html) - attributes для params, standard errors, confidence intervals и diagnostics.
- [NumPy: `linalg.lstsq`](https://numpy.org/doc/stable/reference/generated/numpy.linalg.lstsq.html) - ручной least-squares механизм, который лежит под коэффициентами.
