# Сайт курса

`site/` — готовый к публикации статический сайт курса. Он не требует backend,
сборщика JavaScript или абсолютного пути домена.

Данные для страниц генерируются из `curriculum.json` и `glossary/terms.md`:

```bash
python3 scripts/render_site.py
```

Локальная проверка:

```bash
python3 -m http.server 8000 --directory site
```

После этого откройте `http://localhost:8000`.

Для публикации можно загрузить содержимое `site/` на любой static hosting. Workflow
`.github/workflows/pages.yml` публикует эту папку на GitHub Pages после push в `main`.
