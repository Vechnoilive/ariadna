"""Portable public decision evidence, readable without the simulator."""
import json
from pathlib import Path


def headquarters(records):
    decisions = {r['decision_id']: r for r in records if r['kind'] == 'decision'}
    results = {r['decision_id']: r for r in records if r['kind'] == 'result'}
    entries = []
    for identifier, record in decisions.items():
        decision = record['decision']
        if 'ariadna_counterfactual' not in decision:
            continue
        witness = decision['ariadna_counterfactual']
        actual = results.get(identifier, {}).get('output', {})
        entries.append({'decision_id': identifier, 'time': decision['time'], 'operation': decision['operation'],
                        'selected_candidate': witness['selected_candidate'], 'reason': witness['selection_reason'],
                        'candidates': witness['candidates'], 'calibration_before': witness['calibration_before_selection'],
                        'one_step_prediction': witness['selected_one_step_prediction'],
                        'actual_status': actual.get('status'), 'actual_metrics': actual.get('metrics'),
                        'feedback': results.get(identifier, {}).get('forecast_feedback')})
    return {'format': 'ariadna.headquarters.v1', 'decisions': entries,
            'scope': 'Public forecasts and observed chosen-action outcomes; rejected alternatives are unobserved here.'}


def save_headquarters(records, directory):
    directory = Path(directory)
    report = headquarters(records)
    (directory/'headquarters.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    lines = ['# Контрфактический штаб: журнал обоснований', '', 'Версия 0.4.0.', '',
             '## 1 Область свидетельств', '',
             'Прогноз строится до исполнения. Факт доступен только для выбранной альтернативы; остальные требуют отдельного исследовательского ветвления.', '',
             '## 2 Решения', '']
    for entry in report['decisions']:
        lines.extend([f"### 2.{len([x for x in lines if x.startswith('### ')])+1} Время {entry['time']}: {entry['selected_candidate']}", '',
                      f"Операция: {entry['operation']}. Основание: {entry['reason']}.", '',
                      '| Вариант | Выбран | Оценка | Прогноз прироста выполнения | Прогноз энергии | Информация, условные единицы |',
                      '|---|---|---|---|---|---|'])
        for candidate in entry['candidates']:
            n = candidate['nominal']
            lines.append(f"| {candidate['candidate_id']} | {'Да' if candidate['selected'] else 'Нет'} | {candidate['score']:.6f} | {n['known_completion_gain']:.6f} | {n['energy']:.6f} | {n['information_proxy']:.6f} |")
        feedback = entry['feedback']
        if feedback and feedback['status'] == 'compared':
            lines.extend(['', f"Факт следующего шага: прирост расхода энергии {feedback['actual_energy_delta']:.9f}; выполнение {feedback['actual_completion']:.6f}. Ошибки: {json.dumps(feedback['residuals'], ensure_ascii=False)}."])
        lines.append('')
    (directory/'headquarters.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return report
