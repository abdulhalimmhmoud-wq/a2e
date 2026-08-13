"""معالج الملفات النصية (TXT / MD / CSV) — استخراج ودمج بسيط."""
from __future__ import annotations

from pathlib import Path

from app.tools.translator.formats.base import ExtractionResult, TextUnit

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1256", "latin-1")


def _read(path: Path) -> tuple[str, str]:
    """قراءة الملف مع تجربة الترميزات الشائعة (cp1256 شائع في الملفات العربية القديمة)."""
    raw = path.read_bytes()
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


def extract(path: Path) -> ExtractionResult:
    content, encoding = _read(path)
    lines = content.splitlines()

    units: list[TextUnit] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        units.append(
            TextUnit(
                unit_key=f"plain:line:{index:06d}",
                text=line,
                kind="line",
                location=f"سطر {index + 1}",
                order_index=len(units),
            )
        )

    words = len(content.split())
    return ExtractionResult(
        units=units,
        page_count=max(1, round(words / 250)),
        meta={"encoding": encoding, "line_count": len(lines)},
    )


def merge(
    source_path: Path,
    output_path: Path,
    translations: dict[str, str],
    target_rtl: bool = False,  # noqa: ARG001 — النص العادي مالوش اتجاه مخزَّن
    lang_tag: str = "en-US",  # noqa: ARG001
) -> None:
    content, _ = _read(source_path)
    lines = content.splitlines(keepends=True)

    for index, line in enumerate(lines):
        target = translations.get(f"plain:line:{index:06d}")
        if target is None:
            continue
        # بنحافظ على فاصل السطر الأصلي بالظبط
        newline = ""
        stripped = line
        for ending in ("\r\n", "\n", "\r"):
            if line.endswith(ending):
                newline = ending
                stripped = line[: -len(ending)]
                break
        lines[index] = target + newline

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(lines), encoding="utf-8")
