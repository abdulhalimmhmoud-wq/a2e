"""تجميع الـ runs وتوسيم التنسيق — منطق مشترك بين Excel و PowerPoint.

الصيغتين بيستخدموا نفس البنية: عنصر حاوٍ فيه عدة `r` وكل واحد جوّه
خصائص تنسيق `rPr` ونص `t`. فبنكتب المنطق مرة واحدة ونمرّر أسماء
العناصر المؤهَّلة حسب الصيغة.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from lxml import etree

from app.tools.translator.formats.base import parse_tagged_text, tags_in


@dataclass
class RunGroup:
    sig: str
    runs: list[etree._Element] = field(default_factory=list)
    text: str = ""


def group_runs(
    runs: list[etree._Element], props_q: str, text_q: str
) -> list[RunGroup]:
    """دمج الـ runs المتتالية اللي ليها نفس التنسيق."""
    groups: list[RunGroup] = []
    for run in runs:
        props = run.find(props_q)
        sig = etree.tostring(props, encoding="unicode") if props is not None else ""
        node = run.find(text_q)
        text = (node.text or "") if node is not None else ""

        if groups and groups[-1].sig == sig:
            groups[-1].runs.append(run)
            groups[-1].text += text
        else:
            groups.append(RunGroup(sig=sig, runs=[run], text=text))
    return groups


def _dominant_index(groups: list[RunGroup]) -> int | None:
    best_index, best_len = None, -1
    for index, group in enumerate(groups):
        if len(group.text) > best_len:
            best_index, best_len = index, len(group.text)
    return best_index


def build_tagged(groups: list[RunGroup]) -> tuple[str, dict[str, str]]:
    """نص موسوم + خريطة الوسوم (نفس قاعدة معالج Word)."""
    dominant = _dominant_index(groups)
    parts: list[str] = []
    placeholders: dict[str, str] = {}
    counter = 0

    for index, group in enumerate(groups):
        if not group.text:
            continue
        if index == dominant:
            parts.append(group.text)
        else:
            counter += 1
            tag = str(counter)
            placeholders[tag] = group.sig
            parts.append(f"<g{tag}>{group.text}</g{tag}>")

    return "".join(parts), placeholders


def tag_map(groups: list[RunGroup]) -> dict[str, int]:
    """إعادة بناء (رقم الوسم → فهرس المجموعة) بنفس ترتيب build_tagged."""
    dominant = _dominant_index(groups)
    mapping: dict[str, int] = {}
    counter = 0
    for index, group in enumerate(groups):
        if not group.text:
            continue
        if index == dominant:
            continue
        counter += 1
        mapping[str(counter)] = index
    return mapping


def rebuild_runs(
    container: etree._Element,
    groups: list[RunGroup],
    target: str,
    *,
    run_q: str,
    text_q: str,
    props_q: str,
    preserve_before: tuple[str, ...] = (),
) -> None:
    """استبدال الـ runs بالنص المترجم مع الحفاظ على التنسيق.

    لو النموذج ضيّع وسمًا، بنرجع لوضع آمن: كل النص بالتنسيق الغالب.
    التنسيق بيتبسّط لكن النص عمره ما بيضيع.
    """
    if not groups:
        return

    mapping = tag_map(groups)
    dominant = _dominant_index(groups)
    pieces = parse_tagged_text(target)

    if not set(mapping).issubset(tags_in(target)) or dominant is None:
        pieces = [(None, "".join(text for _, text in pieces))]

    assignments: list[tuple[int, str]] = []
    for tag, text in pieces:
        if not text:
            continue
        index = mapping.get(tag, dominant) if tag else dominant
        if assignments and assignments[-1][0] == index:
            assignments[-1] = (index, assignments[-1][1] + text)
        else:
            assignments.append((index, text))

    new_runs: list[etree._Element] = []
    for index, text in assignments:
        template = groups[index].runs[0]
        run = copy.deepcopy(template)
        for child in list(run):
            if child.tag != props_q:
                run.remove(child)
        node = etree.SubElement(run, text_q)
        node.text = text
        # ضروري للحفاظ على المسافات في أول/آخر النص
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        new_runs.append(run)

    old_runs = {id(run) for group in groups for run in group.runs}
    kept_head = [
        child
        for child in container
        if child.tag in preserve_before and id(child) not in old_runs
    ]
    kept_tail = [
        child
        for child in container
        if child.tag not in preserve_before and id(child) not in old_runs
    ]

    for child in list(container):
        container.remove(child)
    for child in kept_head:
        container.append(child)
    for run in new_runs:
        container.append(run)
    for child in kept_tail:
        container.append(child)
