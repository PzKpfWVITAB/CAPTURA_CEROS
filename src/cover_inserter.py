"""
Motor para insertar páginas de un PDF elegido como Carátula al inicio
de los archivos PDF seleccionados de un directorio (Exclusivo Modo Administrador).
Soporta ejecución asíncrona con cancelación segura y manejo detallado de errores.
"""

import os
import tempfile
from typing import Callable, List, Optional, Tuple

import fitz  # PyMuPDF


def get_pdf_page_count(pdf_path: str) -> int:
    """Retorna el total de páginas de un archivo PDF leyéndolo en memoria."""
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"El archivo no existe:\n{pdf_path}")
    with open(pdf_path, "rb") as f:
        data = f.read()
    if not data:
        raise ValueError(f"El archivo está vacío (0 bytes):\n{pdf_path}")
    with fitz.open(stream=data, filetype="pdf") as doc:
        return len(doc)


def resolve_page_indices(
    mode: str,
    total_cover_pages: int,
    single_page_1based: int = 1,
    range_from_1based: int = 1,
    range_to_1based: int = 1,
) -> Tuple[int, int]:
    """
    Calcula los índices 0-based (from_page, to_page) inclusivos para PyMuPDF `insert_pdf`.
    Modos soportados:
    - 'ALL': Todas las páginas de la carátula (por defecto)
    - 'SINGLE': Una sola página en particular (1-based)
    - 'RANGE': Un rango de páginas (desde..hasta, 1-based)
    """
    if total_cover_pages <= 0:
        raise ValueError("El archivo PDF de carátula no contiene páginas válidas.")

    mode_up = mode.upper().strip()
    if mode_up == "ALL":
        return 0, total_cover_pages - 1

    if mode_up == "SINGLE":
        if single_page_1based < 1 or single_page_1based > total_cover_pages:
            raise ValueError(
                f"La página seleccionada ({single_page_1based}) está fuera del total de páginas de la carátula (1 a {total_cover_pages})."
            )
        idx = single_page_1based - 1
        return idx, idx

    if mode_up == "RANGE":
        if range_from_1based < 1 or range_to_1based > total_cover_pages:
            raise ValueError(
                f"El rango ({range_from_1based} a {range_to_1based}) está fuera del total de páginas de la carátula (1 a {total_cover_pages})."
            )
        if range_from_1based > range_to_1based:
            raise ValueError(
                f"La página inicial ({range_from_1based}) no puede ser mayor que la página final ({range_to_1based})."
            )
        return range_from_1based - 1, range_to_1based - 1

    return 0, total_cover_pages - 1


def _describe_exception(exc: Exception) -> str:
    """Traduce errores comunes del sistema/PyMuPDF a mensajes claros para el usuario."""
    if isinstance(exc, PermissionError):
        return f"Archivo bloqueado o en uso por otro programa / sin permisos de escritura ({exc})"
    if isinstance(exc, FileNotFoundError):
        return f"Archivo o ruta de red no disponible ({exc})"
    msg = str(exc)
    if "encrypted" in msg.lower() or "password" in msg.lower():
        return f"El PDF está protegido con contraseña o cifrado ({msg})"
    if "cannot open" in msg.lower() or "damaged" in msg.lower() or "format" in msg.lower():
        return f"Archivo PDF dañado o estructura inválida ({msg})"
    return f"{type(exc).__name__}: {msg}"


