"""
Almacenamiento local (SQLite + exportación/importación JSON con UUID) y motor transaccional
con registro de movimientos físicos en MySQL (y respaldo local), cálculo de Hash SHA-256,
conteo de páginas PDF y soporte de Rollback completo.
"""

import contextlib
import csv
import datetime
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import fitz  # PyMuPDF
import pymysql
import pymysql.cursors


def get_app_base_dir() -> str:
    """Retorna el directorio donde reside el .exe o el script principal."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def compute_pdf_hash_and_pages(pdf_path: str) -> Tuple[str, int]:
    """
    Calcula el hash SHA-256 del archivo PDF y obtiene su número exacto de páginas.
    Lee el archivo una sola vez en memoria para minimizar tráfico en carpetas de red.
    """
    with open(pdf_path, "rb") as f:
        raw_bytes = f.read()

    sha256_hash = hashlib.sha256(raw_bytes).hexdigest()
    pages_count = 0
    try:
        with fitz.open(stream=raw_bytes, filetype="pdf") as doc:
            pages_count = len(doc)
    except Exception:
        pages_count = 0

    return sha256_hash, pages_count


class MySQLConfigManager:
    """Gestiona la configuración de conexión a la BD MySQL donde se registran los cambios físicos."""

    def __init__(self, data_dir: str) -> None:
        self.config_path = os.path.join(data_dir, "mysql_config.json")
        self.default_config: Dict[str, Any] = {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 3306,
            "user": "root",
            "password": "",
            "database": "captura_ceros_bd",
            "auto_create_tables": True,
        }

    def load(self) -> Dict[str, Any]:
        if not os.path.isfile(self.config_path):
            self.save(self.default_config)
            return dict(self.default_config)
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            merged = dict(self.default_config)
            merged.update(loaded)
            return merged
        except Exception:
            return dict(self.default_config)

    def save(self, cfg: Dict[str, Any]) -> None:
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

    def get_connection(self, create_db_if_missing: bool = True) -> pymysql.Connection:
        cfg = self.load()
        host = str(cfg.get("host", "127.0.0.1")).strip()
        port = int(cfg.get("port", 3306))
        user = str(cfg.get("user", "root")).strip()
        password = str(cfg.get("password", ""))
        database = str(cfg.get("database", "captura_ceros_bd")).strip()

        if create_db_if_missing and cfg.get("auto_create_tables", True):
            server_conn = pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                charset="utf8mb4",
                connect_timeout=5,
            )
            try:
                with server_conn.cursor() as cur:
                    cur.execute(
                        f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
                    )
                server_conn.commit()
            finally:
                server_conn.close()

        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
        )

        if cfg.get("auto_create_tables", True):
            self.ensure_schema(conn)

        return conn

    @staticmethod
    def ensure_schema(conn: pymysql.Connection) -> None:
        """Crea las tablas en MySQL si no existen."""
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS `directorios_aplicados` (
                    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    `folder_uuid` CHAR(36) NOT NULL,
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
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS `cambios_fisicos_archivos` (
                    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    `uuid` CHAR(36) NOT NULL COMMENT 'UUID unico compartido con el JSON/registro local',
                    `folder_uuid` CHAR(36) NOT NULL COMMENT 'UUID del directorio padre',
                    `nombre_original` VARCHAR(255) NOT NULL,
                    `ruta_original` VARCHAR(1000) NOT NULL,
                    `nombre_nuevo` VARCHAR(255) NOT NULL,
                    `ruta_nueva` VARCHAR(1000) NOT NULL,
                    `fecha` DATETIME NOT NULL,
                    `paginas` INT UNSIGNED NOT NULL DEFAULT 0,
                    `hash_sha256` CHAR(64) NOT NULL,
                    `estado` VARCHAR(30) NOT NULL DEFAULT 'APLICADO',
                    `fecha_rollback` DATETIME NULL DEFAULT NULL,
                    PRIMARY KEY (`id`),
                    UNIQUE KEY `uk_archivo_uuid` (`uuid`),
                    KEY `idx_folder_uuid` (`folder_uuid`),
                    KEY `idx_hash_sha256` (`hash_sha256`),
                    KEY `idx_nombre_original` (`nombre_original`),
                    KEY `idx_nombre_nuevo` (`nombre_nuevo`),
                    KEY `idx_fecha` (`fecha`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                """
            )
        conn.commit()

    def test_connection(self) -> Tuple[bool, str]:
        try:
            conn = self.get_connection(create_db_if_missing=True)
            conn.close()
            cfg = self.load()
            return (
                True,
                f"Conexión MySQL exitosa a {cfg['host']}:{cfg['port']} / BD: `{cfg['database']}` (Tablas verificadas).",
            )
        except Exception as exc:
            return False, f"Error al conectar a MySQL:\n{exc}"


