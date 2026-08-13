"""قياس حجم تعليمات النظام لكل مجال مقابل حدّ التخزين المؤقت.

الحد الأدنى للتخزين المؤقت يختلف حسب الموديل. لو التعليمات أقصر منه،
التخزين المؤقت **بيتجاهل بصمت** — من غير خطأ، وبتدفع السعر الكامل في
كل نداء. مع ملف كبير فيه عشرات الدفعات ده فرق حقيقي.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.tools.translator.prompts import DOMAIN_LABELS, build_system_prompt  # noqa: E402

# الحد الأدنى للبادئة القابلة للتخزين المؤقت (توكن)
MINIMUM = {"claude-sonnet-5": 1024, "claude-opus-5": 512, "claude-haiku-4-5": 2048}


def main() -> int:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    for model in ("claude-sonnet-5", "claude-opus-5"):
        threshold = MINIMUM[model]
        print(f"\n=== {model}  (الحد الأدنى {threshold} توكن) ===")

        for domain in DOMAIN_LABELS:
            for glossary_size in (0, 5):
                glossary = [(f"مصطلح{i}", f"term{i}") for i in range(glossary_size)]
                prompt = build_system_prompt(domain=domain, glossary=glossary)

                count = client.messages.count_tokens(
                    model=model,
                    system=[{"type": "text", "text": prompt}],
                    messages=[{"role": "user", "content": "x"}],
                ).input_tokens

                status = "✓ يتخزّن" if count >= threshold else "✗ أقصر من الحد"
                print(f"  {DOMAIN_LABELS[domain]:8} مصطلحات={glossary_size}: "
                      f"{count:>5} توكن   {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
