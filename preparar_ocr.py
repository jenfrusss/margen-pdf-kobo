"""Cache the Spanish/English Latin OCR model during installation."""
import numpy as np
from rapidocr import ModelType, OCRVersion, RapidOCR

engine = RapidOCR(params={"Rec.lang_type": "latin", "Rec.ocr_version": OCRVersion.PPOCRV5,
                          "Rec.model_type": ModelType.MOBILE})
engine(np.full((100, 300, 3), 255, dtype=np.uint8))
print("Modelo OCR español/inglés preparado.")
