"""Structured predicate interpreter; no eval or executable expressions in JSON."""
import operator

MISSING = object()
COMPARISONS = {'eq': operator.eq, 'ne': operator.ne, 'lt': operator.lt,
               'le': operator.le, 'gt': operator.gt, 'ge': operator.ge}


def resolve(context, path):
    value = context
    for part in path.split('.'):
        if isinstance(value, dict):
            value = value.get(part, MISSING)
        else:
            return MISSING
    return value


def evaluate(expression, context):
    if not isinstance(expression, dict):
        raise ValueError('Predicate must be an object')
    if set(expression) == {'value'}:
        return expression['value']
    if set(expression) == {'path'}:
        return resolve(context, expression['path'])
    op = expression.get('op')
    if op in COMPARISONS or op == 'in':
        left, right = (evaluate(expression[k], context) for k in ('left', 'right'))
        if left is MISSING or right is MISSING:
            return False
        try:
            return left in right if op == 'in' else COMPARISONS[op](left, right)
        except TypeError:
            return False
    if op in ('and', 'or'):
        values = [bool(evaluate(x, context)) for x in expression['args']]
        return all(values) if op == 'and' else any(values)
    if op == 'not':
        return not bool(evaluate(expression['arg'], context))
    if op == 'exists':
        return evaluate(expression['arg'], context) is not MISSING
    if op in ('all', 'any', 'count', 'sum'):
        items = evaluate(expression['items'], context)
        if items is MISSING or not isinstance(items, list):
            return False if op in ('all', 'any') else 0
        if 'where' in expression:
            items = [item for item in items if evaluate(expression['where'], {**context, 'item': item})]
        if op == 'count':
            return len(items)
        if op == 'sum':
            return sum(evaluate(expression['select'], {**context, 'item': item}) for item in items)
        values = [bool(evaluate(expression['test'], {**context, 'item': item})) for item in items]
        return all(values) if op == 'all' else any(values)
    raise ValueError('Unknown predicate operation: ' + str(op))


def comparison(path, op, value):
    return {'op': op, 'left': {'path': path}, 'right': {'value': value}}
