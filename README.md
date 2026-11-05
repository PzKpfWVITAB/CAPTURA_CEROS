# CAPTURA_CEROS — Captura Local, Intercambio JSON y Modo Administrador con Registro MySQL

Herramienta de escritorio portable (`CAPTURA_CEROS.exe`) diseñada para capturar de forma **100% local** la clasificación de directorios y archivos PDF que quedaron con campos en ceros (`01_00_00_00_00_00_...`), intercambiar las capturas mediante archivos `.json` con **UUID único** y, en **Modo Administrador (protegido por PIN)**, aplicar los cambios físicos registrando cada movimiento en una base de datos **MySQL** (incluyendo nombre original, ruta original, nombre nuevo, ruta nueva, fecha, conteo de páginas, hash `SHA-256` y `UUID` vinculante).

---

## Estructura SQL para la Base de Datos MySQL (Copiar y Pegar)

Puedes copiar y pegar directamente este bloque SQL en tu gestor de MySQL / MariaDB (HeidiSQL, phpMyAdmin, DBeaver o consola de Laragon).
*(Nota: La aplicación también cuenta con un botón **"🔌 Probar Conexión y Crear Tablas"** dentro del Modo Administrador que ejecuta este mismo esquema automáticamente).*

```sql
-- 1. Crear la base de datos
CREATE DATABASE IF NOT EXISTS `captura_ceros_bd`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `captura_ceros_bd`;

-- 2. Tabla principal de movimientos físicos por archivo PDF (Con Hash SHA-256, Páginas y UUID vinculante)
CREATE TABLE IF NOT EXISTS `cambios_fisicos_archivos` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `uuid` CHAR(36) NOT NULL COMMENT 'UUID unico que vincula el archivo en el JSON/SQLite local con MySQL',
    `folder_uuid` CHAR(36) NOT NULL COMMENT 'UUID del directorio padre al que pertenece el PDF',
    `nombre_original` VARCHAR(255) NOT NULL COMMENT 'Nombre del PDF antes de renombrar (ej. 01_00_00_00_00_00_0000_0001_00.pdf)',
    `ruta_original` VARCHAR(1000) NOT NULL COMMENT 'Ruta completa original antes del cambio fisico',
    `nombre_nuevo` VARCHAR(255) NOT NULL COMMENT 'Nombre nuevo aplicado al PDF',
    `ruta_nueva` VARCHAR(1000) NOT NULL COMMENT 'Ruta completa final ya con carpeta y archivo renombrados',
    `fecha` DATETIME NOT NULL COMMENT 'Fecha y hora exacta en que se aplico el cambio fisico',
    `paginas` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Total de paginas del archivo PDF',
    `hash_sha256` CHAR(64) NOT NULL COMMENT 'Hash SHA-256 del contenido binario del PDF',
    `estado` VARCHAR(30) NOT NULL DEFAULT 'APLICADO' COMMENT 'APLICADO o REVERTIDO_ROLLBACK',
    `fecha_rollback` DATETIME NULL DEFAULT NULL COMMENT 'Fecha en que se revirtio en caso de Rollback',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_archivo_uuid` (`uuid`),
    KEY `idx_folder_uuid` (`folder_uuid`),
    KEY `idx_hash_sha256` (`hash_sha256`),
    KEY `idx_nombre_original` (`nombre_original`),
    KEY `idx_nombre_nuevo` (`nombre_nuevo`),
    KEY `idx_fecha` (`fecha`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Tabla de directorios aplicados (Vinculada mediante folder_uuid)
CREATE TABLE IF NOT EXISTS `directorios_aplicados` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `folder_uuid` CHAR(36) NOT NULL COMMENT 'UUID unico del directorio generado en la captura local',
    `nombre_carpeta_original` VARCHAR(255) NOT NULL,
    `ruta_carpeta_original` VARCHAR(1000) NOT NULL,
    `nombre_carpeta_nuevo` VARCHAR(255) NOT NULL,
    `ruta_carpeta_nueva` VARCHAR(1000) NOT NULL,
    `delegacion` VARCHAR(10) NOT NULL,
    `seccion` VARCHAR(20) NOT NULL,
    `libro` VARCHAR(20) NOT NULL,
    `tomo` VARCHAR(150) NOT NULL,
    `volumen` VARCHAR(20) NOT NULL,
    `fraccionamiento` VARCHAR(200) NOT NULL,
    `anio` CHAR(4) NOT NULL,
    `sufijo` VARCHAR(100) NOT NULL,
    `total_pdfs_renombrados` INT UNSIGNED NOT NULL DEFAULT 0,
    `total_pdfs_ignorados` INT UNSIGNED NOT NULL DEFAULT 0,
    `estado` VARCHAR(30) NOT NULL DEFAULT 'APLICADO',
    `fecha_aplicacion` DATETIME NOT NULL,
    `fecha_rollback` DATETIME NULL DEFAULT NULL,
    `notas` TEXT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_folder_uuid` (`folder_uuid`),
    KEY `idx_estado` (`estado`),
    KEY `idx_fecha_aplicacion` (`fecha_aplicacion`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

---

## Flujo de Trabajo Operativo

### Fase 1: Capturistas (Modo Capturista — 100% Local)
1. El capturista ejecuta **`CAPTURA_CEROS.exe`**. Por defecto arranca en **Modo Capturista** (los botones de cambios físicos y MySQL están bloqueados).
2. Selecciona un directorio individual, visualiza el PDF en el visor lateral (con scroll continuo de páginas, zoom y rotación) y captura `Sección`, `Libro`, `Tomo`, `Volumen`, `Fraccionamiento` (y `Año` si la carpeta tenía `0000`).
3. Al presionar **💾 GUARDAR CAPTURA LOCALMENTE**:
   - Se asigna un **`folder_uuid`** al directorio y un **`file_uuid`** único a cada PDF.
   - Se limpia el formulario automáticamente para capturar la siguiente carpeta.
4. Al finalizar su turno, el capturista va a la Pestaña 2 y presiona **📄 Exportar Respaldo JSON (Para entregar)**, entregándote su archivo `.json`.

### Fase 2: Revisión y Aplicación Física (Modo Administrador)
1. En tu equipo, abres **`CAPTURA_CEROS.exe`** e importas los archivos `.json` de los capturistas con el botón **📥 Importar JSON (Recibir capturas)** (conservando intactos todos los `UUID`).
2. Haces clic arriba a la derecha en **🔒 Activar Modo Administrador** e ingresas el PIN:
   - **PIN:** `1944123321`
3. Se desbloquea el **Panel Exclusivo de Modo Administrador**:
   - Puedes configurar la conexión a tu servidor MySQL en **🗄️ Configurar BD MySQL (Cambios Físicos)...** (por defecto `127.0.0.1:3306`, usuario `root`, BD `captura_ceros_bd`).
   - Revisas las propuestas, las apruebas (**✅ Aprobar / Desaprobar Seleccionada**) y presionas **🚀 APLICAR CAMBIOS FÍSICOS A SELECCIONADA** o **🚀 APLICAR TODAS LAS APROBADAS**.
   - Al aplicar:
     1. Lee cada archivo PDF, calcula su **Hash `SHA-256`** y cuenta sus **páginas**.
     2. Renombra físicamente los PDFs en ceros (ignorando los que ya tenían datos) y renombra la carpeta (conservando el año y el sufijo `_REVISAR`).
     3. Inserta los registros en las tablas MySQL `cambios_fisicos_archivos` y `directorios_aplicados` vinculados por el mismo `UUID` de la captura local.
4. Si en cualquier momento necesitas deshacer un cambio aplicado, seleccionas la carpeta y presionas **⏪ ROLLBACK FÍSICO (Revertir a Original)**: devuelve los archivos y la carpeta a sus nombres originales y actualiza el estado en MySQL a `REVERTIDO_ROLLBACK`.
