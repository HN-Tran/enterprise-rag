from __future__ import annotations

from pathlib import Path

from app.db import exec_script

def main() -> None:
    schema = Path("sql/schema.sql").read_text(encoding="utf-8")
    exec_script(schema)
    print("DB initialized.")

if __name__ == "__main__":
    main()
