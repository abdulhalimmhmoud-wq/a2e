"""إعدادات النظام المركزية."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# جذر المشروع: .../Shaltot
BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Shaltot Suite"
    debug: bool = True

    # مفتاح Anthropic — يُقرأ من .env ولا يُخزَّن في قاعدة البيانات أبدًا
    anthropic_api_key: str = ""

    # الموديلات
    default_model: str = "claude-sonnet-5"
    legal_model: str = "claude-opus-5"

    # المسارات
    storage_dir: Path = BASE_DIR / "storage"
    db_path: Path = BASE_DIR / "storage" / "shaltot.db"

    # حدود الرفع
    max_upload_mb: int = 200

    # تقسيم دفعات الترجمة (تقريبي بالحروف قبل عدّ التوكن)
    batch_char_budget: int = 6000
    batch_max_segments: int = 40

    # عدد الدفعات المتوازية. الدفعة الأولى بتتنفّذ لوحدها دايمًا عشان
    # تكتب الكاش، وبعدها الباقي بيتوازى ويقرا منه.
    # زوّدها لو حدود الاستخدام عندك عالية، قلّلها لو بيجيلك 429.
    translation_concurrency: int = 4

    # عدد الكلمات المُفترض للصفحة عند غياب عدد صفحات حقيقي
    words_per_page: int = 250

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    (settings.storage_dir / "projects").mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()


# ---------------------------------------------------------------------------
# جدول الأسعار — دولار لكل مليون توكن (المصدر: أسعار Anthropic الرسمية)
# ---------------------------------------------------------------------------
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-5": {
        "input": 5.00,
        "output": 25.00,
        "label": "Claude Opus 5",
        "note": "الأعلى جودة — للعقود والمستندات القانونية الحرجة",
    },
    "claude-sonnet-5": {
        # عرض تعريفي 2.00/10.00 حتى 2026-08-31 ثم 3.00/15.00
        "input": 2.00,
        "output": 10.00,
        "input_after_promo": 3.00,
        "output_after_promo": 15.00,
        "promo_ends": "2026-08-31",
        "label": "Claude Sonnet 5",
        "note": "الافتراضي — جودة قريبة من Opus بثلث السعر",
    },
    "claude-haiku-4-5": {
        "input": 1.00,
        "output": 5.00,
        "label": "Claude Haiku 4.5",
        "note": "مهام مساعدة سريعة ورخيصة",
    },
}

# مضاعِفات التكلفة
CACHE_READ_MULTIPLIER = 0.10   # قراءة من الكاش = عُشر سعر الإدخال
CACHE_WRITE_MULTIPLIER = 1.25  # كتابة للكاش (5 دقائق)
BATCH_DISCOUNT = 0.50          # الـ Batch API يخصم 50%
