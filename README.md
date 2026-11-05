# CAPTURA_CEROS — Herramienta Portable de Captura Local, Revisión y Rollback

Aplicación de escritorio portable (`CAPTURA_CEROS.exe`) diseñada para capturar localmente la clasificación de directorios y archivos PDF que quedaron con campos en ceros (`01_00_00_00_00_00_...`) en la ruta de red:
`\\172.40.5.84\ssdirec\REVISANDO\ENTREGA 1\4 ENTREGA SELLOS LIBROS\SELLOS LIBROS\Tuxtla Gutiérrez`

---

## Reglas de Negocio Implementadas

1. **Orden de Campos:**
   `[Delegación]_[Sección]_[Libro]_[Tomo]_[Volumen]_[Fraccionamiento]_[Año]_[Inscripción]_[Bis].pdf`
   - **Delegación:** Por defecto `01` (Tuxtla Gutiérrez).
   - **Sección, Libro, Volumen:** Numéricos de 2 dígitos por defecto (`00`).
   - **Tomo y Fraccionamiento:** Numéricos de 2 dígitos por defecto (`00`), con casilla para habilitar **texto alfanumérico opcional** (ej. `01_AUXILIAR`, `FRACCIONAMIENTO_...`).
2. **Regla para la Carpeta:**
   - Adopta los campos capturados (`Delegación` a `Fraccionamiento`), conserva su **Año** (si no es `0000`; si es `0000` permite capturarlo) y conserva siempre el sufijo **`_REVISAR`** (o `_REVISAR_2`, etc.).
3. **Regla para los Archivos PDF:**
   - **Solo se renombran los PDFs que tienen ceros** en Sección, Libro, Tomo, Volumen y Fraccionamiento (`01_00_00_00_00_00_...`).
   - Si dentro del directorio existen PDFs que ya tienen datos en esos campos (ej. `01_01_01_00_00_00_1991_0001_00.pdf`), **se ignoran automáticamente** y se mantienen intactos.
   - Los PDFs en ceros adoptan los campos capturados + el **Año de la carpeta**, manteniendo intactos su **Número de Inscripción/Registro** y su **Bis (`00`)**.
4. **100% Captura Local, Revisión Previa y Rollback:**
   - **Al guardar una captura NO se modifica ningún archivo ni carpeta física.** Todo se almacena localmente en `data/capturas_ceros.db` y `data/respaldo_capturas.json`.
   - En la pestaña **2. Revisión, Aprobación, Aplicar Cambios y Rollback**, puedes auditar el *Antes vs. Después*, exportar a Excel (CSV), aprobar y aplicar los cambios cuando se autorice, o ejecutar **Rollback** para devolver cualquier directorio y sus PDFs a sus nombres originales exactos.
5. **Visor de PDF Integrado:**
   - Al seleccionar un directorio o hacer clic sobre cualquier archivo PDF de la lista, el visor lateral muestra el documento con controles de **Página Anterior/Siguiente, Zoom y Rotación de 90°** para leer los sellos sin bloquear los archivos en red.
