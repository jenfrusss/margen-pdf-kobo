# Margen

Aplicación local para convertir PDF con texto seleccionable a EPUB o KEPUB para Kobo. Los archivos se procesan en tu equipo y los resultados quedan en `outputs/`.

## Iniciar en Windows

1. Abre PowerShell en esta carpeta.
2. Ejecuta `powershell -ExecutionPolicy Bypass -File .\instalar.ps1` una vez. Instala Flask y PyMuPDF en `.venv/` y descarga `kepubify` v4.0.4 desde su [publicación oficial](https://github.com/pgaskin/kepubify/releases/tag/v4.0.4).
3. Ejecuta `powershell -ExecutionPolicy Bypass -File .\iniciar.ps1` y abre `http://127.0.0.1:8765` si no se abre automáticamente.

Arrastra uno o varios PDF. Puedes elegir EPUB o KEPUB, ajustar título y autor, y conservar portada, índice e imágenes. Descarga cada resultado desde la interfaz.

## Alcance

- Acepta PDF de hasta 80 MB por archivo con texto seleccionable.
- Usa los marcadores de capítulos del PDF si existen; de lo contrario crea una sección continua.
- La maquetación de dos columnas, tablas complejas y notas al pie puede requerir retoques posteriores.
- PDF escaneados requieren OCR antes de convertirlos.
- El servidor escucha solo en `127.0.0.1`.
