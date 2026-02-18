import json
import os
from typing import Any, Dict


class L10n:
    def __init__(self, default_lang: str = "uk"):
        self.default_lang = default_lang
        self.locales: Dict[str, Dict[str, Any]] = {}
        self._load_locales()

    def _load_locales(self):
        locales_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "locales"
        )
        if not os.path.exists(locales_dir):
            return

        for lang in os.listdir(locales_dir):
            lang_path = os.path.join(locales_dir, lang)
            if not os.path.isdir(lang_path):
                continue

            self.locales[lang] = {}
            for filename in os.listdir(lang_path):
                if filename.endswith(".json"):
                    namespace = filename[:-5]
                    with open(
                        os.path.join(lang_path, filename), "r", encoding="utf-8"
                    ) as f:
                        data = json.load(f)
                        if namespace == "common":
                            # common keys are accessible without prefix
                            self.locales[lang].update(data)
                        else:
                            self.locales[lang][namespace] = data

    def format_value(self, key: str, lang: str = None, **kwargs) -> str:
        lang = lang or self.default_lang
        if lang not in self.locales:
            lang = self.default_lang

        data = self.locales.get(lang, {})

        # Try to find the key
        parts = key.split(".")
        value = data
        try:
            for part in parts:
                value = value[part]
            if isinstance(value, str):
                return value.format(**kwargs)
            return str(value)
        except (KeyError, TypeError):
            return key


l10n = L10n()
