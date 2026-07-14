# Документация проекта

Этот каталог хранит решения о содержании и устройстве курса. Канонический список фаз,
уроков, маршрутов и статусов находится в [`../curriculum.json`](../curriculum.json).

## Навигация

- [`course-design.md`](course-design.md) — педагогические принципы и критерии готовности.
- [`data-universe.md`](data-universe.md) — общая предметная область и учебные данные.
- [`research-baseline.md`](research-baseline.md) — критика исходного исследования и
  принятые изменения программы.
- [`phase-06-design.md`](phase-06-design.md) — границы EDA-фазы, роли библиотек, общий
  набор данных и интеграционный проект.
- [`phase-07-design.md`](phase-07-design.md) — архитектура reliability-фазы, матрица
  дефектов, контракты инструментов и интеграционный quality gate.
- [`phase-08-design.md`](phase-08-design.md) — границы продуктовой аналитики, модель
  событийных данных, контракт метрик и интеграционное исследование.
- [`phase-09-design.md`](phase-09-design.md) — границы прикладной статистики, sampling
  assumptions, интервалы, regression diagnostics и итоговый statistical evidence report.
- [`phase-10-design.md`](phase-10-design.md) — границы экспериментальной фазы,
  randomization, A/A, SRM, MDE/power, CUPED, multiple testing, peeking и итоговый
  experiment decision package.
- [`phase-11-design.md`](phase-11-design.md) — границы analytics engineering, dbt graph,
  sources/refs, materializations, data tests, snapshots, docs, SQLFluff и локальный
  dbt-duckdb проект.
- [`phase-12-design.md`](phase-12-design.md) — границы performance-фазы, benchmark
  protocol, Parquet/Arrow/DuckDB/Polars/Ibis, memory budget и multi-engine benchmark
  package.
- [`phase-13-design.md`](phase-13-design.md) — causal question и estimand, DAG,
  adjustment sets, matching/IPW/AIPW, DiD, RDD/IV, sensitivity и итоговый
  causal-study-package.
- [`phase-14-design.md`](phase-14-design.md) — временной индекс, resampling,
  leakage-free rolling features, baselines, ETS/ARIMA, rolling backtesting, интервалы и
  итоговый time-series forecast package.
- [`phase-15-design.md`](phase-15-design.md) — ML problem framing, split protocol,
  preprocessing pipelines, baselines, calibration, leakage, error analysis и итоговый
  model card package.
- [`phase-16-design.md`](phase-16-design.md) — CatBoost baseline, categorical leakage,
  early stopping, importance, SHAP, Optuna/MLflow ledger, drift и итоговый
  tabular-ml-interpretation package.
- [`phase-17-design.md`](phase-17-design.md) — decision memo, stakeholder workbook,
  Quarto HTML/PDF/DOCX reports, Plotly/Streamlit delivery, CLI/schedule, optional
  FastAPI/Docker и итоговый stakeholder delivery package.
- [`phase-18-design.md`](phase-18-design.md) — capstone routes, stage contracts, data and
  baseline gates, independent verification, peer review, defense rubric и итоговый
  capstone portfolio package.
- [`PROJECT_STATUS.md`](PROJECT_STATUS.md) — текущий handoff, открытые вопросы и следующий
  содержательный шаг.

## Что генерируется

Не редактируйте вручную:

- [`../ROADMAP.md`](../ROADMAP.md);
- `README.md` внутри каталогов фаз;
- [`../outputs/index.json`](../outputs/index.json);
- [`../site/data.js`](../site/data.js).

После изменения `curriculum.json` выполните:

```bash
python3 scripts/render_curriculum.py
python3 scripts/render_outputs.py
python3 scripts/render_site.py
python3 scripts/validate_course.py
```
