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
