"""Offline Spanish/English translation using locally installed Argos models."""
from __future__ import annotations

import os
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent / "tools" / "argos-models"
os.environ.setdefault("ARGOS_PACKAGE_DIR", str(MODEL_DIR))

LANGUAGE_PAIRS = {"es-en": ("es", "en"), "en-es": ("en", "es")}


def get_translator(direction: str):
    if direction == "none":
        return None
    if direction not in LANGUAGE_PAIRS:
        raise ValueError("Dirección de traducción no válida.")
    try:
        import argostranslate.translate
    except ImportError as exc:
        raise RuntimeError("Falta el traductor local. Ejecuta instalar.ps1.") from exc
    source, target = LANGUAGE_PAIRS[direction]
    languages = {language.code: language for language in argostranslate.translate.get_installed_languages()}
    if source not in languages or target not in languages:
        raise RuntimeError("Faltan modelos de traducción. Ejecuta instalar.ps1 para descargarlos.")
    translation = languages[source].get_translation(languages[target])
    if translation is None:
        raise RuntimeError("Falta el modelo para esta dirección. Ejecuta instalar.ps1.")
    return translation
