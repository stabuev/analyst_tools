# Сайт курса

`site/` — готовый к публикации статический сайт курса. Он не требует backend или
JavaScript build toolchain. Публичный base URL для canonical и sitemap задаётся в
`scripts/render_site.py`.

Каталог, sitemap и 201 полноценная страница урока генерируются из `curriculum.json`,
`glossary/terms.md` и содержимого `phases/`:

```bash
python3 scripts/render_site.py
```

Локальная проверка:

```bash
python3 -m http.server 8000 --directory site
```

После этого откройте `http://localhost:8000`. Страница урока доступна, например, по
`http://localhost:8000/lessons/pandas/dataframe-and-series/`.

Для публикации можно загрузить содержимое `site/` на любой static hosting. Workflow
`.github/workflows/pages.yml` публикует эту папку на GitHub Pages после push в `main`.
