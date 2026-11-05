"""
Aplicación de Escritorio Portable: Captura Local, Modo Administrador (PIN + MySQL),
Revisión y Rollback de Directorios/PDFs en Ceros.
Ubicación: C:\laragon\www\CAPTURA_CEROS
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Dict, List, Optional

from src.cover_inserter import get_pdf_page_count, prepend_cover_pages_to_pdfs
from src.naming_engine import (
    FolderAnalysis,
    build_proposals,
    format_numeric_field,
    format_optional_alphanumeric_field,
    scan_directory,
)
from src.pdf_viewer import EmbeddedPdfViewer
from src.storage import LocalCaptureStore, get_app_base_dir

DEFAULT_NETWORK_ROOT = (
    r"\\172.40.5.84\ssdirec\REVISANDO\ENTREGA 1\4 ENTREGA SELLOS LIBROS\SELLOS LIBROS\Tuxtla Gutiérrez"
)
PHYSICAL_CHANGES_PIN = "1944123321"


def bootstrap_portable_environment() -> None:
    """
    Se ejecuta antes de abrir la interfaz para garantizar que la carpeta portable
    tenga su estructura local (`data/`), permisos de escritura y dependencias listas.
    """
    base_dir = get_app_base_dir()
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    # Verificar permisos de escritura creando un archivo testigo temporal
    probe_file = os.path.join(data_dir, ".write_probe")
    try:
        with open(probe_file, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe_file)
    except Exception as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Permisos de Escritura Requeridos",
            f"La carpeta donde se encuentra la aplicación no tiene permisos de escritura:\n{base_dir}\n\n"
            f"Copia la carpeta CAPTURA_CEROS_PORTABLE al Escritorio o Documentos del equipo.\nDetalle: {exc}",
        )
        root.destroy()
        raise SystemExit(1)


class CapturaCerosApp(tk.Tk):
    """Ventana principal de la herramienta de captura local y Modo Administrador."""

    def __init__(self) -> None:
        super().__init__()
        self.title(
            "CAPTURA DE CEROS — Sellos Libros (Tuxtla Gutiérrez) | Captura Local y Modo Administrador"
        )
        self.geometry("1480x890")
        self.minsize(1220, 750)
        self.configure(bg="#F1F5F9")

        self.store = LocalCaptureStore()
        self.current_analysis: Optional[FolderAnalysis] = None
        self.is_admin_mode: bool = False

        # Estado de la Pestaña 2 (Inserción de Carátula PDF)
        self.cover_folder_path: str = ""
        self.selected_cover_pdf_path: Optional[str] = None
        self.selected_cover_total_pages: int = 0
        self.last_cover_tree_anchor_idx: Optional[int] = None
        self.cover_task_running: bool = False
        self.cover_cancel_requested: bool = False
        self.cover_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()

        self._configure_styles()
        self._build_layout()
        self._update_admin_ui_state()
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
        style.configure(
            "TLabelframe", background="#F1F5F9", font=("Segoe UI", 9, "bold")
        )
        style.configure(
            "TLabelframe.Label",
            background="#F1F5F9",
            foreground="#0F172A",
            font=("Segoe UI", 9, "bold"),
        )
        style.configure("Treeview", rowheight=25, font=("Consolas", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _build_layout(self) -> None:
        # Encabezado superior con botón de Modo Administrador
        header = tk.Frame(self, bg="#0F172A", padx=16, pady=10)
        header.pack(fill=tk.X, side=tk.TOP)

        title_box = tk.Frame(header, bg="#0F172A")
        title_box.pack(side=tk.LEFT)
        ttk.Label(
            title_box,
            text="HERRAMIENTA DE CAPTURA LOCAL Y AUDITORÍA — CARPETAS Y PDFs EN CEROS",
            style="Header.TLabel",
        ).pack(anchor=tk.W)
        ttk.Label(
            title_box,
            text="Las capturas son 100% locales con UUID único. La aplicación de cambios físicos y registro en MySQL requiere Modo Administrador.",
            style="SubHeader.TLabel",
        ).pack(anchor=tk.W)

        right_header = tk.Frame(header, bg="#0F172A")
        right_header.pack(side=tk.RIGHT)

        self.btn_admin_toggle = tk.Button(
            right_header,
            text="🔒 Activar Modo Administrador",
            bg="#334155",
            fg="#F8FAFC",
            activebackground="#475569",
            activeforeground="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=5,
            cursor="hand2",
            command=self.toggle_admin_mode,
        )
        self.btn_admin_toggle.pack(side=tk.RIGHT, padx=(10, 0))

        self.lbl_role_badge = tk.Label(
            right_header,
            text="MODO: CAPTURISTA (100% Local)",
            bg="#1E293B",
            fg="#38BDF8",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=6,
        )
        self.lbl_role_badge.pack(side=tk.RIGHT, padx=(10, 0))

        self.lbl_global_stats = tk.Label(
            right_header,
            text="Capturas locales: 0",
            bg="#1E293B",
            fg="#E2E8F0",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=6,
        )
        self.lbl_global_stats.pack(side=tk.RIGHT)

        # Notebook con las 3 vistas principales
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        self.tab_capture = ttk.Frame(self.notebook, padding=8)
        self.tab_cover = ttk.Frame(self.notebook, padding=8)
        self.tab_review = ttk.Frame(self.notebook, padding=8)

        self.notebook.add(
            self.tab_capture, text="  1. Captura Local de Directorio + Visor PDF  "
        )
        self.notebook.add(
            self.tab_cover,
            text="  2. Insertar Carátula en PDFs (Solo Administrador)  ",
        )
        self.notebook.add(
            self.tab_review,
            text="  3. Revisión de Lotes JSON y Panel Administrador (MySQL / Cambios Físicos)  ",
        )

        self._build_capture_tab()
        self._build_cover_tab()
        self._build_review_tab()

    # =========================================================================
    # PESTAÑA 1: CAPTURA DE DIRECTORIO Y VISOR DE PDF INTEGRADO
    # =========================================================================
    def _build_capture_tab(self) -> None:
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
        self.entry_folder_path.pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
        )
        self.entry_folder_path.bind(
            "<Return>", lambda _: self.load_directory_from_entry()
        )

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

        paned = ttk.PanedWindow(self.tab_capture, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left_pane = ttk.Frame(paned, padding=(0, 0, 6, 0))
        right_pane = ttk.LabelFrame(
            paned,
            text=" Visor de PDF Integrado (Scroll continuo de páginas) ",
            padding=4,
        )

        paned.add(left_pane, weight=5)
        paned.add(right_pane, weight=6)

        form_frame = ttk.LabelFrame(
            left_pane,
            text=" Campos de Captura (Orden: Delegación _ Sección _ Libro _ Tomo _ Volumen _ Fraccionamiento _ Año) ",
            padding=10,
        )
        form_frame.pack(fill=tk.X, side=tk.TOP, pady=(0, 8))

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
                grid_f,
                text=title_txt,
                font=("Segoe UI", 9, "bold"),
                foreground="#0F172A",
            ).grid(row=0, column=col_idx, sticky=tk.W, padx=4, pady=(0, 1))
            ttk.Label(
                grid_f, text=sub_txt, font=("Segoe UI", 7), foreground="#64748B"
            ).grid(row=1, column=col_idx, sticky=tk.W, padx=4, pady=(0, 4))

        # Validadores en vivo por pulsación de tecla (validate="key")
        vcmd_num2 = (self.register(self._validate_numeric_2digits), "%P")
        vcmd_num4 = (self.register(self._validate_numeric_4digits), "%P")
        vcmd_tomo = (self.register(self._validate_tomo_input), "%P")
        vcmd_frac = (self.register(self._validate_frac_input), "%P")

        self.ent_delegacion = ttk.Entry(
            grid_f,
            textvariable=self.var_delegacion,
            width=9,
            font=("Consolas", 11, "bold"),
            validate="key",
            validatecommand=vcmd_num2,
        )
        self.ent_delegacion.grid(row=2, column=0, sticky=tk.EW, padx=4)

        self.ent_seccion = ttk.Entry(
            grid_f,
            textvariable=self.var_seccion,
            width=9,
            font=("Consolas", 11, "bold"),
            validate="key",
            validatecommand=vcmd_num2,
        )
        self.ent_seccion.grid(row=2, column=1, sticky=tk.EW, padx=4)

        self.ent_libro = ttk.Entry(
            grid_f,
            textvariable=self.var_libro,
            width=9,
            font=("Consolas", 11, "bold"),
            validate="key",
            validatecommand=vcmd_num2,
        )
        self.ent_libro.grid(row=2, column=2, sticky=tk.EW, padx=4)

        self.ent_tomo = ttk.Entry(
            grid_f,
            textvariable=self.var_tomo,
            width=14,
            font=("Consolas", 11, "bold"),
            validate="key",
            validatecommand=vcmd_tomo,
        )
        self.ent_tomo.grid(row=2, column=3, sticky=tk.EW, padx=4)

        self.ent_volumen = ttk.Entry(
            grid_f,
            textvariable=self.var_volumen,
            width=9,
            font=("Consolas", 11, "bold"),
            validate="key",
            validatecommand=vcmd_num2,
        )
        self.ent_volumen.grid(row=2, column=4, sticky=tk.EW, padx=4)

        self.ent_fraccionamiento = ttk.Entry(
            grid_f,
            textvariable=self.var_fraccionamiento,
            width=18,
            font=("Consolas", 11, "bold"),
            validate="key",
            validatecommand=vcmd_frac,
        )
        self.ent_fraccionamiento.grid(row=2, column=5, sticky=tk.EW, padx=4)

        self.ent_anio = ttk.Entry(
            grid_f,
            textvariable=self.var_anio,
            width=9,
            font=("Consolas", 11, "bold"),
            validate="key",
            validatecommand=vcmd_num4,
        )
        self.ent_anio.grid(row=2, column=6, sticky=tk.EW, padx=4)

        self.ent_suffix = ttk.Entry(
            grid_f, textvariable=self.var_suffix, width=13, font=("Consolas", 10)
        )
        self.ent_suffix.grid(row=2, column=7, sticky=tk.EW, padx=4)

        self.ent_delegacion.bind(
            "<FocusOut>", lambda _: self._pad_var(self.var_delegacion, 2, False)
        )
        self.ent_seccion.bind(
            "<FocusOut>", lambda _: self._pad_var(self.var_seccion, 2, False)
        )
        self.ent_libro.bind(
            "<FocusOut>", lambda _: self._pad_var(self.var_libro, 2, False)
        )
        self.ent_tomo.bind(
            "<FocusOut>",
            lambda _: self._pad_var(
                self.var_tomo, 2, self.var_allow_alpha_tomo.get()
            ),
        )
        self.ent_volumen.bind(
            "<FocusOut>", lambda _: self._pad_var(self.var_volumen, 2, False)
        )
        self.ent_fraccionamiento.bind(
            "<FocusOut>",
            lambda _: self._pad_var(
                self.var_fraccionamiento, 2, self.var_allow_alpha_frac.get()
            ),
        )
        self.ent_anio.bind(
            "<FocusOut>", lambda _: self._pad_var(self.var_anio, 4, False)
        )

        chk_tomo = ttk.Checkbutton(
            grid_f,
            text="Alfanumérico opc.",
            variable=self.var_allow_alpha_tomo,
            command=self._on_toggle_alpha_tomo,
        )
        chk_tomo.grid(row=3, column=3, sticky=tk.W, padx=4, pady=(4, 0))

        chk_frac = ttk.Checkbutton(
            grid_f,
            text="Alfanumérico opc.",
            variable=self.var_allow_alpha_frac,
            command=self._on_toggle_alpha_frac,
        )
        chk_frac.grid(row=3, column=5, sticky=tk.W, padx=4, pady=(4, 0))

        self.lbl_anio_hint = ttk.Label(
            grid_f,
            text="Tomado de carpeta",
            font=("Segoe UI", 8, "italic"),
            foreground="#0284C7",
        )
        self.lbl_anio_hint.grid(row=3, column=6, sticky=tk.W, padx=4, pady=(4, 0))

        preview_box = tk.Frame(
            form_frame,
            bg="#F8FAFC",
            highlightbackground="#CBD5E1",
            highlightthickness=1,
            padx=10,
            pady=8,
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

        action_bar = ttk.Frame(form_frame)
        action_bar.pack(fill=tk.X, pady=(4, 0))

        ttk.Label(action_bar, text="Observaciones / Notas:").pack(
            side=tk.LEFT, padx=(0, 6)
        )
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
            text="💾 GUARDAR CAPTURA LOCALMENTE (Genera UUID)",
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

        self.tree_files.tag_configure(
            "RENOMBRAR", background="#F0FDF4", foreground="#14532D"
        )
        self.tree_files.tag_configure(
            "IGNORAR", background="#F8FAFC", foreground="#64748B"
        )

        vsb = ttk.Scrollbar(
            tree_container, orient=tk.VERTICAL, command=self.tree_files.yview
        )
        hsb = ttk.Scrollbar(
            tree_container, orient=tk.HORIZONTAL, command=self.tree_files.xview
        )
        self.tree_files.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree_files.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree_files.bind("<<TreeviewSelect>>", self._on_file_row_selected)

        self.pdf_viewer = EmbeddedPdfViewer(right_pane)
        self.pdf_viewer.pack(fill=tk.BOTH, expand=True)

    # =========================================================================
    # PESTAÑA 2: INSERTAR CARÁTULA EN PDFs (EXCLUSIVO MODO ADMINISTRADOR)
    # =========================================================================
    def _build_cover_tab(self) -> None:
        self.lbl_cover_locked_notice = tk.Label(
            self.tab_cover,
            text="🔒 Función exclusiva para Administrador. Haz clic en '🔒 Activar Modo Administrador' en la esquina superior derecha e ingresa el PIN (1944123321) para usar este módulo.",
            bg="#FEF2F2",
            fg="#991B1B",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=6,
        )
        self.lbl_cover_locked_notice.pack(fill=tk.X, side=tk.TOP, pady=(0, 8))

        # Barra superior para seleccionar la carpeta de trabajo
        self.cover_top_bar = ttk.LabelFrame(
            self.tab_cover,
            text=" 1. Selección de Carpeta con los PDFs y la Carátula ",
            padding=(10, 8),
        )
        self.cover_top_bar.pack(fill=tk.X, side=tk.TOP, pady=(0, 8))

        ttk.Label(self.cover_top_bar, text="Ruta de Carpeta:").pack(
            side=tk.LEFT, padx=(0, 6)
        )

        self.var_cover_folder_path = tk.StringVar(value="")
        self.ent_cover_folder = ttk.Entry(
            self.cover_top_bar,
            textvariable=self.var_cover_folder_path,
            font=("Consolas", 10),
        )
        self.ent_cover_folder.pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6)
        )
        self.ent_cover_folder.bind(
            "<Return>", lambda _: self.load_cover_folder_from_entry()
        )

        self.btn_cover_browse = ttk.Button(
            self.cover_top_bar,
            text="📂 Examinar Carpeta...",
            command=self.browse_cover_directory,
        )
        self.btn_cover_browse.pack(side=tk.LEFT, padx=3)

        self.btn_cover_quick = ttk.Button(
            self.cover_top_bar,
            text="⚡ Elegir de Tuxtla...",
            command=self.open_cover_quick_picker_dialog,
        )
        self.btn_cover_quick.pack(side=tk.LEFT, padx=3)

        self.btn_cover_reload = ttk.Button(
            self.cover_top_bar,
            text="🔄 Cargar PDFs",
            command=self.load_cover_folder_from_entry,
        )
        self.btn_cover_reload.pack(side=tk.LEFT, padx=3)

        # Panel dividido: Izquierda (Configuración de Carátula + Lista de PDFs con Shift+Clic) | Derecha (Visor PDF con pantalla de carga)
        cover_paned = ttk.PanedWindow(self.tab_cover, orient=tk.HORIZONTAL)
        cover_paned.pack(fill=tk.BOTH, expand=True)

        left_cover_pane = ttk.Frame(cover_paned, padding=(0, 0, 6, 0))
        right_cover_pane = ttk.LabelFrame(
            cover_paned,
            text=" Visor de PDF Integrado (Previsualización de Carátula y Documentos) ",
            padding=4,
        )

        cover_paned.add(left_cover_pane, weight=5)
        cover_paned.add(right_cover_pane, weight=6)

        # Sección de definición de Carátula y Rango de Páginas
        cfg_box = ttk.LabelFrame(
            left_cover_pane,
            text=" 2. Configuración del PDF Carátula y Páginas a Insertar al Inicio ",
            padding=10,
        )
        cfg_box.pack(fill=tk.X, side=tk.TOP, pady=(0, 8))

        row_cov_sel = ttk.Frame(cfg_box)
        row_cov_sel.pack(fill=tk.X, pady=(0, 8))

        self.btn_set_as_cover = ttk.Button(
            row_cov_sel,
            text="⭐ Usar PDF Seleccionado en la Tabla como CARÁTULA",
            command=self.set_selected_row_as_cover,
        )
        self.btn_set_as_cover.pack(side=tk.LEFT, padx=(0, 10))

        self.lbl_cover_selected = tk.Label(
            row_cov_sel,
            text="Carátula actual: (Ninguna seleccionada)",
            bg="#FEF9C3",
            fg="#854D0E",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=4,
        )
        self.lbl_cover_selected.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Opciones de páginas de la carátula (Por defecto: TODAS)
        pages_frame = ttk.Frame(cfg_box)
        pages_frame.pack(fill=tk.X, pady=(4, 4))

        ttk.Label(
            pages_frame,
            text="Páginas de la carátula a insertar al inicio de cada PDF:",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, columnspan=6, sticky=tk.W, pady=(0, 6))

        self.var_cover_page_mode = tk.StringVar(value="ALL")
        self.var_cover_single_page = tk.StringVar(value="1")
        self.var_cover_range_from = tk.StringVar(value="1")
        self.var_cover_range_to = tk.StringVar(value="1")

        self.rb_cov_all = ttk.Radiobutton(
            pages_frame,
            text="Todas las páginas de la carátula (Por defecto)",
            value="ALL",
            variable=self.var_cover_page_mode,
            command=self._update_cover_page_inputs_state,
        )
        self.rb_cov_all.grid(row=1, column=0, columnspan=6, sticky=tk.W, pady=2)

        self.rb_cov_single = ttk.Radiobutton(
            pages_frame,
            text="Solo una página en particular:",
            value="SINGLE",
            variable=self.var_cover_page_mode,
            command=self._update_cover_page_inputs_state,
        )
        self.rb_cov_single.grid(row=2, column=0, sticky=tk.W, pady=2)

        ttk.Label(pages_frame, text="Pág. #").grid(
            row=2, column=1, sticky=tk.E, padx=(6, 2)
        )
        self.ent_cov_single = ttk.Entry(
            pages_frame,
            textvariable=self.var_cover_single_page,
            width=6,
            font=("Consolas", 10, "bold"),
        )
        self.ent_cov_single.grid(row=2, column=2, sticky=tk.W, padx=(0, 12))

        self.rb_cov_range = ttk.Radiobutton(
            pages_frame,
            text="Rango de páginas:",
            value="RANGE",
            variable=self.var_cover_page_mode,
            command=self._update_cover_page_inputs_state,
        )
        self.rb_cov_range.grid(row=3, column=0, sticky=tk.W, pady=2)

        ttk.Label(pages_frame, text="Desde pág.").grid(
            row=3, column=1, sticky=tk.E, padx=(6, 2)
        )
        self.ent_cov_from = ttk.Entry(
            pages_frame,
            textvariable=self.var_cover_range_from,
            width=6,
            font=("Consolas", 10, "bold"),
        )
        self.ent_cov_from.grid(row=3, column=2, sticky=tk.W, padx=(0, 8))

        ttk.Label(pages_frame, text="Hasta pág.").grid(
            row=3, column=3, sticky=tk.E, padx=(4, 2)
        )
        self.ent_cov_to = ttk.Entry(
            pages_frame,
            textvariable=self.var_cover_range_to,
            width=6,
            font=("Consolas", 10, "bold"),
        )
        self.ent_cov_to.grid(row=3, column=4, sticky=tk.W)

        # Lista de PDFs de la carpeta con selección múltiple (Shift+Clic Izquierdo y Botón Seleccionar Todo excluyendo carátula)
        list_box = ttk.LabelFrame(
            left_cover_pane,
            text=" 3. Selección de PDFs Destino (Soporta Shift + Clic Izquierdo, Ctrl + Clic o Seleccionar Todo sin Carátula) ",
            padding=8,
        )
        list_box.pack(fill=tk.BOTH, expand=True)

        sel_toolbar = ttk.Frame(list_box)
        sel_toolbar.pack(fill=tk.X, pady=(0, 6))

        self.btn_cov_select_all = ttk.Button(
            sel_toolbar,
            text="☑️ Seleccionar Todo (Excluyendo Carátula)",
            command=self.cover_select_all_excluding_cover,
        )
        self.btn_cov_select_all.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_cov_clear_sel = ttk.Button(
            sel_toolbar,
            text="🔲 Deseleccionar Todo",
            command=self.cover_deselect_all,
        )
        self.btn_cov_clear_sel.pack(side=tk.LEFT, padx=3)

        self.lbl_cov_sel_count = ttk.Label(
            sel_toolbar,
            text="Seleccionados: 0 PDFs",
            font=("Segoe UI", 9, "bold"),
            foreground="#0F766E",
        )
        self.lbl_cov_sel_count.pack(side=tk.RIGHT)

        cov_tree_container = ttk.Frame(list_box)
        cov_tree_container.pack(fill=tk.BOTH, expand=True)

        cov_cols = ("rol", "filename", "pages_info")
        self.tree_cover_pdfs = ttk.Treeview(
            cov_tree_container,
            columns=cov_cols,
            show="headings",
            selectmode="extended",
        )
        self.tree_cover_pdfs.heading("rol", text="Rol / Estado")
        self.tree_cover_pdfs.heading("filename", text="Nombre del Archivo PDF")
        self.tree_cover_pdfs.heading("pages_info", text="Ubicación")

        self.tree_cover_pdfs.column("rol", width=155, anchor=tk.CENTER, stretch=False)
        self.tree_cover_pdfs.column("filename", width=330, anchor=tk.W)
        self.tree_cover_pdfs.column("pages_info", width=220, anchor=tk.W)

        self.tree_cover_pdfs.tag_configure(
            "IS_COVER", background="#FEF08A", foreground="#854D0E"
        )
        self.tree_cover_pdfs.tag_configure(
            "NORMAL_PDF", background="#FFFFFF", foreground="#0F172A"
        )

        c_vsb = ttk.Scrollbar(
            cov_tree_container, orient=tk.VERTICAL, command=self.tree_cover_pdfs.yview
        )
        c_hsb = ttk.Scrollbar(
            cov_tree_container,
            orient=tk.HORIZONTAL,
            command=self.tree_cover_pdfs.xview,
        )
        self.tree_cover_pdfs.configure(
            yscrollcommand=c_vsb.set, xscrollcommand=c_hsb.set
        )
        c_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        c_hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree_cover_pdfs.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Eventos para Shift + Clic Izquierdo, clic simple y actualización del visor
        self.tree_cover_pdfs.bind("<ButtonPress-1>", self._on_cover_tree_click)
        self.tree_cover_pdfs.bind(
            "<<TreeviewSelect>>", self._on_cover_tree_selection_changed
        )

        # Barra inferior de ejecución asíncrona de inserción de carátula
        exec_bar = ttk.Frame(left_cover_pane, padding=(0, 8, 0, 0))
        exec_bar.pack(fill=tk.X, side=tk.BOTTOM)

        prog_box = ttk.Frame(exec_bar)
        prog_box.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.cover_progressbar = ttk.Progressbar(
            prog_box, orient=tk.HORIZONTAL, mode="determinate"
        )
        self.cover_progressbar.pack(fill=tk.X, side=tk.TOP, pady=(0, 3))

        self.lbl_cover_progress = ttk.Label(
            prog_box,
            text="Listo para procesar.",
            font=("Segoe UI", 8, "italic"),
            foreground="#0369A1",
        )
        self.lbl_cover_progress.pack(anchor=tk.W, side=tk.TOP)

        self.btn_cancel_cover_insert = tk.Button(
            exec_bar,
            text="⏹ Cancelar",
            bg="#B91C1C",
            fg="#FFFFFF",
            activebackground="#991B1B",
            activeforeground="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=6,
            state=tk.DISABLED,
            command=self.cancel_cover_insertion,
        )
        self.btn_cancel_cover_insert.pack(side=tk.RIGHT, padx=(6, 0))

        self.btn_execute_cover_insert = tk.Button(
            exec_bar,
            text="📑 INSERTAR CARÁTULA EN PDFs SELECCIONADOS",
            bg="#15803D",
            fg="#FFFFFF",
            activebackground="#166534",
            activeforeground="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=6,
            cursor="hand2",
            command=self.execute_cover_insertion,
        )
        self.btn_execute_cover_insert.pack(side=tk.RIGHT)

        # Visor PDF integrado de la Pestaña 2
        self.cover_pdf_viewer = EmbeddedPdfViewer(right_cover_pane)
        self.cover_pdf_viewer.pack(fill=tk.BOTH, expand=True)

        self._update_cover_page_inputs_state()

    # =========================================================================
    # PESTAÑA 3: REVISIÓN Y PANEL DE MODO ADMINISTRADOR (MYSQL + EJECUCIÓN)
    # =========================================================================
    def _build_review_tab(self) -> None:
        # Barra de herramientas general (Disponible para Capturista y Administrador)
        top_controls = ttk.LabelFrame(
            self.tab_review,
            text=" Herramientas de Captura Local e Intercambio de Lotes JSON ",
            padding=8,
        )
        top_controls.pack(fill=tk.X, side=tk.TOP, pady=(0, 6))

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
            text="🗑️ Eliminar Captura Local",
            command=self.delete_selected_capture,
        ).pack(side=tk.LEFT, padx=3)

        ttk.Separator(btn_left, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8
        )

        ttk.Button(
            btn_left,
            text="📄 Exportar Respaldo JSON (Para entregar)",
            command=self.export_json_dialog,
        ).pack(side=tk.LEFT, padx=3)

        ttk.Button(
            btn_left,
            text="📥 Importar JSON (Recibir capturas)",
            command=self.import_json_dialog,
        ).pack(side=tk.LEFT, padx=3)

        ttk.Button(
            btn_left,
            text="📊 Exportar CSV (Excel)",
            command=self.export_csv_dialog,
        ).pack(side=tk.LEFT, padx=3)

        # Panel exclusivo de Modo Administrador (Aprobación, MySQL, Aplicación Física, Rollback)
        self.admin_panel = ttk.LabelFrame(
            self.tab_review,
            text=" 🛡️ PANEL EXCLUSIVO MODO ADMINISTRADOR — Base de Datos MySQL, Aplicación de Cambios Físicos (Hash SHA-256 + Páginas + UUID) y Rollback ",
            padding=8,
        )
        self.admin_panel.pack(fill=tk.X, side=tk.TOP, pady=(0, 8))

        self.lbl_admin_locked_notice = tk.Label(
            self.admin_panel,
            text="🔒 Panel bloqueado. Haz clic en '🔒 Activar Modo Administrador' en la esquina superior derecha e ingresa el PIN para habilitar la ejecución física y el registro en MySQL.",
            bg="#FEF2F2",
            fg="#991B1B",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=6,
        )
        self.lbl_admin_locked_notice.pack(fill=tk.X, pady=(0, 6))

        self.admin_controls_row = ttk.Frame(self.admin_panel)
        self.admin_controls_row.pack(fill=tk.X)

        self.btn_approve = ttk.Button(
            self.admin_controls_row,
            text="✅ Aprobar / Desaprobar Seleccionada",
            command=self.approve_selected_capture,
        )
        self.btn_approve.pack(side=tk.LEFT, padx=3)

        self.btn_mysql_cfg = ttk.Button(
            self.admin_controls_row,
            text="🗄️ Configurar BD MySQL (Cambios Físicos)...",
            command=self.open_mysql_config_dialog,
        )
        self.btn_mysql_cfg.pack(side=tk.LEFT, padx=6)

        self.lbl_status_progress = ttk.Label(
            self.admin_controls_row,
            text="",
            font=("Segoe UI", 9, "italic"),
            foreground="#0369A1",
        )
        self.lbl_status_progress.pack(side=tk.LEFT, padx=10)

        btn_right = ttk.Frame(self.admin_controls_row)
        btn_right.pack(side=tk.RIGHT)

        self.btn_apply_changes = tk.Button(
            btn_right,
            text="🚀 APLICAR CAMBIOS FÍSICOS A SELECCIONADA",
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
            text="⏪ ROLLBACK FÍSICO (Revertir a Original)",
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

        # Paneles divididos verticalmente: Tabla de Carpetas | Tabla de Archivos con UUID, Páginas y Hash
        v_paned = ttk.PanedWindow(self.tab_review, orient=tk.VERTICAL)
        v_paned.pack(fill=tk.BOTH, expand=True)

        folders_frame = ttk.LabelFrame(
            v_paned,
            text=" Directorios Capturados Localmente / Importados por JSON ",
            padding=6,
        )
        detail_frame = ttk.LabelFrame(
            v_paned,
            text=" Detalle de Archivos PDF (UUID, Nombre Original, Nombre Nuevo, Rutas, Páginas y Hash SHA-256) ",
            padding=6,
        )

        v_paned.add(folders_frame, weight=5)
        v_paned.add(detail_frame, weight=5)

        f_cols = (
            "id",
            "folder_uuid",
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
        self.tree_review_folders.heading("folder_uuid", text="UUID Directorio")
        self.tree_review_folders.heading("estado", text="Estado")
        self.tree_review_folders.heading("original_folder", text="Carpeta Original")
        self.tree_review_folders.heading("proposed_folder", text="Carpeta Propuesta")
        self.tree_review_folders.heading(
            "campos", text="Del|Sec|Lib|Tom|Vol|Frac|Año"
        )
        self.tree_review_folders.heading("pdfs_rename", text="PDFs Renombrar")
        self.tree_review_folders.heading("pdfs_ignored", text="Ignorados")
        self.tree_review_folders.heading("updated_at", text="Fecha Captura/Modif.")
        self.tree_review_folders.heading("notas", text="Notas")

        self.tree_review_folders.column("id", width=42, anchor=tk.CENTER, stretch=False)
        self.tree_review_folders.column(
            "folder_uuid", width=240, anchor=tk.W, stretch=False
        )
        self.tree_review_folders.column(
            "estado", width=145, anchor=tk.CENTER, stretch=False
        )
        self.tree_review_folders.column("original_folder", width=250, anchor=tk.W)
        self.tree_review_folders.column("proposed_folder", width=270, anchor=tk.W)
        self.tree_review_folders.column("campos", width=185, anchor=tk.CENTER)
        self.tree_review_folders.column(
            "pdfs_rename", width=105, anchor=tk.CENTER, stretch=False
        )
        self.tree_review_folders.column(
            "pdfs_ignored", width=80, anchor=tk.CENTER, stretch=False
        )
        self.tree_review_folders.column(
            "updated_at", width=135, anchor=tk.CENTER, stretch=False
        )
        self.tree_review_folders.column("notas", width=160, anchor=tk.W)

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
        self.tree_review_folders.configure(
            yscrollcommand=f_vsb.set, xscrollcommand=f_hsb.set
        )
        f_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        f_hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree_review_folders.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree_review_folders.bind(
            "<<TreeviewSelect>>", self._on_review_folder_selected
        )

        # Tabla inferior de detalle de PDFs con las columnas de auditoría física
        d_cols = (
            "file_uuid",
            "estado_pdf",
            "original_pdf",
            "proposed_pdf",
            "paginas",
            "hash_sha256",
            "fecha_aplicado",
            "ruta_original",
            "ruta_nueva",
        )
        self.tree_review_files = ttk.Treeview(
            detail_frame, columns=d_cols, show="headings", selectmode="browse"
        )
        self.tree_review_files.heading("file_uuid", text="UUID Archivo (Vínculo BD)")
        self.tree_review_files.heading("estado_pdf", text="Estado")
        self.tree_review_files.heading("original_pdf", text="Nombre Original")
        self.tree_review_files.heading("proposed_pdf", text="Nombre Nuevo")
        self.tree_review_files.heading("paginas", text="Páginas")
        self.tree_review_files.heading("hash_sha256", text="Hash SHA-256")
        self.tree_review_files.heading("fecha_aplicado", text="Fecha Aplicación")
        self.tree_review_files.heading("ruta_original", text="Ruta Original")
        self.tree_review_files.heading("ruta_nueva", text="Ruta Nueva")

        self.tree_review_files.column("file_uuid", width=240, anchor=tk.W)
        self.tree_review_files.column(
            "estado_pdf", width=110, anchor=tk.CENTER, stretch=False
        )
        self.tree_review_files.column("original_pdf", width=245, anchor=tk.W)
        self.tree_review_files.column("proposed_pdf", width=265, anchor=tk.W)
        self.tree_review_files.column(
            "paginas", width=70, anchor=tk.CENTER, stretch=False
        )
        self.tree_review_files.column("hash_sha256", width=240, anchor=tk.W)
        self.tree_review_files.column(
            "fecha_aplicado", width=135, anchor=tk.CENTER, stretch=False
        )
        self.tree_review_files.column("ruta_original", width=340, anchor=tk.W)
        self.tree_review_files.column("ruta_nueva", width=340, anchor=tk.W)

        self.tree_review_files.tag_configure(
            "TARGET", background="#F0FDF4", foreground="#14532D"
        )
        self.tree_review_files.tag_configure(
            "IGNORED", background="#F8FAFC", foreground="#64748B"
        )

        d_vsb = ttk.Scrollbar(
            detail_frame, orient=tk.VERTICAL, command=self.tree_review_files.yview
        )
        d_hsb = ttk.Scrollbar(
            detail_frame, orient=tk.HORIZONTAL, command=self.tree_review_files.xview
        )
        self.tree_review_files.configure(
            yscrollcommand=d_vsb.set, xscrollcommand=d_hsb.set
        )
        d_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        d_hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree_review_files.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # =========================================================================
    # MODO ADMINISTRADOR Y CONFIGURACIÓN MYSQL
    # =========================================================================
    def toggle_admin_mode(self) -> None:
        if self.is_admin_mode:
            self.is_admin_mode = False
            self._update_admin_ui_state()
            messagebox.showinfo(
                "Modo Administrador Cerrado",
                "Has vuelto al Modo Capturista (100% Local). Los controles de cambios físicos han sido bloqueados.",
            )
            return

        if self._request_security_pin("Desbloquear Modo Administrador"):
            self.is_admin_mode = True
            self._update_admin_ui_state()
            self.notebook.select(self.tab_review)

    def _update_admin_ui_state(self) -> None:
        if self.is_admin_mode:
            self.lbl_role_badge.config(
                text="🛡️ MODO: ADMINISTRADOR ACTIVO",
                bg="#14532D",
                fg="#4ADE80",
            )
            self.btn_admin_toggle.config(
                text="🔓 Cerrar Modo Administrador",
                bg="#B91C1C",
                fg="#FFFFFF",
            )
            # Pestaña 3
            self.lbl_admin_locked_notice.pack_forget()
            self.btn_approve.config(state=tk.NORMAL)
            self.btn_mysql_cfg.config(state=tk.NORMAL)
            self.btn_apply_changes.config(state=tk.NORMAL, bg="#15803D")
            self.btn_apply_all_approved.config(state=tk.NORMAL, bg="#0F766E")
            self.btn_rollback.config(state=tk.NORMAL, bg="#B91C1C")

            # Pestaña 2 (Insertar Carátula)
            self.lbl_cover_locked_notice.pack_forget()
            self.ent_cover_folder.config(state=tk.NORMAL)
            self.btn_cover_browse.config(state=tk.NORMAL)
            self.btn_cover_quick.config(state=tk.NORMAL)
            self.btn_cover_reload.config(state=tk.NORMAL)
            self.btn_set_as_cover.config(state=tk.NORMAL)
            self.rb_cov_all.config(state=tk.NORMAL)
            self.rb_cov_single.config(state=tk.NORMAL)
            self.rb_cov_range.config(state=tk.NORMAL)
            self._update_cover_page_inputs_state()
            self.btn_cov_select_all.config(state=tk.NORMAL)
            self.btn_cov_clear_sel.config(state=tk.NORMAL)
            self.btn_execute_cover_insert.config(state=tk.NORMAL, bg="#15803D")
        else:
            self.lbl_role_badge.config(
                text="MODO: CAPTURISTA (100% Local)",
                bg="#1E293B",
                fg="#38BDF8",
            )
            self.btn_admin_toggle.config(
                text="🔒 Activar Modo Administrador",
                bg="#334155",
                fg="#F8FAFC",
            )
            # Pestaña 3
            self.lbl_admin_locked_notice.pack(
                fill=tk.X, pady=(0, 6), before=self.admin_controls_row
            )
            self.btn_approve.config(state=tk.DISABLED)
            self.btn_mysql_cfg.config(state=tk.DISABLED)
            self.btn_apply_changes.config(state=tk.DISABLED, bg="#94A3B8")
            self.btn_apply_all_approved.config(state=tk.DISABLED, bg="#94A3B8")
            self.btn_rollback.config(state=tk.DISABLED, bg="#94A3B8")

            # Pestaña 2 (Insertar Carátula)
            self.lbl_cover_locked_notice.pack(
                fill=tk.X, side=tk.TOP, pady=(0, 8), before=self.cover_top_bar
            )
            self.ent_cover_folder.config(state=tk.DISABLED)
            self.btn_cover_browse.config(state=tk.DISABLED)
            self.btn_cover_quick.config(state=tk.DISABLED)
            self.btn_cover_reload.config(state=tk.DISABLED)
            self.btn_set_as_cover.config(state=tk.DISABLED)
            self.rb_cov_all.config(state=tk.DISABLED)
            self.rb_cov_single.config(state=tk.DISABLED)
            self.rb_cov_range.config(state=tk.DISABLED)
            self.ent_cov_single.config(state=tk.DISABLED)
            self.ent_cov_from.config(state=tk.DISABLED)
            self.ent_cov_to.config(state=tk.DISABLED)
            self.btn_cov_select_all.config(state=tk.DISABLED)
            self.btn_cov_clear_sel.config(state=tk.DISABLED)
            self.btn_execute_cover_insert.config(state=tk.DISABLED, bg="#94A3B8")
            self.btn_cancel_cover_insert.config(state=tk.DISABLED)

    # =========================================================================
    # LÓGICA DE PESTAÑA 2: INSERTAR CARÁTULA EN PDFs (SOLO ADMINISTRADOR)
    # =========================================================================
    def _update_cover_page_inputs_state(self) -> None:
        if not self.is_admin_mode:
            self.ent_cov_single.config(state=tk.DISABLED)
            self.ent_cov_from.config(state=tk.DISABLED)
            self.ent_cov_to.config(state=tk.DISABLED)
            return

        mode = self.var_cover_page_mode.get()
        self.ent_cov_single.config(
            state=tk.NORMAL if mode == "SINGLE" else tk.DISABLED
        )
        self.ent_cov_from.config(
            state=tk.NORMAL if mode == "RANGE" else tk.DISABLED
        )
        self.ent_cov_to.config(
            state=tk.NORMAL if mode == "RANGE" else tk.DISABLED
        )

    def browse_cover_directory(self) -> None:
        if not self.is_admin_mode:
            return
        initial = (
            DEFAULT_NETWORK_ROOT if os.path.isdir(DEFAULT_NETWORK_ROOT) else "C:\\"
        )
        chosen = filedialog.askdirectory(
            parent=self,
            title="Seleccionar Carpeta con PDFs y Carátula",
            initialdir=initial,
        )
        if chosen:
            norm = os.path.normpath(chosen)
            self.var_cover_folder_path.set(norm)
            self.load_cover_folder(norm)

    def open_cover_quick_picker_dialog(self) -> None:
        if not self.is_admin_mode:
            return
        root_dir = DEFAULT_NETWORK_ROOT
        if not os.path.isdir(root_dir):
            messagebox.showwarning(
                "Ruta de red no disponible",
                f"No se pudo acceder a:\n{root_dir}",
            )
            return

        dlg = tk.Toplevel(self)
        dlg.title("Seleccionar Directorio de Tuxtla Gutiérrez — Insertar Carátula")
        dlg.geometry("760x500")
        dlg.transient(self)
        dlg.grab_set()

        top = ttk.Frame(dlg, padding=10)
        top.pack(fill=tk.X)
        ttk.Label(
            top,
            text="Selecciona el directorio (Doble clic para cargar sus PDFs):",
            font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.LEFT)

        tree_f = ttk.Frame(dlg, padding=(10, 0, 10, 10))
        tree_f.pack(fill=tk.BOTH, expand=True)

        tv = ttk.Treeview(
            tree_f, columns=("carpeta",), show="headings", selectmode="browse"
        )
        tv.heading("carpeta", text="Directorio en Tuxtla Gutiérrez")
        tv.column("carpeta", width=680, anchor=tk.W)

        vsb = ttk.Scrollbar(tree_f, orient=tk.VERTICAL, command=tv.yview)
        tv.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        tv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for d_name in sorted(os.listdir(root_dir)):
            full_p = os.path.join(root_dir, d_name)
            if os.path.isdir(full_p):
                tv.insert("", tk.END, values=(d_name,))

        def on_choose(_event: Optional[tk.Event] = None) -> None:
            sel = tv.selection()
            if not sel:
                return
            folder_name = tv.item(sel[0], "values")[0]
            chosen_path = os.path.normpath(os.path.join(root_dir, folder_name))
            dlg.destroy()
            self.var_cover_folder_path.set(chosen_path)
            self.load_cover_folder(chosen_path)

        tv.bind("<Double-1>", on_choose)

        bottom = ttk.Frame(dlg, padding=10)
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="Cargar Directorio", command=on_choose).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(bottom, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT)

    def load_cover_folder_from_entry(self) -> None:
        if not self.is_admin_mode:
            return
        path = self.var_cover_folder_path.get().strip()
        if not path:
            messagebox.showwarning("Ruta vacía", "Ingresa o selecciona un directorio.")
            return
        self.load_cover_folder(path)

    def load_cover_folder(self, folder_path: str) -> None:
        norm_path = os.path.normpath(folder_path)
        if not os.path.isdir(norm_path):
            messagebox.showerror(
                "Directorio inválido", f"No existe el directorio:\n{norm_path}"
            )
            return

        self.cover_folder_path = norm_path
        self.selected_cover_pdf_path = None
        self.selected_cover_total_pages = 0
        self.last_cover_tree_anchor_idx = None
        self.var_cover_page_mode.set("ALL")
        self.var_cover_single_page.set("1")
        self.var_cover_range_from.set("1")
        self.var_cover_range_to.set("1")
        self._update_cover_page_inputs_state()

        self.lbl_cover_selected.config(
            text="Carátula actual: (Ninguna seleccionada)",
            bg="#FEF9C3",
            fg="#854D0E",
        )

        self._refresh_cover_pdfs_tree()

    def _refresh_cover_pdfs_tree(self) -> None:
        self.tree_cover_pdfs.delete(*self.tree_cover_pdfs.get_children())
        if not self.cover_folder_path or not os.path.isdir(self.cover_folder_path):
            return

        entries = sorted(
            f
            for f in os.listdir(self.cover_folder_path)
            if f.lower().endswith(".pdf")
            and os.path.isfile(os.path.join(self.cover_folder_path, f))
        )

        norm_cover = (
            os.path.normcase(os.path.normpath(self.selected_cover_pdf_path))
            if self.selected_cover_pdf_path
            else ""
        )

        for fname in entries:
            full_p = os.path.normpath(os.path.join(self.cover_folder_path, fname))
            is_cov = os.path.normcase(full_p) == norm_cover
            rol_txt = (
                f"⭐ CARÁTULA ({self.selected_cover_total_pages} págs.)"
                if is_cov
                else "📄 PDF Destino"
            )
            self.tree_cover_pdfs.insert(
                "",
                tk.END,
                iid=full_p,
                values=(rol_txt, fname, os.path.basename(self.cover_folder_path)),
                tags=("IS_COVER" if is_cov else "NORMAL_PDF",),
            )

        self._update_cover_selection_counter()

    def _on_cover_tree_click(self, event: tk.Event) -> Optional[str]:
        """
        Implementa selección por rango con Shift + Clic Izquierdo excluyendo automáticamente
        la fila marcada como Carátula.
        """
        row_id = self.tree_cover_pdfs.identify_row(event.y)
        if not row_id:
            return None

        all_items = list(self.tree_cover_pdfs.get_children())
        if row_id not in all_items:
            return None

        clicked_idx = all_items.index(row_id)
        shift_pressed = bool(event.state & 0x0001)

        if shift_pressed and self.last_cover_tree_anchor_idx is not None:
            start_i = min(self.last_cover_tree_anchor_idx, clicked_idx)
            end_i = max(self.last_cover_tree_anchor_idx, clicked_idx)
            norm_cover = (
                os.path.normcase(os.path.normpath(self.selected_cover_pdf_path))
                if self.selected_cover_pdf_path
                else ""
            )
            range_items = [
                item_id
                for item_id in all_items[start_i : end_i + 1]
                if os.path.normcase(os.path.normpath(item_id)) != norm_cover
            ]
            self.tree_cover_pdfs.selection_set(range_items)
            self.tree_cover_pdfs.focus(row_id)
            self.cover_pdf_viewer.load_pdf(row_id)
            self._update_cover_selection_counter()
            return "break"

        self.last_cover_tree_anchor_idx = clicked_idx
        return None

    def _on_cover_tree_selection_changed(
        self, _event: Optional[tk.Event] = None
    ) -> None:
        sel = self.tree_cover_pdfs.selection()
        self._update_cover_selection_counter()
        if not sel:
            return
        focused = self.tree_cover_pdfs.focus()
        target_to_preview = focused if focused in sel else sel[-1]
        if (
            target_to_preview
            and os.path.isfile(target_to_preview)
            and target_to_preview != self.cover_pdf_viewer.current_pdf_path
        ):
            self.cover_pdf_viewer.load_pdf(target_to_preview)

    def _update_cover_selection_counter(self) -> None:
        sel = list(self.tree_cover_pdfs.selection())
        norm_cover = (
            os.path.normcase(os.path.normpath(self.selected_cover_pdf_path))
            if self.selected_cover_pdf_path
            else ""
        )
        valid_targets = [
            p
            for p in sel
            if os.path.normcase(os.path.normpath(p)) != norm_cover
        ]
        self.lbl_cov_sel_count.config(
            text=f"PDFs destino seleccionados: {len(valid_targets)}"
        )

    def set_selected_row_as_cover(self) -> None:
        if not self.is_admin_mode:
            return
        sel = self.tree_cover_pdfs.selection()
        if not sel:
            messagebox.showwarning(
                "Sin selección",
                "Selecciona primero un archivo PDF de la lista para definirlo como Carátula.",
            )
            return

        chosen_pdf = sel[0]
        if not os.path.isfile(chosen_pdf):
            return

        try:
            pages_cnt = get_pdf_page_count(chosen_pdf)
        except Exception as exc:
            messagebox.showerror(
                "Error al leer Carátula",
                f"No se pudo abrir el PDF seleccionado:\n{exc}",
            )
            return

        self.selected_cover_pdf_path = chosen_pdf
        self.selected_cover_total_pages = pages_cnt
        self.var_cover_page_mode.set("ALL")
        self.var_cover_single_page.set("1")
        self.var_cover_range_from.set("1")
        self.var_cover_range_to.set(str(max(1, pages_cnt)))
        self._update_cover_page_inputs_state()

        fname = os.path.basename(chosen_pdf)
        self.lbl_cover_selected.config(
            text=f"⭐ Carátula activa: {fname} ({pages_cnt} páginas)",
            bg="#DCFCE7",
            fg="#166534",
        )

        self._refresh_cover_pdfs_tree()
        self.cover_pdf_viewer.load_pdf(chosen_pdf)

    def cover_select_all_excluding_cover(self) -> None:
        if not self.is_admin_mode:
            return
        all_items = list(self.tree_cover_pdfs.get_children())
        if not all_items:
            return

        norm_cover = (
            os.path.normcase(os.path.normpath(self.selected_cover_pdf_path))
            if self.selected_cover_pdf_path
            else ""
        )
        targets = [
            item_id
            for item_id in all_items
            if os.path.normcase(os.path.normpath(item_id)) != norm_cover
        ]
        self.tree_cover_pdfs.selection_set(targets)
        self._update_cover_selection_counter()

    def cover_deselect_all(self) -> None:
        self.tree_cover_pdfs.selection_remove(*self.tree_cover_pdfs.selection())
        self._update_cover_selection_counter()

    def cancel_cover_insertion(self) -> None:
        if self.cover_task_running:
            self.cover_cancel_requested = True
            self.lbl_cover_progress.config(
                text="⏳ Cancelando al terminar el archivo actual...",
                foreground="#B91C1C",
            )
            self.btn_cancel_cover_insert.config(state=tk.DISABLED)

    def _set_cover_controls_busy(self, busy: bool) -> None:
        state_val = tk.DISABLED if busy else tk.NORMAL
        self.ent_cover_folder.config(state=state_val)
        self.btn_cover_browse.config(state=state_val)
        self.btn_cover_quick.config(state=state_val)
        self.btn_cover_reload.config(state=state_val)
        self.btn_set_as_cover.config(state=state_val)
        self.rb_cov_all.config(state=state_val)
        self.rb_cov_single.config(state=state_val)
        self.rb_cov_range.config(state=state_val)
        self.btn_cov_select_all.config(state=state_val)
        self.btn_cov_clear_sel.config(state=state_val)
        if busy:
            self.ent_cov_single.config(state=tk.DISABLED)
            self.ent_cov_from.config(state=tk.DISABLED)
            self.ent_cov_to.config(state=tk.DISABLED)
            self.btn_execute_cover_insert.config(state=tk.DISABLED, bg="#94A3B8")
            self.btn_cancel_cover_insert.config(state=tk.NORMAL)
        else:
            self._update_cover_page_inputs_state()
            self.btn_execute_cover_insert.config(state=tk.NORMAL, bg="#15803D")
            self.btn_cancel_cover_insert.config(state=tk.DISABLED)

    def execute_cover_insertion(self) -> None:
        if not self.is_admin_mode:
            messagebox.showwarning(
                "Modo Administrador Requerido",
                "Activa primero el Modo Administrador con el PIN.",
            )
            return

        if self.cover_task_running:
            messagebox.showinfo(
                "Proceso en curso",
                "Ya se están insertando carátulas en segundo plano. Espera a que termine o presiona '⏹ Cancelar'.",
            )
            return

        if not self.selected_cover_pdf_path or not os.path.isfile(
            self.selected_cover_pdf_path
        ):
            messagebox.showwarning(
                "Carátula no definida",
                "Primero selecciona un PDF de la tabla y haz clic en '⭐ Usar PDF Seleccionado en la Tabla como CARÁTULA'.",
            )
            return

        norm_cover = os.path.normcase(
            os.path.normpath(self.selected_cover_pdf_path)
        )
        selected_targets = [
            p
            for p in self.tree_cover_pdfs.selection()
            if os.path.normcase(os.path.normpath(p)) != norm_cover
        ]

        if not selected_targets:
            messagebox.showwarning(
                "Sin PDFs destino seleccionados",
                "Selecciona uno o más archivos PDF destino (usando Shift+Clic o el botón '☑️ Seleccionar Todo (Excluyendo Carátula)').",
            )
            return

        mode = self.var_cover_page_mode.get()
        try:
            single_p = int(self.var_cover_single_page.get().strip() or "1")
            from_p = int(self.var_cover_range_from.get().strip() or "1")
            to_p = int(self.var_cover_range_to.get().strip() or "1")
        except ValueError:
            messagebox.showerror(
                "Número de página inválido",
                "Ingresa números enteros válidos para la selección de páginas.",
            )
            return

        if mode == "ALL":
            pages_desc = f"TODAS las páginas (1 a {self.selected_cover_total_pages})"
        elif mode == "SINGLE":
            pages_desc = f"SOLO la página {single_p}"
        else:
            pages_desc = f"RANGO de páginas {from_p} a {to_p}"

        confirm = messagebox.askyesno(
            "Confirmar Inserción Asíncrona de Carátula en PDFs",
            f"¿Deseas insertar las páginas de la carátula al inicio de los PDFs seleccionados?\n\n"
            f"• Archivo Carátula: {os.path.basename(self.selected_cover_pdf_path)}\n"
            f"• Páginas a insertar: {pages_desc}\n"
            f"• Total de PDFs destino: {len(selected_targets)} archivos (la carátula queda excluida).",
        )
        if not confirm:
            return

        # Cerrar el visor para liberar cualquier descriptor abierto
        self.cover_pdf_viewer.close_pdf()

        # Preparar estado asíncrono y bloquear botones de edición mientras corre el worker
        self.cover_task_running = True
        self.cover_cancel_requested = False
        self._set_cover_controls_busy(True)
        self.cover_progressbar["maximum"] = max(1, len(selected_targets))
        self.cover_progressbar["value"] = 0
        self.lbl_cover_progress.config(
            text=f"Iniciando lote de {len(selected_targets)} PDFs...",
            foreground="#0369A1",
        )

        # Vaciar cola previa
        while not self.cover_queue.empty():
            try:
                self.cover_queue.get_nowait()
            except queue.Empty:
                break

        cover_path_arg = self.selected_cover_pdf_path
        targets_arg = list(selected_targets)

        def worker_task() -> None:
            def on_prog(idx: int, total: int, msg: str) -> None:
                self.cover_queue.put(
                    {"type": "progress", "idx": idx, "total": total, "msg": msg}
                )

            def is_cancelled() -> bool:
                return self.cover_cancel_requested

            try:
                ok_count, err_list, inserted_pages = prepend_cover_pages_to_pdfs(
                    cover_pdf_path=cover_path_arg,
                    target_pdf_paths=targets_arg,
                    mode=mode,
                    single_page_1based=single_p,
                    range_from_1based=from_p,
                    range_to_1based=to_p,
                    progress_callback=on_prog,
                    cancel_check=is_cancelled,
                )
                self.cover_queue.put(
                    {
                        "type": "done",
                        "ok_count": ok_count,
                        "total_count": len(targets_arg),
                        "err_list": err_list,
                        "inserted_pages": inserted_pages,
                    }
                )
            except Exception as fatal_exc:
                self.cover_queue.put(
                    {"type": "fatal_error", "error": str(fatal_exc)}
                )

        threading.Thread(target=worker_task, daemon=True).start()
        self.after(60, self._poll_cover_worker_queue)

    def _poll_cover_worker_queue(self) -> None:
        try:
            while True:
                item = self.cover_queue.get_nowait()
                msg_type = item.get("type")

                if msg_type == "progress":
                    idx = item["idx"]
                    total = item["total"]
                    msg = item["msg"]
                    self.cover_progressbar["maximum"] = max(1, total)
                    self.cover_progressbar["value"] = idx
                    self.lbl_cover_progress.config(
                        text=f"[{idx}/{total}] {msg}", foreground="#0369A1"
                    )

                elif msg_type == "fatal_error":
                    self.cover_task_running = False
                    self._set_cover_controls_busy(False)
                    self.cover_progressbar["value"] = 0
                    self.lbl_cover_progress.config(
                        text="Error crítico al iniciar inserción.",
                        foreground="#B91C1C",
                    )
                    messagebox.showerror(
                        "Error al Insertar Carátula", item.get("error", "Error desconocido")
                    )
                    return

                elif msg_type == "done":
                    self.cover_task_running = False
                    self._set_cover_controls_busy(False)
                    ok_count = item["ok_count"]
                    total_count = item["total_count"]
                    err_list: List[str] = item["err_list"]
                    inserted_pages = item["inserted_pages"]

                    self.cover_progressbar["value"] = total_count
                    self.lbl_cover_progress.config(
                        text=f"Completado: {ok_count}/{total_count} exitosos ({len(err_list)} errores).",
                        foreground="#15803D" if not err_list else "#B91C1C",
                    )

                    if err_list:
                        self._show_cover_errors_dialog(
                            ok_count, total_count, inserted_pages, err_list
                        )
                    else:
                        messagebox.showinfo(
                            "Carátula Insertada con Éxito",
                            f"Proceso completado sin errores.\n\n"
                            f"• PDFs actualizados con éxito: {ok_count} de {total_count}\n"
                            f"• Páginas insertadas al inicio de cada PDF: {inserted_pages}",
                        )
                    return
        except queue.Empty:
            pass

        if self.cover_task_running:
            self.after(60, self._poll_cover_worker_queue)

    def _show_cover_errors_dialog(
        self,
        ok_count: int,
        total_count: int,
        inserted_pages: int,
        err_list: List[str],
    ) -> None:
        """Muestra una ventana detallada y desplazable con todos los errores ocurridos durante el lote."""
        dlg = tk.Toplevel(self)
        dlg.title("Reporte de Resultados y Errores — Inserción de Carátula")
        dlg.geometry("680x440")
        dlg.transient(self)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text=f"⚠️ Proceso finalizado con observaciones ({len(err_list)} incidencias)",
            font=("Segoe UI", 10, "bold"),
            foreground="#B91C1C",
        ).pack(anchor=tk.W, pady=(0, 4))

        ttk.Label(
            frame,
            text=(
                f"• Archivos actualizados correctamente: {ok_count} de {total_count}\n"
                f"• Páginas insertadas por archivo exitoso: {inserted_pages}\n"
                f"• Archivos con error o no modificados: {len(err_list)}"
            ),
            font=("Segoe UI", 9),
        ).pack(anchor=tk.W, pady=(0, 8))

        txt_area = scrolledtext.ScrolledText(
            frame, font=("Consolas", 9), wrap=tk.WORD, height=14
        )
        txt_area.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        txt_area.insert(tk.END, "\n".join(err_list))
        txt_area.config(state=tk.DISABLED)

        ttk.Button(frame, text="Cerrar", command=dlg.destroy).pack(side=tk.RIGHT)

    def open_mysql_config_dialog(self) -> None:
        if not self.is_admin_mode:
            return

        cfg = self.store.mysql_manager.load()
        dlg = tk.Toplevel(self)
        dlg.title("Configuración de Base de Datos MySQL — Registro de Cambios Físicos")
        dlg.geometry("500x380")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        f = ttk.Frame(dlg, padding=16)
        f.pack(fill=tk.BOTH, expand=True)

        var_enabled = tk.BooleanVar(value=bool(cfg.get("enabled", True)))
        var_host = tk.StringVar(value=str(cfg.get("host", "127.0.0.1")))
        var_port = tk.StringVar(value=str(cfg.get("port", 3306)))
        var_user = tk.StringVar(value=str(cfg.get("user", "root")))
        var_pass = tk.StringVar(value=str(cfg.get("password", "")))
        var_db = tk.StringVar(value=str(cfg.get("database", "captura_ceros_bd")))
        var_autocreate = tk.BooleanVar(value=bool(cfg.get("auto_create_tables", True)))

        ttk.Checkbutton(
            f,
            text="Registrar todos los movimientos físicos en Base de Datos MySQL",
            variable=var_enabled,
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))

        fields = [
            ("Servidor (Host):", var_host, None),
            ("Puerto:", var_port, None),
            ("Usuario MySQL:", var_user, None),
            ("Contraseña:", var_pass, "•"),
            ("Nombre de Base de Datos:", var_db, None),
        ]
        for idx, (label_txt, var, mask) in enumerate(fields, start=1):
            ttk.Label(f, text=label_txt, font=("Segoe UI", 9, "bold")).grid(
                row=idx, column=0, sticky=tk.W, pady=5, padx=(0, 10)
            )
            ent = ttk.Entry(f, textvariable=var, width=32, show=mask or "")
            ent.grid(row=idx, column=1, sticky=tk.EW, pady=5)

        ttk.Checkbutton(
            f,
            text="Crear base de datos y tablas automáticamente si no existen",
            variable=var_autocreate,
        ).grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=(8, 12))

        def build_cfg_dict() -> Dict[str, Any]:
            try:
                p_int = int(var_port.get().strip())
            except ValueError:
                p_int = 3306
            return {
                "enabled": var_enabled.get(),
                "host": var_host.get().strip() or "127.0.0.1",
                "port": p_int,
                "user": var_user.get().strip() or "root",
                "password": var_pass.get(),
                "database": var_db.get().strip() or "captura_ceros_bd",
                "auto_create_tables": var_autocreate.get(),
            }

        def on_test() -> None:
            self.store.mysql_manager.save(build_cfg_dict())
            ok, msg = self.store.mysql_manager.test_connection()
            if ok:
                messagebox.showinfo("Conexión MySQL Exitosa", msg, parent=dlg)
            else:
                messagebox.showerror("Fallo de Conexión MySQL", msg, parent=dlg)

        def on_save() -> None:
            self.store.mysql_manager.save(build_cfg_dict())
            messagebox.showinfo(
                "Configuración Guardada",
                "Los parámetros de MySQL se guardaron correctamente.",
                parent=dlg,
            )
            dlg.destroy()

        btn_bar = ttk.Frame(f)
        btn_bar.grid(row=7, column=0, columnspan=2, sticky=tk.EW, pady=(10, 0))
        ttk.Button(btn_bar, text="🔌 Probar Conexión y Crear Tablas", command=on_test).pack(
            side=tk.LEFT
        )
        ttk.Button(btn_bar, text="Guardar", command=on_save).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(btn_bar, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT)

    # =========================================================================
    # LÓGICA DE CAPTURA Y PREVISUALIZACIÓN
    # =========================================================================
    def _validate_numeric_2digits(self, proposed_text: str) -> bool:
        """Restringe el campo a solo números y máximo 2 dígitos."""
        if proposed_text == "":
            return True
        return proposed_text.isdigit() and len(proposed_text) <= 2

    def _validate_numeric_4digits(self, proposed_text: str) -> bool:
        """Restringe el campo Año a solo números y máximo 4 dígitos."""
        if proposed_text == "":
            return True
        return proposed_text.isdigit() and len(proposed_text) <= 4

    def _validate_tomo_input(self, proposed_text: str) -> bool:
        """
        Si 'Alfanumérico opc.' en Tomo NO está activado, impide escribir letras o más de 2 dígitos.
        """
        if proposed_text == "":
            return True
        if self.var_allow_alpha_tomo.get():
            return True
        return proposed_text.isdigit() and len(proposed_text) <= 2

    def _validate_frac_input(self, proposed_text: str) -> bool:
        """
        Si 'Alfanumérico opc.' en Fraccionamiento NO está activado, impide escribir letras o más de 2 dígitos.
        """
        if proposed_text == "":
            return True
        if self.var_allow_alpha_frac.get():
            return True
        return proposed_text.isdigit() and len(proposed_text) <= 2

    def _on_toggle_alpha_tomo(self) -> None:
        if not self.var_allow_alpha_tomo.get():
            digits = "".join(c for c in self.var_tomo.get() if c.isdigit())[:2]
            self.var_tomo.set(digits.zfill(2) if digits else "00")
        self._on_fields_changed()

    def _on_toggle_alpha_frac(self) -> None:
        if not self.var_allow_alpha_frac.get():
            digits = "".join(
                c for c in self.var_fraccionamiento.get() if c.isdigit()
            )[:2]
            self.var_fraccionamiento.set(digits.zfill(2) if digits else "00")
        self._on_fields_changed()

    def _pad_var(self, var: tk.StringVar, width: int, allow_alpha: bool) -> None:
        raw = var.get().strip()
        if not raw:
            var.set("0" * width)
            return
        if allow_alpha:
            var.set(format_optional_alphanumeric_field(raw, width))
        else:
            digits_only = "".join(ch for ch in raw if ch.isdigit())
            if not digits_only:
                var.set("0" * width)
            else:
                var.set(digits_only.zfill(width))

    def reset_fields_to_zero(self) -> None:
        self.var_allow_alpha_tomo.set(False)
        self.var_allow_alpha_frac.set(False)
        self.var_delegacion.set("01")
        self.var_seccion.set("00")
        self.var_libro.set("00")
        self.var_tomo.set("00")
        self.var_volumen.set("00")
        self.var_fraccionamiento.set("00")
        if self.current_analysis and not self.current_analysis.year_is_zero:
            self.var_anio.set(self.current_analysis.detected_year)
        self._on_fields_changed()

    def clear_capture_form_completely(self) -> None:
        """Limpia por completo el formulario, la tabla y el visor PDF tras guardar una captura."""
        self.current_analysis = None
        self.var_allow_alpha_tomo.set(False)
        self.var_allow_alpha_frac.set(False)
        self.var_folder_path.set("")
        self.var_delegacion.set("01")
        self.var_seccion.set("00")
        self.var_libro.set("00")
        self.var_tomo.set("00")
        self.var_volumen.set("00")
        self.var_fraccionamiento.set("00")
        self.var_anio.set("0000")
        self.var_suffix.set("REVISAR")
        self.var_notes.set("")

        self.ent_anio.config(state=tk.NORMAL)
        self.lbl_anio_hint.config(text="Tomado de carpeta", foreground="#0284C7")
        self.lbl_orig_folder.config(text="(Seleccione un directorio)")
        self.lbl_prop_folder.config(text="-")
        self.lbl_files_summary.config(
            text="En ceros a renombrar: 0   |   Con datos (Ignorados): 0"
        )
        self.tree_files.delete(*self.tree_files.get_children())
        self.pdf_viewer.close_pdf()

    def _request_security_pin(self, action_title: str) -> bool:
        """Solicita el PIN de seguridad (1944123321)."""
        dlg = tk.Toplevel(self)
        dlg.title("Autorización de Modo Administrador")
        dlg.geometry("420x210")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        dlg.configure(bg="#F8FAFC")

        authorized = {"ok": False}

        frame = ttk.Frame(dlg, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text=f"🔒 {action_title}",
            font=("Segoe UI", 10, "bold"),
            foreground="#0F172A",
        ).pack(anchor=tk.W, pady=(0, 6))

        ttk.Label(
            frame,
            text="Ingresa el PIN de Administrador para continuar:",
            font=("Segoe UI", 9),
        ).pack(anchor=tk.W, pady=(0, 8))

        pin_var = tk.StringVar(value="")
        ent_pin = ttk.Entry(
            frame,
            textvariable=pin_var,
            show="•",
            font=("Consolas", 13, "bold"),
            justify=tk.CENTER,
        )
        ent_pin.pack(fill=tk.X, pady=(0, 14))
        ent_pin.focus_set()

        def verify_and_close(_event: Optional[tk.Event] = None) -> None:
            if pin_var.get().strip() == PHYSICAL_CHANGES_PIN:
                authorized["ok"] = True
                dlg.destroy()
            else:
                messagebox.showerror(
                    "PIN Incorrecto",
                    "El PIN ingresado no es válido.",
                    parent=dlg,
                )
                pin_var.set("")
                ent_pin.focus_set()

        ent_pin.bind("<Return>", verify_and_close)

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X)
        ttk.Button(
            btn_row, text="Desbloquear", command=verify_and_close
        ).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btn_row, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT)

        self.wait_window(dlg)
        return authorized["ok"]

    def browse_directory(self) -> None:
        initial = (
            DEFAULT_NETWORK_ROOT if os.path.isdir(DEFAULT_NETWORK_ROOT) else "C:\\"
        )
        chosen = filedialog.askdirectory(
            parent=self,
            title="Seleccionar Directorio Individual a Capturar",
            initialdir=initial,
        )
        if chosen:
            self.var_folder_path.set(os.path.normpath(chosen))
            self.load_directory(chosen)

    def open_quick_picker_dialog(self) -> None:
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
        ttk.Button(
            bottom, text="Cargar Directorio Seleccionado", command=on_choose
        ).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bottom, text="Cancelar", command=dlg.destroy).pack(side=tk.RIGHT)

    def load_directory_from_entry(self) -> None:
        path = self.var_folder_path.get().strip()
        if not path:
            messagebox.showwarning(
                "Ruta vacía", "Ingresa o selecciona la ruta de un directorio."
            )
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

        saved = self.store.get_capture_by_path(analysis.folder_path)
        if saved:
            self.var_allow_alpha_tomo.set(
                not saved["tomo"].isdigit() or len(saved["tomo"]) > 2
            )
            self.var_allow_alpha_frac.set(
                not saved["fraccionamiento"].isdigit()
                or len(saved["fraccionamiento"]) > 2
            )
            self.var_delegacion.set(saved["delegacion"])
            self.var_seccion.set(saved["seccion"])
            self.var_libro.set(saved["libro"])
            self.var_tomo.set(saved["tomo"])
            self.var_volumen.set(saved["volumen"])
            self.var_fraccionamiento.set(saved["fraccionamiento"])
            self.var_anio.set(saved["anio"])
            self.var_suffix.set(saved["suffix"])
            self.var_notes.set(saved["notes"] or "")
        else:
            self.var_allow_alpha_tomo.set(False)
            self.var_allow_alpha_frac.set(False)
            self.var_delegacion.set(analysis.delegacion or "01")
            self.var_seccion.set("00")
            self.var_libro.set("00")
            self.var_tomo.set("00")
            self.var_volumen.set("00")
            self.var_fraccionamiento.set("00")
            self.var_anio.set(analysis.detected_year)
            self.var_suffix.set(analysis.detected_suffix)
            self.var_notes.set("")

        # El año siempre es editable: se auto-rellena con el de la carpeta, pero el capturista puede cambiarlo
        self.ent_anio.config(state=tk.NORMAL)
        if analysis.year_is_zero:
            self.lbl_anio_hint.config(
                text="Carpeta en 0000: Captura el año", foreground="#DC2626"
            )
        else:
            self.lbl_anio_hint.config(
                text=f"Auto-rellenado ({analysis.detected_year}) - Editable",
                foreground="#0284C7",
            )

        self._on_fields_changed()

        children = self.tree_files.get_children()
        if children:
            self.tree_files.selection_set(children[0])
            self.tree_files.focus(children[0])
            self._on_file_row_selected()
        else:
            self.pdf_viewer.close_pdf()

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

        self._pad_var(self.var_delegacion, 2, False)
        self._pad_var(self.var_seccion, 2, False)
        self._pad_var(self.var_libro, 2, False)
        self._pad_var(self.var_tomo, 2, self.var_allow_alpha_tomo.get())
        self._pad_var(self.var_volumen, 2, False)
        self._pad_var(
            self.var_fraccionamiento, 2, self.var_allow_alpha_frac.get()
        )
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

        saved_folder_name = self.current_analysis.folder_name
        saved_rename_count = len(self.current_analysis.pdfs_to_rename)
        saved_ignored_count = len(self.current_analysis.pdfs_ignored)
        saved_record = self.store.get_capture_by_id(capture_id)
        folder_uuid = saved_record.get("folder_uuid", "") if saved_record else ""

        self._refresh_review_table()
        # Limpiar formulario completamente para iniciar la siguiente captura desde cero
        self.clear_capture_form_completely()

        messagebox.showinfo(
            "Captura Guardada Localmente",
            f"Registro #{capture_id} guardado con éxito en la base de datos local.\n\n"
            f"• UUID Directorio: {folder_uuid}\n"
            f"• Carpeta Original: {saved_folder_name}\n"
            f"• Carpeta Propuesta: {prop_folder}\n"
            f"• PDFs a renombrar: {saved_rename_count}\n"
            f"• PDFs ignorados (intactos): {saved_ignored_count}\n\n"
            "El formulario ha sido limpiado para capturar el siguiente directorio.",
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
            tag = (
                c["status"]
                if c["status"]
                in (
                    "PENDIENTE_REVISION",
                    "APROBADO",
                    "APLICADO",
                    "REVERTIDO_ROLLBACK",
                )
                else "PENDIENTE_REVISION"
            )

            self.tree_review_folders.insert(
                "",
                tk.END,
                iid=str(c["id"]),
                values=(
                    c["id"],
                    c.get("folder_uuid", ""),
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
                    f.get("file_uuid", ""),
                    f["status"] if is_target else "IGNORADO",
                    f["original_filename"],
                    f["proposed_filename"],
                    f.get("pages", 0) if f.get("pages", 0) > 0 else "-",
                    f.get("file_hash", "") or "(Pendiente de aplicar)",
                    f.get("applied_at", "") or "-",
                    f.get("original_full_path", ""),
                    f.get("proposed_full_path", ""),
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
                "Esta carpeta ya fue renombrada físicamente. Si necesitas cambiar su captura, primero ejecuta 'Rollback' en Modo Administrador.",
            )
            return

        self.var_folder_path.set(cap["original_folder_path"])
        self.load_directory(cap["original_folder_path"])
        self.notebook.select(self.tab_capture)

    def approve_selected_capture(self) -> None:
        if not self.is_admin_mode:
            messagebox.showwarning(
                "Modo Administrador Requerido",
                "Primero activa el Modo Administrador con tu PIN.",
            )
            return
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

    def _update_progress_label(self, idx: int, total: int, message: str) -> None:
        self.lbl_status_progress.config(text=f"[{idx}/{total}] {message}")
        self.update_idletasks()

    def apply_selected_capture(self) -> None:
        if not self.is_admin_mode:
            messagebox.showwarning(
                "Modo Administrador Requerido",
                "Activa primero el Modo Administrador con el PIN.",
            )
            return

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
            "Confirmar Aplicación Física de Cambios y Registro MySQL",
            f"¿Estás seguro de aplicar físicamente el renombrado en red?\n\n"
            f"UUID Directorio:\n  {cap.get('folder_uuid', '')}\n"
            f"Carpeta Actual:\n  {cap['original_folder_name']}\n"
            f"Carpeta Nueva:\n  {cap['proposed_folder_name']}\n\n"
            f"• Se calculará Hash SHA-256 y conteo de páginas de {cap['total_pdfs_rename']} PDFs.\n"
            f"• Se registrarán los cambios en la BD MySQL vinculados por UUID.\n"
            f"• Se ignorarán intactos: {cap['total_pdfs_ignored']} PDFs.",
        )
        if not confirm:
            return

        self.pdf_viewer.close_pdf()
        self.lbl_status_progress.config(text="Iniciando procesamiento físico...")
        self.update_idletasks()

        ok, msg = self.store.apply_capture_changes(
            cid,
            require_mysql=True,
            progress_callback=self._update_progress_label,
        )
        self.lbl_status_progress.config(text="")
        self._refresh_review_table()
        if ok:
            messagebox.showinfo("Cambios Aplicados y Registrados en MySQL", msg)
        else:
            messagebox.showerror("Error al Aplicar Cambios", msg)

    def apply_all_approved_captures(self) -> None:
        if not self.is_admin_mode:
            messagebox.showwarning(
                "Modo Administrador Requerido",
                "Activa primero el Modo Administrador con el PIN.",
            )
            return

        captures = [
            c for c in self.store.get_all_captures() if c["status"] == "APROBADO"
        ]
        if not captures:
            messagebox.showinfo(
                "Sin capturas aprobadas",
                "No hay capturas con estado 'APROBADO'. Marca primero las capturas revisadas con el botón '✅ Aprobar / Desaprobar Seleccionada'.",
            )
            return

        confirm = messagebox.askyesno(
            "Aplicar Lote de Capturas Aprobadas",
            f"Se aplicarán los cambios físicos y se registrarán en MySQL (con Hash SHA-256, conteo de páginas y UUID) {len(captures)} directorios APROBADOS.\n\n¿Deseas continuar?",
        )
        if not confirm:
            return

        self.pdf_viewer.close_pdf()
        success_count = 0
        errors: List[str] = []

        for c in captures:
            ok, msg = self.store.apply_capture_changes(
                c["id"],
                require_mysql=True,
                progress_callback=self._update_progress_label,
            )
            if ok:
                success_count += 1
            else:
                errors.append(f"• {c['original_folder_name']}: {msg}")

        self.lbl_status_progress.config(text="")
        self._refresh_review_table()
        summary = f"Directorios aplicados y registrados en MySQL con éxito: {success_count} de {len(captures)}."
        if errors:
            summary += "\n\nErrores encontrados:\n" + "\n".join(errors[:10])
            messagebox.showwarning("Resultado de Ejecución por Lote", summary)
        else:
            messagebox.showinfo("Lote Aplicado con Éxito", summary)

    def rollback_selected_capture(self) -> None:
        if not self.is_admin_mode:
            messagebox.showwarning(
                "Modo Administrador Requerido",
                "Activa primero el Modo Administrador con el PIN.",
            )
            return

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
            "Confirmar ROLLBACK Físico (Reversión Total)",
            f"¿Deseas revertir la carpeta y sus {cap['total_pdfs_rename']} PDFs a sus nombres originales y actualizar el estado en MySQL?\n\n"
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
            messagebox.showinfo(
                "Exportación Exitosa", f"Reporte CSV guardado en:\n{path}"
            )

    def export_json_dialog(self) -> None:
        out = filedialog.asksaveasfilename(
            parent=self,
            title="Exportar Respaldo JSON de Capturas (Con UUIDs)",
            defaultextension=".json",
            initialfile="respaldo_capturas_ceros.json",
            filetypes=[("Archivo JSON", "*.json")],
        )
        if out:
            path = self.store.export_backup_json(out)
            messagebox.showinfo(
                "Exportación Exitosa", f"Respaldo JSON guardado en:\n{path}"
            )

    def import_json_dialog(self) -> None:
        in_path = filedialog.askopenfilename(
            parent=self,
            title="Importar Capturas desde Archivo JSON",
            filetypes=[("Archivo JSON", "*.json")],
        )
        if not in_path:
            return
        try:
            inserted, updated, skipped = self.store.import_backup_json(in_path)
        except Exception as exc:
            messagebox.showerror(
                "Error al Importar JSON",
                f"No se pudo importar el archivo JSON:\n{exc}",
            )
            return

        self._refresh_review_table()
        messagebox.showinfo(
            "Importación JSON Completada",
            f"Archivo importado exitosamente (conservando UUIDs de vinculación):\n{in_path}\n\n"
            f"• Capturas nuevas insertadas: {inserted}\n"
            f"• Capturas existentes actualizadas: {updated}\n"
            f"• Capturas omitidas (ya aplicadas físicamente): {skipped}",
        )


def main() -> None:
    bootstrap_portable_environment()
    app = CapturaCerosApp()
    app.mainloop()


if __name__ == "__main__":
    main()
