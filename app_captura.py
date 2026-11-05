"""
Aplicación de Escritorio Portable: Captura Local, Revisión y Rollback de Directorios/PDFs en Ceros
Ubicación: C:\laragon\www\CAPTURA_CEROS
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

from src.naming_engine import (
    FolderAnalysis,
    build_proposals,
    format_numeric_field,
    format_optional_alphanumeric_field,
    scan_directory,
)
from src.pdf_viewer import EmbeddedPdfViewer
from src.storage import LocalCaptureStore

DEFAULT_NETWORK_ROOT = (
    r"\\172.40.5.84\ssdirec\REVISANDO\ENTREGA 1\4 ENTREGA SELLOS LIBROS\SELLOS LIBROS\Tuxtla Gutiérrez"
)


class CapturaCerosApp(tk.Tk):
    """Ventana principal de la herramienta de captura local y auditoría."""

    def __init__(self) -> None:
        super().__init__()
        self.title(
            "CAPTURA DE CEROS — Sellos Libros (Tuxtla Gutiérrez) | Captura Local, Revisión y Rollback"
        )
        self.geometry("1460x880")
        self.minsize(1200, 740)
        self.configure(bg="#F1F5F9")

        self.store = LocalCaptureStore()
        self.current_analysis: Optional[FolderAnalysis] = None
        self.selected_review_id: Optional[int] = None

        self._configure_styles()
        self._build_layout()
        self._refresh_review_table()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("TFrame", background="#F1F5F9")
        style.configure("Card.TFrame", background="#FFFFFF")
        style.configure("TLabel", background="#F1F5F9", font=("Segoe UI", 9))
        style.configure("Card.TLabel", background="#FFFFFF", font=("Segoe UI", 9))
        style.configure(
            "Header.TLabel",
            background="#0F172A",
            foreground="#FFFFFF",
            font=("Segoe UI", 12, "bold"),
        )
        style.configure(
            "SubHeader.TLabel",
            background="#0F172A",
            foreground="#94A3B8",
            font=("Segoe UI", 9),
        )
        style.configure("TLabelframe", background="#F1F5F9", font=("Segoe UI", 9, "bold"))
        style.configure("TLabelframe.Label", background="#F1F5F9", foreground="#0F172A", font=("Segoe UI", 9, "bold"))
        style.configure("Treeview", rowheight=25, font=("Consolas", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _build_layout(self) -> None:
        # Encabezado superior
        header = tk.Frame(self, bg="#0F172A", padx=16, pady=10)
        header.pack(fill=tk.X, side=tk.TOP)

        title_box = tk.Frame(header, bg="#0F172A")
        title_box.pack(side=tk.LEFT)
        ttk.Label(
            title_box,
            text="HERRAMIENTA DE CAPTURA LOCAL — CARPETAS Y PDFs EN CEROS",
            style="Header.TLabel",
        ).pack(anchor=tk.W)
        ttk.Label(
            title_box,
            text="Modo Seguro: Los datos capturados se guardan localmente para revisión previa. Ningún archivo físico se modifica sin autorización.",
            style="SubHeader.TLabel",
        ).pack(anchor=tk.W)

        badge_frame = tk.Frame(header, bg="#0F172A")
        badge_frame.pack(side=tk.RIGHT)
        self.lbl_global_stats = tk.Label(
            badge_frame,
            text="Capturas locales: 0",
            bg="#1E293B",
            fg="#38BDF8",
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=6,
        )
        self.lbl_global_stats.pack(side=tk.RIGHT)

        # Notebook con las 2 vistas principales
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        self.tab_capture = ttk.Frame(self.notebook, padding=8)
        self.tab_review = ttk.Frame(self.notebook, padding=8)

        self.notebook.add(
            self.tab_capture, text="  1. Captura de Directorio + Visor PDF  "
        )
        self.notebook.add(
            self.tab_review,
            text="  2. Revisión, Aprobación, Aplicar Cambios y Rollback  ",
        )

        self._build_capture_tab()
        self._build_review_tab()

    # =========================================================================
    # PESTAÑA 1: CAPTURA DE DIRECTORIO Y VISOR DE PDF INTEGRADO
    # =========================================================================
    def _build_capture_tab(self) -> None:
        # 1. Barra de selección de directorio individual
        top_bar = ttk.LabelFrame(
            self.tab_capture,
            text=" Selección Individual de Directorio a Capturar ",
            padding=(10, 8),
        )
        top_bar.pack(fill=tk.X, side=tk.TOP, pady=(0, 8))

        ttk.Label(top_bar, text="Ruta de Carpeta:").pack(side=tk.LEFT, padx=(0, 6))

        self.var_folder_path = tk.StringVar(value="")
        self.entry_folder_path = ttk.Entry(
            top_bar, textvariable=self.var_folder_path, font=("Consolas", 10)
        )
        self.entry_folder_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.entry_folder_path.bind("<Return>", lambda _: self.load_directory_from_entry())

        ttk.Button(
            top_bar,
            text="📂 Examinar Carpeta...",
            command=self.browse_directory,
        ).pack(side=tk.LEFT, padx=3)

        ttk.Button(
            top_bar,
            text="⚡ Elegir de Tuxtla (En Ceros)...",
            command=self.open_quick_picker_dialog,
        ).pack(side=tk.LEFT, padx=3)

        ttk.Button(
            top_bar,
            text="🔄 Cargar Ruta",
            command=self.load_directory_from_entry,
        ).pack(side=tk.LEFT, padx=3)

        # Panel dividido horizontalmente: Izquierda (Formulario + Tabla PDFs) | Derecha (Visor PDF)
        paned = ttk.PanedWindow(self.tab_capture, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left_pane = ttk.Frame(paned, padding=(0, 0, 6, 0))
        right_pane = ttk.LabelFrame(
            paned, text=" Visor de PDF Integrado (Inspección de Sello/Libro) ", padding=4
        )

        paned.add(left_pane, weight=5)
        paned.add(right_pane, weight=6)

        # --- SUBPANEL IZQUIERDO: FORMULARIO DE CAPTURA ---
        form_frame = ttk.LabelFrame(
            left_pane,
            text=" Campos de Captura (Orden: Delegación _ Sección _ Libro _ Tomo _ Volumen _ Fraccionamiento _ Año) ",
            padding=10,
        )
        form_frame.pack(fill=tk.X, side=tk.TOP, pady=(0, 8))

        # Variables de captura
        self.var_delegacion = tk.StringVar(value="01")
        self.var_seccion = tk.StringVar(value="00")
        self.var_libro = tk.StringVar(value="00")
        self.var_tomo = tk.StringVar(value="00")
        self.var_volumen = tk.StringVar(value="00")
        self.var_fraccionamiento = tk.StringVar(value="00")
        self.var_anio = tk.StringVar(value="0000")
        self.var_suffix = tk.StringVar(value="REVISAR")
        self.var_notes = tk.StringVar(value="")

        self.var_allow_alpha_tomo = tk.BooleanVar(value=False)
        self.var_allow_alpha_frac = tk.BooleanVar(value=False)

        # Escuchar cambios para actualizar vista previa en tiempo real
        for v in (
            self.var_delegacion,
            self.var_seccion,
            self.var_libro,
            self.var_tomo,
            self.var_volumen,
            self.var_fraccionamiento,
            self.var_anio,
            self.var_suffix,
        ):
            v.trace_add("write", lambda *_: self._on_fields_changed())

        grid_f = ttk.Frame(form_frame)
        grid_f.pack(fill=tk.X)

        # Fila 0: Etiquetas de columnas
        headers = [
            ("1. Delegación", "Default: 01 (Tuxtla)"),
            ("2. Sección", "Numérico (2 díg)"),
            ("3. Libro", "Numérico (2 díg)"),
            ("4. Tomo", "Num / Alfanum opc."),
            ("5. Volumen", "Numérico (2 díg)"),
            ("6. Fraccionamiento", "Num / Alfanum opc."),
            ("7. Año", "De carpeta / Captura"),
            ("Sufijo Carpeta", "Se conserva _REVISAR"),
        ]
        for col_idx, (title_txt, sub_txt) in enumerate(headers):
            ttk.Label(
                grid_f, text=title_txt, font=("Segoe UI", 9, "bold"), foreground="#0F172A"
            ).grid(row=0, column=col_idx, sticky=tk.W, padx=4, pady=(0, 1))
            ttk.Label(
                grid_f, text=sub_txt, font=("Segoe UI", 7), foreground="#64748B"
            ).grid(row=1, column=col_idx, sticky=tk.W, padx=4, pady=(0, 4))

        # Fila 2: Cajas de texto
        self.ent_delegacion = ttk.Entry(
            grid_f, textvariable=self.var_delegacion, width=9, font=("Consolas", 11, "bold")
        )
        self.ent_delegacion.grid(row=2, column=0, sticky=tk.EW, padx=4)

        self.ent_seccion = ttk.Entry(
            grid_f, textvariable=self.var_seccion, width=9, font=("Consolas", 11, "bold")
        )
        self.ent_seccion.grid(row=2, column=1, sticky=tk.EW, padx=4)

        self.ent_libro = ttk.Entry(
            grid_f, textvariable=self.var_libro, width=9, font=("Consolas", 11, "bold")
        )
        self.ent_libro.grid(row=2, column=2, sticky=tk.EW, padx=4)

        self.ent_tomo = ttk.Entry(
            grid_f, textvariable=self.var_tomo, width=14, font=("Consolas", 11, "bold")
        )
        self.ent_tomo.grid(row=2, column=3, sticky=tk.EW, padx=4)

        self.ent_volumen = ttk.Entry(
            grid_f, textvariable=self.var_volumen, width=9, font=("Consolas", 11, "bold")
        )
        self.ent_volumen.grid(row=2, column=4, sticky=tk.EW, padx=4)

        self.ent_fraccionamiento = ttk.Entry(
            grid_f, textvariable=self.var_fraccionamiento, width=18, font=("Consolas", 11, "bold")
        )
        self.ent_fraccionamiento.grid(row=2, column=5, sticky=tk.EW, padx=4)

        self.ent_anio = ttk.Entry(
            grid_f, textvariable=self.var_anio, width=9, font=("Consolas", 11, "bold")
        )
        self.ent_anio.grid(row=2, column=6, sticky=tk.EW, padx=4)

        self.ent_suffix = ttk.Entry(
            grid_f, textvariable=self.var_suffix, width=13, font=("Consolas", 10)
        )
        self.ent_suffix.grid(row=2, column=7, sticky=tk.EW, padx=4)

        # Auto-formateo a 2 dígitos al salir del campo (FocusOut)
        self.ent_delegacion.bind("<FocusOut>", lambda _: self._pad_var(self.var_delegacion, 2, False))
        self.ent_seccion.bind("<FocusOut>", lambda _: self._pad_var(self.var_seccion, 2, False))
        self.ent_libro.bind("<FocusOut>", lambda _: self._pad_var(self.var_libro, 2, False))
        self.ent_tomo.bind(
            "<FocusOut>",
            lambda _: self._pad_var(self.var_tomo, 2, self.var_allow_alpha_tomo.get()),
        )
        self.ent_volumen.bind("<FocusOut>", lambda _: self._pad_var(self.var_volumen, 2, False))
        self.ent_fraccionamiento.bind(
            "<FocusOut>",
            lambda _: self._pad_var(
                self.var_fraccionamiento, 2, self.var_allow_alpha_frac.get()
            ),
        )
        self.ent_anio.bind("<FocusOut>", lambda _: self._pad_var(self.var_anio, 4, False))

        # Checkboxes para activar modo alfanumérico opcional en Tomo y Fraccionamiento
        chk_tomo = ttk.Checkbutton(
            grid_f,
            text="Alfanumérico opc.",
            variable=self.var_allow_alpha_tomo,
            command=self._on_fields_changed,
        )
        chk_tomo.grid(row=3, column=3, sticky=tk.W, padx=4, pady=(4, 0))

        chk_frac = ttk.Checkbutton(
            grid_f,
            text="Alfanumérico opc.",
            variable=self.var_allow_alpha_frac,
            command=self._on_fields_changed,
        )
        chk_frac.grid(row=3, column=5, sticky=tk.W, padx=4, pady=(4, 0))

        self.lbl_anio_hint = ttk.Label(
            grid_f,
            text="Tomado de carpeta",
            font=("Segoe UI", 8, "italic"),
            foreground="#0284C7",
        )
        self.lbl_anio_hint.grid(row=3, column=6, sticky=tk.W, padx=4, pady=(4, 0))

        # Notas opcionales y Vista Previa de Carpeta
        preview_box = tk.Frame(
            form_frame, bg="#F8FAFC", highlightbackground="#CBD5E1", highlightthickness=1, padx=10, pady=8
        )
        preview_box.pack(fill=tk.X, pady=(10, 6))

        row_orig = tk.Frame(preview_box, bg="#F8FAFC")
        row_orig.pack(fill=tk.X, pady=1)
        tk.Label(
            row_orig,
            text="Carpeta Original:   ",
            bg="#F8FAFC",
            fg="#475569",
            font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.LEFT)
        self.lbl_orig_folder = tk.Label(
            row_orig,
            text="(Seleccione un directorio)",
            bg="#F8FAFC",
            fg="#334155",
            font=("Consolas", 10),
        )
        self.lbl_orig_folder.pack(side=tk.LEFT)

        row_prop = tk.Frame(preview_box, bg="#F8FAFC")
        row_prop.pack(fill=tk.X, pady=1)
        tk.Label(
            row_prop,
            text="Carpeta Propuesta:",
            bg="#F8FAFC",
            fg="#0F766E",
            font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.LEFT)
        self.lbl_prop_folder = tk.Label(
            row_prop,
            text="-",
            bg="#F8FAFC",
            fg="#0F766E",
            font=("Consolas", 11, "bold"),
        )
        self.lbl_prop_folder.pack(side=tk.LEFT, padx=(4, 0))

        # Barra de Notas y Botón Guardar Captura Local
        action_bar = ttk.Frame(form_frame)
        action_bar.pack(fill=tk.X, pady=(4, 0))

        ttk.Label(action_bar, text="Observaciones / Notas:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Entry(action_bar, textvariable=self.var_notes, width=32).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10)
        )

        ttk.Button(
            action_bar,
            text="🧹 Limpiar Campos a 00",
            command=self.reset_fields_to_zero,
        ).pack(side=tk.LEFT, padx=4)

        self.btn_save_local = tk.Button(
            action_bar,
            text="💾 GUARDAR CAPTURA LOCALMENTE (Sin tocar red)",
            bg="#0284C7",
            fg="#FFFFFF",
            activebackground="#0369A1",
            activeforeground="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=5,
            cursor="hand2",
            command=self.save_current_capture_locally,
        )
        self.btn_save_local.pack(side=tk.RIGHT)

        # --- SUBPANEL IZQUIERDO INFERIOR: TABLA DE ARCHIVOS PDF ---
        files_frame = ttk.LabelFrame(
            left_pane,
            text=" Archivos PDF en el Directorio (Clic en cualquier fila para visualizar el PDF a la derecha) ",
            padding=8,
        )
        files_frame.pack(fill=tk.BOTH, expand=True)

        summary_bar = ttk.Frame(files_frame)
        summary_bar.pack(fill=tk.X, pady=(0, 6))

        self.lbl_files_summary = ttk.Label(
            summary_bar,
            text="En ceros a renombrar: 0   |   Con datos (Ignorados): 0",
            font=("Segoe UI", 9, "bold"),
            foreground="#1E293B",
        )
        self.lbl_files_summary.pack(side=tk.LEFT)

        self.var_filter_files = tk.StringVar(value="TODOS")
        filter_box = ttk.Frame(summary_bar)
        filter_box.pack(side=tk.RIGHT)
        ttk.Label(filter_box, text="Mostrar:").pack(side=tk.LEFT, padx=4)
        for txt, val in [
            ("Todos", "TODOS"),
            ("Solo en Ceros (Renombrar)", "CEROS"),
            ("Solo Ignorados", "IGNORADOS"),
        ]:
            ttk.Radiobutton(
                filter_box,
                text=txt,
                value=val,
                variable=self.var_filter_files,
                command=self._populate_files_preview_tree,
            ).pack(side=tk.LEFT, padx=3)

        # Treeview de previsualización de PDFs
        tree_container = ttk.Frame(files_frame)
        tree_container.pack(fill=tk.BOTH, expand=True)

        cols = ("accion", "original", "propuesto", "inscripcion", "bis")
        self.tree_files = ttk.Treeview(
            tree_container, columns=cols, show="headings", selectmode="browse"
        )
        self.tree_files.heading("accion", text="Acción")
        self.tree_files.heading("original", text="Nombre PDF Original")
        self.tree_files.heading("propuesto", text="Nombre PDF Propuesto (Simulación)")
        self.tree_files.heading("inscripcion", text="Inscripción")
        self.tree_files.heading("bis", text="Bis")

        self.tree_files.column("accion", width=110, anchor=tk.CENTER, stretch=False)
        self.tree_files.column("original", width=265, anchor=tk.W)
        self.tree_files.column("propuesto", width=285, anchor=tk.W)
        self.tree_files.column("inscripcion", width=80, anchor=tk.CENTER, stretch=False)
        self.tree_files.column("bis", width=65, anchor=tk.CENTER, stretch=False)

        self.tree_files.tag_configure("RENOMBRAR", background="#F0FDF4", foreground="#14532D")
        self.tree_files.tag_configure("IGNORAR", background="#F8FAFC", foreground="#64748B")

        vsb = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.tree_files.yview)
        hsb = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL, command=self.tree_files.xview)
        self.tree_files.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree_files.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree_files.bind("<<TreeviewSelect>>", self._on_file_row_selected)

        # --- SUBPANEL DERECHO: VISOR PDF INTEGRADO ---
        self.pdf_viewer = EmbeddedPdfViewer(right_pane)
        self.pdf_viewer.pack(fill=tk.BOTH, expand=True)

    # =========================================================================
    # PESTAÑA 2: REVISIÓN, APROBACIÓN, APLICACIÓN DE CAMBIOS Y ROLLBACK
    # =========================================================================
    def _build_review_tab(self) -> None:
        top_controls = ttk.LabelFrame(
            self.tab_review,
            text=" Gestión de Capturas Locales, Auditoría Previa, Ejecución y Rollback ",
            padding=10,
        )
        top_controls.pack(fill=tk.X, side=tk.TOP, pady=(0, 8))

        btn_left = ttk.Frame(top_controls)
        btn_left.pack(side=tk.LEFT)

        ttk.Button(
            btn_left,
            text="🔄 Actualizar Lista",
            command=self._refresh_review_table,
        ).pack(side=tk.LEFT, padx=3)

        ttk.Button(
            btn_left,
            text="✏️ Cargar en Editor para Corregir",
            command=self.edit_selected_capture,
        ).pack(side=tk.LEFT, padx=3)

        ttk.Button(
            btn_left,
            text="✅ Marcar como APROBADO",
            command=self.approve_selected_capture,
        ).pack(side=tk.LEFT, padx=3)

        ttk.Button(
            btn_left,
            text="🗑️ Eliminar Captura Local",
            command=self.delete_selected_capture,
        ).pack(side=tk.LEFT, padx=3)

        ttk.Separator(btn_left, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(
            btn_left,
            text="📊 Exportar CSV (Excel)",
            command=self.export_csv_dialog,
        ).pack(side=tk.LEFT, padx=3)

        ttk.Button(
            btn_left,
            text="📄 Exportar Respaldo JSON",
            command=self.export_json_dialog,
        ).pack(side=tk.LEFT, padx=3)

        # Botones de Ejecución Física y Rollback a la derecha
        btn_right = ttk.Frame(top_controls)
        btn_right.pack(side=tk.RIGHT)

        self.btn_apply_changes = tk.Button(
            btn_right,
            text="🚀 APLICAR CAMBIOS A SELECCIONADA",
            bg="#15803D",
            fg="#FFFFFF",
            activebackground="#166534",
            activeforeground="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=4,
            cursor="hand2",
            command=self.apply_selected_capture,
        )
        self.btn_apply_changes.pack(side=tk.LEFT, padx=4)

        self.btn_apply_all_approved = tk.Button(
            btn_right,
            text="🚀 APLICAR TODAS LAS APROBADAS",
            bg="#0F766E",
            fg="#FFFFFF",
            activebackground="#115E59",
            activeforeground="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=4,
            cursor="hand2",
            command=self.apply_all_approved_captures,
        )
        self.btn_apply_all_approved.pack(side=tk.LEFT, padx=4)

        self.btn_rollback = tk.Button(
            btn_right,
            text="⏪ ROLLBACK (Revertir a Original)",
            bg="#B91C1C",
            fg="#FFFFFF",
            activebackground="#991B1B",
            activeforeground="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=4,
            cursor="hand2",
            command=self.rollback_selected_capture,
        )
        self.btn_rollback.pack(side=tk.LEFT, padx=4)

        # Panel dividido verticalmente: Arriba (Tabla de Directorios Capturados) | Abajo (Detalle de PDFs de la captura seleccionada)
        v_paned = ttk.PanedWindow(self.tab_review, orient=tk.VERTICAL)
        v_paned.pack(fill=tk.BOTH, expand=True)

        folders_frame = ttk.LabelFrame(
            v_paned,
            text=" Directorios Capturados Localmente (Selecciona uno para inspeccionar su lote de PDFs abajo) ",
            padding=6,
        )
        detail_frame = ttk.LabelFrame(
            v_paned,
            text=" Detalle de Archivos PDF (Antes vs. Después) del Directorio Seleccionado ",
            padding=6,
        )

        v_paned.add(folders_frame, weight=5)
        v_paned.add(detail_frame, weight=5)

        # Tabla de carpetas capturadas
        f_cols = (
            "id",
            "estado",
            "original_folder",
            "proposed_folder",
            "campos",
            "pdfs_rename",
            "pdfs_ignored",
            "updated_at",
            "notas",
        )
        self.tree_review_folders = ttk.Treeview(
            folders_frame, columns=f_cols, show="headings", selectmode="browse"
        )
        self.tree_review_folders.heading("id", text="ID")
        self.tree_review_folders.heading("estado", text="Estado")
        self.tree_review_folders.heading("original_folder", text="Carpeta Original")
        self.tree_review_folders.heading("proposed_folder", text="Carpeta Propuesta")
        self.tree_review_folders.heading("campos", text="Del|Sec|Lib|Tom|Vol|Frac|Año")
        self.tree_review_folders.heading("pdfs_rename", text="PDFs a Renombrar")
        self.tree_review_folders.heading("pdfs_ignored", text="Ignorados")
        self.tree_review_folders.heading("updated_at", text="Última Actualización")
        self.tree_review_folders.heading("notas", text="Notas")

        self.tree_review_folders.column("id", width=45, anchor=tk.CENTER, stretch=False)
        self.tree_review_folders.column("estado", width=150, anchor=tk.CENTER, stretch=False)
        self.tree_review_folders.column("original_folder", width=270, anchor=tk.W)
        self.tree_review_folders.column("proposed_folder", width=300, anchor=tk.W)
        self.tree_review_folders.column("campos", width=200, anchor=tk.CENTER)
        self.tree_review_folders.column("pdfs_rename", width=115, anchor=tk.CENTER, stretch=False)
        self.tree_review_folders.column("pdfs_ignored", width=85, anchor=tk.CENTER, stretch=False)
        self.tree_review_folders.column("updated_at", width=140, anchor=tk.CENTER, stretch=False)
        self.tree_review_folders.column("notas", width=180, anchor=tk.W)

        self.tree_review_folders.tag_configure(
            "PENDIENTE_REVISION", background="#FEF9C3", foreground="#854D0E"
        )
        self.tree_review_folders.tag_configure(
            "APROBADO", background="#E0F2FE", foreground="#075985"
        )
        self.tree_review_folders.tag_configure(
            "APLICADO", background="#DCFCE7", foreground="#166534"
        )
        self.tree_review_folders.tag_configure(
            "REVERTIDO_ROLLBACK", background="#FEE2E2", foreground="#991B1B"
        )

        f_vsb = ttk.Scrollbar(
            folders_frame, orient=tk.VERTICAL, command=self.tree_review_folders.yview
        )
        f_hsb = ttk.Scrollbar(
            folders_frame, orient=tk.HORIZONTAL, command=self.tree_review_folders.xview
        )
        self.tree_review_folders.configure(yscrollcommand=f_vsb.set, xscrollcommand=f_hsb.set)
        f_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        f_hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree_review_folders.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree_review_folders.bind(
            "<<TreeviewSelect>>", self._on_review_folder_selected
        )

        # Tabla inferior de detalle de PDFs de la carpeta seleccionada
        d_cols = ("estado_pdf", "original_pdf", "proposed_pdf", "cola_inscripcion")
        self.tree_review_files = ttk.Treeview(
            detail_frame, columns=d_cols, show="headings", selectmode="browse"
        )
        self.tree_review_files.heading("estado_pdf", text="Estado Archivo")
        self.tree_review_files.heading("original_pdf", text="Archivo PDF Original")
        self.tree_review_files.heading("proposed_pdf", text="Archivo PDF Propuesto / Resultante")
        self.tree_review_files.heading("cola_inscripcion", text="Inscripción y Bis Conservados")

        self.tree_review_files.column("estado_pdf", width=130, anchor=tk.CENTER, stretch=False)
        self.tree_review_files.column("original_pdf", width=380, anchor=tk.W)
        self.tree_review_files.column("proposed_pdf", width=420, anchor=tk.W)
        self.tree_review_files.column("cola_inscripcion", width=180, anchor=tk.CENTER)

        self.tree_review_files.tag_configure("TARGET", background="#F0FDF4", foreground="#14532D")
        self.tree_review_files.tag_configure("IGNORED", background="#F8FAFC", foreground="#64748B")

        d_vsb = ttk.Scrollbar(
            detail_frame, orient=tk.VERTICAL, command=self.tree_review_files.yview
        )
        self.tree_review_files.configure(yscrollcommand=d_vsb.set)
        d_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_review_files.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # =========================================================================
    # LÓGICA DE CAPTURA Y PREVISUALIZACIÓN
    # =========================================================================
    def _pad_var(self, var: tk.StringVar, width: int, allow_alpha: bool) -> None:
        raw = var.get().strip()
        if not raw:
            var.set("0" * width)
            return
        if allow_alpha:
            var.set(format_optional_alphanumeric_field(raw, width))
        else:
            # Solo dígitos si no está marcado alfanumérico
            digits_only = "".join(ch for ch in raw if ch.isdigit())
            if not digits_only:
                var.set("0" * width)
            else:
                var.set(digits_only.zfill(width))

    def reset_fields_to_zero(self) -> None:
        self.var_delegacion.set("01")
        self.var_seccion.set("00")
        self.var_libro.set("00")
        self.var_tomo.set("00")
        self.var_volumen.set("00")
        self.var_fraccionamiento.set("00")
        if self.current_analysis and not self.current_analysis.year_is_zero:
            self.var_anio.set(self.current_analysis.detected_year)
        self._on_fields_changed()

    def browse_directory(self) -> None:
        initial = DEFAULT_NETWORK_ROOT if os.path.isdir(DEFAULT_NETWORK_ROOT) else "C:\\"
        chosen = filedialog.askdirectory(
            parent=self,
            title="Seleccionar Directorio Individual a Capturar",
            initialdir=initial,
        )
        if chosen:
            self.var_folder_path.set(os.path.normpath(chosen))
            self.load_directory(chosen)

    def open_quick_picker_dialog(self) -> None:
        """
        Abre un selector rápido que lista todas las carpetas con ceros o _REVISAR
        dentro de Tuxtla Gutiérrez e indica cuáles ya tienen captura local.
        """
        root_dir = DEFAULT_NETWORK_ROOT
        if not os.path.isdir(root_dir):
            messagebox.showwarning(
                "Ruta de red no disponible",
                f"No se pudo acceder a la ruta predeterminada:\n{root_dir}\n\nUsa 'Examinar Carpeta...' para elegir otra ubicación.",
            )
            return

        dlg = tk.Toplevel(self)
        dlg.title("Selector Rápido de Directorios en Ceros — Tuxtla Gutiérrez")
        dlg.geometry("820x520")
        dlg.transient(self)
        dlg.grab_set()

        top = ttk.Frame(dlg, padding=10)
        top.pack(fill=tk.X)
        ttk.Label(
            top,
            text="Directorios detectados con campos en ceros o sufijo _REVISAR (Doble clic para cargar):",
            font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.LEFT)

        var_only_pending = tk.BooleanVar(value=False)

        tree_f = ttk.Frame(dlg, padding=(10, 0, 10, 10))
        tree_f.pack(fill=tk.BOTH, expand=True)

        cols = ("carpeta", "estado_local", "propuesta_guardada")
        tv = ttk.Treeview(tree_f, columns=cols, show="headings", selectmode="browse")
        tv.heading("carpeta", text="Nombre de Carpeta en Red")
        tv.heading("estado_local", text="Estado en Captura Local")
        tv.heading("propuesta_guardada", text="Propuesta Guardada")

        tv.column("carpeta", width=290, anchor=tk.W)
        tv.column("estado_local", width=160, anchor=tk.CENTER)
        tv.column("propuesta_guardada", width=310, anchor=tk.W)

        tv.tag_configure("CAPTURED", background="#DCFCE7", foreground="#166534")
        tv.tag_configure("NEW", background="#FFFFFF", foreground="#0F172A")

        vsb = ttk.Scrollbar(tree_f, orient=tk.VERTICAL, command=tv.yview)
        tv.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        tv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        existing_map = {
            os.path.normcase(c["original_folder_path"]): c
            for c in self.store.get_all_captures()
        }

        all_entries = sorted(os.listdir(root_dir))
        candidate_Dirs = [
            d
            for d in all_entries
            if ("_00_00_" in d or "REVISAR" in d.upper())
            and os.path.isdir(os.path.join(root_dir, d))
        ]

        def populate_picker() -> None:
            tv.delete(*tv.get_children())
            for d_name in candidate_Dirs:
                full_p = os.path.normpath(os.path.join(root_dir, d_name))
                cap = existing_map.get(os.path.normcase(full_p))
                if var_only_pending.get() and cap is not None:
                    continue
                if cap:
                    tv.insert(
                        "",
                        tk.END,
                        values=(d_name, cap["status"], cap["proposed_folder_name"]),
                        tags=("CAPTURED",),
                    )
                else:
                    tv.insert(
                        "",
                        tk.END,
                        values=(d_name, "SIN CAPTURAR", "-"),
                        tags=("NEW",),
                    )

        ttk.Checkbutton(
            top,
            text="Ocultar ya capturadas",
            variable=var_only_pending,
            command=populate_picker,
        ).pack(side=tk.RIGHT)

        populate_picker()

        def on_choose(_event: Optional[tk.Event] = None) -> None:
            sel = tv.selection()
            if not sel:
                return
            folder_name = tv.item(sel[0], "values")[0]
            chosen_path = os.path.normpath(os.path.join(root_dir, folder_name))
            dlg.destroy()
            self.var_folder_path.set(chosen_path)
            self.load_directory(chosen_path)

        tv.bind("<Double-1>", on_choose)

        bottom = ttk.Frame(dlg, padding=10)
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="Cargar Directorio Seleccionado", command=on_choose).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(bottom, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT)

    def load_directory_from_entry(self) -> None:
        path = self.var_folder_path.get().strip()
        if not path:
            messagebox.showwarning("Ruta vacía", "Ingresa o selecciona la ruta de un directorio.")
            return
        self.load_directory(path)

    def load_directory(self, folder_path: str) -> None:
        try:
            analysis = scan_directory(folder_path)
        except Exception as exc:
            messagebox.showerror("Error al leer carpeta", str(exc))
            return

        self.current_analysis = analysis
        self.lbl_orig_folder.config(text=analysis.folder_name)

        # Verificar si ya existe una captura previa guardada localmente para esta carpeta
        saved = self.store.get_capture_by_path(analysis.folder_path)
        if saved:
            self.var_delegacion.set(saved["delegacion"])
            self.var_seccion.set(saved["seccion"])
            self.var_libro.set(saved["libro"])
            self.var_tomo.set(saved["tomo"])
            self.var_volumen.set(saved["volumen"])
            self.var_fraccionamiento.set(saved["fraccionamiento"])
            self.var_anio.set(saved["anio"])
            self.var_suffix.set(saved["suffix"])
            self.var_notes.set(saved["notes"] or "")
            self.var_allow_alpha_tomo.set(not saved["tomo"].isdigit())
            self.var_allow_alpha_frac.set(not saved["fraccionamiento"].isdigit())
        else:
            # Valores por defecto según las reglas de negocio
            self.var_delegacion.set(analysis.delegacion or "01")
            self.var_seccion.set("00")
            self.var_libro.set("00")
            self.var_tomo.set("00")
            self.var_volumen.set("00")
            self.var_fraccionamiento.set("00")
            self.var_anio.set(analysis.detected_year)
            self.var_suffix.set(analysis.detected_suffix)
            self.var_notes.set("")
            self.var_allow_alpha_tomo.set(False)
            self.var_allow_alpha_frac.set(False)

        # Si el año de la carpeta no es 0000, se bloquea edición accidental o se indica que viene de la carpeta
        if analysis.year_is_zero:
            self.ent_anio.config(state=tk.NORMAL)
            self.lbl_anio_hint.config(
                text="Carpeta en 0000: Captura el año", foreground="#DC2626"
            )
        else:
            self.ent_anio.config(state="readonly")
            self.lbl_anio_hint.config(
                text=f"Fijo de carpeta ({analysis.detected_year})", foreground="#0284C7"
            )

        self._on_fields_changed()

        # Seleccionar y cargar automáticamente el primer PDF en ceros en el visor
        children = self.tree_files.get_children()
        if children:
            self.tree_files.selection_set(children[0])
            self.tree_files.focus(children[0])
            self._on_file_row_selected()
        else:
            self.pdf_viewer.close_pdf()

        # Poner foco directo en el campo Sección para capturar rápido con Tab
        self.ent_seccion.focus_set()
        self.ent_seccion.selection_range(0, tk.END)

    def _on_fields_changed(self) -> None:
        if not self.current_analysis:
            return

        tomo_val = (
            format_optional_alphanumeric_field(self.var_tomo.get(), 2)
            if self.var_allow_alpha_tomo.get()
            else format_numeric_field(
                "".join(c for c in self.var_tomo.get() if c.isdigit()), 2
            )
        )
        frac_val = (
            format_optional_alphanumeric_field(self.var_fraccionamiento.get(), 2)
            if self.var_allow_alpha_frac.get()
            else format_numeric_field(
                "".join(c for c in self.var_fraccionamiento.get() if c.isdigit()), 2
            )
        )

        prop_folder, _ = build_proposals(
            self.current_analysis,
            delegacion=self.var_delegacion.get(),
            seccion=self.var_seccion.get(),
            libro=self.var_libro.get(),
            tomo=tomo_val,
            volumen=self.var_volumen.get(),
            fraccionamiento=frac_val,
            anio=self.var_anio.get(),
            suffix=self.var_suffix.get(),
        )

        self.lbl_prop_folder.config(text=prop_folder)
        self.lbl_files_summary.config(
            text=(
                f"PDFs en ceros a renombrar: {len(self.current_analysis.pdfs_to_rename)}   |   "
                f"PDFs con datos (Ignorados): {len(self.current_analysis.pdfs_ignored)}"
            )
        )
        self._populate_files_preview_tree()

    def _populate_files_preview_tree(self) -> None:
        self.tree_files.delete(*self.tree_files.get_children())
        if not self.current_analysis:
            return

        mode = self.var_filter_files.get()

        if mode in ("TODOS", "CEROS"):
            for item in self.current_analysis.pdfs_to_rename:
                self.tree_files.insert(
                    "",
                    tk.END,
                    iid=item.full_path,
                    values=(
                        "RENOMBRAR",
                        item.original_name,
                        item.proposed_name,
                        item.inscripcion,
                        item.bis_and_extra,
                    ),
                    tags=("RENOMBRAR",),
                )

        if mode in ("TODOS", "IGNORADOS"):
            for item in self.current_analysis.pdfs_ignored:
                self.tree_files.insert(
                    "",
                    tk.END,
                    iid=item.full_path,
                    values=(
                        "IGNORAR (Intacto)",
                        item.original_name,
                        item.original_name,
                        "-",
                        "-",
                    ),
                    tags=("IGNORAR",),
                )

    def _on_file_row_selected(self, _event: Optional[tk.Event] = None) -> None:
        sel = self.tree_files.selection()
        if not sel:
            return
        pdf_full_path = sel[0]
        if os.path.isfile(pdf_full_path):
            self.pdf_viewer.load_pdf(pdf_full_path)

    def save_current_capture_locally(self) -> None:
        if not self.current_analysis:
            messagebox.showwarning(
                "Sin directorio cargado",
                "Primero selecciona y carga un directorio para guardar su captura.",
            )
            return

        # Normalizar todos los campos antes de guardar
        self._pad_var(self.var_delegacion, 2, False)
        self._pad_var(self.var_seccion, 2, False)
        self._pad_var(self.var_libro, 2, False)
        self._pad_var(self.var_tomo, 2, self.var_allow_alpha_tomo.get())
        self._pad_var(self.var_volumen, 2, False)
        self._pad_var(self.var_fraccionamiento, 2, self.var_allow_alpha_frac.get())
        self._pad_var(self.var_anio, 4, False)

        prop_folder, _ = build_proposals(
            self.current_analysis,
            delegacion=self.var_delegacion.get(),
            seccion=self.var_seccion.get(),
            libro=self.var_libro.get(),
            tomo=self.var_tomo.get(),
            volumen=self.var_volumen.get(),
            fraccionamiento=self.var_fraccionamiento.get(),
            anio=self.var_anio.get(),
            suffix=self.var_suffix.get(),
        )

        if len(self.current_analysis.pdfs_to_rename) == 0:
            messagebox.showwarning(
                "Sin PDFs en ceros",
                "Este directorio no contiene archivos PDF con formato en ceros (01_00_00_00_00_00_...).",
            )
            return

        try:
            capture_id = self.store.save_capture(
                original_folder_path=self.current_analysis.folder_path,
                original_folder_name=self.current_analysis.folder_name,
                proposed_folder_name=prop_folder,
                delegacion=self.var_delegacion.get(),
                seccion=self.var_seccion.get(),
                libro=self.var_libro.get(),
                tomo=self.var_tomo.get(),
                volumen=self.var_volumen.get(),
                fraccionamiento=self.var_fraccionamiento.get(),
                anio=self.var_anio.get(),
                suffix=self.var_suffix.get().strip(" _"),
                pdfs_to_rename=self.current_analysis.pdfs_to_rename,
                pdfs_ignored=self.current_analysis.pdfs_ignored,
                notes=self.var_notes.get().strip(),
            )
        except Exception as exc:
            messagebox.showerror("Error al guardar captura", str(exc))
            return

        self._refresh_review_table()
        messagebox.showinfo(
            "Captura Guardada Localmente",
            f"Registro #{capture_id} guardado con éxito en la base de datos local.\n\n"
            f"• Carpeta Original: {self.current_analysis.folder_name}\n"
            f"• Carpeta Propuesta: {prop_folder}\n"
            f"• PDFs a renombrar: {len(self.current_analysis.pdfs_to_rename)}\n"
            f"• PDFs ignorados (intactos): {len(self.current_analysis.pdfs_ignored)}\n\n"
            "No se ha modificado ningún archivo físico en red. Puedes revisarlo en la Pestaña 2.",
        )

    # =========================================================================
    # LÓGICA DE REVISIÓN, APROBACIÓN, APLICACIÓN Y ROLLBACK
    # =========================================================================
    def _refresh_review_table(self) -> None:
        self.tree_review_folders.delete(*self.tree_review_folders.get_children())
        self.tree_review_files.delete(*self.tree_review_files.get_children())

        captures = self.store.get_all_captures()
        self.lbl_global_stats.config(text=f"Capturas locales: {len(captures)}")

        for c in captures:
            campos_str = (
                f"{c['delegacion']}_{c['seccion']}_{c['libro']}_"
                f"{c['tomo']}_{c['volumen']}_{c['fraccionamiento']}_{c['anio']}"
            )
            tag = c["status"] if c["status"] in (
                "PENDIENTE_REVISION",
                "APROBADO",
                "APLICADO",
                "REVERTIDO_ROLLBACK",
            ) else "PENDIENTE_REVISION"

            self.tree_review_folders.insert(
                "",
                tk.END,
                iid=str(c["id"]),
                values=(
                    c["id"],
                    c["status"],
                    c["original_folder_name"],
                    c["proposed_folder_name"],
                    campos_str,
                    c["total_pdfs_rename"],
                    c["total_pdfs_ignored"],
                    c["updated_at"],
                    c["notes"] or "",
                ),
                tags=(tag,),
            )

    def _get_selected_capture_id(self) -> Optional[int]:
        sel = self.tree_review_folders.selection()
        if not sel:
            messagebox.showwarning(
                "Sin selección", "Selecciona una carpeta de la tabla superior."
            )
            return None
        return int(sel[0])

    def _on_review_folder_selected(self, _event: Optional[tk.Event] = None) -> None:
        sel = self.tree_review_folders.selection()
        self.tree_review_files.delete(*self.tree_review_files.get_children())
        if not sel:
            return
        cid = int(sel[0])
        files = self.store.get_files_for_capture(cid)
        for f in files:
            is_target = f["is_target_zero"] == 1
            self.tree_review_files.insert(
                "",
                tk.END,
                values=(
                    f["status"] if is_target else "IGNORADO (Con datos)",
                    f["original_filename"],
                    f["proposed_filename"],
                    f["inscripcion_bis_tail"] if is_target else "No se toca",
                ),
                tags=("TARGET" if is_target else "IGNORED",),
            )

    def edit_selected_capture(self) -> None:
        cid = self._get_selected_capture_id()
        if cid is None:
            return
        cap = self.store.get_capture_by_id(cid)
        if not cap:
            return
        if cap["status"] == "APLICADO":
            messagebox.showwarning(
                "Ya Aplicado",
                "Esta carpeta ya fue renombrada físicamente. Si necesitas cambiar su captura, primero ejecuta 'Rollback'.",
            )
            return

        self.var_folder_path.set(cap["original_folder_path"])
        self.load_directory(cap["original_folder_path"])
        self.notebook.select(self.tab_capture)

    def approve_selected_capture(self) -> None:
        cid = self._get_selected_capture_id()
        if cid is None:
            return
        cap = self.store.get_capture_by_id(cid)
        if not cap:
            return
        if cap["status"] == "APLICADO":
            messagebox.showinfo("Info", "Esta captura ya está aplicada.")
            return
        new_status = (
            "APROBADO" if cap["status"] != "APROBADO" else "PENDIENTE_REVISION"
        )
        self.store.set_approval_status(cid, new_status)
        self._refresh_review_table()

    def delete_selected_capture(self) -> None:
        cid = self._get_selected_capture_id()
        if cid is None:
            return
        cap = self.store.get_capture_by_id(cid)
        if not cap:
            return
        if cap["status"] == "APLICADO":
            messagebox.showerror(
                "No permitido",
                "No puedes borrar el registro de una carpeta que ya fue APLICADA porque perderías su historial de Rollback.",
            )
            return
        if messagebox.askyesno(
            "Confirmar Eliminación Local",
            f"¿Eliminar la captura local de:\n{cap['original_folder_name']}?\n\n(No afecta ningún archivo físico).",
        ):
            self.store.delete_capture(cid)
            self._refresh_review_table()

    def apply_selected_capture(self) -> None:
        cid = self._get_selected_capture_id()
        if cid is None:
            return
        cap = self.store.get_capture_by_id(cid)
        if not cap:
            return
        if cap["status"] == "APLICADO":
            messagebox.showinfo("Ya aplicado", "Esta captura ya fue aplicada.")
            return

        confirm = messagebox.askyesno(
            "Confirmar Aplicación Física de Cambios",
            f"¿Estás seguro de aplicar físicamente el renombrado en red?\n\n"
            f"Carpeta Actual:\n  {cap['original_folder_name']}\n"
            f"Carpeta Nueva:\n  {cap['proposed_folder_name']}\n\n"
            f"• Se renombrarán: {cap['total_pdfs_rename']} archivos PDF en ceros.\n"
            f"• Se ignorarán intactos: {cap['total_pdfs_ignored']} archivos PDF.\n\n"
            "El historial quedará resguardado para hacer Rollback en cualquier momento.",
        )
        if not confirm:
            return

        # Cerrar visor por si tenía abierto un PDF de esa carpeta
        self.pdf_viewer.close_pdf()

        ok, msg = self.store.apply_capture_changes(cid)
        self._refresh_review_table()
        if ok:
            messagebox.showinfo("Cambios Aplicados Correctamente", msg)
        else:
            messagebox.showerror("Error al Aplicar Cambios", msg)

    def apply_all_approved_captures(self) -> None:
        captures = [
            c for c in self.store.get_all_captures() if c["status"] == "APROBADO"
        ]
        if not captures:
            messagebox.showinfo(
                "Sin capturas aprobadas",
                "No hay capturas con estado 'APROBADO'. Marca primero las capturas revisadas con el botón '✅ Marcar como APROBADO'.",
            )
            return

        confirm = messagebox.askyesno(
            "Aplicar Lote de Capturas Aprobadas",
            f"Se aplicarán los cambios físicos a {len(captures)} directorios con estado APROBADO.\n\n¿Deseas continuar?",
        )
        if not confirm:
            return

        self.pdf_viewer.close_pdf()
        success_count = 0
        errors: List[str] = []

        for c in captures:
            ok, msg = self.store.apply_capture_changes(c["id"])
            if ok:
                success_count += 1
            else:
                errors.append(f"• {c['original_folder_name']}: {msg}")

        self._refresh_review_table()
        summary = f"Directorios aplicados con éxito: {success_count} de {len(captures)}."
        if errors:
            summary += "\n\nErrores encontrados:\n" + "\n".join(errors[:10])
            messagebox.showwarning("Resultado de Ejecución por Lote", summary)
        else:
            messagebox.showinfo("Lote Aplicado con Éxito", summary)

    def rollback_selected_capture(self) -> None:
        cid = self._get_selected_capture_id()
        if cid is None:
            return
        cap = self.store.get_capture_by_id(cid)
        if not cap:
            return
        if cap["status"] != "APLICADO":
            messagebox.showwarning(
                "Rollback no requerido",
                f"El directorio tiene estado '{cap['status']}' (aún no ha sido aplicado físicamente).",
            )
            return

        confirm = messagebox.askyesno(
            "Confirmar ROLLBACK (Reversión Total)",
            f"¿Deseas revertir la carpeta y sus {cap['total_pdfs_rename']} PDFs a sus nombres originales?\n\n"
            f"De (Actual):\n  {cap['proposed_folder_name']}\n"
            f"A (Original):\n  {cap['original_folder_name']}",
        )
        if not confirm:
            return

        self.pdf_viewer.close_pdf()
        ok, msg = self.store.rollback_capture_changes(cid)
        self._refresh_review_table()
        if ok:
            messagebox.showinfo("Rollback Exitoso", msg)
        else:
            messagebox.showerror("Error en Rollback", msg)

    def export_csv_dialog(self) -> None:
        out = filedialog.asksaveasfilename(
            parent=self,
            title="Exportar Reporte CSV de Capturas",
            defaultextension=".csv",
            initialfile="reporte_capturas_ceros.csv",
            filetypes=[("Archivo CSV (Excel)", "*.csv")],
        )
        if out:
            path = self.store.export_csv_report(out)
            messagebox.showinfo("Exportación Exitosa", f"Reporte CSV guardado en:\n{path}")

    def export_json_dialog(self) -> None:
        out = filedialog.asksaveasfilename(
            parent=self,
            title="Exportar Respaldo JSON de Capturas",
            defaultextension=".json",
            initialfile="respaldo_capturas_ceros.json",
            filetypes=[("Archivo JSON", "*.json")],
        )
        if out:
            path = self.store.export_backup_json(out)
            messagebox.showinfo("Exportación Exitosa", f"Respaldo JSON guardado en:\n{path}")


def main() -> None:
    app = CapturaCerosApp()
    app.mainloop()


if __name__ == "__main__":
    main()
