# Материалы зависимости и генеративные инструменты Ариадны

Версия программы 0.9.0. Редакция документа от 12.11.2026. Разработчик: Заречкин Артём Алексеевич, группа Б24-507.

## 1 Зависимости выполнения и сборки

Python-миссии, HTTP, журналы и сборка ZIP используют стандартную библиотеку. Requires-python в pyproject.toml — >=3.11; build-system setuptools>=68 нужен для установки пакета, а не для прямого запуска scripts/start_local.py.

Интерфейс включает локальную сборку Three.js 0.180.0, OrbitControls, SVGRenderer и Projector. Лицензия MIT сохранена в viewer/vendor/THREE-LICENSE.md и сборке. CDN для запуска не требуется. Для пересборки package.json фиксирует three 0.180.0 и esbuild 0.25.12: npm install --ignore-scripts, затем npm run build:three. Node.js не нужен для обычной миссии.

Документы собираются опциональным python-docx; PDF экспортируются LibreOffice, проверяются Poppler. Браузерные проверки используют Playwright и Chromium, запись видео — FFmpeg. Презентация и видео готовятся и передаются автором отдельно. Издательские и проверочные инструменты не являются зависимостями контроллера.

## 2 Происхождение изображений и геометрии

| Материал | Происхождение и назначение | Проверка |
|---|---|---|
| grass.jpg, stone.jpg, bark.jpg | Генерация текстур травы, камня и коры для проекта | viewer/assets/manifest.json |
| sand.jpg, snow.jpg, concrete.jpg | Генерация текстур песка, снега и бетона | examples/texture_prompts_080.json и manifest.json |
| apartment-cover.jpg | Сгенерированная обложка домашней сцены | Отдельный иллюстративный актив |
| viewer/textures.js | Те же шесть JPEG как data URI для автономного просмотра | Сверка исходных байтов по manifest.json |
| Роботы, мебель и окружение | Процедурная геометрия кода проекта | viewer/map.js, home-models.js и связанные модули |
| Архитектурные схемы документов | Детерминированное построение по структуре кода | docs/figures/*.png |
| submission/assets/*.png | Сохранённые снимки интерфейса из исходного комплекта | Визуальные приложения; дата кадра не означает дату повторного испытания |

Полные исторические запросы первых текстур сохранены в приложенном реестре examples/texture_prompts_080.json в имеющейся части. Генерация выполнялась интерактивно; исходники проекта указывают кодирование JPEG через FFmpeg. Повтор генерации по тексту не гарантирует совпадения байтов. Точный состав поставки фиксируется хешами, а не повторной генерацией.

Материалы дерева, плитки, ткани, металла и воды квартиры вычисляются в браузере. Текстуры и декоративная геометрия не добавляют модели жидкости, трения и разрушений. Геометрия за границами карты является оформлением. Физические корпуса и препятствия публикуются отдельно.

## 3 Изменения стороннего средства просмотра

При сборке SVGRenderer локально дополняется SVG pattern для материалов grass, sand, snow и concrete вместо однотонной заливки. Это приближение отображения, без аппаратных теней. Изменение описано в scripts/build_three.mjs; MIT-уведомления сохраняются. Рабочий Python-код от Three.js не зависит.

## 4 Роль генеративных инструментов и права

ChatGPT использовался при анализе требований, проектировании, подготовке и проверке кода и документов. Во время расчёта обращения к LLM и API-ключи не требуются. Синтез сценария ограничен известным графом, а не свободным ответом модели. Проверки выполняются исполнимым кодом и по первичным журналам.

Открытая лицензия на авторский проект не назначена; комплект передаётся закрытым способом согласно ТЗ. Сторонняя лицензия Three.js сохраняется. Файлы шрифтов не распространяются. В DOCX указан Times New Roman; при отсутствии используется метрически совместимая Liberation Serif для экспорта PDF. Шрифты сами по себе не подтверждают соответствие структуры ГОСТ.

Исторический media_provenance.json относится к ранее подготовленной презентации и видео и удаляется из актуального комплекта, поскольку сами файлы передаются отдельно. Файл submission/screencast со ссылкой сохранён побайтово. Содержимое внешнего видео в этой редакции не проверялось.

## 5 Сохранённые запросы первых текстур


### 2.1 Трава

Use case: stylized-concept. Asset type: seamless albedo texture for a real-time 3D rescue simulator. Primary request: one square tileable forest meadow ground material, small short grass blades mixed with subtle dry earth and moss, restrained natural sage and olive greens, refined realistic game art. Flat orthographic top-down surface scan, uniform diffuse illumination, no directional shadows, no perspective, no horizon, no large objects, no trees, no stones, no text or borders. Fill the entire image with a repeating surface; all four edges must tile seamlessly. This is a material texture, not a landscape illustration. 1024 by 1024 square.

### 2.2 Камень

Use case: stylized-concept. Asset type: square seamless albedo material for real-time 3D rescue terrain. One tileable natural weathered granite stone surface, pale cool gray with restrained warm mineral speckles, fine rough grain, small subtle fissures. Premium realistic game environment texture. Flat orthographic surface scan, perfectly even diffuse illumination, no directional light or baked shadows, no perspective, no big stones or separate objects, no horizon, no text, no borders. Image is entirely continuous rock material, seamless on all four edges. 1024x1024.

### 2.3 Кора

Use case: stylized-concept. Asset type: seamless tree bark albedo texture for real-time 3D rescue forest. One square tileable pine bark surface with vertical dark brown and warm gray ridges, subtle moss in crevices, realistic restrained material detail, no lighting baked in. Flat orthographic close surface scan, uniform diffuse illumination, no shadows, no perspective, no branch, no whole tree, no landscape, no text, no borders. Entire image filled by continuous bark material; all edges tile seamlessly. 1024x1024 square.

