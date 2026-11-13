import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hackroi.contracts import canonical, exported_schemas
from hackroi.http import parse_json


def main():
    expected = exported_schemas()
    if {path.name for path in (ROOT / "contracts").glob("*.schema.json")} != set(expected):
        raise SystemExit("Набор JSON Schema отличается от исполнимого профиля")
    for filename, schema in expected.items():
        actual = parse_json((ROOT / "contracts" / filename).read_bytes())
        if canonical(schema) != canonical(actual):
            raise SystemExit("Устаревшая JSON Schema: " + filename)
    print(f"JSON Schema: {len(expected)} файлов согласованы с исполнимым профилем")


if __name__ == "__main__":
    main()
