"""Translation manager loads canonical locale filenames."""
from pathlib import Path

from core.i18n import Language, TranslationManager


ROOT = Path(__file__).resolve().parents[1]


def test_translation_manager_loads_canonical_english_catalog() -> None:
    saved: list[str] = []
    manager = TranslationManager(
        ROOT / "translations",
        language_loader=lambda: "en_US",
        language_saver=saved.append,
    )

    assert manager.current_language is Language.EN_US
    assert manager.translate("map.dimension") == "Dimension"
    assert "Language.ZH_CN" not in manager.available_language_codes

    manager.set_language(Language.ZH_CN)
    assert saved == ["zh_CN"]
    assert manager.translate("map.dimension") == "维度"
