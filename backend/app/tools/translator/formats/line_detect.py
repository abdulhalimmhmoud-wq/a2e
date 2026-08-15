"""كشف مواضع السطور في صفحة ممسوحة.

الصفحة اللي فيها طبقة نص بتدّي مواضعها مجانًا من بنية الـ PDF. الصفحة
الممسوحة مالهاش، فالتصدير كان بيوزّع الترجمة على مساحة الكتابة
**بالتقدير** — والنتيجة صفحة سطورها مش في أماكنها وفيها فراغات.

الوحدة دي بتجيب المواضع الحقيقية بالكشف البصري. الاعتماد اختياري:
لو Surya مش متثبّت أو فشل، بيرجع None والتصدير بيرجع للتوزيع
التقديري بدل ما يقع.
"""
from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

_predictor = None
_unavailable = False

# الكشف بيشتغل على المعالج، فتحميل النموذج مرة واحدة بيفرق كتير
def _get_predictor():
    global _predictor, _unavailable  # noqa: PLW0603

    if _unavailable:
        return None
    if _predictor is not None:
        return _predictor

    try:
        from surya.detection import DetectionPredictor

        _predictor = DetectionPredictor(device="cpu")
    except Exception as exc:  # noqa: BLE001
        logger.info("كشف السطور مش متاح (%s) — هيتم التوزيع بالتقدير", exc)
        _unavailable = True
        return None
    return _predictor


def detect_lines(
    image_bytes: bytes,
    page_width: float,
    page_height: float,
    min_confidence: float = 0.5,
) -> list[tuple[float, float, float, float]] | None:
    """مواضع السطور بإحداثيات **الصفحة** مش الصورة.

    الكشف بيرجّع إحداثيات بالبكسل على الصورة المرسومة، والتصدير
    محتاجها بنقاط الصفحة — فبنحوّلها بنسبة المقاسين.
    """
    predictor = _get_predictor()
    if predictor is None:
        return None

    try:
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes))
        results = predictor([image])
    except Exception as exc:  # noqa: BLE001
        logger.warning("كشف السطور فشل: %s", exc)
        return None

    if not results:
        return None

    scale_x = page_width / image.width
    scale_y = page_height / image.height

    boxes: list[tuple[float, float, float, float]] = []
    for box in getattr(results[0], "bboxes", []) or []:
        if getattr(box, "confidence", 1.0) < min_confidence:
            continue
        x0, y0, x1, y1 = box.bbox
        boxes.append((x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y))

    if not boxes:
        return None

    # ترتيب القراءة: من فوق لتحت، والمتقاربين رأسيًا حسب موضعهم الأفقي
    boxes.sort(key=lambda b: (round(b[1] / 12), b[0]))
    return boxes


def available() -> bool:
    """هل الكشف البصري متاح على الجهاز ده؟"""
    return _get_predictor() is not None
