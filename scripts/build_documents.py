"""Build the four current DOCX documents. Optional dependency: python-docx."""
import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hackroi import __version__
AUTHOR = 'Заречкин Артём Алексеевич'
GROUP = 'Б24-507'
REVISION = tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['tool']['ariadna']['documents']['revision']
MONTHS = ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря')
revision_date = date.fromisoformat(REVISION)
DATE = f'{revision_date.day} {MONTHS[revision_date.month-1]} {revision_date.year} года'
PRINT_PAGES = {'explanatory_note': {'__total__': 20,
                      'Аннотация': 2,
                      '1 Введение': 4,
                      '2 Назначение и постановка задачи': 4,
                      '3 Предметная область и миссии': 5,
                      '4 Архитектура среды и управления': 5,
                      '5 Онтология агентов и объектов': 6,
                      '6 Пространство время связь и физика': 7,
                      '7 Сценарии и игровые модели': 8,
                      '8 Метасценарный контроллер и прогноз': 9,
                      '9 Протокол взаимодействия': 11,
                      '10 Ограничения доверие и неопределённость': 12,
                      '11 Журналирование и аудит': 12,
                      '12 Контрольные образцы и программа экспериментов': 13,
                      '13 Результаты испытаний': 13,
                      '14 Ограничения отказы и границы применимости': 14,
                      '15 Ожидаемые технические и экономические показатели': 15,
                      '16 Заключение': 15,
                      '17 Список использованных источников': 15,
                      'Приложение А Запуск и протокольные примеры': 17,
                      'Приложение Б Карта обязательных разделов и свидетельств': 18,
                      'Приложение В Генеративные инструменты и материалы': 19,
                      'Приложение Г Космический агент и сравнение ветвей': 20},
 'test_protocol': {'__total__': 9,
                   'Аннотация': 2,
                   '1 Объект и цель испытаний': 3,
                   '2 Требования и проверяемые свойства': 3,
                   '3 Условия и средства': 3,
                   '4 Порядок и методы': 4,
                   '5 Результаты проверки кода и поставки': 5,
                   '6 Результаты домашних миссий': 5,
                   '7 Результаты полевых миссий': 6,
                   '8 Исторические и перекрёстные испытания': 7,
                   '9 Свидетельства и вывод': 7,
                   '10 Источники': 8,
                   '11 Проверка космической категории и двумерных ветвей': 9},
 'run_guide': {'__total__': 7,
               'Аннотация': 2,
               '1 Назначение программы': 3,
               '2 Условия выполнения': 3,
               '3 Запуск и завершение': 3,
               '4 Работа с интерфейсом': 4,
               '5 Раздельный запуск и получение журналов': 4,
               '6 Воспроизводимые серии и документы': 5,
               '7 Сообщения оператору': 6,
               '8 Космический ретранслятор и схемы ветвей': 7},
 'essay': {'__total__': 5,
           '1 Задача совместного действия': 2,
           '2 Практические области применения': 2,
           '3 Что даёт сравнение планов': 3,
           '4 Как измерять существенный выигрыш': 4,
           '5 Границы и развитие': 4,
           '6 Источники': 5}}

DOCUMENTS = (
    ('EXPLANATORY_NOTE', 'explanatory_note', 'Пояснительная записка', 'АРИАДНА.09.01.81'),
    ('TEST_PROTOCOL', 'test_protocol', 'Программа и методика испытаний', 'АРИАДНА.09.01.51'),
    ('RUN_GUIDE', 'run_guide', 'Руководство оператора', 'АРИАДНА.09.01.34'),
    ('ESSAY', 'essay', 'Эссе о применении решения', 'АРИАДНА.09.01.ЭС'),
)


def clean(text):
    text = re.sub(r'\[([^]]+)\]\(([^)]+)\)', r'\1 (\2)', text)
    return text.replace('**', '').replace('`', '')