def prepend_cover_pages_to_pdfs(
    cover_pdf_path: str,
    target_pdf_paths: List[str],
    mode: str = "ALL",
    single_page_1based: int = 1,
    range_from_1based: int = 1,
    range_to_1based: int = 1,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Tuple[int, List[str], int]:
    """
    Inserta al inicio (start_at=0) de cada PDF en `target_pdf_paths` las páginas indicadas
    del archivo `cover_pdf_path`. Excluye automáticamente el archivo carátula si estuviera en la lista.
    Realiza escritura atómica segura para no corromper archivos en red y captura errores individualmente
    para que un archivo dañado o bloqueado no detenga el resto del lote.
    Retorna: (cantidad_exitosos, lista_errores, paginas_insertadas_por_pdf)
    """
    if not os.path.isfile(cover_pdf_path):
        raise FileNotFoundError(f"No se encontró el PDF de carátula:\n{cover_pdf_path}")

    try:
        with open(cover_pdf_path, "rb") as f:
            cover_bytes = f.read()
    except Exception as exc:
        raise RuntimeError(
            f"No se pudo leer el archivo de carátula:\n{_describe_exception(exc)}"
        ) from exc

    if not cover_bytes:
        raise ValueError("El archivo PDF de carátula está vacío (0 bytes).")

    try:
        cover_doc = fitz.open(stream=cover_bytes, filetype="pdf")
    except Exception as exc:
        raise RuntimeError(
            f"El PDF de carátula está dañado o no es un PDF válido:\n{_describe_exception(exc)}"
        ) from exc

    try:
        if cover_doc.needs_pass:
            raise ValueError("El PDF de carátula está protegido con contraseña.")

        total_cover_pages = len(cover_doc)
        from_idx, to_idx = resolve_page_indices(
            mode=mode,
            total_cover_pages=total_cover_pages,
            single_page_1based=single_page_1based,
            range_from_1based=range_from_1based,
            range_to_1based=range_to_1based,
        )
        pages_inserted_count = (to_idx - from_idx) + 1

        norm_cover = os.path.normcase(os.path.normpath(cover_pdf_path))
        filtered_targets = [
            p
            for p in target_pdf_paths
            if os.path.normcase(os.path.normpath(p)) != norm_cover
        ]

        success_count = 0
        errors: List[str] = []
        total_files = len(filtered_targets)

        for idx, target_path in enumerate(filtered_targets, start=1):
            if cancel_check and cancel_check():
                errors.append(
                    f"[PROCESO CANCELADO POR EL USUARIO en el archivo {idx} de {total_files}]"
                )
                break

            fname = os.path.basename(target_path)
            if progress_callback:
                progress_callback(idx, total_files, f"Procesando: {fname}")

            tmp_path: Optional[str] = None
            try:
                if not os.path.isfile(target_path):
                    raise FileNotFoundError("El archivo no existe en la ruta indicada.")

                with open(target_path, "rb") as tf:
                    target_bytes = tf.read()

                if not target_bytes:
                    raise ValueError("Archivo vacío (0 bytes).")

                target_doc = fitz.open(stream=target_bytes, filetype="pdf")
                try:
                    if target_doc.needs_pass:
                        raise ValueError("Archivo protegido con contraseña.")
                    if len(target_doc) == 0:
                        raise ValueError("El PDF no contiene páginas.")

                    # Insertar al inicio (start_at=0) las páginas seleccionadas de la carátula
                    target_doc.insert_pdf(
                        cover_doc,
                        from_page=from_idx,
                        to_page=to_idx,
                        start_at=0,
                    )
                    out_bytes = target_doc.tobytes(garbage=2, deflate=True)
                finally:
                    target_doc.close()

                # Escritura atómica segura mediante archivo temporal en el mismo directorio
                parent_dir = os.path.dirname(target_path)
                tmp_fd, tmp_path = tempfile.mkstemp(
                    suffix=".tmp_pdf", dir=parent_dir
                )
                with os.fdopen(tmp_fd, "wb") as out_f:
                    out_f.write(out_bytes)
                    out_f.flush()

                try:
                    os.replace(tmp_path, target_path)
                    tmp_path = None
                except Exception:
                    # Si el servidor SMB no permite os.replace directo, limpiar temporal e intentar escritura directa
                    if tmp_path and os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass
                        tmp_path = None
                    with open(target_path, "wb") as direct_f:
                        direct_f.write(out_bytes)
                        direct_f.flush()

                success_count += 1
            except Exception as exc:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                errors.append(f"• {fname} -> {_describe_exception(exc)}")

        return success_count, errors, pages_inserted_count
    finally:
        cover_doc.close()
