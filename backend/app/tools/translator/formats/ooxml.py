"""أدوات مشتركة للتعامل مع ملفات OOXML كأرشيف ZIP.

ليه بنعدّل الـ XML مباشرة بدل استخدام مكتبة جاهزة للكتابة؟
لأن openpyxl (مثلًا) بيعيد بناء ملف Excel من الصفر عند الحفظ، وبالتالي
**بيضيّع الرسوم البيانية والصور والتنسيقات الشرطية**. لما نعدّل الـ XML
جوّه الأرشيف ونسيب باقي الملفات زي ما هي بالبايت، مفيش أي حاجة بتضيع.
"""
from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

# فضاءات الأسماء المستخدمة عبر صيغ OOXML
NS = {
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def q(prefix: str, tag: str) -> str:
    """اسم عنصر مؤهَّل بفضاء الاسم."""
    return f"{{{NS[prefix]}}}{tag}"


@dataclass
class OoxmlPackage:
    """أرشيف OOXML محمّل في الذاكرة مع تتبّع الأجزاء المعدّلة."""

    path: Path
    entries: dict[str, bytes] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    _trees: dict[str, etree._Element] = field(default_factory=dict)
    _dirty: set[str] = field(default_factory=set)

    @classmethod
    def open(cls, path: Path) -> OoxmlPackage:
        package = cls(path=path)
        with zipfile.ZipFile(path, "r") as archive:
            for info in archive.infolist():
                package.order.append(info.filename)
                package.entries[info.filename] = archive.read(info.filename)
        return package

    def tree(self, name: str) -> etree._Element | None:
        """شجرة XML لجزء معيّن (مع تخزين مؤقت)."""
        if name in self._trees:
            return self._trees[name]
        blob = self.entries.get(name)
        if blob is None:
            return None
        try:
            root = etree.fromstring(blob)
        except etree.XMLSyntaxError:
            return None
        self._trees[name] = root
        return root

    def mark_dirty(self, name: str) -> None:
        self._dirty.add(name)

    def names(self, prefix: str = "", suffix: str = "") -> list[str]:
        """أسماء الأجزاء المطابقة، مرتّبة ترتيبًا حتميًا."""
        return sorted(
            name
            for name in self.entries
            if name.startswith(prefix) and name.endswith(suffix)
        )

    def rels_for(self, part_name: str) -> dict[str, str]:
        """خريطة (r:id → المسار الهدف) لجزء معيّن."""
        folder, _, filename = part_name.rpartition("/")
        rels_name = f"{folder}/_rels/{filename}.rels" if folder else f"_rels/{filename}.rels"
        root = self.tree(rels_name)
        if root is None:
            return {}

        mapping: dict[str, str] = {}
        for relationship in root:
            rid = relationship.get("Id")
            target = relationship.get("Target")
            if not rid or not target:
                continue
            if target.startswith("/"):
                mapping[rid] = target.lstrip("/")
            elif target.startswith("../"):
                parent = folder.rpartition("/")[0]
                mapping[rid] = f"{parent}/{target[3:]}" if parent else target[3:]
            else:
                mapping[rid] = f"{folder}/{target}" if folder else target
        return mapping

    def save(self, output: Path) -> None:
        """كتابة الأرشيف بنفس الترتيب، مع استبدال الأجزاء المعدّلة فقط."""
        for name in self._dirty:
            root = self._trees.get(name)
            if root is not None:
                self.entries[name] = etree.tostring(
                    root, xml_declaration=True, encoding="UTF-8", standalone=True
                )

        output.parent.mkdir(parents=True, exist_ok=True)
        if not self._dirty:
            # مفيش تعديل — ننسخ الملف كما هو بالبايت
            shutil.copyfile(self.path, output)
            return

        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in self.order:
                archive.writestr(name, self.entries[name])