def build_one(source, output, title, designation, page_map=None):
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    page_map = page_map or {}
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin, sec.right_margin = Cm(3), Cm(1.5)
    sec.top_margin, sec.bottom_margin = Cm(2), Cm(2)
    sec.header_distance, sec.footer_distance = Cm(.8), Cm(1)
    sec.different_first_page_header_footer = True
    for border in doc.styles.element.xpath('.//w:pBdr'):
        border.getparent().remove(border)
    for name in ('Normal', 'Title', 'Heading 1', 'Heading 2', 'Caption'):
        style = doc.styles[name]
        style.font.name = 'Times New Roman'
        style.font.size = Pt(14)
        style.font.color.rgb = RGBColor(0, 0, 0)
        fonts = style._element.get_or_add_rPr().get_or_add_rFonts()
        for key in list(fonts.attrib):
            if 'theme' in key.lower(): del fonts.attrib[key]
        for key in ('ascii', 'hAnsi', 'eastAsia', 'cs'): fonts.set(qn('w:'+key), 'Times New Roman')
        pf = style.paragraph_format
        pf.space_after, pf.space_before = Pt(0), Pt(0)
        pf.line_spacing, pf.widow_control = 1.5, True
    normal = doc.styles['Normal'].paragraph_format
    normal.first_line_indent, normal.alignment = Cm(1.25), WD_ALIGN_PARAGRAPH.JUSTIFY
    for name in ('Heading 1', 'Heading 2'):
        st = doc.styles[name]
        st.font.bold = True
        pf = st.paragraph_format
        pf.first_line_indent = Cm(0)
        pf.space_before, pf.space_after = Pt(14), Pt(7)
        pf.keep_with_next, pf.alignment = True, WD_ALIGN_PARAGRAPH.LEFT
    doc.styles['Title'].font.size = Pt(20)
    doc.styles['Title'].font.bold = True
    doc.styles['Title'].paragraph_format.first_line_indent = Cm(0)
    doc.styles['Caption'].font.size = Pt(12)
    doc.styles['Caption'].paragraph_format.first_line_indent = Cm(0)
    doc.styles['Caption'].paragraph_format.line_spacing = 1.15
    header = sec.header.paragraphs[0]
    header.text, header.alignment = designation, WD_ALIGN_PARAGRAPH.RIGHT
    header.paragraph_format.first_line_indent = Cm(0)
    for run in header.runs: run.font.size = Pt(10)
    footer = sec.footer.paragraphs[0]
    footer.paragraph_format.first_line_indent = Cm(0)
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fld = OxmlElement('w:fldSimple'); fld.set(qn('w:instr'), 'PAGE')
    run = OxmlElement('w:r'); text = OxmlElement('w:t');text.text = '1';run.append(text);fld.append(run);footer._p.append(fld)
    def centered(text, size=14, before=0, bold=False, style=None):
        p = doc.add_paragraph(style=style)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.space_before = Pt(before)
        r = p.add_run(text);r.font.size = Pt(size);r.bold = bold
        return p
    centered('ХАКАТОН «МЕТАРОЙ 1.0»', bold=True)
    centered('Программный комплекс Ариадна', size=20, before=78, bold=True, style='Title')
    centered(title, size=16, before=22, bold=True)
    centered(designation, before=16)
    centered('Версия программы '+__version__, before=10)
    centered('Листов '+str(page_map.get('__total__', 1)))
    p = doc.add_paragraph('Разработчик\n'+AUTHOR+'\nГруппа '+GROUP)
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.space_before = Pt(70)
    centered('Москва 2026', before=60)
    centered('Редакция от '+DATE, before=10, size=12)
    doc.add_page_break()
    source_lines = source.read_text(encoding='utf-8').splitlines()
    sections = re.split(r'^## ', '\n'.join(source_lines), flags=re.M)[1:]
    headings = [x.split('\n', 1)[0] for x in sections]
    essay = source.stem == 'ESSAY'
    if not essay:
        annotation = next(x.split('\n', 1)[1].strip() for x in sections if x.startswith('Аннотация\n'))
        doc.add_heading('Аннотация', 1)
        for block in re.split(r'\n\s*\n', annotation): doc.add_paragraph(clean(block.replace('\n', ' ')))
        if source.stem == 'EXPLANATORY_NOTE': doc.add_page_break()
        doc.add_heading('Содержание', 1)
        for heading in headings:
            if heading == 'Аннотация': continue
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.first_line_indent, pf.line_spacing, pf.space_after = Cm(0), 1.05, Pt(3)
            pf.tab_stops.add_tab_stop(Cm(16.35), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
            r = p.add_run(heading+'\t'+str(page_map.get(heading, 1)));r.font.size = Pt(12)
        doc.add_page_break()
    figure = 0
    table_number = 0
    def paragraph(text, code=False):
        p = doc.add_paragraph(clean(text) if not code else text)
        if code:
            p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.line_spacing = 1.05
            p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_after = Pt(2)
            for r in p.runs: r.font.name='Courier New';r.font.size=Pt(9)
        return p
    def make_table(lines):
        rows = [[clean(x.strip()) for x in line.strip().strip('|').split('|')] for line in lines]
        rows = [row for row in rows if not all(set(x)<=set('-: ') for x in row)]
        n = len(rows[0])
        widths = {3: [5.5, 6.6, 4.4],4:[5.2,4.2,3.55,3.55]}.get(n,[16.5/n]*n)
        if rows[0][0] == 'Сообщение или код': widths=[4.9,5.1,6.5]
        if rows[0][0] == 'Карта и seed': widths=[4.2,4.1,4.1,4.1]
        table = doc.add_table(rows=0,cols=n)
        table.alignment=WD_TABLE_ALIGNMENT.CENTER;table.autofit=False
        for c,w in zip(table.columns,widths):c.width=Cm(w)
        for i,row in enumerate(rows):
            cells=table.add_row().cells
            for cell,value,w in zip(cells,row,widths):
                cell.width=Cm(w);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
                tcPr=cell._tc.get_or_add_tcPr()
                margins=OxmlElement('w:tcMar')
                for edge in ('top','bottom','left','right'):
                    e=OxmlElement('w:'+edge);e.set(qn('w:w'),'90');e.set(qn('w:type'),'dxa');margins.append(e)
                tcPr.append(margins)
                borders=OxmlElement('w:tcBorders')
                for edge in ('top','bottom','left','right'):
                    e=OxmlElement('w:'+edge);e.set(qn('w:val'),'single');e.set(qn('w:sz'),'4');e.set(qn('w:color'),'D9D9D9');borders.append(e)
                tcPr.append(borders)
                if i==0:
                    shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'EEEEEE');tcPr.append(shade)
                cell.text=value
                for p in cell.paragraphs:
                    p.paragraph_format.keep_with_next=i<len(rows)-1
                    p.paragraph_format.first_line_indent=Cm(0);p.paragraph_format.line_spacing=1.1
                    p.paragraph_format.alignment=WD_ALIGN_PARAGRAPH.LEFT
                    for r in p.runs:r.font.size=Pt(10 if '_' in value and ' ' not in value and (len(value)>25 or rows[0][0]=='Сообщение или код') else 11.5);r.bold=i==0
            trpr=table.rows[i]._tr.get_or_add_trPr();ns=OxmlElement('w:cantSplit');trpr.append(ns)
            if i==0:trpr.append(OxmlElement('w:tblHeader'))
        doc.add_paragraph().paragraph_format.space_after=Pt(4)
    for sec_text in sections:
        heading,body=sec_text.split('\n',1)
        if heading=='Аннотация' and not essay:continue
        if heading.startswith('Приложение') or heading.startswith('11 Проверка космической'):doc.add_page_break()
        section_heading=doc.add_heading(heading,1)
        if heading.startswith('8 Космический ретранслятор'):
            section_heading.paragraph_format.page_break_before=True
        lines=body.strip().splitlines();i=0;block=[]
        def flush():
            if block:paragraph(' '.join(block));block.clear()
        while i<len(lines):
            line=lines[i]
            if line.startswith('```'):
                flush();i+=1;code=[]
                while i<len(lines) and not lines[i].startswith('```'):code.append(lines[i]);i+=1
                for code_line in code:paragraph(code_line,True)
            elif line.startswith('|'):
                flush();table_lines=[]
                while i<len(lines) and lines[i].startswith('|'):table_lines.append(lines[i]);i+=1
                make_table(table_lines);continue
            elif line.startswith('### '):flush();doc.add_heading(line[4:],2)
            elif (match:=re.fullmatch(r'!\[([^]]+)\]\(([^)]+)\)',line)):
                flush();figure+=1;p=doc.add_paragraph();p.paragraph_format.first_line_indent=Cm(0);p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.keep_with_next=True
                p.add_run().add_picture(str(source.parent/match[2]),width=Cm(16.1))
                p=doc.add_paragraph(f'Рисунок {figure} - {match[1]}',style='Caption');p.alignment=WD_ALIGN_PARAGRAPH.CENTER
            elif line.startswith(('Таблица ','Листинг ')):
                flush();p=doc.add_paragraph(line,style='Caption');p.paragraph_format.keep_with_next=True;p.paragraph_format.space_before=Pt(6);p.paragraph_format.space_after=Pt(4)
            elif not line.strip():flush()
            else:block.append(line.strip())
            i+=1
        flush()
    doc.core_properties.title='Ариадна '+title
    doc.core_properties.author=AUTHOR
    doc.core_properties.subject='Метарой 1.0; программа '+__version__+'; редакция '+revision_date.strftime('%d.%m.%Y')
    doc.core_properties.created = doc.core_properties.modified = datetime.combine(revision_date, datetime.min.time(), timezone.utc)
    doc.core_properties.keywords=designation
    output.parent.mkdir(parents=True,exist_ok=True)
    doc.save(output)
    return output


