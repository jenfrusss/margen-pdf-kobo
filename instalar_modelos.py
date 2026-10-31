"""Install the two Argos translation directions in the local tools directory."""
import os
from pathlib import Path

model_dir = Path(__file__).resolve().parent / "tools" / "argos-models"
model_dir.mkdir(parents=True, exist_ok=True)
os.environ["ARGOS_PACKAGE_DIR"] = str(model_dir)

import argostranslate.package

installed = {(item.from_code, item.to_code) for item in argostranslate.package.get_installed_packages()}
needed = {("es", "en"), ("en", "es")} - installed
if needed:
    print("Buscando modelos de traduccion...", flush=True)
    argostranslate.package.update_package_index()
    available = {(item.from_code, item.to_code): item for item in argostranslate.package.get_available_packages()}
    for pair in sorted(needed):
        if pair not in available:
            raise RuntimeError(f"No hay modelo disponible para {pair[0]} a {pair[1]}.")
        print(f"Descargando {pair[0]} a {pair[1]}...", flush=True)
        path = available[pair].download()
        argostranslate.package.install_from_path(path)
print("Modelos espanol e ingles listos.", flush=True)
