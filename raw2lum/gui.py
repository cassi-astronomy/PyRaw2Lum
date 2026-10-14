"""Jednoduche lokalni GUI bez potreby weboveho prohlizece."""

from __future__ import annotations

import math
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog as tk_filedialog
from tkinter import messagebox as tk_messagebox
from tkinter import simpledialog as tk_simpledialog
from tkinter import ttk

import numpy as np
from PIL import Image, ImageTk
from tkinterdnd2 import DND_FILES, TkinterDnD

from .astrometry import BRIGHT_STARS, STAR_BY_LABEL, StarMatch, solve_orientation
from .astap_solver import (
    find_astap_executable,
    installed_database_families,
    recommended_database,
    save_astap_solution,
    solve_raw_with_astap,
)
from .core import (
    exif_time_to_utc,
    make_orientation_preview,
    profile_for_image,
    process_file,
    read_exif,
)
from .extinction import (
    bundled_gaia_catalog_path,
    combine_extinction_preview,
    make_aperture_diagnostic,
    make_bouguer_plot,
    measure_extinction,
    mid_exposure_utc,
    save_extinction_result,
)
from .i18n import LANGUAGES, load_language, set_language, tr
from .photometric_calibration import (
    StarCalibrationRegistry,
    calibration_label,
    derive_star_calibration,
    save_star_calibration,
)
from .profiles import profile_for_camera
from .vignetting import save_vignetting_calibration
from .vignetting_calibration import calibrate_vignetting, make_vignetting_plot
from .vignetting_registry import VignettingProfileRegistry, profile_label


RAW_TYPES = [
    ("RAW snímky", "*.CR2 *.cr2 *.CR3 *.cr3 *.NEF *.nef *.ARW *.arw"),
    ("Všechny soubory", "*.*"),
]
RAW_SUFFIXES = {".cr2", ".cr3", ".nef", ".arw", ".dng"}
TIMEZONE_CHOICES = [
    ("Evropa/Praha – automaticky SEC/SELČ", "Europe/Prague"),
    ("SEC – pevně UTC+01:00", "UTC+01:00"),
    ("SELČ – pevně UTC+02:00", "UTC+02:00"),
    ("UTC", "UTC"),
]
for _offset in range(-12, 15):
    if _offset not in (0, 1, 2):
        TIMEZONE_CHOICES.append(
            (f"Jiný pevný posun UTC{_offset:+03d}:00", f"UTC{_offset:+03d}:00")
        )


class _LocalizedDialogProxy:
    def __init__(self, module) -> None:
        self.module = module

    def __getattr__(self, name):
        function = getattr(self.module, name)

        def localized(*args, **kwargs):
            converted = tuple(tr(value) if isinstance(value, str) else value for value in args)
            for key in ("title", "message", "prompt"):
                if isinstance(kwargs.get(key), str):
                    kwargs[key] = tr(kwargs[key])
            if "filetypes" in kwargs:
                kwargs["filetypes"] = [
                    (tr(label), pattern) for label, pattern in kwargs["filetypes"]
                ]
            return function(*converted, **kwargs)

        return localized


filedialog = _LocalizedDialogProxy(tk_filedialog)
messagebox = _LocalizedDialogProxy(tk_messagebox)
simpledialog = _LocalizedDialogProxy(tk_simpledialog)