def export_pdf(docx, executable):
    with tempfile.TemporaryDirectory(prefix='ariadna-office-') as profile:
        result = subprocess.run([executable, '-env:UserInstallation='+Path(profile).as_uri(),
                                 '--headless', '--convert-to', 'pdf:writer_pdf_Export',
                                 '--outdir', str(docx.parent), str(docx)],
                                capture_output=True, text=True, timeout=120)
    pdf = docx.with_suffix('.pdf')
    if result.returncode or not pdf.is_file():
        raise RuntimeError('PDF export failed: '+result.stderr[-1500:])
    return pdf


def measured_pages(source, pdf):
    from pypdf import PdfReader
    normalize = lambda value: ' '.join(value.split())
    pages = [normalize(page.extract_text()) for page in PdfReader(pdf).pages]
    headings = re.findall(r'^## (.+)$', source.read_text(encoding='utf-8'), flags=re.M)
    body_start = 2 if source.stem == 'ESSAY' else 4 if source.stem == 'EXPLANATORY_NOTE' else 3
    result = {'__total__': len(pages)}
    for heading in headings:
        first = 2 if heading == 'Аннотация' else body_start
        matches = [i for i, text in enumerate(pages, 1) if i >= first and normalize(heading) in text]
        if not matches:
            raise ValueError('Heading missing from PDF: '+heading)
        result[heading] = matches[0]
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'submission')
    p.add_argument('--pages',type=Path,help='JSON: output stem -> heading/page and __total__')
    p.add_argument('--force',action='store_true')
    p.add_argument('--pdf',action='store_true',help='Export PDF with LibreOffice and converge printed contents/page counts')
    p.add_argument('--soffice',default=shutil.which('soffice'),help='Path to LibreOffice soffice executable')
    p.add_argument('--only',nargs='+',choices=[row[1] for row in DOCUMENTS],help='Rebuild only the selected documents')
    args=p.parse_args()
    maps=json.loads(args.pages.read_text(encoding='utf-8')) if args.pages else PRINT_PAGES
    selected=[row for row in DOCUMENTS if not args.only or row[1] in args.only]
    if args.pdf and not args.soffice:
        p.error('--pdf requires LibreOffice; use --soffice /path/to/soffice')
    if args.pdf:
        from pypdf import PdfReader  # Optional authoring dependency; fail before replacing outputs.
    for source,stem,title,designation in selected:
        target=args.output/(stem+'.docx')
        if any(path.exists() for path in (target, target.with_suffix('.pdf'))) and not args.force:
            raise ValueError('Refusing to overwrite: '+str(target)+'; use --force')
    for source,stem,title,designation in selected:
        target=args.output/(stem+'.docx')
        source_path=ROOT/'docs'/(source+'.md')
        page_map=maps.get(stem, {})
        for attempt in range(4):
            build_one(source_path,target,title,designation,page_map)
            if not args.pdf:break
            target.with_suffix('.pdf').unlink(missing_ok=True)
            measured=measured_pages(source_path,export_pdf(target,args.soffice))
            if measured==page_map:break
            page_map=measured
        else:raise ValueError('Pagination did not converge: '+stem)
        print(json.dumps({'document':stem,'pdf':args.pdf,'pages':page_map.get('__total__')},ensure_ascii=False))
if __name__=='__main__':main()