class LocalCaptureStore:
    """
    Gestiona las capturas 100% locales (con UUID por carpeta y por archivo),
    la importación/exportación de lotes JSON y la aplicación física en MySQL.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        base_dir = get_app_base_dir()
        if db_path:
            self.data_dir = os.path.dirname(os.path.abspath(db_path))
            os.makedirs(self.data_dir, exist_ok=True)
            self.db_path = db_path
        else:
            self.data_dir = os.path.join(base_dir, "data")
            os.makedirs(self.data_dir, exist_ok=True)
            self.db_path = os.path.join(self.data_dir, "capturas_ceros.db")

        self.mysql_manager = MySQLConfigManager(self.data_dir)
        self._init_db()

    @contextlib.contextmanager
    def _get_conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS folder_captures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder_uuid TEXT UNIQUE NOT NULL,
                    original_folder_path TEXT UNIQUE NOT NULL,
                    parent_dir TEXT NOT NULL,
                    original_folder_name TEXT NOT NULL,
                    proposed_folder_name TEXT NOT NULL,
                    delegacion TEXT NOT NULL,
                    seccion TEXT NOT NULL,
                    libro TEXT NOT NULL,
                    tomo TEXT NOT NULL,
                    volumen TEXT NOT NULL,
                    fraccionamiento TEXT NOT NULL,
                    anio TEXT NOT NULL,
                    suffix TEXT NOT NULL,
                    total_pdfs_rename INTEGER NOT NULL DEFAULT 0,
                    total_pdfs_ignored INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'PENDIENTE_REVISION',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    applied_at TEXT DEFAULT '',
                    rolled_back_at TEXT DEFAULT '',
                    last_error TEXT DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_captures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_uuid TEXT UNIQUE NOT NULL,
                    folder_capture_id INTEGER NOT NULL,
                    folder_uuid TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    original_full_path TEXT NOT NULL,
                    proposed_filename TEXT NOT NULL,
                    proposed_full_path TEXT NOT NULL,
                    is_target_zero INTEGER NOT NULL DEFAULT 1,
                    inscripcion_bis_tail TEXT DEFAULT '',
                    pages INTEGER NOT NULL DEFAULT 0,
                    file_hash TEXT DEFAULT '',
                    applied_at TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'PENDIENTE',
                    FOREIGN KEY (folder_capture_id) REFERENCES folder_captures(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder_capture_id INTEGER,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            # Asegurar columnas nuevas en bases de datos SQLite existentes (migración transparente)
            self._ensure_sqlite_migrations(conn)
            conn.commit()

    def _ensure_sqlite_migrations(self, conn: sqlite3.Connection) -> None:
        f_cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(folder_captures)").fetchall()
        }
        if "folder_uuid" not in f_cols:
            conn.execute("ALTER TABLE folder_captures ADD COLUMN folder_uuid TEXT DEFAULT ''")
            rows = conn.execute("SELECT id FROM folder_captures WHERE folder_uuid = '' OR folder_uuid IS NULL").fetchall()
            for r in rows:
                conn.execute(
                    "UPDATE folder_captures SET folder_uuid = ? WHERE id = ?",
                    (str(uuid.uuid4()), r["id"]),
                )

        c_cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(file_captures)").fetchall()
        }
        for col_name, col_def in [
            ("file_uuid", "TEXT DEFAULT ''"),
            ("folder_uuid", "TEXT DEFAULT ''"),
            ("original_full_path", "TEXT DEFAULT ''"),
            ("proposed_full_path", "TEXT DEFAULT ''"),
            ("pages", "INTEGER NOT NULL DEFAULT 0"),
            ("file_hash", "TEXT DEFAULT ''"),
            ("applied_at", "TEXT DEFAULT ''"),
        ]:
            if col_name not in c_cols:
                conn.execute(f"ALTER TABLE file_captures ADD COLUMN {col_name} {col_def}")

        # Rellenar file_uuid vacíos si existieran
        empty_files = conn.execute(
            "SELECT id FROM file_captures WHERE file_uuid = '' OR file_uuid IS NULL"
        ).fetchall()
        for ef in empty_files:
            conn.execute(
                "UPDATE file_captures SET file_uuid = ? WHERE id = ?",
                (str(uuid.uuid4()), ef["id"]),
            )

    def save_capture(
        self,
        original_folder_path: str,
        original_folder_name: str,
        proposed_folder_name: str,
        delegacion: str,
        seccion: str,
        libro: str,
        tomo: str,
        volumen: str,
        fraccionamiento: str,
        anio: str,
        suffix: str,
        pdfs_to_rename: List[Any],
        pdfs_ignored: List[Any],
        notes: str = "",
    ) -> int:
        """
        Guarda o actualiza localmente una captura de directorio y sus PDFs.
        Genera y preserva UUIDs únicos tanto para la carpeta como para cada archivo PDF.
        """
        norm_path = os.path.normpath(original_folder_path)
        parent_dir = os.path.dirname(norm_path)
        proposed_folder_full_path = os.path.join(parent_dir, proposed_folder_name)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id, folder_uuid, status FROM folder_captures WHERE original_folder_path = ?",
                (norm_path,),
            ).fetchone()

            if existing and existing["status"] == "APLICADO":
                raise RuntimeError(
                    "Esta carpeta ya tiene cambios APLICADOS físicamente. "
                    "Si deseas modificar su captura, primero ejecuta 'Rollback' en Modo Administrador."
                )

            # Mapa de UUIDs previos por nombre de archivo para no cambiarles el UUID si se edita la captura
            existing_file_uuids: Dict[str, str] = {}
            if existing:
                folder_id = int(existing["id"])
                folder_uuid = existing["folder_uuid"] or str(uuid.uuid4())
                prev_files = conn.execute(
                    "SELECT original_filename, file_uuid FROM file_captures WHERE folder_capture_id = ?",
                    (folder_id,),
                ).fetchall()
                for pf in prev_files:
                    if pf["file_uuid"]:
                        existing_file_uuids[pf["original_filename"]] = pf["file_uuid"]

                conn.execute(
                    """
                    UPDATE folder_captures SET
                        folder_uuid = ?,
                        parent_dir = ?,
                        original_folder_name = ?,
                        proposed_folder_name = ?,
                        delegacion = ?,
                        seccion = ?,
                        libro = ?,
                        tomo = ?,
                        volumen = ?,
                        fraccionamiento = ?,
                        anio = ?,
                        suffix = ?,
                        total_pdfs_rename = ?,
                        total_pdfs_ignored = ?,
                        status = 'PENDIENTE_REVISION',
                        notes = ?,
                        updated_at = ?,
                        last_error = ''
                    WHERE id = ?
                    """,
                    (
                        folder_uuid,
                        parent_dir,
                        original_folder_name,
                        proposed_folder_name,
                        delegacion,
                        seccion,
                        libro,
                        tomo,
                        volumen,
                        fraccionamiento,
                        anio,
                        suffix,
                        len(pdfs_to_rename),
                        len(pdfs_ignored),
                        notes,
                        now,
                        folder_id,
                    ),
                )
                conn.execute(
                    "DELETE FROM file_captures WHERE folder_capture_id = ?",
                    (folder_id,),
                )
            else:
                folder_uuid = str(uuid.uuid4())
                cur = conn.execute(
                    """
                    INSERT INTO folder_captures (
                        folder_uuid, original_folder_path, parent_dir, original_folder_name,
                        proposed_folder_name, delegacion, seccion, libro, tomo,
                        volumen, fraccionamiento, anio, suffix,
                        total_pdfs_rename, total_pdfs_ignored, status, notes,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDIENTE_REVISION', ?, ?, ?)
                    """,
                    (
                        folder_uuid,
                        norm_path,
                        parent_dir,
                        original_folder_name,
                        proposed_folder_name,
                        delegacion,
                        seccion,
                        libro,
                        tomo,
                        volumen,
                        fraccionamiento,
                        anio,
                        suffix,
                        len(pdfs_to_rename),
                        len(pdfs_ignored),
                        notes,
                        now,
                        now,
                    ),
                )
                folder_id = int(cur.lastrowid)

            file_rows = []
            for p in pdfs_to_rename:
                f_uuid = existing_file_uuids.get(p.original_name) or str(uuid.uuid4())
                orig_full = os.path.join(norm_path, p.original_name)
                prop_full = os.path.join(proposed_folder_full_path, p.proposed_name)
                file_rows.append(
                    (
                        f_uuid,
                        folder_id,
                        folder_uuid,
                        p.original_name,
                        orig_full,
                        p.proposed_name,
                        prop_full,
                        1,
                        p.inscripcion_bis_tail,
                        0,
                        "",
                        "",
                        "PENDIENTE",
                    )
                )
            for p in pdfs_ignored:
                f_uuid = existing_file_uuids.get(p.original_name) or str(uuid.uuid4())
                orig_full = os.path.join(norm_path, p.original_name)
                prop_full = os.path.join(proposed_folder_full_path, p.original_name)
                file_rows.append(
                    (
                        f_uuid,
                        folder_id,
                        folder_uuid,
                        p.original_name,
                        orig_full,
                        p.original_name,
                        prop_full,
                        0,
                        "",
                        0,
                        "",
                        "",
                        "IGNORADO",
                    )
                )

            conn.executemany(
                """
                INSERT INTO file_captures (
                    file_uuid, folder_capture_id, folder_uuid,
                    original_filename, original_full_path,
                    proposed_filename, proposed_full_path,
                    is_target_zero, inscripcion_bis_tail,
                    pages, file_hash, applied_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                file_rows,
            )

            conn.execute(
                "INSERT INTO audit_logs (folder_capture_id, action, details, created_at) VALUES (?, ?, ?, ?)",
                (
                    folder_id,
                    "CAPTURA_LOCAL",
                    f"[{folder_uuid}] {original_folder_name} -> {proposed_folder_name} ({len(pdfs_to_rename)} PDFs a renombrar)",
                    now,
                ),
            )
            conn.commit()

        self.export_backup_json()
        return folder_id

    def get_all_captures(self) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM folder_captures ORDER BY updated_at DESC, id DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_capture_by_id(self, capture_id: int) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM folder_captures WHERE id = ?", (capture_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_capture_by_path(self, folder_path: str) -> Optional[Dict[str, Any]]:
        norm_path = os.path.normpath(folder_path)
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM folder_captures WHERE original_folder_path = ?",
                (norm_path,),
            ).fetchone()
            return dict(row) if row else None

    def get_files_for_capture(self, capture_id: int) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM file_captures WHERE folder_capture_id = ? ORDER BY is_target_zero DESC, original_filename ASC",
                (capture_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def set_approval_status(self, capture_id: int, status: str) -> None:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE folder_captures SET status = ?, updated_at = ? WHERE id = ? AND status != 'APLICADO'",
                (status, now, capture_id),
            )
            conn.execute(
                "INSERT INTO audit_logs (folder_capture_id, action, details, created_at) VALUES (?, ?, ?, ?)",
                (capture_id, f"ESTADO_{status}", f"Cambio de estado a {status}", now),
            )
            conn.commit()
        self.export_backup_json()

    def delete_capture(self, capture_id: int) -> None:
        cap = self.get_capture_by_id(capture_id)
        if not cap:
            return
        if cap["status"] == "APLICADO":
            raise RuntimeError(
                "No se puede eliminar un registro que ya fue APLICADO sin antes hacer Rollback."
            )
        with self._get_conn() as conn:
            conn.execute("DELETE FROM file_captures WHERE folder_capture_id = ?", (capture_id,))
            conn.execute("DELETE FROM folder_captures WHERE id = ?", (capture_id,))
            conn.commit()
        self.export_backup_json()

    def apply_capture_changes(
        self,
        capture_id: int,
        require_mysql: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Tuple[bool, str]:
        """
        1. Verifica la conexión a MySQL (si está activa).
        2. Por cada PDF en ceros, calcula su Hash SHA-256 y cuenta sus páginas.
        3. Renombra físicamente los PDFs y el directorio.
        4. Registra todos los movimientos físicos en la BD MySQL (`directorios_aplicados` y `cambios_fisicos_archivos`)
           vinculados mediante el `uuid` local, y actualiza la BD SQLite local.
        """
        cap = self.get_capture_by_id(capture_id)
        if not cap:
            return False, "No se encontró la captura solicitada."

        if cap["status"] == "APLICADO":
            return False, "Esta captura ya fue aplicada anteriormente."

        mysql_cfg = self.mysql_manager.load()
        mysql_conn: Optional[pymysql.Connection] = None
        if require_mysql and mysql_cfg.get("enabled", True):
            try:
                mysql_conn = self.mysql_manager.get_connection(create_db_if_missing=True)
            except Exception as exc:
                return (
                    False,
                    f"No se pudo conectar a la Base de Datos MySQL de cambios físicos:\n{exc}\n\n"
                    "Revisa la configuración MySQL en el panel de Administrador.",
                )

        orig_folder = cap["original_folder_path"]
        parent_dir = cap["parent_dir"]
        new_folder = os.path.join(parent_dir, cap["proposed_folder_name"])
        folder_uuid = cap.get("folder_uuid") or str(uuid.uuid4())

        if not os.path.isdir(orig_folder):
            if mysql_conn:
                mysql_conn.close()
            return False, f"El directorio original no existe o no está accesible:\n{orig_folder}"

        if os.path.normcase(orig_folder) != os.path.normcase(new_folder) and os.path.exists(new_folder):
            if mysql_conn:
                mysql_conn.close()
            return False, f"Ya existe una carpeta con el nombre destino:\n{new_folder}"

        files = self.get_files_for_capture(capture_id)
        target_files = [f for f in files if f["is_target_zero"] == 1]

        # 1. Validar existencia y calcular Hash SHA-256 + Páginas antes de mover nada
        file_metrics: Dict[int, Tuple[str, int, str, str, str]] = {}
        total_targets = len(target_files)

        for idx, f in enumerate(target_files, start=1):
            src_file = os.path.join(orig_folder, f["original_filename"])
            dst_file_in_orig = os.path.join(orig_folder, f["proposed_filename"])
            final_dst_file = os.path.join(new_folder, f["proposed_filename"])
            f_uuid = f.get("file_uuid") or str(uuid.uuid4())

            if not os.path.isfile(src_file):
                if mysql_conn:
                    mysql_conn.close()
                return False, f"Archivo origen no encontrado:\n{src_file}"
            if (
                os.path.normcase(src_file) != os.path.normcase(dst_file_in_orig)
                and os.path.exists(dst_file_in_orig)
            ):
                if mysql_conn:
                    mysql_conn.close()
                return False, f"El archivo destino ya existe:\n{dst_file_in_orig}"

            if progress_callback:
                progress_callback(idx, total_targets, f"Calculando Hash y páginas: {f['original_filename']}")

            sha256_val, pages_cnt = compute_pdf_hash_and_pages(src_file)
            file_metrics[f["id"]] = (sha256_val, pages_cnt, src_file, final_dst_file, f_uuid)

        # 2. Ejecutar renombrado físico con rollback automático de emergencia ante cualquier fallo
        renamed_pairs: List[Tuple[str, str, int]] = []
        folder_renamed = False
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            for f in target_files:
                src_file = os.path.join(orig_folder, f["original_filename"])
                dst_file = os.path.join(orig_folder, f["proposed_filename"])
                if src_file != dst_file:
                    os.rename(src_file, dst_file)
                renamed_pairs.append((src_file, dst_file, f["id"]))

            if orig_folder != new_folder:
                os.rename(orig_folder, new_folder)
                folder_renamed = True

            # 3. Registrar movimientos físicos en MySQL
            if mysql_conn is not None:
                with mysql_conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO `directorios_aplicados` (
                            `folder_uuid`, `nombre_carpeta_original`, `ruta_carpeta_original`,
                            `nombre_carpeta_nuevo`, `ruta_carpeta_nueva`,
                            `delegacion`, `seccion`, `libro`, `tomo`, `volumen`, `fraccionamiento`, `anio`, `sufijo`,
                            `total_pdfs_renombrados`, `total_pdfs_ignorados`, `estado`, `fecha_aplicacion`, `notas`
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'APLICADO', %s, %s)
                        ON DUPLICATE KEY UPDATE
                            `nombre_carpeta_nuevo` = VALUES(`nombre_carpeta_nuevo`),
                            `ruta_carpeta_nueva` = VALUES(`ruta_carpeta_nueva`),
                            `estado` = 'APLICADO',
                            `fecha_aplicacion` = VALUES(`fecha_aplicacion`),
                            `fecha_rollback` = NULL
                        """,
                        (
                            folder_uuid,
                            cap["original_folder_name"],
                            orig_folder,
                            cap["proposed_folder_name"],
                            new_folder,
                            cap["delegacion"],
                            cap["seccion"],
                            cap["libro"],
                            cap["tomo"],
                            cap["volumen"],
                            cap["fraccionamiento"],
                            cap["anio"],
                            cap["suffix"],
                            len(target_files),
                            cap["total_pdfs_ignored"],
                            now,
                            cap.get("notes", ""),
                        ),
                    )

                    mysql_file_rows = []
                    for f in target_files:
                        sha256_val, pages_cnt, orig_full_p, final_new_p, f_uuid = file_metrics[f["id"]]
                        mysql_file_rows.append(
                            (
                                f_uuid,
                                folder_uuid,
                                f["original_filename"],
                                orig_full_p,
                                f["proposed_filename"],
                                final_new_p,
                                now,
                                pages_cnt,
                                sha256_val,
                            )
                        )

                    if mysql_file_rows:
                        cur.executemany(
                            """
                            INSERT INTO `cambios_fisicos_archivos` (
                                `uuid`, `folder_uuid`, `nombre_original`, `ruta_original`,
                                `nombre_nuevo`, `ruta_nueva`, `fecha`, `paginas`, `hash_sha256`, `estado`
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'APLICADO')
                            ON DUPLICATE KEY UPDATE
                                `nombre_nuevo` = VALUES(`nombre_nuevo`),
                                `ruta_nueva` = VALUES(`ruta_nueva`),
                                `fecha` = VALUES(`fecha`),
                                `paginas` = VALUES(`paginas`),
                                `hash_sha256` = VALUES(`hash_sha256`),
                                `estado` = 'APLICADO',
                                `fecha_rollback` = NULL
                            """,
                            mysql_file_rows,
                        )
                mysql_conn.commit()

        except Exception as exc:
            # Revertir carpeta y archivos si algo falló (incluyendo fallo de escritura en MySQL)
            if folder_renamed and os.path.exists(new_folder) and not os.path.exists(orig_folder):
                try:
                    os.rename(new_folder, orig_folder)
                except Exception:
                    pass
            for src_f, dst_f, _ in reversed(renamed_pairs):
                try:
                    if os.path.exists(dst_f) and not os.path.exists(src_f):
                        os.rename(dst_f, src_f)
                except Exception:
                    pass
            if mysql_conn:
                mysql_conn.close()
            err_msg = f"Error al aplicar cambios (se revirtieron los cambios físicos): {exc}"
            self._record_error(capture_id, err_msg)
            return False, err_msg
        finally:
            if mysql_conn:
                try:
                    mysql_conn.close()
                except Exception:
                    pass

        # 4. Actualizar base de datos local SQLite con los hashes, páginas y fechas
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE folder_captures
                SET status = 'APLICADO', applied_at = ?, updated_at = ?, last_error = ''
                WHERE id = ?
                """,
                (now, now, capture_id),
            )
            for f in target_files:
                sha256_val, pages_cnt, orig_full_p, final_new_p, f_uuid = file_metrics[f["id"]]
                conn.execute(
                    """
                    UPDATE file_captures
                    SET file_uuid = ?,
                        original_full_path = ?,
                        proposed_full_path = ?,
                        pages = ?,
                        file_hash = ?,
                        applied_at = ?,
                        status = 'APLICADO'
                    WHERE id = ?
                    """,
                    (
                        f_uuid,
                        orig_full_p,
                        final_new_p,
                        pages_cnt,
                        sha256_val,
                        now,
                        f["id"],
                    ),
                )
            conn.execute(
                "INSERT INTO audit_logs (folder_capture_id, action, details, created_at) VALUES (?, ?, ?, ?)",
                (
                    capture_id,
                    "APLICAR_CAMBIOS",
                    f"[{folder_uuid}] Renombrados {len(target_files)} PDFs y carpeta '{cap['original_folder_name']}' -> '{cap['proposed_folder_name']}'",
                    now,
                ),
            )
            conn.commit()

        self.export_backup_json()
        return (
            True,
            f"Se renombraron exitosamente {len(target_files)} PDFs y el directorio a:\n"
            f"{cap['proposed_folder_name']}\n\n"
            f"Folder UUID: {folder_uuid}\n"
            "Todos los hashes SHA-256, conteos de páginas y rutas quedaron registrados.",
        )

    def rollback_capture_changes(
        self, capture_id: int, require_mysql: bool = False
    ) -> Tuple[bool, str]:
        """
        Revierte (Rollback) un directorio y todos sus PDFs a sus nombres originales exactos
        y actualiza el estado a REVERTIDO_ROLLBACK tanto localmente como en MySQL.
        """
        cap = self.get_capture_by_id(capture_id)
        if not cap:
            return False, "No se encontró la captura solicitada."

        if cap["status"] != "APLICADO":
            return False, "Solo se puede hacer Rollback de capturas que tengan estado 'APLICADO'."

        orig_folder = cap["original_folder_path"]
        parent_dir = cap["parent_dir"]
        applied_folder = os.path.join(parent_dir, cap["proposed_folder_name"])
        folder_uuid = cap.get("folder_uuid", "")

        if not os.path.isdir(applied_folder):
            return False, f"No se encontró el directorio aplicado para revertir:\n{applied_folder}"

        if os.path.normcase(orig_folder) != os.path.normcase(applied_folder) and os.path.exists(orig_folder):
            return False, f"Ya existe una carpeta con el nombre original:\n{orig_folder}"

        files = self.get_files_for_capture(capture_id)
        target_files = [f for f in files if f["is_target_zero"] == 1]

        for f in target_files:
            cur_file = os.path.join(applied_folder, f["proposed_filename"])
            orig_file = os.path.join(applied_folder, f["original_filename"])
            if not os.path.isfile(cur_file):
                return False, f"No se encontró el archivo renombrado para revertir:\n{cur_file}"
            if os.path.normcase(cur_file) != os.path.normcase(orig_file) and os.path.exists(orig_file):
                return False, f"Conflicto al revertir, ya existe:\n{orig_file}"

        reverted_pairs: List[Tuple[str, str]] = []
        try:
            for f in target_files:
                cur_file = os.path.join(applied_folder, f["proposed_filename"])
                orig_file = os.path.join(applied_folder, f["original_filename"])
                if cur_file != orig_file:
                    os.rename(cur_file, orig_file)
                reverted_pairs.append((cur_file, orig_file))

            if applied_folder != orig_folder:
                os.rename(applied_folder, orig_folder)

        except Exception as exc:
            for cur_f, orig_f in reversed(reverted_pairs):
                try:
                    if os.path.exists(orig_f) and not os.path.exists(cur_f):
                        os.rename(orig_f, cur_f)
                except Exception:
                    pass
            err_msg = f"Error durante Rollback (se conservaron los nombres previos): {exc}"
            self._record_error(capture_id, err_msg)
            return False, err_msg

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Actualizar también en MySQL si está habilitado
        mysql_cfg = self.mysql_manager.load()
        if mysql_cfg.get("enabled", True):
            try:
                mysql_conn = self.mysql_manager.get_connection(create_db_if_missing=False)
                with mysql_conn.cursor() as cur:
                    cur.execute(
                        "UPDATE `directorios_aplicados` SET `estado` = 'REVERTIDO_ROLLBACK', `fecha_rollback` = %s WHERE `folder_uuid` = %s",
                        (now, folder_uuid),
                    )
                    cur.execute(
                        "UPDATE `cambios_fisicos_archivos` SET `estado` = 'REVERTIDO_ROLLBACK', `fecha_rollback` = %s WHERE `folder_uuid` = %s",
                        (now, folder_uuid),
                    )
                mysql_conn.commit()
                mysql_conn.close()
            except Exception as exc:
                if require_mysql:
                    return False, f"Archivos revertidos físicamente, pero hubo aviso MySQL: {exc}"

        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE folder_captures
                SET status = 'REVERTIDO_ROLLBACK', rolled_back_at = ?, updated_at = ?, last_error = ''
                WHERE id = ?
                """,
                (now, now, capture_id),
            )
            conn.execute(
                "UPDATE file_captures SET status = 'REVERTIDO' WHERE folder_capture_id = ? AND is_target_zero = 1",
                (capture_id,),
            )
            conn.execute(
                "INSERT INTO audit_logs (folder_capture_id, action, details, created_at) VALUES (?, ?, ?, ?)",
                (
                    capture_id,
                    "ROLLBACK",
                    f"[{folder_uuid}] Revertidos {len(target_files)} PDFs y carpeta '{cap['proposed_folder_name']}' -> '{cap['original_folder_name']}'",
                    now,
                ),
            )
            conn.commit()

        self.export_backup_json()
        return (
            True,
            f"Rollback completado con éxito. La carpeta y sus {len(target_files)} PDFs volvieron a su estado original:\n"
            f"{cap['original_folder_name']}",
        )

    def _record_error(self, capture_id: int, error_msg: str) -> None:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE folder_captures SET last_error = ?, updated_at = ? WHERE id = ?",
                (error_msg, now, capture_id),
            )
            conn.execute(
                "INSERT INTO audit_logs (folder_capture_id, action, details, created_at) VALUES (?, 'ERROR', ?, ?)",
                (capture_id, error_msg, now),
            )
            conn.commit()

    def export_backup_json(self, custom_path: Optional[str] = None) -> str:
        """Exporta toda la base de datos local a un archivo JSON legible (incluyendo UUIDs)."""
        out_path = custom_path or os.path.join(self.data_dir, "respaldo_capturas.json")
        captures = self.get_all_captures()
        for cap in captures:
            cap["files"] = self.get_files_for_capture(cap["id"])

        payload = {
            "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_folders": len(captures),
            "captures": captures,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return out_path

    def import_backup_json(self, json_path: str) -> Tuple[int, int, int]:
        """
        Importa capturas desde un archivo JSON generado por export_backup_json,
        conservando intactos los `folder_uuid` y `file_uuid` para vincularlos con MySQL.
        Retorna (insertadas, actualizadas, omitidas_por_aplicadas).
        """
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict) and "captures" in data:
            captures_list = data["captures"]
        elif isinstance(data, list):
            captures_list = data
        else:
            raise ValueError(
                "El archivo JSON no tiene el formato compatible de exportación ('captures')."
            )

        inserted = 0
        updated = 0
        skipped_applied = 0
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._get_conn() as conn:
            for cap in captures_list:
                if not isinstance(cap, dict) or "original_folder_path" not in cap:
                    continue

                norm_path = os.path.normpath(str(cap["original_folder_path"]))
                folder_uuid = str(cap.get("folder_uuid") or uuid.uuid4())
                parent_dir = str(cap.get("parent_dir") or os.path.dirname(norm_path))
                orig_name = str(
                    cap.get("original_folder_name") or os.path.basename(norm_path)
                )
                prop_name = str(cap.get("proposed_folder_name") or orig_name)
                prop_folder_full = os.path.join(parent_dir, prop_name)

                delegacion = str(cap.get("delegacion", "01"))
                seccion = str(cap.get("seccion", "00"))
                libro = str(cap.get("libro", "00"))
                tomo = str(cap.get("tomo", "00"))
                volumen = str(cap.get("volumen", "00"))
                fraccionamiento = str(cap.get("fraccionamiento", "00"))
                anio = str(cap.get("anio", "0000"))
                suffix = str(cap.get("suffix", "REVISAR"))
                status = str(cap.get("status", "PENDIENTE_REVISION"))
                notes = str(cap.get("notes", ""))
                created_at = str(cap.get("created_at") or now)
                updated_at = str(cap.get("updated_at") or now)
                applied_at = str(cap.get("applied_at") or "")
                rolled_back_at = str(cap.get("rolled_back_at") or "")

                files_data = cap.get("files", [])
                total_rename = int(
                    cap.get(
                        "total_pdfs_rename",
                        sum(1 for x in files_data if x.get("is_target_zero", 1) == 1),
                    )
                )
                total_ignored = int(
                    cap.get(
                        "total_pdfs_ignored",
                        sum(1 for x in files_data if x.get("is_target_zero", 1) == 0),
                    )
                )

                existing = conn.execute(
                    "SELECT id, status FROM folder_captures WHERE original_folder_path = ? OR folder_uuid = ?",
                    (norm_path, folder_uuid),
                ).fetchone()

                if existing:
                    if existing["status"] == "APLICADO":
                        skipped_applied += 1
                        continue

                    folder_id = int(existing["id"])
                    conn.execute(
                        """
                        UPDATE folder_captures SET
                            folder_uuid = ?,
                            original_folder_path = ?,
                            parent_dir = ?,
                            original_folder_name = ?,
                            proposed_folder_name = ?,
                            delegacion = ?,
                            seccion = ?,
                            libro = ?,
                            tomo = ?,
                            volumen = ?,
                            fraccionamiento = ?,
                            anio = ?,
                            suffix = ?,
                            total_pdfs_rename = ?,
                            total_pdfs_ignored = ?,
                            status = ?,
                            notes = ?,
                            updated_at = ?,
                            applied_at = ?,
                            rolled_back_at = ?
                        WHERE id = ?
                        """,
                        (
                            folder_uuid,
                            norm_path,
                            parent_dir,
                            orig_name,
                            prop_name,
                            delegacion,
                            seccion,
                            libro,
                            tomo,
                            volumen,
                            fraccionamiento,
                            anio,
                            suffix,
                            total_rename,
                            total_ignored,
                            status,
                            notes,
                            updated_at,
                            applied_at,
                            rolled_back_at,
                            folder_id,
                        ),
                    )
                    conn.execute(
                        "DELETE FROM file_captures WHERE folder_capture_id = ?",
                        (folder_id,),
                    )
                    updated += 1
                else:
                    cur = conn.execute(
                        """
                        INSERT INTO folder_captures (
                            folder_uuid, original_folder_path, parent_dir, original_folder_name,
                            proposed_folder_name, delegacion, seccion, libro, tomo,
                            volumen, fraccionamiento, anio, suffix,
                            total_pdfs_rename, total_pdfs_ignored, status, notes,
                            created_at, updated_at, applied_at, rolled_back_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            folder_uuid,
                            norm_path,
                            parent_dir,
                            orig_name,
                            prop_name,
                            delegacion,
                            seccion,
                            libro,
                            tomo,
                            volumen,
                            fraccionamiento,
                            anio,
                            suffix,
                            total_rename,
                            total_ignored,
                            status,
                            notes,
                            created_at,
                            updated_at,
                            applied_at,
                            rolled_back_at,
                        ),
                    )
                    folder_id = int(cur.lastrowid)
                    inserted += 1

                file_rows = []
                for f_item in files_data:
                    orig_fn = str(f_item.get("original_filename", ""))
                    if not orig_fn:
                        continue
                    f_uuid = str(f_item.get("file_uuid") or uuid.uuid4())
                    prop_fn = str(f_item.get("proposed_filename", orig_fn))
                    orig_full = str(
                        f_item.get("original_full_path") or os.path.join(norm_path, orig_fn)
                    )
                    prop_full = str(
                        f_item.get("proposed_full_path")
                        or os.path.join(prop_folder_full, prop_fn)
                    )
                    is_zero = int(f_item.get("is_target_zero", 1))
                    tail = str(f_item.get("inscripcion_bis_tail", ""))
                    pages_cnt = int(f_item.get("pages", 0))
                    f_hash = str(f_item.get("file_hash", ""))
                    f_applied = str(f_item.get("applied_at", ""))
                    f_status = str(
                        f_item.get(
                            "status", "PENDIENTE" if is_zero == 1 else "IGNORADO"
                        )
                    )
                    file_rows.append(
                        (
                            f_uuid,
                            folder_id,
                            folder_uuid,
                            orig_fn,
                            orig_full,
                            prop_fn,
                            prop_full,
                            is_zero,
                            tail,
                            pages_cnt,
                            f_hash,
                            f_applied,
                            f_status,
                        )
                    )

                if file_rows:
                    conn.executemany(
                        """
                        INSERT INTO file_captures (
                            file_uuid, folder_capture_id, folder_uuid,
                            original_filename, original_full_path,
                            proposed_filename, proposed_full_path,
                            is_target_zero, inscripcion_bis_tail,
                            pages, file_hash, applied_at, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        file_rows,
                    )

            conn.execute(
                "INSERT INTO audit_logs (folder_capture_id, action, details, created_at) VALUES (NULL, 'IMPORTAR_JSON', ?, ?)",
                (
                    f"Importado {os.path.basename(json_path)}: {inserted} nuevas, {updated} actualizadas, {skipped_applied} omitidas",
                    now,
                ),
            )
            conn.commit()

        self.export_backup_json()
        return inserted, updated, skipped_applied

    def export_csv_report(self, out_path: str) -> str:
        """Exporta un reporte CSV detallado para revisión en Excel (incluye UUIDs)."""
        captures = self.get_all_captures()
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "ID_Captura",
                    "Folder_UUID",
                    "Estado",
                    "Carpeta_Original",
                    "Carpeta_Propuesta",
                    "Delegacion",
                    "Seccion",
                    "Libro",
                    "Tomo",
                    "Volumen",
                    "Fraccionamiento",
                    "Anio",
                    "PDFs_Renombrar",
                    "PDFs_Ignorados",
                    "Ruta_Original",
                    "Fecha_Captura",
                    "Notas",
                ]
            )
            for c in captures:
                writer.writerow(
                    [
                        c["id"],
                        c.get("folder_uuid", ""),
                        c["status"],
                        c["original_folder_name"],
                        c["proposed_folder_name"],
                        c["delegacion"],
                        c["seccion"],
                        c["libro"],
                        c["tomo"],
                        c["volumen"],
                        c["fraccionamiento"],
                        c["anio"],
                        c["total_pdfs_rename"],
                        c["total_pdfs_ignored"],
                        c["original_folder_path"],
                        c["updated_at"],
                        c["notes"],
                    ]
                )
        return out_path
