"""
Motor de análisis y generación de nombres propuestos para carpetas y archivos PDF
con campos en ceros (01_00_00_00_00_00_...).
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# Patrón para detectar archivos PDF cuyos campos Sección..Fraccionamiento están en ceros:
# Ejemplo: 01_00_00_00_00_00_0000_0001_00.pdf o 01_00_00_00_00_00_1996_0002_00_DUP1.pdf
# Grupos:
# 1: Delegación (2 dígitos, ej. 01)
# 2: Sección (00)
# 3: Libro (00)
# 4: Tomo (00)
# 5: Volumen (00)
# 6: Fraccionamiento (00)
# 7: Año en el PDF (4 dígitos, ej. 0000 o 1985)
# 8: Resto del nombre antes de .pdf (Inscripción + Bis + sufijos como _DUP1, ej. 0001_00 o 0001_00_DUP1)
ZERO_PDF_REGEX = re.compile(
    r"^(\d{2})_(00)_(00)_(00)_(00)_(00)_(\d{4})_(.+)\.pdf$",
    re.IGNORECASE,
)

# Patrón para PDFs con estructura de 7 campos estándar:
STANDARD_PDF_REGEX = re.compile(
    r"^(\d{2})_([^_]+)_([^_]+)_([^_]+)_([^_]+)_([^_]+)_(\d{4})_(.+)\.pdf$",
    re.IGNORECASE,
)

# Patrón para analizar carpetas tipo:
# 01_00_00_00_00_00_1985_REVISAR
# 01_00_00_00_00_00_1985_REVISAR_2
# 01_00_00_00_00_00_1996
# 01_00_00_00_00_00_0000_REVISAR
FOLDER_REGEX = re.compile(
    r"^(\d{2})_([^_]+)_([^_]+)_([^_]+)_([^_]+)_([^_]+)_(\d{4})(?:_(.*))?$",
    re.IGNORECASE,
)


@dataclass
class PdfProposal:
    """Representa el análisis y propuesta de renombrado de un archivo PDF individual."""
    original_name: str
    full_path: str
    is_target_zero: bool = False
    is_year_zero: bool = False
    is_selected_for_rename: bool = False
    detected_delegacion: str = "01"
    detected_seccion: str = "00"
    detected_libro: str = "00"
    detected_tomo: str = "00"
    detected_volumen: str = "00"
    detected_fraccionamiento: str = "00"
    detected_year: str = "0000"
    inscripcion_bis_tail: str = ""  # Ej: "0001_00" o "0001_00_DUP1"
    inscripcion: str = ""           # Ej: "0001"
    bis_and_extra: str = ""         # Ej: "00" o "00_DUP1"
    proposed_name: str = ""
    reason_ignored: str = ""


@dataclass
class FolderAnalysis:
    """Resultado de escanear un directorio con sus PDFs."""
    folder_path: str
    folder_name: str
    delegacion: str = "01"
    detected_year: str = "0000"
    year_is_zero: bool = True
    detected_suffix: str = "REVISAR"
    all_pdfs: List[PdfProposal] = field(default_factory=list)

    @property
    def pdfs_to_rename(self) -> List[PdfProposal]:
        return [p for p in self.all_pdfs if p.is_selected_for_rename]

    @property
    def pdfs_ignored(self) -> List[PdfProposal]:
        return [p for p in self.all_pdfs if not p.is_selected_for_rename]

    def select_all(self) -> None:
        for p in self.all_pdfs:
            p.is_selected_for_rename = True

    def select_only_zeros(self) -> None:
        for p in self.all_pdfs:
            p.is_selected_for_rename = bool(p.is_target_zero or p.is_year_zero)

    def deselect_all(self) -> None:
        for p in self.all_pdfs:
            p.is_selected_for_rename = False


def format_numeric_field(val: str, width: int = 2) -> str:
    """
    Formatea un campo numérico rellenando con ceros a la izquierda (por defecto 2 dígitos).
    Si es vacío, retorna '00'.
    """
    clean = val.strip()
    if not clean:
        return "0" * width
    if clean.isdigit():
        return clean.zfill(width)
    return clean.upper().replace(" ", "_")


def format_optional_alphanumeric_field(val: str, width: int = 2) -> str:
    """
    Para Tomo y Fraccionamiento: por defecto son números de 2 dígitos ('00', '01'),
    pero opcionalmente aceptan texto alfanumérico (ej. '01_AUXILIAR' o 'FRACCIONAMIENTO_PATRIA').
    """
    clean = val.strip()
    if not clean:
        return "0" * width
    if clean.isdigit():
        return clean.zfill(width)
    # Normalizar espacios por guiones bajos y pasar a mayúsculas
    normalized = re.sub(r"\s+", "_", clean.upper())
    return normalized


def parse_folder_name(folder_name: str) -> Tuple[str, str, str]:
    """
    Extrae (delegacion, año, sufijo) del nombre de la carpeta.
    Ejemplo: '01_00_00_00_00_00_1985_REVISAR_2' -> ('01', '1985', 'REVISAR_2')
    Ejemplo: '01_00_00_00_00_00_1996' -> ('01', '1996', 'REVISAR')
    """
    match = FOLDER_REGEX.match(folder_name.strip())
    if match:
        delegacion = match.group(1)
        year = match.group(7)
        suffix = match.group(8) if match.group(8) else "REVISAR"
        # Si el sufijo no contiene REVISAR, aseguramos que mantenga REVISAR según regla de negocio
        if "REVISAR" not in suffix.upper():
            suffix = f"REVISAR_{suffix}" if suffix else "REVISAR"
        return delegacion, year, suffix

    # Fallback: buscar un año de 4 dígitos (19xx o 20xx o 0000) y sufijo
    year_match = re.search(r"_(\d{4})(?:_(.+))?$", folder_name)
    if year_match:
        year = year_match.group(1)
        suffix = year_match.group(2) or "REVISAR"
        if "REVISAR" not in suffix.upper():
            suffix = f"REVISAR_{suffix}" if suffix else "REVISAR"
        return "01", year, suffix

    return "01", "0000", "REVISAR"


def analyze_pdf_filename(filename: str, full_path: str) -> PdfProposal:
    """
    Analiza la estructura del nombre de un archivo PDF.
    Detecta si sus campos o su año están en ceros (00_00_00_00_00 o 0000),
    pero extrae componentes válidos de delegación, año, inscripción y bis de cualquier PDF,
    permitiendo la selección manual o por lotes sin bloqueos.
    """
    match_zero = ZERO_PDF_REGEX.match(filename)
    if match_zero:
        delegacion = match_zero.group(1)
        pdf_year = match_zero.group(7)
        tail = match_zero.group(8)
        parts = tail.split("_", 1)
        inscripcion = parts[0]
        bis_and_extra = parts[1] if len(parts) > 1 else "00"
        is_yr_zero = (pdf_year == "0000")
        return PdfProposal(
            original_name=filename,
            full_path=full_path,
            is_target_zero=True,
            is_year_zero=is_yr_zero,
            is_selected_for_rename=True,
            detected_delegacion=delegacion,
            detected_seccion="00",
            detected_libro="00",
            detected_tomo="00",
            detected_volumen="00",
            detected_fraccionamiento="00",
            detected_year=pdf_year,
            inscripcion_bis_tail=tail,
            inscripcion=inscripcion,
            bis_and_extra=bis_and_extra,
            proposed_name="",
            reason_ignored="",
        )

    match_std = STANDARD_PDF_REGEX.match(filename)
    if match_std:
        delegacion = match_std.group(1)
        sec = match_std.group(2)
        lib = match_std.group(3)
        tom = match_std.group(4)
        vol = match_std.group(5)
        fra = match_std.group(6)
        pdf_year = match_std.group(7)
        tail = match_std.group(8)
        parts = tail.split("_", 1)
        inscripcion = parts[0]
        bis_and_extra = parts[1] if len(parts) > 1 else "00"
        is_zero_fields = (
            sec in ("00", "0")
            and lib in ("00", "0")
            and tom in ("00", "0")
            and vol in ("00", "0")
            and fra in ("00", "0")
        )
        is_yr_zero = (pdf_year == "0000")
        is_target_zero = is_zero_fields or is_yr_zero
        return PdfProposal(
            original_name=filename,
            full_path=full_path,
            is_target_zero=is_target_zero,
            is_year_zero=is_yr_zero,
            is_selected_for_rename=is_target_zero,
            detected_delegacion=delegacion,
            detected_seccion=sec,
            detected_libro=lib,
            detected_tomo=tom,
            detected_volumen=vol,
            detected_fraccionamiento=fra,
            detected_year=pdf_year,
            inscripcion_bis_tail=tail,
            inscripcion=inscripcion,
            bis_and_extra=bis_and_extra,
            proposed_name="",
            reason_ignored="" if is_target_zero else "No seleccionado inicialmente (Contiene datos)",
        )

    # Fallback para archivos PDF con estructura de año + inscripción
    year_match = re.search(r"_(\d{4})_(.+)\.pdf$", filename, re.IGNORECASE)
    if year_match:
        pdf_year = year_match.group(1)
        tail = year_match.group(2)
        parts = tail.split("_", 1)
        inscripcion = parts[0]
        bis_and_extra = parts[1] if len(parts) > 1 else "00"
        is_yr_zero = (pdf_year == "0000")
        return PdfProposal(
            original_name=filename,
            full_path=full_path,
            is_target_zero=is_yr_zero,
            is_year_zero=is_yr_zero,
            is_selected_for_rename=is_yr_zero,
            detected_delegacion="01",
            detected_year=pdf_year,
            inscripcion_bis_tail=tail,
            inscripcion=inscripcion,
            bis_and_extra=bis_and_extra,
            proposed_name="",
            reason_ignored="" if is_yr_zero else "No seleccionado inicialmente",
        )

    base_no_ext, _ = os.path.splitext(filename)
    parts = base_no_ext.split("_", 1)
    inscripcion = parts[0]
    bis_and_extra = parts[1] if len(parts) > 1 else "00"
    return PdfProposal(
        original_name=filename,
        full_path=full_path,
        is_target_zero=False,
        is_year_zero=False,
        is_selected_for_rename=False,
        detected_delegacion="01",
        detected_year="0000",
        inscripcion_bis_tail=base_no_ext,
        inscripcion=inscripcion,
        bis_and_extra=bis_and_extra,
        proposed_name="",
        reason_ignored="Formato no estándar (No seleccionado)",
    )


def scan_directory(folder_path: str) -> FolderAnalysis:
    """
    Escanea una carpeta seleccionada y analiza todos sus PDFs.
    Permite seleccionar individualmente qué PDFs renombrar y cuáles conservar intactos.
    """
    folder_path = os.path.normpath(folder_path)
    folder_name = os.path.basename(folder_path)
    delegacion, detected_year, detected_suffix = parse_folder_name(folder_name)

    analysis = FolderAnalysis(
        folder_path=folder_path,
        folder_name=folder_name,
        delegacion=delegacion or "01",
        detected_year=detected_year,
        year_is_zero=(detected_year == "0000"),
        detected_suffix=detected_suffix,
    )

    try:
        entries = sorted(os.listdir(folder_path))
    except OSError as exc:
        raise RuntimeError(f"No se pudo leer el directorio:\n{folder_path}\n\nDetalle: {exc}") from exc

    for entry in entries:
        if not entry.lower().endswith(".pdf"):
            continue
        full_p = os.path.join(folder_path, entry)
        if not os.path.isfile(full_p):
            continue

        proposal = analyze_pdf_filename(entry, full_p)
        analysis.all_pdfs.append(proposal)

    return analysis


def build_proposals(
    analysis: FolderAnalysis,
    delegacion: str,
    seccion: str,
    libro: str,
    tomo: str,
    volumen: str,
    fraccionamiento: str,
    anio: str,
    suffix: str = "",
) -> Tuple[str, List[PdfProposal]]:
    """
    Genera el nuevo nombre de carpeta propuesto y actualiza los nombres propuestos
    de todos los PDFs seleccionados para renombrar:
    - Delegación (por defecto 01)
    - Sección, Libro, Tomo, Volumen, Fraccionamiento capturados
    - Año de la carpeta (o capturado si era 0000)
    - Sufijo _REVISAR en la carpeta
    - Inscripción y Bis (o sufijo) intactos en cada PDF
    """
    f_del = format_numeric_field(delegacion or "01", 2)
    f_sec = format_numeric_field(seccion, 2)
    f_lib = format_numeric_field(libro, 2)
    f_tom = format_optional_alphanumeric_field(tomo, 2)
    f_vol = format_numeric_field(volumen, 2)
    f_fra = format_optional_alphanumeric_field(fraccionamiento, 2)
    f_anio = format_numeric_field(anio, 4)

    prefix = f"{f_del}_{f_sec}_{f_lib}_{f_tom}_{f_vol}_{f_fra}_{f_anio}"

    clean_suffix = (suffix if suffix != "" else analysis.detected_suffix).strip(" _")
    if clean_suffix:
        proposed_folder_name = f"{prefix}_{clean_suffix}"
    else:
        proposed_folder_name = prefix

    target_list = analysis.all_pdfs if analysis.all_pdfs else analysis.pdfs_to_rename
    updated_pdfs: List[PdfProposal] = []
    for item in target_list:
        if getattr(item, "is_selected_for_rename", True):
            tail = item.inscripcion_bis_tail or os.path.splitext(item.original_name)[0]
            new_pdf_name = f"{prefix}_{tail}.pdf"
            item.proposed_name = new_pdf_name
            updated_pdfs.append(item)
        else:
            item.proposed_name = item.original_name

    return proposed_folder_name, updated_pdfs
