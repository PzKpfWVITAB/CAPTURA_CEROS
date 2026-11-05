"""
Visor de páginas PDF integrado con PyMuPDF (fitz) y Pillow para Tkinter.
Permite inspeccionar los documentos en red sin bloquear ni modificar los archivos.
"""

import io
import os
import tkinter as tk
from tkinter import ttk
from typing import Optional

import fitz  # PyMuPDF
from PIL import Image, ImageTk


class EmbeddedPdfViewer(ttk.Frame):
    """
    Componente reutilizable de visor PDF con controles de:
    - Navegación de páginas (Anterior / Siguiente)
    - Zoom (- / + / Ajustar)
    - Rotación (90° Izquierda / Derecha para leer sellos laterales)
    - Arrastre con el ratón (Pan) y rueda del ratón (Scroll)
    """

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self.current_pdf_path: Optional[str] = None
        self.doc: Optional[fitz.Document] = None
        self.current_page: int = 0
        self.total_pages: int = 0
        self.zoom_level: float = 1.25
        self.rotation: int = 0
        self._photo_image: Optional[ImageTk.PhotoImage] = None

        self._build_ui()

    def _build_ui(self) -> None:
        # Barra superior de herramientas del visor
        toolbar = ttk.Frame(self, padding=(6, 4))
        toolbar.pack(fill=tk.X, side=tk.TOP)

        self.lbl_filename = ttk.Label(
            toolbar,
            text="Sin PDF cargado",
            font=("Segoe UI", 9, "bold"),
            foreground="#1E293B",
        )
        self.lbl_filename.pack(side=tk.LEFT, padx=(0, 10))

        # Controles derecha
        controls = ttk.Frame(toolbar)
        controls.pack(side=tk.RIGHT)

        self.btn_prev = ttk.Button(
            controls, text="◀ Ant.", width=6, command=self.prev_page, state=tk.DISABLED
        )
        self.btn_prev.pack(side=tk.LEFT, padx=2)

        self.lbl_page = ttk.Label(controls, text="Pág: 0 / 0", width=11, anchor=tk.CENTER)
        self.lbl_page.pack(side=tk.LEFT, padx=2)

        self.btn_next = ttk.Button(
            controls, text="Sig. ▶", width=6, command=self.next_page, state=tk.DISABLED
        )
        self.btn_next.pack(side=tk.LEFT, padx=2)

        ttk.Separator(controls, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Button(controls, text="🔍-", width=4, command=self.zoom_out).pack(
            side=tk.LEFT, padx=1
        )
        self.lbl_zoom = ttk.Label(controls, text="125%", width=6, anchor=tk.CENTER)
        self.lbl_zoom.pack(side=tk.LEFT, padx=1)
        ttk.Button(controls, text="🔍+", width=4, command=self.zoom_in).pack(
            side=tk.LEFT, padx=1
        )

        ttk.Separator(controls, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Button(controls, text="↺ 90°", width=5, command=self.rotate_left).pack(
            side=tk.LEFT, padx=1
        )
        ttk.Button(controls, text="↻ 90°", width=5, command=self.rotate_right).pack(
            side=tk.LEFT, padx=1
        )
        ttk.Button(controls, text="Externo ↗", width=9, command=self.open_external).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        # Lienzo con barras de desplazamiento
        canvas_container = ttk.Frame(self)
        canvas_container.pack(fill=tk.BOTH, expand=True)

        self.v_scroll = ttk.Scrollbar(canvas_container, orient=tk.VERTICAL)
        self.h_scroll = ttk.Scrollbar(canvas_container, orient=tk.HORIZONTAL)

        self.canvas = tk.Canvas(
            canvas_container,
            bg="#334155",
            highlightthickness=0,
            yscrollcommand=self.v_scroll.set,
            xscrollcommand=self.h_scroll.set,
        )

        self.v_scroll.config(command=self.canvas.yview)
        self.h_scroll.config(command=self.canvas.xview)

        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Eventos de ratón para arrastrar (pan) y rueda (scroll continuo entre páginas)
        self.canvas.bind("<ButtonPress-1>", self._on_pan_start)
        self.canvas.bind("<B1-Motion>", self._on_pan_move)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Enter>", lambda _: self.canvas.focus_set())

    def _on_pan_start(self, event: tk.Event) -> None:
        self.canvas.scan_mark(event.x, event.y)

    def _on_pan_move(self, event: tk.Event) -> None:
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_mousewheel(self, event: tk.Event) -> None:
        if not self.doc or self.total_pages == 0:
            return

        if event.state & 0x0004:  # Ctrl presionado -> Zoom
            if event.delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            return

        top_frac, bottom_frac = self.canvas.yview()
        scrolling_down = event.delta < 0
        scrolling_up = event.delta > 0

        if scrolling_down:
            # Si ya estamos al final de la página actual, pasar automáticamente a la siguiente página
            if bottom_frac >= 0.995:
                if self.current_page < self.total_pages - 1:
                    self.current_page += 1
                    self._render_current_page(scroll_to="top")
            else:
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        elif scrolling_up:
            # Si ya estamos al inicio de la página actual, regresar automáticamente a la página anterior
            if top_frac <= 0.005:
                if self.current_page > 0:
                    self.current_page -= 1
                    self._render_current_page(scroll_to="bottom")
            else:
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def load_pdf(self, pdf_path: str) -> None:
        """
        Carga un archivo PDF en memoria para no dejar bloqueado el descriptor
        en la carpeta de red.
        """
        self.close_pdf()
        if not pdf_path or not os.path.isfile(pdf_path):
            self.lbl_filename.config(text="Archivo no encontrado")
            return

        try:
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

            self.doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            self.current_pdf_path = pdf_path
            self.total_pages = len(self.doc)
            self.current_page = 0
            self.rotation = 0
            self.lbl_filename.config(text=os.path.basename(pdf_path))
            self._render_current_page()
        except Exception as exc:
            self.lbl_filename.config(text=f"Error al abrir PDF: {exc}")

    def close_pdf(self) -> None:
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass
            self.doc = None
        self.current_pdf_path = None
        self.current_page = 0
        self.total_pages = 0
        self.canvas.delete("all")
        self.lbl_page.config(text="Pág: 0 / 0")
        self.btn_prev.config(state=tk.DISABLED)
        self.btn_next.config(state=tk.DISABLED)

    def _render_current_page(self, scroll_to: str = "top") -> None:
        if not self.doc or self.total_pages == 0:
            return

        page = self.doc.load_page(self.current_page)
        mat = fitz.Matrix(self.zoom_level, self.zoom_level).prerotate(self.rotation)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        img_data = pix.tobytes("ppm")
        pil_img = Image.open(io.BytesIO(img_data))
        self._photo_image = ImageTk.PhotoImage(pil_img)

        self.canvas.delete("all")
        w, h = pil_img.size
        self.canvas.create_image(15, 15, anchor=tk.NW, image=self._photo_image)
        self.canvas.config(scrollregion=(0, 0, w + 30, h + 30))

        if scroll_to == "bottom":
            self.canvas.yview_moveto(1.0)
        elif scroll_to == "top":
            self.canvas.yview_moveto(0.0)

        self.lbl_page.config(text=f"Pág: {self.current_page + 1} / {self.total_pages}")
        self.lbl_zoom.config(text=f"{int(self.zoom_level * 100)}%")

        self.btn_prev.config(
            state=tk.NORMAL if self.current_page > 0 else tk.DISABLED
        )
        self.btn_next.config(
            state=tk.NORMAL if self.current_page < self.total_pages - 1 else tk.DISABLED
        )

    def prev_page(self) -> None:
        if self.doc and self.current_page > 0:
            self.current_page -= 1
            self._render_current_page()

    def next_page(self) -> None:
        if self.doc and self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._render_current_page()

    def zoom_in(self) -> None:
        if self.zoom_level < 3.5:
            self.zoom_level = round(self.zoom_level + 0.25, 2)
            self._render_current_page()

    def zoom_out(self) -> None:
        if self.zoom_level > 0.5:
            self.zoom_level = round(self.zoom_level - 0.25, 2)
            self._render_current_page()

    def rotate_left(self) -> None:
        self.rotation = (self.rotation - 90) % 360
        self._render_current_page()

    def rotate_right(self) -> None:
        self.rotation = (self.rotation + 90) % 360
        self._render_current_page()

    def open_external(self) -> None:
        if self.current_pdf_path and os.path.isfile(self.current_pdf_path):
            os.startfile(self.current_pdf_path)
