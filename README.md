# Margen

Aplicación local para convertir PDF con texto seleccionable a EPUB o KEPUB para Kobo. Los archivos se procesan en tu equipo y los resultados quedan en `outputs/`.

## Iniciar en Windows

1. Abre PowerShell en esta carpeta.
2. Ejecuta `powershell -ExecutionPolicy Bypass -File .\instalar.ps1` una vez (y después de actualizar el proyecto). Instala las dependencias en `.venv/`, descarga `kepubify` v4.0.4 desde su [publicación oficial](https://github.com/pgaskin/kepubify/releases/tag/v4.0.4) y los modelos de traducción español ↔ inglés de [Argos Translate](https://argos-translate.readthedocs.io/en/stable/).
3. Ejecuta `powershell -ExecutionPolicy Bypass -File .\iniciar.ps1` y abre `http://127.0.0.1:8765` si no se abre automáticamente.

Arrastra uno o varios PDF. Puedes elegir EPUB o KEPUB, traducir el texto de español a inglés o de inglés a español, ajustar título y autor, y conservar portada, índice e imágenes. Descarga cada resultado desde la interfaz. La traducción se hace localmente después de instalar los modelos; puede tardar varios minutos en libros largos.

## Enviar al Kobo por USB

Conecta el Kobo al ordenador y toca **Conectar** en la pantalla del lector. La app comprueba periódicamente si aparece una unidad Kobo; también puedes pulsar **Actualizar**. Después de convertir, pulsa **Enviar al Kobo** junto al libro. El archivo se copia a la carpeta principal de la unidad y la app muestra la ruta final. Si ya existe otro libro con ese nombre, crea una copia numerada sin reemplazar el anterior. [Expulsa el dispositivo de forma segura](https://help.kobo.com/hc/en-us/articles/360017765933-Eject-your-Kobo-eReader-when-connected-to-a-computer) antes de desconectarlo. La detección requiere que el lector esté montado como unidad y tenga su carpeta `.kobo`.

## Alcance

- Acepta PDF de hasta 80 MB por archivo con texto seleccionable.
- Usa los marcadores de capítulos del PDF si existen; de lo contrario crea una sección continua.
- La maquetación de dos columnas, tablas complejas y notas al pie puede requerir retoques posteriores.
- PDF escaneados requieren OCR antes de convertirlos.
- La traducción automática puede necesitar revisión, especialmente en nombres propios, expresiones y documentos con columnas. Las imágenes y la portada no se traducen.
- El servidor escucha solo en `127.0.0.1`.
