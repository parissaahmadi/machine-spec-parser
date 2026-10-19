from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "datasheets"


def read(name: str) -> str:
    return (DATA / name).read_text(encoding="utf-8")
