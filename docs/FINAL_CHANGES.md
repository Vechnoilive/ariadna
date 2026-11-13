# Изменения финального комплекта Ариадны

Версия программы 0.9.0. Сравнение с точным архивом HackRoi-main (8).zip. Дата проверки — 12 ноября 2026 года.

Основная логика среды, контроллера, физика, карты, интерфейс и тесты сохранены побайтово. Изменены только перечисленные существующие файлы; удаления применены после переноса нужных сведений в актуальную документацию. Файл submission/screencast сохранён побайтово.

В исходнике 218 файлов. Изменены 16 существующих, удалены 32, добавлены 13, включая этот перечень и FINAL_VERIFICATION.json. Остальные 170 файлов не изменены. В финальном проекте 199 файлов плюс автоматически созданный MANIFEST.json архива.

## 1 Изменённые существующие файлы

| Путь | Назначение изменения |
|---|---|
| `README.md` | Актуальные запуск, ссылки и результаты |
| `docs/ASSETS.md` | Актуализация документа и сведений по текущей реализации |
| `docs/ESSAY.md` | Актуализация документа и сведений по текущей реализации |
| `docs/EXPLANATORY_NOTE.md` | Актуализация документа и сведений по текущей реализации |
| `docs/PROTOCOL.md` | Актуализация документа и сведений по текущей реализации |
| `docs/SOURCES.json` | Источники, дата проверки и точная ссылка на исходный архив по SHA-256 |
| `docs/SUBMISSION.md` | Актуализация документа и сведений по текущей реализации |
| `hackroi/release.py` | Набор документов, ссылка на видео и статусы комплекта в упаковщике |
| `interop/README.md` | Актуальные сведения об адаптере и ограничениях |
| `scripts/build_documents.py` | Сборка четырёх актуальных DOCX |
| `scripts/build_presentation.mjs` | Только ссылки на объединённые документы; презентация не пересоздавалась |
| `scripts/check_documents.py` | Проверка актуальных документов и свидетельств |
| `submission/explanatory_note.docx` | Актуальная печатная редакция документа |
| `submission/explanatory_note.pdf` | Актуальная печатная редакция документа |
| `submission/test_protocol.docx` | Актуальная печатная редакция документа |
| `submission/test_protocol.pdf` | Актуальная печатная редакция документа |

## 2 Добавленные файлы

- `docs/RUN_GUIDE.md`
- `docs/SCENARIOS.md`
- `docs/TEST_PROTOCOL.md`
- `docs/figures/architecture.png`
- `docs/figures/control_cycle.png`
- `experiments/results/verification_2026-11-12.json`
- `submission/essay.docx`
- `submission/essay.pdf`
- `submission/run_guide.docx`
- `submission/run_guide.pdf`
- `submission/verification_evidence.zip`
- `docs/FINAL_CHANGES.md`
- `docs/FINAL_VERIFICATION.json`

Новые PDF и DOCX — эссе и руководство. Markdown описывают запуск, сценарии, игровые формализации и испытания. Схемы включены в записку. Verification_evidence.zip хранит первичные журналы 24 повторных прогонов. FINAL_VERIFICATION.json фиксирует проверку именно этой финальной сборки и её ограничения.

## 3 Удалённые файлы

- `docs/APARTMENT.md`
- `docs/ARCHITECTURE.md`
- `docs/ASSETS_3D.md`
- `docs/AUDIT_FINDINGS_080.md`
- `docs/CAMPAIGN_090.md`
- `docs/COMPLIANCE_070.md`
- `docs/COMPLIANCE_080.md`
- `docs/CONCEPT.md`
- `docs/DEMO_SCRIPT.md`
- `docs/DIARY.md`
- `docs/INTERFACE.md`
- `docs/MISSIONS.md`
- `docs/OPEN_QUESTIONS.md`
- `docs/PHYSICS.md`
- `docs/REQUIREMENTS.md`
- `docs/STAGE2.md`
- `docs/STAGE3.md`
- `docs/STAGE4.md`
- `docs/STAGE5.md`
- `docs/STAGE6.md`
- `docs/STUDIO.md`
- `docs/TEST_PROTOCOL_080.md`
- `docs/VERIFICATION.md`
- `experiments/results/stage4_branches.md`
- `experiments/results/stage4_report.md`
- `experiments/results/stage5_report.md`
- `scripts/build_registers.py`
- `submission/compliance.docx`
- `submission/compliance.pdf`
- `submission/development_diary.docx`
- `submission/development_diary.pdf`
- `submission/media_provenance.json`

Отчёты этапов, старые аудиты и отдельные технические описания объединены в EXPLANATORY_NOTE.md, PROTOCOL.md, SCENARIOS.md, RUN_GUIDE.md, TEST_PROTOCOL.md, ASSETS.md и SUBMISSION.md. Печатный дневник и отдельная матрица соответствия больше не нужны в минимальном комплекте. Build_registers.py собирал удалённые формы. Media_provenance.json ссылался на прежние презентацию и видео, отсутствующие в исходном ZIP.

## 4 Что сохранено

Исходный код миссий и алгоритмов, тесты, JSON Schema, сценарии, interop, все карты, viewer и его данные, текстуры, MIT-уведомление Three.js, исходные определения экспериментов и JSON-сводки. Архивы evidence.zip, missions_evidence.zip и campaign_evidence.zip не удалены: они нужны для проверки поставленного просмотра. Исторические версии внутри свидетельств не переписаны.

Презентация отсутствовала в переданном исходнике. Внешняя ссылка на скринкаст сохранена, содержимое видео не проверялось. Этот комплект не создаёт новую презентацию или новое видео.

## 5 Проверки перед выдачей

- Повторный запуск всех 200 Python-тестов — успешно.
- Экспорт семи схем и пять сценарных деклараций — согласованы с кодом.
- Четыре актуальных документа и первичные свидетельства — проверены.
- Повторный аудит поставленного просмотра и его журналов — пройден.
- Компиляция Python и синтаксис 23 файлов JavaScript — без ошибок.
- Реальный запуск scripts/start_local.py, 16 файлов интерфейса по HTTP, новая остановка квартиры на 9 с и новая полевая миссия forest на 57 с, аудит и скачивание ZIP журналов — успешно.
- Побайтовое сравнение неизменённых файлов с исходным архивом — успешно.
- Итоговый ZIP дополнительно проверяется по составу, CRC и SHA-256 и распаковывается для повторной проверки.

Полный браузерный тест здесь выполнить не удалось: локальный Chromium завершился до открытия приложения из-за запрета системного сокета в среде выполнения. Поэтому проверки графического отображения не объявлены пройденными. Windows и иные версии Python в этом прогоне не запускались. Пройденные проверки подтверждают отсутствие обнаруженных регрессий в их объёме, а не абсолютную гарантию на любом компьютере.

## 6 Запуск

Распакуйте архив в отдельный каталог. Из корня проекта выполните python3 scripts/start_local.py --open либо откройте start.bat в Windows. В GitHub ничего автоматически не отправлялось.