class PyRaw2LumApp(TkinterDnD.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.language_code = load_language()
        set_language(self.language_code)
        self.language_choice = tk.StringVar(value=LANGUAGES[self.language_code])
        self.title(tr("PyRaw2Lum – měření jasu oblohy"))
        self.geometry("1040x900")
        self.minsize(880, 760)
        self.lights: list[Path] = []
        self.locations: dict[Path, str] = {}
        self.north_angles: dict[Path, float] = {}
        self.orientation_matrices: dict[Path, np.ndarray] = {}
        self.orientation_info: dict[Path, dict[str, object]] = {}
        self.wcs_solutions: dict[Path, dict[str, object]] = {}
        self.site_coordinates: dict[Path, tuple[float, float]] = {}
        self.last_site_coordinates: tuple[float, float] | None = None
        self.darks: list[Path] = []
        self.output_path = tk.StringVar(value=str(Path.cwd() / "vystup"))
        self.timezone_choice = tk.StringVar(value=tr(TIMEZONE_CHOICES[0][0]))
        self.scale = tk.IntVar(value=2)
        self.show_horizon_circle = tk.BooleanVar(value=True)
        self.show_altitude_circles = tk.BooleanVar(value=False)
        self.map_mode = tk.StringVar(value="auto")
        self.extinction_light = tk.StringVar()
        self.extinction_catalog = tk.StringVar(value=str(bundled_gaia_catalog_path()))
        self.extinction_mode = tk.StringVar(value="tracker")
        self.extinction_min_altitude = tk.DoubleVar(value=20.0)
        self.extinction_max_v = tk.DoubleVar(value=6.0)
        self.extinction_aperture_mode = tk.StringVar(value="auto")
        self.extinction_aperture = tk.DoubleVar(value=2.5)
        self.extinction_vignetting_choice = tk.StringVar()
        self.extinction_vignetting_by_label: dict[str, str | None] = {}
        self.vignetting_registry = VignettingProfileRegistry()
        self.vignetting_entries: list[tuple[Path, object]] = []
        self.calibration_images: list[Path] = []
        self.vignetting_description = tk.StringVar()
        self.vignetting_geometry = tk.StringVar(value="auto")
        self.target_shape = tk.StringVar(value="square")
        self.target_size = tk.IntVar(value=40)
        self.photometric_registry = StarCalibrationRegistry()
        self.photometric_entries: list[tuple[Path, object]] = []
        self.last_extinction_result = None
        astap_executable = find_astap_executable()
        self.astap_executable = tk.StringVar(
            value=str(astap_executable) if astap_executable else ""
        )
        self.astap_image = tk.StringVar()
        self.astap_fov_height = tk.DoubleVar(value=17.0)
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self._build()
        self._refresh_lights()
        self._refresh_darks()
        self._refresh_vignetting_profiles()
        self._refresh_photometric_profiles()
        self.after(100, self._poll_messages)

    def _build(self) -> None:
        self._build_menu()
        notebook = ttk.Notebook(self)
        self.notebook = notebook
        notebook.pack(fill="both", expand=True)
        root = ttk.Frame(notebook, padding=18)
        notebook.add(root, text="Jas oblohy")
        ttk.Label(root, text="PyRaw2Lum", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        ttk.Label(
            root,
            text="Fotometrie oblohy · rybí oko i běžné objektivy · MSA a cd/m²",
        ).pack(anchor="w", pady=(0, 15))

        light_box = ttk.LabelFrame(root, text="Light RAW snímky", padding=10)
        light_box.pack(fill="both", expand=True)
        ttk.Label(
            light_box,
            text="Přetáhněte sem jeden nebo více light RAWů, nebo použijte tlačítko Přidat…",
        ).pack(anchor="w", pady=(0, 7))
        table_frame = ttk.Frame(light_box)
        table_frame.pack(side="left", fill="both", expand=True)
        self.light_table = ttk.Treeview(
            table_frame,
            columns=("file", "location", "orientation"),
            show="headings",
            selectmode="extended",
            height=8,
        )
        self.light_table.heading("file", text="Light RAW soubor")
        self.light_table.heading("location", text="Lokalita (volitelná)")
        self.light_table.heading("orientation", text="Panorama")
        self.light_table.column("file", width=520, minwidth=280, stretch=True)
        self.light_table.column("location", width=190, minwidth=130, stretch=True)
        self.light_table.column("orientation", width=120, minwidth=100, stretch=False)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.light_table.yview)
        self.light_table.configure(yscrollcommand=scrollbar.set)
        self.light_table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="left", fill="y")
        self.light_table.drop_target_register(DND_FILES)
        self.light_table.dnd_bind("<<Drop>>", self._drop_lights)
        self.light_table.bind("<Double-1>", self._double_click_location)
        buttons = ttk.Frame(light_box)
        buttons.pack(side="left", fill="y", padx=(10, 0))
        ttk.Button(buttons, text="Přidat…", command=self._add_lights).pack(fill="x")
        ttk.Button(buttons, text="Lokalita…", command=self._edit_locations).pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="Orientace…", command=self._set_orientation).pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="ASTAP WCS…", command=self._solve_selected_astap).pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="Odebrat", command=self._remove_lights).pack(fill="x", pady=6)
        ttk.Button(buttons, text="Vymazat", command=self._clear_lights).pack(fill="x")

        dark_box = ttk.LabelFrame(root, text="Dark RAW snímky", padding=10)
        dark_box.pack(fill="x", pady=(10, 2))
        ttk.Label(
            dark_box,
            text=(
                "Přidejte darky pro všechny použité expoziční časy. Program pro každý light "
                "vybere shodný fotoaparát a ISO, expozice ±1,0 s."
            ),
        ).pack(anchor="w", pady=(0, 7))
        dark_list_frame = ttk.Frame(dark_box)
        dark_list_frame.pack(side="left", fill="both", expand=True)
        self.dark_list = tk.Listbox(dark_list_frame, height=4, selectmode="extended")
        dark_scrollbar = ttk.Scrollbar(
            dark_list_frame, orient="vertical", command=self.dark_list.yview
        )
        self.dark_list.configure(yscrollcommand=dark_scrollbar.set)
        self.dark_list.pack(side="left", fill="both", expand=True)
        dark_scrollbar.pack(side="left", fill="y")
        self.dark_list.drop_target_register(DND_FILES)
        self.dark_list.dnd_bind("<<Drop>>", self._drop_darks)
        dark_buttons = ttk.Frame(dark_box)
        dark_buttons.pack(side="left", fill="y", padx=(10, 0))
        ttk.Button(dark_buttons, text="Přidat…", command=self._add_darks).pack(fill="x")
        ttk.Button(dark_buttons, text="Odebrat", command=self._remove_darks).pack(
            fill="x", pady=6
        )
        ttk.Button(dark_buttons, text="Vymazat", command=self._clear_darks).pack(fill="x")
        self._path_row(root, "Výstupní složka", self.output_path, self._choose_output)
        profile_box = ttk.LabelFrame(
            root, text="Profily vinětace – automatický výběr", padding=8
        )
        profile_box.pack(fill="x", pady=5)
        profile_list_frame = ttk.Frame(profile_box)
        profile_list_frame.pack(side="left", fill="both", expand=True)
        self.vignetting_profile_list = tk.Listbox(
            profile_list_frame, height=3, selectmode="extended"
        )
        profile_scrollbar = ttk.Scrollbar(
            profile_list_frame,
            orient="vertical",
            command=self.vignetting_profile_list.yview,
        )
        self.vignetting_profile_list.configure(yscrollcommand=profile_scrollbar.set)
        self.vignetting_profile_list.pack(side="left", fill="both", expand=True)
        profile_scrollbar.pack(side="left", fill="y")
        profile_buttons = ttk.Frame(profile_box)
        profile_buttons.pack(side="left", fill="y", padx=(8, 0))
        ttk.Button(
            profile_buttons, text="Přidat profil…", command=self._add_vignetting_profile
        ).pack(fill="x")
        ttk.Button(
            profile_buttons, text="Upravit popis…", command=self._edit_vignetting_description
        ).pack(fill="x", pady=(6, 0))
        ttk.Button(
            profile_buttons, text="Odebrat profil", command=self._remove_vignetting_profiles
        ).pack(fill="x", pady=(6, 0))
        ttk.Label(
            profile_box,
            text=(
                "Pro každý light se automaticky vybere profil stejného fotoaparátu, "
                "objektivu a clony; bez shody se použije vestavěná vinětace."
            ),
            foreground="#666666",
            wraplength=310,
        ).pack(side="left", padx=(10, 0))
        timezone_row = ttk.Frame(root)
        timezone_row.pack(fill="x", pady=5)
        ttk.Label(timezone_row, text="Čas uložený v EXIFu", width=18).pack(side="left")
        timezone_box = ttk.Combobox(
            timezone_row,
            textvariable=self.timezone_choice,
            values=[tr(label) for label, _value in TIMEZONE_CHOICES],
            state="readonly",
        )
        timezone_box.pack(side="left", fill="x", expand=True)
        ttk.Label(
            root,
            text="Ve výsledném obrázku bude čas vždy přepočten a uveden v UTC.",
            foreground="#666666",
        ).pack(anchor="w", padx=(145, 0))

        options = ttk.Frame(root)
        options.pack(fill="x", pady=(8, 6))
        ttk.Label(options, text="Velikost prezentačního PNG:").pack(side="left")
        ttk.Radiobutton(options, text="1× (nativní mapa)", variable=self.scale, value=1).pack(side="left", padx=8)
        ttk.Radiobutton(options, text="2×", variable=self.scale, value=2).pack(side="left", padx=8)
        ttk.Radiobutton(options, text="3×", variable=self.scale, value=3).pack(side="left", padx=8)

        map_modes = ttk.Frame(root)
        map_modes.pack(fill="x", pady=(0, 6))
        ttk.Label(map_modes, text="Geometrie výstupu:").pack(side="left")
        ttk.Radiobutton(map_modes, text="automaticky", variable=self.map_mode, value="auto").pack(side="left", padx=8)
        ttk.Radiobutton(map_modes, text="rybí oko", variable=self.map_mode, value="fisheye").pack(side="left", padx=8)
        ttk.Radiobutton(map_modes, text="obdélníková mapa", variable=self.map_mode, value="rectilinear").pack(side="left", padx=8)

        overlays = ttk.Frame(root)
        overlays.pack(fill="x", pady=(0, 6))
        ttk.Label(overlays, text="Souřadnicová síť:").pack(side="left")
        ttk.Checkbutton(
            overlays,
            text="horizont",
            variable=self.show_horizon_circle,
        ).pack(side="left", padx=(8, 4))
        ttk.Checkbutton(
            overlays,
            text="výška/azimut po 10°",
            variable=self.show_altitude_circles,
        ).pack(side="left", padx=4)
        ttk.Label(
            overlays,
            text="(jen po astrometrii)",
            foreground="#666666",
        ).pack(side="left", padx=(6, 0))

        action = ttk.Frame(root)
        action.pack(fill="x", pady=(8, 8))
        self.start_button = ttk.Button(action, text="Spustit zpracování", command=self._start)
        self.start_button.pack(side="left")
        self.progress = ttk.Progressbar(action, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(12, 0))
        self.log = tk.Text(root, height=7, state="disabled", wrap="word")
        self.log.pack(fill="x")

        extinction_tab = ttk.Frame(notebook, padding=18)
        self.extinction_tab = extinction_tab
        notebook.add(extinction_tab, text="Extinkce – experimentální")
        self._build_extinction_tab(extinction_tab)

        vignetting_tab = ttk.Frame(notebook, padding=18)
        notebook.add(vignetting_tab, text="Kalibrace vinětace")
        self._build_vignetting_tab(vignetting_tab)
        photometric_tab = ttk.Frame(notebook, padding=18)
        self.photometric_tab = photometric_tab
        notebook.add(photometric_tab, text="Kalibrace sestavy – hvězdy")
        self._build_photometric_calibration_tab(photometric_tab)
        self._localize_widget_tree(notebook)
        for tab_id in notebook.tabs():
            notebook.tab(tab_id, text=tr(notebook.tab(tab_id, "text")))
        for column in ("file", "location", "orientation"):
            self.light_table.heading(
                column, text=tr(self.light_table.heading(column, "text"))
            )

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        language_menu = tk.Menu(menu, tearoff=False)
        for code, label in LANGUAGES.items():
            language_menu.add_radiobutton(
                label=label,
                variable=self.language_choice,
                value=label,
                command=lambda selected=code: self._switch_language(selected),
            )
        menu.add_cascade(label="Jazyk / Language", menu=language_menu)
        self.configure(menu=menu)

    def _switch_language(self, language: str) -> None:
        if language == self.language_code:
            return
        timezone = self._timezone_value()
        self.language_code = language
        set_language(language, persist=True)
        self.language_choice.set(LANGUAGES[language])
        self.title(tr("PyRaw2Lum – měření jasu oblohy"))
        self.notebook.destroy()
        self.timezone_choice.set(
            next(tr(label) for label, value in TIMEZONE_CHOICES if value == timezone)
        )
        self._build()
        self._refresh_lights()
        self._refresh_darks()
        self._refresh_calibration_images()
        self._refresh_vignetting_profiles()
        self._refresh_photometric_profiles()

    def _timezone_value(self) -> str:
        selected = self.timezone_choice.get()
        for label, value in TIMEZONE_CHOICES:
            if selected in (label, tr(label, "en")):
                return value
        return "Europe/Prague"

    def _localize_widget_tree(self, widget) -> None:
        for child in widget.winfo_children():
            try:
                if "text" in child.keys():
                    child.configure(text=tr(child.cget("text")))
            except tk.TclError:
                pass
            self._localize_widget_tree(child)

    def _build_extinction_tab(self, root: ttk.Frame) -> None:
        ttk.Label(root, text="Atmosférická extinkce", font=("Segoe UI", 20, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            root,
            text=(
                "Experimentální Bouguerův fit z izolovaných nesaturovaných hvězd Gaia GSPC. "
                "Light musí mít nejprve vyřešenou astrometrickou orientaci ze hvězd."
            ),
            wraplength=920,
        ).pack(anchor="w", pady=(2, 16))

        source_row = ttk.Frame(root)
        source_row.pack(fill="x", pady=5)
        ttk.Label(source_row, text="Light RAW", width=21).pack(side="left")
        self.extinction_light_box = ttk.Combobox(
            source_row,
            textvariable=self.extinction_light,
            state="readonly",
        )
        self.extinction_light_box.pack(side="left", fill="x", expand=True)

        correction_box = ttk.LabelFrame(root, text="Kalibrační korekce RAWu", padding=8)
        correction_box.pack(fill="x", pady=(8, 4))
        ttk.Label(
            correction_box,
            text=(
                "Darky jsou sdílené s kartou Jas oblohy. Pro light se automaticky "
                "vyberou podle fotoaparátu, ISO a expozice ±1,0 s."
            ),
            wraplength=880,
        ).pack(anchor="w", pady=(0, 5))
        dark_row = ttk.Frame(correction_box)
        dark_row.pack(fill="x")
        self.extinction_dark_list = tk.Listbox(dark_row, height=2, selectmode="extended")
        self.extinction_dark_list.pack(side="left", fill="x", expand=True)
        self.extinction_dark_list.drop_target_register(DND_FILES)
        self.extinction_dark_list.dnd_bind("<<Drop>>", self._drop_darks)
        dark_buttons = ttk.Frame(dark_row)
        dark_buttons.pack(side="left", padx=(8, 0))
        ttk.Button(dark_buttons, text="Přidat dark…", command=self._add_darks).pack(fill="x")
        ttk.Button(
            dark_buttons, text="Odebrat", command=self._remove_extinction_darks
        ).pack(fill="x", pady=(4, 0))
        flat_row = ttk.Frame(correction_box)
        flat_row.pack(fill="x", pady=(7, 0))
        ttk.Label(flat_row, text="Flat / profil vinětace", width=21).pack(side="left")
        self.extinction_vignetting_box = ttk.Combobox(
            flat_row,
            textvariable=self.extinction_vignetting_choice,
            state="readonly",
        )
        self.extinction_vignetting_box.pack(side="left", fill="x", expand=True)

        self._path_row(
            root,
            "Gaia GSPC CSV",
            self.extinction_catalog,
            self._choose_extinction_catalog,
            hint="CSV musí obsahovat source_id, ra, dec, v_jkc_mag a volitelně b_jkc_mag a v_jkc_flag.",
        )

        mode_box = ttk.LabelFrame(root, text="Způsob pořízení", padding=10)
        mode_box.pack(fill="x", pady=(14, 8))
        ttk.Radiobutton(
            mode_box,
            text="Tracker – bodové hvězdy",
            variable=self.extinction_mode,
            value="tracker",
        ).pack(anchor="w")
        ttk.Radiobutton(
            mode_box,
            text="Pevný stativ – individuální stopy podle deklinace",
            variable=self.extinction_mode,
            value="fixed",
        ).pack(anchor="w", pady=(4, 0))

        options = ttk.LabelFrame(root, text="Výběr a fotometrie hvězd", padding=10)
        options.pack(fill="x", pady=8)
        rows = (
            ("Minimální výška nad obzorem", self.extinction_min_altitude, "°", 15.0, 45.0, 1.0),
            ("Nejslabší katalogová hvězda V", self.extinction_max_v, "mag", 5.0, 10.0, 0.1),
        )
        for row_index, (label, variable, unit, lower, upper, increment) in enumerate(rows):
            ttk.Label(options, text=label).grid(row=row_index, column=0, sticky="w", pady=3)
            ttk.Spinbox(
                options,
                textvariable=variable,
                from_=lower,
                to=upper,
                increment=increment,
                width=8,
            ).grid(row=row_index, column=1, padx=(12, 5), pady=3)
            ttk.Label(options, text=unit).grid(row=row_index, column=2, sticky="w", pady=3)
        aperture_row = ttk.Frame(options)
        aperture_row.grid(row=2, column=0, columnspan=3, sticky="w", pady=(7, 2))
        ttk.Label(aperture_row, text="Apertura").pack(side="left", padx=(0, 12))
        ttk.Radiobutton(
            aperture_row,
            text="Automatická – křivka růstu",
            variable=self.extinction_aperture_mode,
            value="auto",
            command=self._update_extinction_aperture_state,
        ).pack(side="left")
        ttk.Radiobutton(
            aperture_row,
            text="Ruční poloměr",
            variable=self.extinction_aperture_mode,
            value="manual",
            command=self._update_extinction_aperture_state,
        ).pack(side="left", padx=(14, 5))
        self.extinction_aperture_spin = ttk.Spinbox(
            aperture_row,
            textvariable=self.extinction_aperture,
            from_=1.0,
            to=8.0,
            increment=0.5,
            width=7,
        )
        self.extinction_aperture_spin.pack(side="left")
        ttk.Label(aperture_row, text="px mapy").pack(side="left", padx=(5, 0))
        self._update_extinction_aperture_state()

        ttk.Label(
            root,
            text=(
                "Automatika vybere jeden společný poloměr z mediánu křivek růstu jasných "
                "izolovaných hvězd; tím nevzniká závislost apertury na jasu hvězdy. "
                "Snímky na trackeru používají kruhovou aperturu. U pevného stativu se pro "
                "každou hvězdu vypočte vlastní stopa mezi začátkem a koncem expozice. "
                "Čas astrometrie i extinkce se vztahuje ke středu expozice."
            ),
            wraplength=920,
            foreground="#555555",
        ).pack(anchor="w", pady=(4, 12))

        action = ttk.Frame(root)
        action.pack(fill="x")
        self.extinction_button = ttk.Button(
            action, text="Změřit extinkci", command=self._start_extinction
        )
        self.extinction_button.pack(side="left")
        self.extinction_progress = ttk.Progressbar(action, mode="indeterminate")
        self.extinction_progress.pack(side="left", fill="x", expand=True, padx=(12, 0))

        self.extinction_result = tk.Text(root, height=7, state="disabled", wrap="word")
        self.extinction_result.pack(fill="x", pady=(12, 6))
        self.extinction_plot_label = tk.Label(
            root,
            text="Po změření se zde ihned zobrazí Bouguerův graf a kontrola apertur.",
            background="#f2f2f2",
            foreground="#555555",
            cursor="hand2",
        )
        self.extinction_plot_label.pack(fill="both", expand=True)
        self.extinction_plot_label.bind("<Button-1>", self._open_extinction_plot)
        self.extinction_preview_source: Image.Image | None = None
        self.extinction_preview_photo: ImageTk.PhotoImage | None = None

    def _update_extinction_aperture_state(self) -> None:
        if hasattr(self, "extinction_aperture_spin"):
            state = "normal" if self.extinction_aperture_mode.get() == "manual" else "disabled"
            self.extinction_aperture_spin.configure(state=state)

    def _build_vignetting_tab(self, root: ttk.Frame) -> None:
        ttk.Label(root, text="Kalibrace vinětace", font=("Segoe UI", 20, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            root,
            text=(
                "Přidejte nejméně 10 RAWů stejného umělého zdroje v různých částech "
                "obrazu. Doporučeno je 15–30 poloh, včetně středu, stran a rohů. "
                "Použijí se odpovídající darky z karty Jas oblohy."
            ),
            wraplength=920,
        ).pack(anchor="w", pady=(2, 12))
        target_box = ttk.LabelFrame(root, text="Kalibrační obrazec na monitoru", padding=8)
        target_box.pack(fill="x", pady=(0, 10))
        ttk.Label(
            target_box,
            text=(
                "Otevře čistou černou plochu přes celý monitor s jediným bílým zdrojem "
                "uprostřed. Zavře se libovolnou klávesou."
            ),
            wraplength=600,
        ).pack(side="left", fill="x", expand=True)
        ttk.Radiobutton(
            target_box, text="Čtverec", variable=self.target_shape, value="square"
        ).pack(side="left", padx=4)
        ttk.Radiobutton(
            target_box, text="Kruh", variable=self.target_shape, value="circle"
        ).pack(side="left", padx=4)
        ttk.Spinbox(
            target_box, textvariable=self.target_size, from_=8, to=200, width=5
        ).pack(side="left", padx=4)
        ttk.Label(target_box, text="px").pack(side="left")
        ttk.Button(
            target_box, text="Otevřít přes celou obrazovku", command=self._open_calibration_target
        ).pack(side="left", padx=(8, 0))
        box = ttk.LabelFrame(root, text="Kalibrační RAW snímky", padding=10)
        box.pack(fill="x")
        description_row = ttk.Frame(box)
        description_row.pack(fill="x", pady=(0, 7))
        ttk.Label(description_row, text="Popis profilu / sestavy", width=23).pack(side="left")
        ttk.Entry(description_row, textvariable=self.vignetting_description).pack(
            side="left", fill="x", expand=True
        )
        ttk.Label(
            description_row,
            text="např. Canon 600D + Sigma 4,5 mm",
            foreground="#666666",
        ).pack(side="left", padx=(8, 0))
        geometry_row = ttk.Frame(box)
        geometry_row.pack(fill="x", pady=(0, 7))
        ttk.Label(geometry_row, text="Geometrie objektivu", width=23).pack(side="left")
        ttk.Radiobutton(
            geometry_row, text="automaticky", variable=self.vignetting_geometry, value="auto"
        ).pack(side="left")
        ttk.Radiobutton(
            geometry_row, text="rybí oko", variable=self.vignetting_geometry, value="fisheye"
        ).pack(side="left", padx=(12, 0))
        ttk.Radiobutton(
            geometry_row, text="běžný objektiv", variable=self.vignetting_geometry, value="rectilinear"
        ).pack(side="left", padx=(12, 0))
        list_frame = ttk.Frame(box)
        list_frame.pack(side="left", fill="both", expand=True)
        self.calibration_list = tk.Listbox(list_frame, height=9, selectmode="extended")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.calibration_list.yview)
        self.calibration_list.configure(yscrollcommand=scrollbar.set)
        self.calibration_list.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="left", fill="y")
        self.calibration_list.drop_target_register(DND_FILES)
        self.calibration_list.dnd_bind("<<Drop>>", self._drop_calibration_images)
        buttons = ttk.Frame(box)
        buttons.pack(side="left", fill="y", padx=(10, 0))
        ttk.Button(buttons, text="Přidat…", command=self._add_calibration_images).pack(fill="x")
        ttk.Button(buttons, text="Odebrat", command=self._remove_calibration_images).pack(
            fill="x", pady=6
        )
        ttk.Button(buttons, text="Vymazat", command=self._clear_calibration_images).pack(fill="x")

        ttk.Label(
            root,
            text=(
                "Zdroj nesmí být saturovaný. Fotoaparát, ISO a clona mají zůstat stejné; "
                "expozici lze měnit, ale stabilní expozice je přesnější. Program změří "
                "samostatný radiální profil R, G a B."
            ),
            wraplength=920,
            foreground="#555555",
        ).pack(anchor="w", pady=(10, 8))
        action = ttk.Frame(root)
        action.pack(fill="x")
        self.vignetting_button = ttk.Button(
            action, text="Změřit a uložit profil", command=self._start_vignetting_calibration
        )
        self.vignetting_button.pack(side="left")
        self.vignetting_progress = ttk.Progressbar(action, mode="indeterminate")
        self.vignetting_progress.pack(side="left", fill="x", expand=True, padx=(12, 0))
        self.vignetting_log = tk.Text(root, height=6, state="disabled", wrap="word")
        self.vignetting_log.pack(fill="x", pady=(10, 6))
        self.vignetting_plot_label = tk.Label(
            root,
            text="Po změření se zde zobrazí profil propustnosti R/G/B.",
            background="#f2f2f2",
            foreground="#555555",
            cursor="hand2",
        )
        self.vignetting_plot_label.pack(fill="both", expand=True)
        self.vignetting_plot_label.bind("<Button-1>", self._open_vignetting_plot)
        self.vignetting_preview_source: Image.Image | None = None
        self.vignetting_preview_photo: ImageTk.PhotoImage | None = None

    def _build_photometric_calibration_tab(self, root: ttk.Frame) -> None:
        ttk.Label(
            root, text="Experimentální kalibrace sestavy na hvězdách", font=("Segoe UI", 20, "bold")
        ).pack(anchor="w")
        ttk.Label(
            root,
            text=(
                "Z posledního úspěšného měření extinkce vytvoří absolutní fotometrický "
                "profil fotoaparátu, objektivu a clony. Bouguerův fit oddělí extinkci "
                "atmosféry; nulový bod se převede pomocí prostorového úhlu pixelu a "
                "katalogové Johnsonovy V fotometrie."
            ),
            wraplength=920,
        ).pack(anchor="w", pady=(2, 10))
        ttk.Label(
            root,
            text=(
                "Postup: na kartě Extinkce vyberte light, přiřaďte darky a flat / profil "
                "vinětace a změřte kvalitní bezoblačný snímek s širokým rozsahem vzdušné "
                "hmoty. Potom zde vytvořte profil. Funkce je "
                "experimentální a nenahrazuje laboratorní kalibraci V(λ)."
            ),
            foreground="#555555",
            wraplength=920,
        ).pack(anchor="w", pady=(0, 12))
        self.photometric_input_status = ttk.Label(
            root,
            text="Poslední kalibrovaný vstup: zatím nebylo provedeno měření extinkce.",
            foreground="#555555",
            wraplength=920,
        )
        self.photometric_input_status.pack(anchor="w", pady=(0, 10))
        input_box = ttk.LabelFrame(root, text="Kalibrovaný vstup pro hvězdy", padding=8)
        input_box.pack(fill="x", pady=(0, 10))
        input_light_row = ttk.Frame(input_box)
        input_light_row.pack(fill="x")
        ttk.Label(input_light_row, text="Light RAW", width=21).pack(side="left")
        self.photometric_light_box = ttk.Combobox(
            input_light_row,
            textvariable=self.extinction_light,
            state="readonly",
        )
        self.photometric_light_box.pack(side="left", fill="x", expand=True)
        input_dark_row = ttk.Frame(input_box)
        input_dark_row.pack(fill="x", pady=(6, 0))
        ttk.Label(input_dark_row, text="Dark RAW", width=21).pack(side="left")
        self.photometric_dark_summary = ttk.Label(input_dark_row, foreground="#555555")
        self.photometric_dark_summary.pack(side="left", fill="x", expand=True)
        ttk.Button(input_dark_row, text="Přidat dark…", command=self._add_darks).pack(side="left")
        input_flat_row = ttk.Frame(input_box)
        input_flat_row.pack(fill="x", pady=(6, 0))
        ttk.Label(input_flat_row, text="Flat / profil vinětace", width=21).pack(side="left")
        self.photometric_vignetting_box = ttk.Combobox(
            input_flat_row,
            textvariable=self.extinction_vignetting_choice,
            state="readonly",
        )
        self.photometric_vignetting_box.pack(side="left", fill="x", expand=True)
        ttk.Button(
            input_box,
            text="Změřit kalibrovaný vstup a zobrazit extinkci",
            command=self._measure_star_calibration_input,
        ).pack(anchor="w", pady=(8, 0))
        astap_box = ttk.LabelFrame(
            root, text="Automatická astrometrie delšího objektivu (ASTAP)", padding=10
        )
        astap_box.pack(fill="x", pady=(0, 10))
        ttk.Label(
            astap_box,
            text=(
                "Pro běžný (nerektifikovaný rybím okem) snímek vytvoří WCS řešení. "
                "Výšku zorného pole lze upravit; pro 50 mm + APS-C je přibližně 17°."
            ),
            wraplength=900,
        ).pack(anchor="w", pady=(0, 5))
        self._path_row(
            astap_box,
            "Program ASTAP:",
            self.astap_executable,
            self._choose_astap_executable,
        )
        self._path_row(
            astap_box,
            "Snímek RAW:",
            self.astap_image,
            self._choose_astap_image,
        )
        astap_options = ttk.Frame(astap_box)
        astap_options.pack(fill="x", pady=(4, 0))
        ttk.Label(astap_options, text="Výška pole [°]:").pack(side="left")
        ttk.Spinbox(
            astap_options,
            from_=0.1,
            to=120.0,
            increment=0.1,
            width=8,
            textvariable=self.astap_fov_height,
        ).pack(side="left", padx=(6, 12))
        self.astap_button = ttk.Button(
            astap_options, text="Vyřešit WCS", command=self._start_astap_solve
        )
        self.astap_button.pack(side="left")
        self.astap_progress = ttk.Progressbar(astap_options, mode="indeterminate", length=140)
        self.astap_progress.pack(side="left", padx=(12, 0))
        self.astap_database_label = ttk.Label(astap_options, foreground="#555555")
        self.astap_database_label.pack(side="left", padx=(12, 0))
        self._refresh_astap_database_status()
        box = ttk.LabelFrame(root, text="Uložené fotometrické profily", padding=10)
        box.pack(fill="both", expand=True)
        list_frame = ttk.Frame(box)
        list_frame.pack(side="left", fill="both", expand=True)
        self.photometric_profile_list = tk.Listbox(
            list_frame, height=10, selectmode="extended"
        )
        scroll = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.photometric_profile_list.yview
        )
        self.photometric_profile_list.configure(yscrollcommand=scroll.set)
        self.photometric_profile_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        buttons = ttk.Frame(box)
        buttons.pack(side="left", fill="y", padx=(10, 0))
        ttk.Button(
            buttons,
            text="Vytvořit z posledního měření extinkce",
            command=self._create_star_calibration,
        ).pack(fill="x")
        ttk.Button(
            buttons, text="Přidat profil…", command=self._add_photometric_profile
        ).pack(fill="x", pady=(8, 0))
        ttk.Button(
            buttons, text="Odebrat profil", command=self._remove_photometric_profiles
        ).pack(fill="x", pady=(8, 0))
        self.photometric_log = tk.Text(root, height=8, state="disabled", wrap="word")
        self.photometric_log.pack(fill="x", pady=(12, 0))

    def _path_row(
        self,
        parent,
        label: str,
        variable: tk.StringVar,
        command,
        hint: str | None = None,
    ) -> ttk.Entry:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        ttk.Label(row, text=label, width=18).pack(side="left")
        entry = ttk.Entry(row, textvariable=variable)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Vybrat…", command=command).pack(side="left", padx=(8, 0))
        if hint:
            ttk.Label(parent, text=hint, foreground="#666666").pack(anchor="w", padx=(145, 0))
        return entry

    def _dropped_paths(self, data: str) -> list[Path]:
        # splitlist korektne zpracuje i Windows cesty v zavorkach, ktere
        # tkdnd pouziva pro nazvy obsahujici mezery.
        return [Path(value) for value in self.tk.splitlist(data)]

    def _valid_raws(self, paths: list[Path]) -> tuple[list[Path], list[Path]]:
        valid = [path for path in paths if path.is_file() and path.suffix.lower() in RAW_SUFFIXES]
        invalid = [path for path in paths if path not in valid]
        return valid, invalid

    def _drop_lights(self, event):
        valid, invalid = self._valid_raws(self._dropped_paths(event.data))
        for path in valid:
            self._append_light(path)
        if invalid:
            self._write_log(
                "Přeskočené soubory: " + ", ".join(path.name or str(path) for path in invalid)
            )
        return event.action

    def _drop_darks(self, event):
        valid, invalid = self._valid_raws(self._dropped_paths(event.data))
        for path in valid:
            self._append_dark(path)
        if invalid:
            self._write_log(
                "Přeskočené soubory: " + ", ".join(path.name or str(path) for path in invalid)
            )
        return event.action

    def _drop_calibration_images(self, event):
        valid, invalid = self._valid_raws(self._dropped_paths(event.data))
        for path in valid:
            self._append_calibration_image(path)
        if invalid:
            self._write_vignetting(
                "Přeskočené soubory: " + ", ".join(path.name or str(path) for path in invalid)
            )
        return event.action

    def _add_lights(self) -> None:
        for name in filedialog.askopenfilenames(title="Vyberte light RAW snímky", filetypes=RAW_TYPES):
            self._append_light(Path(name))

    def _append_light(self, path: Path) -> None:
        if path not in self.lights:
            self.lights.append(path)
            self._refresh_lights()

    def _refresh_lights(self) -> None:
        self.light_table.delete(*self.light_table.get_children())
        for index, path in enumerate(self.lights):
            self.light_table.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    str(path),
                    self.locations.get(path, ""),
                    tr(
                        "astrometrie"
                        if path in self.orientation_matrices
                        else "ASTAP WCS"
                        if path in self.wcs_solutions
                        else "směr určen"
                        if path in self.north_angles
                        else "jen kruhová mapa"
                    ),
                ),
            )
        values = [str(path) for path in self.lights]
        self.extinction_light_box.configure(values=values)
        if hasattr(self, "photometric_light_box"):
            self.photometric_light_box.configure(values=values)
        if self.extinction_light.get() not in values:
            self.extinction_light.set(values[0] if values else "")

    def _edit_locations(self) -> None:
        selected = self.light_table.selection()
        if not selected:
            messagebox.showinfo("Vyberte snímek", "Nejprve vyberte jeden nebo více light snímků.")
            return
        first_path = self.lights[int(selected[0])]
        initial = self.locations.get(first_path, "") if len(selected) == 1 else ""
        value = simpledialog.askstring(
            "Lokalita snímku",
            "Zadejte lokalitu pro vybrané snímky (prázdná = bez lokality):",
            initialvalue=initial,
            parent=self,
        )
        if value is None:
            return
        for item in selected:
            path = self.lights[int(item)]
            cleaned = value.strip()
            if cleaned:
                self.locations[path] = cleaned
            else:
                self.locations.pop(path, None)
        self._refresh_lights()

    def _double_click_location(self, event) -> None:
        item = self.light_table.identify_row(event.y)
        column = self.light_table.identify_column(event.x)
        if item and column == "#2":
            self.light_table.selection_set(item)
            self._edit_locations()

    def _set_orientation(self) -> None:
        selected = self.light_table.selection()
        if len(selected) != 1:
            messagebox.showinfo(
                "Vyberte jeden snímek",
                "Pro určení světových stran vyberte právě jeden light snímek.",
            )
            return
        path = self.lights[int(selected[0])]
        try:
            preview_array = make_orientation_preview(path)
            exif = read_exif(path)
            profile = profile_for_camera(exif.camera_model)
            captured_at_utc = exif_time_to_utc(
                exif.captured_at,
                self._timezone_value(),
            )
            astrometry_at_utc = (
                mid_exposure_utc(captured_at_utc, exif.exposure_s)
                if captured_at_utc is not None
                else None
            )
        except Exception as exc:
            messagebox.showerror("Náhled nelze vytvořit", str(exc))
            return

        dialog = tk.Toplevel(self)
        dialog.title(f"{tr('Orientace panoramatu')} – {path.name}")
        dialog.transient(self)
        dialog.grab_set()
        ttk.Label(
            dialog,
            text=(
                "Klikněte na známý směr, nebo postupně na 2–3 vybrané jasné hvězdy. "
                "Astrometrie opraví také náklon fotoaparátu."
            ),
            padding=(12, 10),
        ).pack()
        max_display = 600
        scale = min(max_display / preview_array.shape[1], max_display / preview_array.shape[0])
        display_w = max(1, int(preview_array.shape[1] * scale))
        display_h = max(1, int(preview_array.shape[0] * scale))
        source_image = Image.fromarray(preview_array, mode="L")
        image = source_image.resize(
            (display_w, display_h), Image.Resampling.BILINEAR
        )
        photo = ImageTk.PhotoImage(image)
        preview_frame = ttk.Frame(dialog)
        preview_frame.pack(padx=12)
        canvas = tk.Canvas(
            preview_frame,
            width=display_w,
            height=display_h,
            highlightthickness=1,
            highlightbackground="#777777",
            takefocus=True,
        )
        canvas.pack(side="left")
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.image = photo

        loupe_pixels = 31
        loupe_zoom = 8
        loupe_size = loupe_pixels * loupe_zoom
        loupe_box = ttk.Frame(preview_frame, padding=(12, 0, 0, 0))
        loupe_box.pack(side="left", anchor="n")
        ttk.Label(loupe_box, text="Lupa 8×", font=("Segoe UI", 11, "bold")).pack()
        loupe_canvas = tk.Canvas(
            loupe_box,
            width=loupe_size,
            height=loupe_size,
            background="black",
            highlightthickness=1,
            highlightbackground="#777777",
            cursor="crosshair",
        )
        loupe_canvas.pack(pady=(4, 5))
        loupe_image_id = loupe_canvas.create_image(0, 0, anchor="nw")
        loupe_canvas.create_line(
            loupe_size / 2 - 18,
            loupe_size / 2,
            loupe_size / 2 + 18,
            loupe_size / 2,
            fill="#00ffff",
            width=1,
        )
        loupe_canvas.create_line(
            loupe_size / 2,
            loupe_size / 2 - 18,
            loupe_size / 2,
            loupe_size / 2 + 18,
            fill="#00ffff",
            width=1,
        )
        loupe_coordinates = tk.StringVar(value="x=–  y=–")
        ttk.Label(loupe_box, textvariable=loupe_coordinates).pack()
        ttk.Label(
            loupe_box,
            text=(
                "Přejeďte myší nad hlavním náhledem.\n"
                "Kliknutím do lupy přesuňte hvězdu\n"
                "přesně pod středový kříž.\n"
                "Šipky: krok 0,5 px · Shift+šipky: 0,1 px"
            ),
            justify="center",
            foreground="#555555",
        ).pack(pady=(5, 0))
        nudge_frame = ttk.Frame(loupe_box)
        nudge_frame.pack(pady=(5, 0))
        cx, cy = display_w / 2.0, display_h / 2.0
        canvas.create_line(cx - 10, cy, cx + 10, cy, fill="#00ffff", width=2)
        canvas.create_line(cx, cy - 10, cx, cy + 10, fill="#00ffff", width=2)
        chosen: dict[str, float | None] = {
            "angle": self.north_angles.get(path),
            "x": None,
            "y": None,
        }
        directions = (
            ("Sever (S)", 0.0),
            ("Východ (V)", 90.0),
            ("Jih (J)", 180.0),
            ("Západ (Z)", 270.0),
        )
        reference_direction = tk.StringVar(value=tr(directions[0][0]))
        direction_azimuth = {tr(label): azimuth for label, azimuth in directions}
        marker_ids: list[int] = []
        star_marker_ids: list[int] = []
        matches: list[StarMatch] = []
        loupe_center: dict[str, float] = {
            "x": preview_array.shape[1] / 2.0,
            "y": preview_array.shape[0] / 2.0,
        }

        def update_loupe(source_x: float, source_y: float) -> None:
            source_x = min(max(source_x, 0.0), preview_array.shape[1] - 1.0)
            source_y = min(max(source_y, 0.0), preview_array.shape[0] - 1.0)
            loupe_center["x"], loupe_center["y"] = source_x, source_y
            # Vzorkovani primo z celeho nahledu zachova i pulpixelovy posun.
            # Kriz zustava uprostred a obraz hvezdy se pod nim viditelne posouva.
            enlarged = source_image.transform(
                (loupe_size, loupe_size),
                Image.Transform.AFFINE,
                (
                    1.0 / loupe_zoom,
                    0.0,
                    source_x - loupe_size / (2.0 * loupe_zoom),
                    0.0,
                    1.0 / loupe_zoom,
                    source_y - loupe_size / (2.0 * loupe_zoom),
                ),
                resample=Image.Resampling.NEAREST,
                fillcolor=0,
            )
            loupe_photo = ImageTk.PhotoImage(enlarged)
            loupe_canvas.itemconfigure(loupe_image_id, image=loupe_photo)
            loupe_canvas.image = loupe_photo
            loupe_coordinates.set(f"x={source_x:.2f}  y={source_y:.2f}")

        def draw_marker(x: float, y: float) -> None:
            for item in marker_ids:
                canvas.delete(item)
            marker_ids.clear()
            marker_ids.extend(
                [
                    canvas.create_oval(x - 8, y - 8, x + 8, y + 8, outline="#ff3030", width=3),
                    canvas.create_line(cx, cy, x, y, fill="#ff3030", width=2),
                ]
            )

        def select_source(source_x: float, source_y: float) -> None:
            source_x = min(max(source_x, 0.0), preview_array.shape[1] - 1.0)
            source_y = min(max(source_y, 0.0), preview_array.shape[0] - 1.0)
            chosen["x"], chosen["y"] = source_x, source_y
            chosen["angle"] = math.degrees(
                math.atan2(
                    source_y - preview_array.shape[0] / 2.0,
                    source_x - preview_array.shape[1] / 2.0,
                )
            )
            draw_marker(source_x * scale, source_y * scale)
            update_loupe(source_x, source_y)
            canvas.focus_set()

        if chosen["angle"] is not None:
            angle = math.radians(float(chosen["angle"]))
            radius = min(display_w, display_h) * 0.32
            marker_x = cx + radius * math.cos(angle)
            marker_y = cy + radius * math.sin(angle)
            chosen["x"], chosen["y"] = marker_x / scale, marker_y / scale
            draw_marker(marker_x, marker_y)
            update_loupe(float(chosen["x"]), float(chosen["y"]))

        def choose(event) -> None:
            if math.hypot(event.x - cx, event.y - cy) < 12:
                return
            select_source(event.x / scale, event.y / scale)

        def track_for_loupe(event) -> None:
            update_loupe(event.x / scale, event.y / scale)

        def choose_in_loupe(event) -> None:
            source_x = loupe_center["x"] + (event.x - loupe_size / 2.0) / loupe_zoom
            source_y = loupe_center["y"] + (event.y - loupe_size / 2.0) / loupe_zoom
            select_source(source_x, source_y)

        def nudge_by(dx: float, dy: float) -> None:
            if chosen["x"] is None or chosen["y"] is None:
                return
            select_source(float(chosen["x"]) + dx, float(chosen["y"]) + dy)

        def nudge(event) -> str:
            step = 0.1 if event.state & 0x0001 else 0.5
            dx, dy = {
                "Left": (-step, 0.0),
                "Right": (step, 0.0),
                "Up": (0.0, -step),
                "Down": (0.0, step),
            }[event.keysym]
            nudge_by(dx, dy)
            return "break"

        ttk.Button(nudge_frame, text="↑", width=3, command=lambda: nudge_by(0.0, -0.5)).grid(
            row=0, column=1
        )
        ttk.Button(nudge_frame, text="←", width=3, command=lambda: nudge_by(-0.5, 0.0)).grid(
            row=1, column=0
        )
        ttk.Button(nudge_frame, text="↓", width=3, command=lambda: nudge_by(0.0, 0.5)).grid(
            row=1, column=1
        )
        ttk.Button(nudge_frame, text="→", width=3, command=lambda: nudge_by(0.5, 0.0)).grid(
            row=1, column=2
        )

        canvas.bind("<Button-1>", choose)
        canvas.bind("<Motion>", track_for_loupe)
        loupe_canvas.bind("<Button-1>", choose_in_loupe)
        for key in ("Left", "Right", "Up", "Down"):
            canvas.bind(f"<{key}>", nudge)
            canvas.bind(f"<Shift-{key}>", nudge)
            loupe_canvas.bind(f"<{key}>", nudge)
            loupe_canvas.bind(f"<Shift-{key}>", nudge)
            dialog.bind(f"<{key}>", nudge, add="+")
            dialog.bind(f"<Shift-{key}>", nudge, add="+")
        update_loupe(loupe_center["x"], loupe_center["y"])
        manual_box = ttk.LabelFrame(dialog, text="Jednoduchá orientace jedním směrem", padding=8)
        manual_box.pack(fill="x", padx=12, pady=(10, 4))
        ttk.Label(manual_box, text="Označený směr:").pack(side="left")
        ttk.Combobox(
            manual_box,
            textvariable=reference_direction,
            values=list(direction_azimuth),
            state="readonly",
            width=13,
        ).pack(side="left", padx=(6, 14))

        def save() -> None:
            if chosen["angle"] is None:
                messagebox.showinfo(
                    "Směr není označen",
                    "Nejprve klikněte na bod ve známém světovém směru.",
                    parent=dialog,
                )
                return
            self.north_angles[path] = (
                float(chosen["angle"]) + direction_azimuth[reference_direction.get()]
            ) % 360.0
            self.orientation_matrices.pop(path, None)
            self.orientation_info[path] = {
                "method": "cardinal_direction",
                "reference": reference_direction.get(),
            }
            self._refresh_lights()
            dialog.destroy()

        def clear() -> None:
            self.north_angles.pop(path, None)
            self.orientation_matrices.pop(path, None)
            self.orientation_info.pop(path, None)
            self._refresh_lights()
            dialog.destroy()

        ttk.Button(manual_box, text="Uložit směr", command=save).pack(side="left")

        astrometry_box = ttk.LabelFrame(
            dialog,
            text="Astrometrická orientace ze 2–3 hvězd",
            padding=8,
        )
        astrometry_box.pack(fill="x", padx=12, pady=4)
        coordinates = self.site_coordinates.get(path) or self.last_site_coordinates
        latitude = tk.StringVar(value=f"{coordinates[0]:.6f}" if coordinates else "")
        longitude = tk.StringVar(value=f"{coordinates[1]:.6f}" if coordinates else "")
        coordinate_row = ttk.Frame(astrometry_box)
        coordinate_row.pack(fill="x")
        ttk.Label(coordinate_row, text="Šířka:").pack(side="left")
        ttk.Entry(coordinate_row, textvariable=latitude, width=12).pack(side="left", padx=(4, 10))
        ttk.Label(coordinate_row, text="Délka:").pack(side="left")
        ttk.Entry(coordinate_row, textvariable=longitude, width=12).pack(side="left", padx=(4, 10))
        ttk.Label(
            coordinate_row,
            text=f"Střed expozice: {astrometry_at_utc or 'čas v EXIFu chybí'}",
            foreground="#555555",
        ).pack(side="left", padx=(8, 0))

        star_choice = tk.StringVar(
            value=next(star.label for star in BRIGHT_STARS if star.name == "Polaris")
        )
        star_row = ttk.Frame(astrometry_box)
        star_row.pack(fill="x", pady=(7, 4))
        ttk.Label(star_row, text="Hvězda:").pack(side="left")
        star_box = ttk.Combobox(
            star_row,
            textvariable=star_choice,
            values=[star.label for star in BRIGHT_STARS],
            state="readonly",
            width=38,
        )
        star_box.pack(side="left", padx=(4, 8), fill="x", expand=True)
        star_labels = [star.label for star in BRIGHT_STARS]
        typeahead = {"prefix": "", "last_time": 0}

        def choose_star_by_typing(event) -> str | None:
            if not event.char or not event.char.isprintable() or event.char.isspace():
                return None
            now = int(event.time)
            prefix = (
                typeahead["prefix"] + event.char
                if now - int(typeahead["last_time"]) <= 1200
                else event.char
            ).casefold()
            matches = [
                index
                for index, label in enumerate(star_labels)
                if label.casefold().startswith(prefix)
            ]
            if not matches:
                prefix = event.char.casefold()
                matches = [
                    index
                    for index, label in enumerate(star_labels)
                    if label.casefold().startswith(prefix)
                ]
            if matches:
                current = star_box.current()
                if len(prefix) == 1 and current in matches:
                    selected = matches[(matches.index(current) + 1) % len(matches)]
                else:
                    selected = matches[0]
                star_box.current(selected)
                typeahead["prefix"] = prefix
                typeahead["last_time"] = now
                return "break"
            return None

        star_box.bind("<KeyPress>", choose_star_by_typing)
        match_list = tk.Listbox(astrometry_box, height=3)
        match_list.pack(fill="x", pady=(3, 4))

        def redraw_star_markers() -> None:
            for item in star_marker_ids:
                canvas.delete(item)
            star_marker_ids.clear()
            match_list.delete(0, "end")
            for number, match in enumerate(matches, start=1):
                px, py = match.x * scale, match.y * scale
                star_marker_ids.extend(
                    [
                        canvas.create_oval(
                            px - 7, py - 7, px + 7, py + 7, outline="#00ff70", width=2
                        ),
                        canvas.create_text(
                            px + 10,
                            py - 10,
                            text=str(number),
                            fill="#00ff70",
                            anchor="sw",
                            font=("Segoe UI", 11, "bold"),
                        ),
                    ]
                )
                match_list.insert(
                    "end",
                    f"{number}. {match.star.name}  x={match.x:.1f}, y={match.y:.1f}",
                )

        def add_star() -> None:
            if chosen["x"] is None or chosen["y"] is None:
                messagebox.showinfo(
                    "Hvězda není označena",
                    "Nejprve klikněte na vybranou hvězdu v náhledu.",
                    parent=dialog,
                )
                return
            star = STAR_BY_LABEL[star_choice.get()]
            matches[:] = [match for match in matches if match.star != star]
            matches.append(StarMatch(star, float(chosen["x"]), float(chosen["y"])))
            redraw_star_markers()

        def remove_star() -> None:
            selected_match = match_list.curselection()
            if selected_match:
                matches.pop(int(selected_match[0]))
                redraw_star_markers()

        ttk.Button(star_row, text="Přidat kliknutou", command=add_star).pack(side="left")
        ttk.Button(star_row, text="Odebrat", command=remove_star).pack(side="left", padx=(6, 0))

        def solve_stars() -> None:
            if astrometry_at_utc is None:
                messagebox.showerror("Chybí čas", "RAW neobsahuje použitelný čas pořízení.", parent=dialog)
                return
            try:
                lat = float(latitude.get().replace(",", "."))
                lon = float(longitude.get().replace(",", "."))
                solution = solve_orientation(matches, profile, astrometry_at_utc, lat, lon)
            except Exception as exc:
                messagebox.showerror("Astrometrii nelze vyřešit", str(exc), parent=dialog)
                return
            worst_residual = max(solution.residual_deg)
            if solution.rms_deg > 0.75 or worst_residual > 1.0:
                messagebox.showerror(
                    "Příliš velká odchylka",
                    f"RMS odchylka je {solution.rms_deg:.2f}° a nejhorší hvězda "
                    f"{worst_residual:.2f}°. Požadováno je nejvýše 0,75° RMS "
                    "a 1,00° pro jednotlivou hvězdu. Zkontrolujte kliknutí, "
                    "identifikaci hvězd, čas a souřadnice.",
                    parent=dialog,
                )
                return
            self.orientation_matrices[path] = solution.camera_to_enu
            self.north_angles.pop(path, None)
            self.orientation_info[path] = {
                "method": "manual_stars",
                "latitude_deg": lat,
                "longitude_deg": lon,
                "captured_at_utc": captured_at_utc,
                "astrometry_at_utc": astrometry_at_utc,
                "rms_deg": solution.rms_deg,
                "projection_radius_scale": solution.radius_scale,
                "projection_scale_correction": solution.radius_scale / (
                    profile.crop_size
                    * profile.focal_length_mm
                    / profile.sensor_width_mm
                ),
                "stars": [
                    {
                        "name": match.star.name,
                        "magnitude": match.star.magnitude,
                        "x": match.x,
                        "y": match.y,
                        "residual_deg": residual,
                    }
                    for match, residual in zip(matches, solution.residual_deg)
                ],
            }
            self.site_coordinates[path] = (lat, lon)
            self.last_site_coordinates = (lat, lon)
            self._refresh_lights()
            residual_text = ", ".join(f"{value:.2f}°" for value in solution.residual_deg)
            scale_correction = 100.0 * (
                solution.radius_scale
                / (profile.crop_size * profile.focal_length_mm / profile.sensor_width_mm)
                - 1.0
            )
            messagebox.showinfo(
                "Astrometrie uložena",
                f"RMS odchylka: {solution.rms_deg:.3f}°\n"
                f"Odchylky hvězd: {residual_text}\n"
                f"Korekce projekčního měřítka: {scale_correction:+.2f} %",
                parent=dialog,
            )
            dialog.destroy()

        bottom = ttk.Frame(dialog, padding=(12, 5, 12, 12))
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Vyřešit hvězdy a uložit", command=solve_stars).pack(side="left")
        ttk.Button(bottom, text="Bez orientace", command=clear).pack(side="left", padx=8)
        ttk.Button(bottom, text="Zrušit", command=dialog.destroy).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        self.wait_window(dialog)

    def _remove_lights(self) -> None:
        indices = sorted((int(item) for item in self.light_table.selection()), reverse=True)
        for index in indices:
            path = self.lights.pop(index)
            self.locations.pop(path, None)
            self.north_angles.pop(path, None)
            self.orientation_matrices.pop(path, None)
            self.orientation_info.pop(path, None)
            self.wcs_solutions.pop(path, None)
            self.site_coordinates.pop(path, None)
        self._refresh_lights()

    def _clear_lights(self) -> None:
        self.lights.clear()
        self.locations.clear()
        self.north_angles.clear()
        self.orientation_matrices.clear()
        self.orientation_info.clear()
        self.wcs_solutions.clear()
        self.site_coordinates.clear()
        self._refresh_lights()

    def _add_darks(self) -> None:
        for name in filedialog.askopenfilenames(title="Vyberte dark RAW snímky", filetypes=RAW_TYPES):
            self._append_dark(Path(name))

    def _append_dark(self, path: Path) -> None:
        if path not in self.darks:
            self.darks.append(path)
            self._refresh_darks()

    def _refresh_darks(self) -> None:
        for widget_name in ("dark_list", "extinction_dark_list"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            widget.delete(0, "end")
            for path in self.darks:
                widget.insert("end", str(path))
        if hasattr(self, "photometric_dark_summary"):
            names = ", ".join(path.name for path in self.darks)
            self.photometric_dark_summary.configure(
                text=(names if names else tr("žádný dark nebyl přidán"))
            )

    def _remove_darks(self) -> None:
        for index in reversed(self.dark_list.curselection()):
            self.darks.pop(index)
        self._refresh_darks()

    def _remove_extinction_darks(self) -> None:
        for index in reversed(self.extinction_dark_list.curselection()):
            self.darks.pop(index)
        self._refresh_darks()

    def _clear_darks(self) -> None:
        self.darks.clear()
        self._refresh_darks()

    def _add_calibration_images(self) -> None:
        names = filedialog.askopenfilenames(
            title="Vyberte kalibrační RAWy umělé hvězdy", filetypes=RAW_TYPES
        )
        for name in names:
            self._append_calibration_image(Path(name))

    def _append_calibration_image(self, path: Path) -> None:
        if path not in self.calibration_images:
            self.calibration_images.append(path)
            self._refresh_calibration_images()

    def _refresh_calibration_images(self) -> None:
        self.calibration_list.delete(0, "end")
        for path in self.calibration_images:
            self.calibration_list.insert("end", str(path))

    def _remove_calibration_images(self) -> None:
        for index in reversed(self.calibration_list.curselection()):
            self.calibration_images.pop(index)
        self._refresh_calibration_images()

    def _clear_calibration_images(self) -> None:
        self.calibration_images.clear()
        self._refresh_calibration_images()

    def _choose_output(self) -> None:
        name = filedialog.askdirectory(title="Vyberte výstupní složku")
        if name:
            self.output_path.set(name)

    def _add_vignetting_profile(self) -> None:
        name = filedialog.askopenfilename(
            title="Vyberte profil vinětace PyRaw2Lum",
            filetypes=[("Profil vinětace JSON", "*.json"), ("Všechny soubory", "*.*")],
        )
        if not name:
            return
        try:
            self.vignetting_registry.import_file(name)
            self._refresh_vignetting_profiles()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Profil nelze přidat", str(exc))

    def _refresh_vignetting_profiles(self) -> None:
        self.vignetting_entries = self.vignetting_registry.entries()
        self.vignetting_profile_list.delete(0, "end")
        for _path, calibration in self.vignetting_entries:
            self.vignetting_profile_list.insert("end", profile_label(calibration))
        self._refresh_extinction_vignetting_choices()

    def _refresh_extinction_vignetting_choices(self) -> None:
        box = getattr(self, "extinction_vignetting_box", None)
        if box is None:
            return
        previous = self.extinction_vignetting_by_label.get(
            self.extinction_vignetting_choice.get(), "__AUTO__"
        )
        automatic = tr("Automaticky podle EXIFu (jinak vestavěná korekce)")
        built_in = tr("Vestavěná korekce sestavy")
        mapping: dict[str, str | None] = {automatic: "__AUTO__", built_in: None}
        for path, calibration in self.vignetting_entries:
            label = profile_label(calibration)
            if label in mapping:
                label = f"{label} [{path.name}]"
            mapping[label] = str(path)
        self.extinction_vignetting_by_label = mapping
        box.configure(values=list(mapping))
        if hasattr(self, "photometric_vignetting_box"):
            self.photometric_vignetting_box.configure(values=list(mapping))
        selected = next(
            (label for label, value in mapping.items() if value == previous), automatic
        )
        self.extinction_vignetting_choice.set(selected)

    def _selected_extinction_vignetting_path(self, light: Path) -> str | None:
        selection = self.extinction_vignetting_by_label.get(
            self.extinction_vignetting_choice.get(), "__AUTO__"
        )
        if selection == "__AUTO__":
            return self._automatic_vignetting_path(light)
        return selection

    def _measure_star_calibration_input(self) -> None:
        self.notebook.select(self.extinction_tab)
        self.after_idle(self._start_extinction)

    def _edit_vignetting_description(self) -> None:
        selection = tuple(self.vignetting_profile_list.curselection())
        if len(selection) != 1:
            messagebox.showerror(
                "Vyberte jeden profil",
                "Pro úpravu popisu vyberte právě jeden profil vinětace.",
            )
            return
        path, calibration = self.vignetting_entries[selection[0]]
        description = simpledialog.askstring(
            "Popis profilu vinětace",
            "Zadejte název sestavy nebo jiný popis (prázdné = bez popisu):",
            initialvalue=calibration.description or "",
            parent=self,
        )
        if description is None:
            return
        try:
            self.vignetting_registry.update_description(path, description)
            self._refresh_vignetting_profiles()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Popis nelze uložit", str(exc))

    def _remove_vignetting_profiles(self) -> None:
        selection = tuple(self.vignetting_profile_list.curselection())
        if not selection:
            return
        if not messagebox.askyesno(
            "Odebrat profily vinětace",
            "Opravdu odebrat vybrané profily ze správce PyRaw2Lum?",
        ):
            return
        for index in reversed(selection):
            path, _calibration = self.vignetting_entries[index]
            self.vignetting_registry.remove(path)
        self._refresh_vignetting_profiles()

    def _automatic_vignetting_path(self, light: Path, mode: str = "fisheye") -> str | None:
        exif = read_exif(light)
        profile = profile_for_image(light, mode)
        match = self.vignetting_registry.match(exif, profile)
        return str(match) if match is not None else None

    def _refresh_photometric_profiles(self) -> None:
        self.photometric_entries = self.photometric_registry.entries()
        self.photometric_profile_list.delete(0, "end")
        for _path, calibration in self.photometric_entries:
            self.photometric_profile_list.insert("end", calibration_label(calibration))

    def _add_photometric_profile(self) -> None:
        name = filedialog.askopenfilename(
            title="Vyberte hvězdný fotometrický profil PyRaw2Lum",
            filetypes=[("Fotometrický profil JSON", "*.json"), ("Všechny soubory", "*.*")],
        )
        if not name:
            return
        try:
            self.photometric_registry.import_file(name)
            self._refresh_photometric_profiles()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Profil nelze přidat", str(exc))

    def _remove_photometric_profiles(self) -> None:
        selection = tuple(self.photometric_profile_list.curselection())
        if not selection:
            return
        if not messagebox.askyesno(
            "Odebrat fotometrické profily",
            "Opravdu odebrat vybrané hvězdné kalibrace ze správce PyRaw2Lum?",
        ):
            return
        for index in reversed(selection):
            path, _calibration = self.photometric_entries[index]
            self.photometric_registry.remove(path)
        self._refresh_photometric_profiles()

    def _automatic_photometric_path(self, light: Path, mode: str = "fisheye") -> str | None:
        exif = read_exif(light)
        profile = profile_for_image(light, mode)
        match = self.photometric_registry.match(exif, profile)
        return str(match) if match is not None else None

    def _write_photometric(self, message: str) -> None:
        self.photometric_log.configure(state="normal")
        self.photometric_log.insert("end", tr(message) + "\n")
        self.photometric_log.see("end")
        self.photometric_log.configure(state="disabled")

    def _refresh_astap_database_status(self) -> None:
        executable = Path(self.astap_executable.get()) if self.astap_executable.get() else None
        installed = installed_database_families(executable) if executable and executable.is_file() else ()
        try:
            recommended = recommended_database(float(self.astap_fov_height.get()))
        except (ValueError, tk.TclError):
            recommended = "?"
        found = ", ".join(installed) if installed else tr("žádná")
        self.astap_database_label.configure(
            text=tr(f"Databáze: {found}; doporučena {recommended}")
        )

    def _choose_astap_executable(self) -> None:
        name = filedialog.askopenfilename(
            title="Vyberte program ASTAP",
            filetypes=[("Program ASTAP", "astap*.exe"), ("Všechny soubory", "*.*")],
        )
        if name:
            self.astap_executable.set(name)
            self._refresh_astap_database_status()

    def _choose_astap_image(self) -> None:
        name = filedialog.askopenfilename(
            title="Vyberte hvězdný RAW pro ASTAP", filetypes=RAW_TYPES
        )
        if name:
            self.astap_image.set(name)
            try:
                exif = read_exif(name)
                model = exif.camera_model.casefold()
                sensor_height = 14.9 if "600d" in model else 24.0 if any(
                    value in model for value in ("r6", "6d")
                ) else None
                if sensor_height and exif.focal_length_mm:
                    fov = math.degrees(
                        2.0 * math.atan(sensor_height / (2.0 * exif.focal_length_mm))
                    )
                    self.astap_fov_height.set(round(fov, 2))
            except (OSError, ValueError, TypeError):
                pass
            self._refresh_astap_database_status()

    def _start_astap_solve(self) -> None:
        source = Path(self.astap_image.get())
        executable = Path(self.astap_executable.get())
        try:
            field_height = float(self.astap_fov_height.get())
        except (ValueError, tk.TclError):
            messagebox.showerror("Neplatné nastavení", "Zkontrolujte výšku zorného pole ASTAP.")
            return
        self._refresh_astap_database_status()
        if not source.is_file():
            messagebox.showerror("Chybí snímek", "Vyberte existující hvězdný RAW pro ASTAP.")
            return
        if not executable.is_file():
            messagebox.showerror("Chybí ASTAP", "Vyberte spustitelný soubor programu ASTAP.")
            return
        self.astap_button.configure(state="disabled")
        self.astap_progress.start(12)
        self._write_photometric(
            f"\nASTAP: {source.name}; výška pole {field_height:g}°; "
            f"doporučená databáze {recommended_database(field_height)}"
        )
        threading.Thread(
            target=self._astap_worker,
            args=(source, executable, field_height),
            daemon=True,
        ).start()

    def _solve_selected_astap(self) -> None:
        """Solve the selected main light and keep its WCS for map rendering."""

        selected = self.light_table.selection()
        if len(selected) != 1:
            messagebox.showinfo("Vyberte snímek", "Vyberte právě jeden light snímek.")
            return
        source = self.lights[int(selected[0])]
        previous = self.site_coordinates.get(source) or self.last_site_coordinates
        latitude = simpledialog.askfloat(
            "Poloha snímku",
            "Zeměpisná šířka [°]:",
            initialvalue=previous[0] if previous else 50.0,
            minvalue=-90.0,
            maxvalue=90.0,
            parent=self,
        )
        if latitude is None:
            return
        longitude = simpledialog.askfloat(
            "Poloha snímku",
            "Zeměpisná délka [°; východ kladný]:",
            initialvalue=previous[1] if previous else 15.0,
            minvalue=-180.0,
            maxvalue=180.0,
            parent=self,
        )
        if longitude is None:
            return
        self.site_coordinates[source] = (float(latitude), float(longitude))
        self.last_site_coordinates = self.site_coordinates[source]
        self.astap_image.set(str(source))
        try:
            exif = read_exif(source)
            model = exif.camera_model.casefold()
            sensor_height = 14.9 if "600d" in model else 24.0 if any(
                value in model for value in ("r6", "6d")
            ) else None
            if sensor_height and exif.focal_length_mm:
                self.astap_fov_height.set(round(math.degrees(
                    2.0 * math.atan(sensor_height / (2.0 * exif.focal_length_mm))
                ), 2))
        except (OSError, ValueError, TypeError):
            pass
        self._refresh_astap_database_status()
        self.notebook.select(self.photometric_tab)
        self._start_astap_solve()

    def _astap_worker(self, source: Path, executable: Path, field_height: float) -> None:
        try:
            solution = solve_raw_with_astap(
                source,
                executable,
                field_height,
                progress=lambda message: self.messages.put(("astap_log", message)),
            )
            output = Path(self.output_path.get()) / f"{source.stem}_astap_wcs.json"
            save_astap_solution(solution, output)
            self.messages.put(("astap_done", (solution, output)))
        except Exception as exc:
            self.messages.put(("astap_error", str(exc)))

    def _create_star_calibration(self) -> None:
        result = self.last_extinction_result
        if result is None:
            messagebox.showerror(
                "Chybí měření extinkce",
                "Nejprve na kartě Extinkce dokončete měření kvalitního snímku.",
            )
            return
        try:
            source = Path(result.source)
            exif = read_exif(source)
            profile = profile_for_camera(exif.camera_model)
            calibration = derive_star_calibration(result, profile, exif)
            managed_path = self.photometric_registry.store(calibration)
            output_path = Path(self.output_path.get()) / (
                f"{source.stem}_fotometricka_kalibrace_hvezdy.json"
            )
            save_star_calibration(calibration, output_path)
            self._refresh_photometric_profiles()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Kalibraci nelze vytvořit", str(exc))
            return
        self._write_photometric(
            "\nPROFIL ULOŽEN\n"
            f"Převodní koeficient T: {calibration.calibration_divisor:.7g}\n"
            f"Hvězd ve fitu: {calibration.used_stars}\n"
            f"RMS fitu: {calibration.fit_rms_mag:.3f} mag\n"
            f"Extinkce: {calibration.extinction_mag_per_airmass:.4f} mag/airmass\n"
            f"Spravovaný profil: {managed_path}\nKopie výsledku: {output_path}"
        )
        messagebox.showinfo(
            "Fotometrická kalibrace vytvořena",
            "Experimentální profil byl uložen a bude se automaticky používat pro shodnou sestavu.",
        )

    def _open_calibration_target(self) -> None:
        try:
            size = max(8, min(200, int(self.target_size.get())))
        except (ValueError, tk.TclError):
            size = 40
            self.target_size.set(size)
        dialog = tk.Toplevel(self)
        dialog.configure(background="black")
        dialog.attributes("-fullscreen", True)
        dialog.attributes("-topmost", True)
        dialog.configure(cursor="none")
        canvas = tk.Canvas(dialog, background="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        def draw_target(_event=None) -> None:
            canvas.delete("all")
            center_x = canvas.winfo_width() / 2.0
            center_y = canvas.winfo_height() / 2.0
            half = size / 2.0
            bounds = (center_x - half, center_y - half, center_x + half, center_y + half)
            if self.target_shape.get() == "circle":
                canvas.create_oval(*bounds, fill="white", outline="white")
            else:
                canvas.create_rectangle(*bounds, fill="white", outline="white")

        dialog.bind("<Configure>", draw_target)
        dialog.bind("<KeyPress>", lambda _event: dialog.destroy())
        dialog.after(100, dialog.focus_force)

    def _choose_extinction_catalog(self) -> None:
        name = filedialog.askopenfilename(
            title="Vyberte export katalogu Gaia GSPC",
            filetypes=[("CSV soubory", "*.csv"), ("Všechny soubory", "*.*")],
        )
        if name:
            self.extinction_catalog.set(name)

    def _write_log(self, message: str) -> None:
        message = tr(message)
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _write_extinction(self, message: str) -> None:
        message = tr(message)
        self.extinction_result.configure(state="normal")
        self.extinction_result.insert("end", message + "\n")
        self.extinction_result.see("end")
        self.extinction_result.configure(state="disabled")

    def _write_vignetting(self, message: str) -> None:
        message = tr(message)
        self.vignetting_log.configure(state="normal")
        self.vignetting_log.insert("end", message + "\n")
        self.vignetting_log.see("end")
        self.vignetting_log.configure(state="disabled")

    def _show_extinction_plot(self, source: Image.Image) -> None:
        self.extinction_preview_source = source.copy()
        available_width = max(500, self.extinction_plot_label.winfo_width())
        available_height = max(260, self.extinction_plot_label.winfo_height())
        scale = min(available_width / source.width, available_height / source.height, 1.0)
        size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
        preview = source.resize(size, Image.Resampling.LANCZOS)
        self.extinction_preview_photo = ImageTk.PhotoImage(preview)
        self.extinction_plot_label.configure(
            image=self.extinction_preview_photo,
            text="",
            background="white",
        )

    def _open_extinction_plot(self, _event=None) -> None:
        if self.extinction_preview_source is None:
            return
        dialog = tk.Toplevel(self)
        dialog.title(tr("Bouguerův diagram – rychlá kontrola"))
        dialog.transient(self)
        photo = ImageTk.PhotoImage(self.extinction_preview_source)
        label = tk.Label(dialog, image=photo, background="white")
        label.image = photo
        label.pack(fill="both", expand=True)

    def _show_vignetting_plot(self, source: Image.Image) -> None:
        self.vignetting_preview_source = source.copy()
        available_width = max(500, self.vignetting_plot_label.winfo_width())
        available_height = max(260, self.vignetting_plot_label.winfo_height())
        scale = min(available_width / source.width, available_height / source.height, 1.0)
        size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
        preview = source.resize(size, Image.Resampling.LANCZOS)
        self.vignetting_preview_photo = ImageTk.PhotoImage(preview)
        self.vignetting_plot_label.configure(
            image=self.vignetting_preview_photo, text="", background="white"
        )

    def _open_vignetting_plot(self, _event=None) -> None:
        if self.vignetting_preview_source is None:
            return
        dialog = tk.Toplevel(self)
        dialog.title(tr("Profil vinětace – rychlá kontrola"))
        dialog.transient(self)
        photo = ImageTk.PhotoImage(self.vignetting_preview_source)
        label = tk.Label(dialog, image=photo, background="white")
        label.image = photo
        label.pack(fill="both", expand=True)

    def _start_vignetting_calibration(self) -> None:
        if len(self.calibration_images) < 10:
            messagebox.showerror(
                "Málo snímků", "Přidejte alespoň 10 kalibračních RAW snímků."
            )
            return
        if not self.darks:
            messagebox.showerror(
                "Chybí dark", "Na kartě Jas oblohy přidejte odpovídající dark RAW."
            )
            return
        output = Path(self.output_path.get())
        self.vignetting_log.configure(state="normal")
        self.vignetting_log.delete("1.0", "end")
        self.vignetting_log.configure(state="disabled")
        self.vignetting_preview_source = None
        self.vignetting_preview_photo = None
        self.vignetting_plot_label.configure(
            image="", text="Hledám zdroj a měřím jednotlivé polohy…", background="#f2f2f2"
        )
        self.vignetting_button.configure(state="disabled")
        self.vignetting_progress.start(12)
        threading.Thread(
            target=self._vignetting_worker,
            args=(
                list(self.calibration_images),
                list(self.darks),
                output,
                self.vignetting_description.get().strip(),
                self.vignetting_geometry.get(),
            ),
            daemon=True,
        ).start()

    def _vignetting_worker(
        self,
        calibration_images: list[Path],
        darks: list[Path],
        output: Path,
        description: str,
        projection_mode: str,
    ) -> None:
        try:
            calibration, measurements = calibrate_vignetting(
                calibration_images,
                darks,
                description=description,
                progress=lambda text: self.messages.put(("vign_log", text)),
                projection_mode=projection_mode,
            )
            reference_profile = (
                profile_for_camera(calibration.camera_model)
                if calibration.projection == "fisheye_equisolid"
                else None
            )
            preview = make_vignetting_plot(
                calibration, measurements, reference_profile=reference_profile
            )
            preview_shown = threading.Event()
            self.messages.put(("vign_preview", (preview, preview_shown)))
            preview_shown.wait(timeout=2.0)
            aperture_text = f"{calibration.aperture:g}".replace(".", "_")
            profile_path = output / f"{calibration.profile_key}_vinetace_f{aperture_text}.json"
            plot_path = output / f"{calibration.profile_key}_vinetace_f{aperture_text}.png"
            save_vignetting_calibration(calibration, profile_path)
            output.mkdir(parents=True, exist_ok=True)
            preview.save(plot_path)
            self.messages.put(("vign_done", (calibration, profile_path, plot_path)))
        except Exception as exc:
            self.messages.put(("vign_error", str(exc)))

    def _start_extinction(self) -> None:
        try:
            light = Path(self.extinction_light.get())
            catalog = Path(self.extinction_catalog.get())
            minimum_altitude = float(self.extinction_min_altitude.get())
            maximum_v = float(self.extinction_max_v.get())
            aperture = float(self.extinction_aperture.get())
            aperture_mode = self.extinction_aperture_mode.get()
        except (TypeError, ValueError, tk.TclError):
            messagebox.showerror("Neplatné nastavení", "Zkontrolujte číselné volby extinkce.")
            return
        if light not in self.lights:
            messagebox.showerror("Chybí light", "Vyberte light RAW ze seznamu první karty.")
            return
        if not self.darks:
            messagebox.showerror("Chybí dark", "Přidejte odpovídající dark RAW na první kartě.")
            return
        if not catalog.is_file():
            messagebox.showerror("Chybí katalog", "Vyberte existující CSV export Gaia GSPC.")
            return
        try:
            vignetting_path = self._selected_extinction_vignetting_path(light)
            photometric_path = self._automatic_photometric_path(light)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Kalibrační profil nelze vybrat", str(exc))
            return
        if light not in self.orientation_matrices or light not in self.site_coordinates:
            messagebox.showerror(
                "Chybí astrometrie",
                "Pro tento light nejprve na první kartě vyřešte orientaci ze 2–3 hvězd.",
            )
            return
        if not 10.0 <= minimum_altitude <= 60.0 or not 3.0 <= maximum_v <= 10.0:
            messagebox.showerror("Neplatné nastavení", "Výška nebo mezní V magnituda jsou mimo povolený rozsah.")
            return
        if aperture_mode == "manual" and not 1.0 <= aperture <= 8.0:
            messagebox.showerror("Neplatné nastavení", "Poloměr apertury musí být 1 až 8 pixelů.")
            return

        self.extinction_result.configure(state="normal")
        self.extinction_result.delete("1.0", "end")
        self.extinction_result.configure(state="disabled")
        self.extinction_preview_source = None
        self.extinction_preview_photo = None
        self.extinction_plot_label.configure(
            image="",
            text="Počítám fotometrii a Bouguerův fit…",
            background="#f2f2f2",
        )
        self._write_extinction(f"Zpracovávám {light.name}…")
        self.extinction_button.configure(state="disabled")
        self.extinction_progress.start(12)
        latitude, longitude = self.site_coordinates[light]
        job = (
            light,
            list(self.darks),
            catalog,
            self.orientation_matrices[light].copy(),
            dict(self.orientation_info[light]),
            latitude,
            longitude,
            self._timezone_value(),
            self.extinction_mode.get(),
            minimum_altitude,
            maximum_v,
            aperture_mode,
            aperture,
            self.output_path.get(),
            vignetting_path,
            photometric_path,
        )
        threading.Thread(target=self._extinction_worker, args=job, daemon=True).start()

    def _extinction_worker(
        self,
        light: Path,
        darks: list[Path],
        catalog: Path,
        orientation_matrix: np.ndarray,
        orientation_info: dict[str, object],
        latitude: float,
        longitude: float,
        source_timezone: str,
        mode: str,
        minimum_altitude: float,
        maximum_v: float,
        aperture_mode: str,
        aperture: float,
        output_path: str,
        vignetting_calibration_path: str | None,
        photometric_calibration_path: str | None,
    ) -> None:
        try:
            result = measure_extinction(
                light,
                darks,
                catalog,
                orientation_matrix,
                orientation_info,
                latitude,
                longitude,
                source_timezone,
                mode=mode,
                minimum_altitude_deg=minimum_altitude,
                maximum_v_mag=maximum_v,
                aperture_mode=aperture_mode,
                aperture_radius_px=aperture,
                vignetting_calibration_path=vignetting_calibration_path,
                photometric_calibration_path=photometric_calibration_path,
                progress=lambda text: self.messages.put(("ext_log", text)),
            )
            aperture_diagnostic = make_aperture_diagnostic(
                make_orientation_preview(light), result
            )
            preview = combine_extinction_preview(
                make_bouguer_plot(result), aperture_diagnostic
            )
            preview_shown = threading.Event()
            self.messages.put(("ext_preview", (preview, preview_shown)))
            # GUI dostane nahled pred tim, nez se zacnou zapisovat vystupni soubory.
            preview_shown.wait(timeout=2.0)
            paths = save_extinction_result(
                result, output_path, aperture_diagnostic=aperture_diagnostic
            )
            self.messages.put(("ext_done", (result, paths)))
        except Exception as exc:
            self.messages.put(("ext_error", str(exc)))

    def _start(self) -> None:
        if not self.lights:
            messagebox.showerror("Chybí light", "Přidejte alespoň jeden light RAW snímek.")
            return
        if not self.darks:
            messagebox.showerror("Chybí dark", "Přidejte alespoň jeden dark RAW snímek.")
            return
        self.start_button.configure(state="disabled")
        self.progress.configure(maximum=len(self.lights), value=0)
        self._write_log("Spouštím zpracování…")
        job = (
            list(self.lights),
            dict(self.locations),
            dict(self.north_angles),
            dict(self.orientation_matrices),
            dict(self.orientation_info),
            dict(self.wcs_solutions),
            dict(self.site_coordinates),
            list(self.darks),
            self.output_path.get(),
            int(self.scale.get()),
            self._timezone_value(),
            self.language_code,
            bool(self.show_horizon_circle.get()),
            bool(self.show_altitude_circles.get()),
            self.map_mode.get(),
        )
        threading.Thread(target=self._worker, args=job, daemon=True).start()

    def _worker(
        self,
        lights: list[Path],
        locations: dict[Path, str],
        north_angles: dict[Path, float],
        orientation_matrices: dict[Path, np.ndarray],
        orientation_info: dict[Path, dict[str, object]],
        wcs_solutions: dict[Path, dict[str, object]],
        site_coordinates: dict[Path, tuple[float, float]],
        dark_paths: list[Path],
        output_path: str,
        display_scale: int,
        source_timezone: str,
        language: str,
        show_horizon_circle: bool,
        show_altitude_circles: bool,
        map_mode: str,
    ) -> None:
        errors: list[str] = []
        for index, light in enumerate(lights, start=1):
            try:
                exif = read_exif(light)
                selected_mode = map_mode
                if selected_mode == "auto":
                    selected_mode = (
                        "rectilinear"
                        if light in wcs_solutions or (exif.focal_length_mm or 0.0) > 10.0
                        else "fisheye"
                    )
                vignetting_calibration_path = self._automatic_vignetting_path(light, selected_mode)
                photometric_calibration_path = self._automatic_photometric_path(light, selected_mode)
                if vignetting_calibration_path:
                    self.messages.put(
                        ("log", f"Automaticky vybrán profil vinětace: {vignetting_calibration_path}")
                    )
                if photometric_calibration_path:
                    self.messages.put(
                        ("log", f"Automaticky vybrán hvězdný fotometrický profil: {photometric_calibration_path}")
                    )
                process_file(
                    light,
                    dark_paths,
                    output_path,
                    display_scale=display_scale,
                    progress=lambda text: self.messages.put(("log", text)),
                    location=locations.get(light),
                    source_timezone=source_timezone,
                    north_angle_deg=north_angles.get(light),
                    orientation_matrix=orientation_matrices.get(light),
                    orientation_info=orientation_info.get(light),
                    vignetting_calibration_path=vignetting_calibration_path,
                    photometric_calibration_path=photometric_calibration_path,
                    language=language,
                    show_horizon_circle=show_horizon_circle,
                    show_altitude_circles=show_altitude_circles,
                    projection_mode=selected_mode,
                    wcs_solution=wcs_solutions.get(light),
                    site_coordinates=site_coordinates.get(light),
                )
            except Exception as exc:
                errors.append(f"{light.name}: {exc}")
                self.messages.put(("log", f"CHYBA {light.name}: {exc}"))
            self.messages.put(("progress", index))
        self.messages.put(("done", errors))

    def _poll_messages(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "log":
                    self._write_log(str(payload))
                elif kind == "progress":
                    self.progress.configure(value=int(payload))
                elif kind == "done":
                    self.start_button.configure(state="normal")
                    errors = list(payload)
                    if errors:
                        messagebox.showwarning("Dokončeno s chybami", "\n".join(errors))
                    else:
                        messagebox.showinfo("Hotovo", "Všechny snímky byly úspěšně zpracovány.")
                elif kind == "ext_log":
                    self._write_extinction(str(payload))
                elif kind == "ext_preview":
                    preview, preview_shown = payload
                    self._show_extinction_plot(preview)
                    self._write_extinction("Fit je hotový – graf je zobrazen, ukládám výstupy…")
                    preview_shown.set()
                elif kind == "ext_done":
                    self.extinction_progress.stop()
                    self.extinction_button.configure(state="normal")
                    result, paths = payload
                    self.last_extinction_result = result
                    color = (
                        f"\nBarevný člen C: {result.color_coefficient:+.4f} mag/(B−V)"
                        if result.color_coefficient is not None
                        else "\nBarevný člen: nebyl fitován"
                    )
                    aperture_text = (
                        f"Apertura: {result.aperture_mode}, "
                        f"r = {result.aperture_radius_px:g} px"
                        + (
                            f" ({result.aperture_calibration_stars} kalibračních hvězd)"
                            if result.aperture_mode == "auto"
                            else ""
                        )
                    )
                    aperture_path_text = (
                        f"Kontrola apertur: {paths[3]}" if len(paths) > 3 else ""
                    )
                    dark_text = ", ".join(Path(path).name for path in result.darks_used)
                    flat_text = (
                        Path(result.vignetting_calibration_used).name
                        if result.vignetting_calibration_used not in (None, "built-in")
                        else tr("vestavěná korekce sestavy")
                    )
                    self.photometric_input_status.configure(
                        text=tr("Poslední kalibrovaný vstup:")
                        + f" {Path(result.source).name} · Dark: {dark_text} · Flat: {flat_text}"
                    )
                    self._write_extinction(
                        "\nVÝSLEDEK (experimentální)\n"
                        f"Extinkce k: {result.extinction_mag_per_airmass:.4f} "
                        f"± {result.extinction_std_error:.4f} mag/airmass\n"
                        f"Použité hvězdy: {result.used_stars}/{result.measured_stars} změřených "
                        f"({result.catalog_candidates} kandidátů)\n"
                        f"Rozsah vzdušné hmoty: {result.airmass_min:.2f}–{result.airmass_max:.2f}"
                        f"\nRMS fitu: {result.fit_rms_mag:.3f} mag"
                        f"{color}\nStřed expozice: {result.mid_exposure_utc}\n"
                        f"Dark: {dark_text}\nFlat / vinětace: {flat_text}\n"
                        f"{aperture_text}\n"
                        f"JSON: {paths[0]}\nCSV hvězd: {paths[1]}\n"
                        f"Bouguerův graf: {paths[2]}\n"
                        f"{aperture_path_text}"
                    )
                elif kind == "ext_error":
                    self.extinction_progress.stop()
                    self.extinction_button.configure(state="normal")
                    self._write_extinction(f"\nCHYBA: {payload}")
                    messagebox.showerror("Extinkci nelze změřit", str(payload))
                elif kind == "vign_log":
                    self._write_vignetting(str(payload))
                elif kind == "vign_preview":
                    preview, preview_shown = payload
                    self._show_vignetting_plot(preview)
                    self._write_vignetting("Fit je hotový – zobrazuji profil a ukládám JSON…")
                    preview_shown.set()
                elif kind == "vign_done":
                    self.vignetting_progress.stop()
                    self.vignetting_button.configure(state="normal")
                    calibration, profile_path, plot_path = payload
                    managed_path = self.vignetting_registry.store(calibration)
                    self._refresh_vignetting_profiles()
                    rms = ", ".join(
                        f"{channel} {calibration.fit_rms_percent[channel]:.2f} %"
                        for channel in ("R", "G", "B")
                    )
                    comparison = []
                    for radius in (0.5, 0.8, 1.0):
                        green = math.exp(
                            sum(
                                coefficient * radius ** (2 * (index + 1))
                                for index, coefficient in enumerate(
                                    calibration.coefficients["G"]
                                )
                            )
                        )
                        if calibration.projection == "fisheye_equisolid":
                            reference_profile = profile_for_camera(calibration.camera_model)
                            original = float(np.polyval(
                                reference_profile.vignetting_coefficients, radius
                            ))
                            comparison.append(
                                f"r={radius:.1f}: nový G {green:.3f}, Hollan {original:.3f}"
                            )
                        else:
                            comparison.append(f"r={radius:.1f}: propustnost G {green:.3f}")
                    self._write_vignetting(
                        f"\nPROFIL ULOŽEN\n{profile_path}\nGraf: {plot_path}\n"
                        f"RMS fitu: {rms}\n"
                        + "Srovnání propustnosti: " + "; ".join(comparison) + "\n"
                        "Profil byl přidán do automatického správce."
                    )
                    messagebox.showinfo(
                        "Kalibrace vinětace dokončena",
                        f"Profil byl uložen a přidán do správce.\n\n{managed_path}",
                    )
                elif kind == "vign_error":
                    self.vignetting_progress.stop()
                    self.vignetting_button.configure(state="normal")
                    self._write_vignetting(f"\nCHYBA: {payload}")
                    messagebox.showerror("Vinětaci nelze zkalibrovat", str(payload))
                elif kind == "astap_log":
                    self._write_photometric(str(payload))
                elif kind == "astap_done":
                    self.astap_progress.stop()
                    self.astap_button.configure(state="normal")
                    solution, output = payload
                    source = Path(solution.source)
                    if source in self.lights:
                        self.wcs_solutions[source] = solution.report()
                        self._refresh_lights()
                    self._write_photometric(
                        "ASTAP WCS VYŘEŠENO\n"
                        f"Střed: RA {solution.center_ra_deg:.5f}°, "
                        f"Dec {solution.center_dec_deg:+.5f}°\n"
                        f"Pole: {solution.field_width_deg:.3f} × "
                        f"{solution.field_height_deg:.3f}°\n"
                        f"Měřítko: {solution.pixel_scale_x_arcsec:.2f} × "
                        f"{solution.pixel_scale_y_arcsec:.2f} arcsec/pixel\n"
                        f"JSON WCS: {output}"
                    )
                    messagebox.showinfo("Astrometrie dokončena", "ASTAP úspěšně vyřešil WCS snímku.")
                elif kind == "astap_error":
                    self.astap_progress.stop()
                    self.astap_button.configure(state="normal")
                    self._write_photometric(f"\nASTAP CHYBA: {payload}")
                    messagebox.showerror("ASTAP snímek nevyřešil", str(payload))
        except queue.Empty:
            pass
        self.after(100, self._poll_messages)


def main() -> None:
    PyRaw2LumApp().mainloop()


if __name__ == "__main__":
    main()
