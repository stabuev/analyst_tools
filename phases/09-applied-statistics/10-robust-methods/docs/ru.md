# Робастные и непараметрические методы

> Финальный статистический отчет ценен не числом, а проверяемой связкой evidence и limitations.

**Тип:** Case  
**Треки:** Product, ML  
**Пререквизиты:** `09-applied-statistics/09-regression-diagnostics`  
**Время:** ~105 минут  
**Результат:** собирает statistical evidence package: sampling audit, distribution cards,
estimates, intervals, bootstrap, correlation audit, OLS diagnostics, robust/nonparametric
sensitivity checks, report и checksum manifest.

## Цели обучения

- Сравнивать обычные и robust estimates для heavy-tailed revenue.
- Использовать непараметрический check как sensitivity, а не как замену дизайна.
- Собирать статистический handoff из машинных артефактов.
- Связывать каждый claim с файлом и limitation.
- Выпускать SHA-256 manifest для проверяемой поставки.

## Проблема

К концу фазы есть много файлов:

```text
sampling audit
distribution cards
point estimates
bias/variance
confidence intervals
bootstrap intervals
correlation audit
OLS coefficients
regression diagnostics
```

Но заказчику нельзя отдавать папку "как-нибудь разберетесь". Нужно собрать evidence
package: главный ответ, артефакты, robust sensitivity, figures и manifest.

## Концепция

### Robust estimates

Mean revenue чувствителен к хвостам и нулям. Поэтому рядом кладутся:

- mean;
- median;
- 20% trimmed mean;
- 10/90 winsorized mean.

Они не заменяют бизнес-метрику автоматически. Они показывают чувствительность.

### Nonparametric sensitivity

Mann-Whitney U check сравнивает sessions у activated и non-activated users без нормальной
модели среднего. На tiny sample он получает `small_group` warning, и это нормально:
warning лучше, чем притворная уверенность.

### Evidence package

Финальный пакет должен быть самодостаточным:

```text
statistical-evidence-report/
├── question.json
├── sampling/
├── distributions/
├── estimates/
├── association/
├── regression/
├── robustness/
├── figures/
├── report.md
└── manifest.json
```

## Соберите это

Сначала robust estimates:

```python
mean = np.mean(revenue)
median = np.median(revenue)
trimmed = stats.trim_mean(revenue, 0.2)
winsorized = np.mean(np.clip(revenue, q10, q90))
```

Затем leave-one-out sensitivity:

```python
for user in users:
    mean_without_user = mean(revenue excluding user)
```

И checksum:

```python
sha256(file_bytes)
```

## Используйте это

Запустите артефакт:

```bash
uv run --locked python phases/09-applied-statistics/10-robust-methods/outputs/robust_evidence_packager.py \
  --phase-root phases/09-applied-statistics \
  --output-dir phases/09-applied-statistics/10-robust-methods/outputs/statistical-evidence-report
```

Короткий пример:

```bash
uv run --locked python phases/09-applied-statistics/10-robust-methods/code/main.py
```

## Сломайте это

1. Удалите один upstream artifact.

Ожидаемый результат: packager падает до manifest, потому что evidence package не должен
молчаливо пропускать источник.

2. Измените любой файл после сборки.

Ожидаемый результат: checksum в `manifest.json` перестанет совпадать.

3. Удалите regression warning flags.

Ожидаемый результат: sensitivity report потеряет limitation, и tests должны это поймать.

## Проверьте это

Запустите tests:

```bash
uv run --locked python -m unittest discover \
  -s phases/09-applied-statistics/10-robust-methods/tests -v
```

Tests проверяют:

- обязательную структуру пакета;
- SHA-256 checksums;
- robust estimates;
- nonparametric sensitivity;
- ссылки report на artifacts;
- PNG figures;
- CLI-сборку в новой директории.

## Поставьте результат

Артефакт урока - `outputs/robust_evidence_packager.py`. Итоговая поставка лежит в
`outputs/statistical-evidence-report/`. Это финальный артефакт фазы 09.

Разрешенный вывод:

```text
Association and estimation evidence with explicit limitations.
```

Запрещенные выводы:

```text
causal effect
experiment won
production forecast
```

## Упражнения

1. Добавьте Hodges-Lehmann style location estimate для revenue sensitivity.
2. Добавьте отдельную секцию `claims.json`, где каждый claim ссылается на artifact path.
3. Сделайте manifest validator, который проверяет пакет после передачи.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Robust estimate | Всегда лучший estimate | Оценка, менее чувствительная к выбросам при своей цене |
| Nonparametric check | Метод без assumptions | Метод с другими, часто более мягкими assumptions |
| Sensitivity | Исправление bias | Проверка, насколько вывод меняется при альтернативных разумных расчетах |
| Evidence package | Архив файлов | Связанная поставка claims, artifacts, limitations и manifest |
| Manifest | Декоративный JSON | Проверка целостности файлов через checksums |

## Дополнительное чтение

- [SciPy: `trim_mean`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.trim_mean.html) - trimmed mean как простой robust location estimate.
- [SciPy: `mannwhitneyu`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.mannwhitneyu.html) - непараметрическое сравнение двух независимых выборок.
- [Python: `hashlib`](https://docs.python.org/3/library/hashlib.html) - SHA-256 manifest для проверяемой передачи файлов.
- [NIST/SEMATECH e-Handbook: Robust location estimates](https://www.itl.nist.gov/div898/handbook/eda/section3/eda35h.htm) - медиана, trimmed mean и устойчивые альтернативы среднего.
