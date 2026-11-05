"""
Almacenamiento local (SQLite + exportación JSON/CSV) y motor transaccional
con soporte de Revisión, Aplicación de Cambios y Rollback completo.
"""

import contextlib
import csv
import datetime
import json
import os
import sqlite3
import sys
from typing import Any, Dict, Iterator, List, Optional, Tuple


def get_app_base_dir() -> str:
    """Retorna el directorio donde reside el .exe o el script principal."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LocalCaptureStore:
    """
    Gestiona las capturas locales sin tocar la red hasta que el usuario
    apruebe y ejecute los cambios, permitiendo Rollback completo.
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
                    folder_capture_id INTEGER NOT NULL,
                    original_filename TEXT NOT NULL,
                    proposed_filename TEXT NOT NULL,
                    is_target_zero INTEGER NOT NULL DEFAULT 1,
                    inscripcion_bis_tail TEXT DEFAULT '',
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
            conn.commit()

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
        No modifica ningún archivo físico en disco ni en red.
        """
        norm_path = os.path.normpath(original_folder_path)
        parent_dir = os.path.dirname(norm_path)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id, status FROM folder_captures WHERE original_folder_path = ?",
                (norm_path,),
            ).fetchone()

            if existing and existing["status"] == "APLICADO":
                raise RuntimeError(
                    "Esta carpeta ya tiene cambios APLICADOS físicamente. "
                    "Si deseas modificar su captura, primero ejecuta 'Rollback' sobre ella."
                )

            if existing:
                folder_id = existing["id"]
                conn.execute(
                    """
                    UPDATE folder_captures SET
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
                cur = conn.execute(
                    """
                    INSERT INTO folder_captures (
                        original_folder_path, parent_dir, original_folder_name,
                        proposed_folder_name, delegacion, seccion, libro, tomo,
                        volumen, fraccionamiento, anio, suffix,
                        total_pdfs_rename, total_pdfs_ignored, status, notes,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDIENTE_REVISION', ?, ?, ?)
                    """,
                    (
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
                file_rows.append(
                    (
                        folder_id,
                        p.original_name,
                        p.proposed_name,
                        1,
                        p.inscripcion_bis_tail,
                        "PENDIENTE",
                    )
                )
            for p in pdfs_ignored:
                file_rows.append(
                    (
                        folder_id,
                        p.original_name,
                        p.original_name,
                        0,
                        "",
                        "IGNORADO",
                    )
                )

            conn.executemany(
                """
                INSERT INTO file_captures (
                    folder_capture_id, original_filename, proposed_filename,
                    is_target_zero, inscripcion_bis_tail, status
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                file_rows,
            )

            conn.execute(
                "INSERT INTO audit_logs (folder_capture_id, action, details, created_at) VALUES (?, ?, ?, ?)",
                (
                    folder_id,
                    "CAPTURA_LOCAL",
                    f"{original_folder_name} -> {proposed_folder_name} ({len(pdfs_to_rename)} PDFs a renombrar, {len(pdfs_ignored)} ignorados)",
                    now,
                ),
            )
            conn.commit()

        # Guardar respaldo instantáneo en JSON para portabilidad total
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
        """Permite cambiar entre PENDIENTE_REVISION y APROBADO."""
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

    def apply_capture_changes(self, capture_id: int) -> Tuple[bool, str]:
        """
        Aplica físicamente el renombrado de PDFs en cero y luego de la carpeta.
        Si cualquier paso intermedio falla, revierte automáticamente lo que haya tocado
        para dejar el directorio en estado íntegro.
        """
        cap = self.get_capture_by_id(capture_id)
        if not cap:
            return False, "No se encontró la captura solicitada."

        if cap["status"] == "APLICADO":
            return False, "Esta captura ya fue aplicada anteriormente."

        orig_folder = cap["original_folder_path"]
        parent_dir = cap["parent_dir"]
        new_folder = os.path.join(parent_dir, cap["proposed_folder_name"])

        if not os.path.isdir(orig_folder):
            return False, f"El directorio original no existe o no está accesible:\n{orig_folder}"

        if os.path.normcase(orig_folder) != os.path.normcase(new_folder) and os.path.exists(new_folder):
            return False, f"Ya existe una carpeta con el nombre destino:\n{new_folder}"

        files = self.get_files_for_capture(capture_id)
        target_files = [f for f in files if f["is_target_zero"] == 1]

        # 1. Validar que todos los archivos origen existan y no haya colisiones
        for f in target_files:
            src_file = os.path.join(orig_folder, f["original_filename"])
            dst_file = os.path.join(orig_folder, f["proposed_filename"])
            if not os.path.isfile(src_file):
                return False, f"Archivo origen no encontrado:\n{src_file}"
            if os.path.normcase(src_file) != os.path.normcase(dst_file) and os.path.exists(dst_file):
                return False, f"El archivo destino ya existe:\n{dst_file}"

        # 2. Renombrar PDFs con registro transaccional en memoria por si hay fallo de red
        renamed_pairs: List[Tuple[str, str, int]] = []
        try:
            for f in target_files:
                src_file = os.path.join(orig_folder, f["original_filename"])
                dst_file = os.path.join(orig_folder, f["proposed_filename"])
                if src_file != dst_file:
                    os.rename(src_file, dst_file)
                renamed_pairs.append((src_file, dst_file, f["id"]))

            # 3. Renombrar carpeta
            if orig_folder != new_folder:
                os.rename(orig_folder, new_folder)

        except Exception as exc:
            # Rollback automático de emergencia si falló a mitad
            for src_f, dst_f, _ in reversed(renamed_pairs):
                try:
                    if os.path.exists(dst_f) and not os.path.exists(src_f):
                        os.rename(dst_f, src_f)
                except Exception:
                    pass
            err_msg = f"Error al aplicar cambios (se revirtieron los pasos parciales): {exc}"
            self._record_error(capture_id, err_msg)
            return False, err_msg

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE folder_captures
                SET status = 'APLICADO', applied_at = ?, updated_at = ?, last_error = ''
                WHERE id = ?
                """,
                (now, now, capture_id),
            )
            conn.execute(
                "UPDATE file_captures SET status = 'APLICADO' WHERE folder_capture_id = ? AND is_target_zero = 1",
                (capture_id,),
            )
            conn.execute(
                "INSERT INTO audit_logs (folder_capture_id, action, details, created_at) VALUES (?, ?, ?, ?)",
                (
                    capture_id,
                    "APLICAR_CAMBIOS",
                    f"Renombrados {len(target_files)} PDFs y carpeta '{cap['original_folder_name']}' -> '{cap['proposed_folder_name']}'",
                    now,
                ),
            )
            conn.commit()

        self.export_backup_json()
        return True, f"Se renombraron exitosamente {len(target_files)} PDFs y el directorio a:\n{cap['proposed_folder_name']}"

    def rollback_capture_changes(self, capture_id: int) -> Tuple[bool, str]:
        """
        Revierte (Rollback) un directorio y todos sus PDFs a sus nombres originales exactos.
        """
        cap = self.get_capture_by_id(capture_id)
        if not cap:
            return False, "No se encontró la captura solicitada."

        if cap["status"] != "APLICADO":
            return False, "Solo se puede hacer Rollback de capturas que tengan estado 'APLICADO'."

        orig_folder = cap["original_folder_path"]
        parent_dir = cap["parent_dir"]
        applied_folder = os.path.join(parent_dir, cap["proposed_folder_name"])

        if not os.path.isdir(applied_folder):
            return False, f"No se encontró el directorio aplicado para revertir:\n{applied_folder}"

        if os.path.normcase(orig_folder) != os.path.normcase(applied_folder) and os.path.exists(orig_folder):
            return False, f"Ya existe una carpeta con el nombre original:\n{orig_folder}"

        files = self.get_files_for_capture(capture_id)
        target_files = [f for f in files if f["is_target_zero"] == 1]

        # 1. Verificar archivos dentro de la carpeta aplicada
        for f in target_files:
            cur_file = os.path.join(applied_folder, f["proposed_filename"])
            orig_file = os.path.join(applied_folder, f["original_filename"])
            if not os.path.isfile(cur_file):
                return False, f"No se encontró el archivo renombrado para revertir:\n{cur_file}"
            if os.path.normcase(cur_file) != os.path.normcase(orig_file) and os.path.exists(orig_file):
                return False, f"Conflicto al revertir, ya existe:\n{orig_file}"

        reverted_pairs: List[Tuple[str, str]] = []
        try:
            # 2. Revertir primero los nombres de los PDFs dentro de la carpeta actual
            for f in target_files:
                cur_file = os.path.join(applied_folder, f["proposed_filename"])
                orig_file = os.path.join(applied_folder, f["original_filename"])
                if cur_file != orig_file:
                    os.rename(cur_file, orig_file)
                reverted_pairs.append((cur_file, orig_file))

            # 3. Revertir el nombre de la carpeta al original
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
                    f"Revertidos {len(target_files)} PDFs y carpeta '{cap['proposed_folder_name']}' -> '{cap['original_folder_name']}'",
                    now,
                ),
            )
            conn.commit()

        self.export_backup_json()
        return True, f"Rollback completado con éxito. La carpeta y sus {len(target_files)} PDFs volvieron a su estado original:\n{cap['original_folder_name']}"

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
        """Exporta toda la base de datos local a un archivo JSON legible."""
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

    def export_csv_report(self, out_path: str) -> str:
        """Exporta un reporte CSV detallado para revisión en Excel."""
        captures = self.get_all_captures()
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "ID_Captura",
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
