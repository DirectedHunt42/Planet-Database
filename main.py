from __future__ import annotations

import ctypes
import copy
import json
import math
import os
import tempfile
import tkinter as tk
import uuid
import zipfile
import zlib
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk
import darkdetect


APP_NAME = "Planet Database"
APP_VERSION = "0.4.0"
APP_ICON_PATH = Path(__file__).with_name("icons") / "planet-database.ico"
DATABASE_FILENAME = "planet-systems.json"
LEGACY_SETTINGS_FILENAME = "settings.json"
LIGHTYEARS_PER_GRID_STEP = 1_000
INITIAL_SPACING = 16.0
MIN_SPACING = 8.0
MAX_SPACING = 512.0
MAX_PROJECT_ARCHIVE_BYTES = 128 * 1024 * 1024
NICE_GRID_INTERVALS_LIGHTYEARS = (
    1,
    2,
    5,
    10,
    20,
    25,
    50,
    100,
    200,
    250,
    500,
    1_000,
)
PANEL = ("#e4e9ef", "#0b111b")
CANVAS_BACKGROUND = ("#f7f9fb", "#060a10")
GRID = ("#becbd7", "#263849")
SUBGRID = ("#d5dee6", "#182733")
TEXT = ("#172735", "#e3edf5")
MUTED = ("#52697c", "#7990a4")
ACCENT = ("#007e98", "#6de3f5")
MAX_COORDINATE_LIGHTYEARS = 10**15
DEFAULT_STAR_TYPE = "yellow_dwarf"
STAR_TYPES: dict[str, tuple[str, str, str, int]] = {
    "yellow_dwarf": ("Yellow dwarf", "#f6c94b", "circle", 5),
    "red_dwarf": ("Red dwarf", "#e05c52", "circle", 4),
    "orange_dwarf": ("Orange dwarf", "#ee9147", "circle", 5),
    "brown_dwarf": ("Brown dwarf", "#a96f58", "circle", 4),
    "white_dwarf": ("White dwarf", "#f3f5ff", "ring", 4),
    "red_giant": ("Red giant", "#e45845", "circle", 8),
    "orange_giant": ("Orange giant", "#f08c3d", "circle", 8),
    "blue_giant": ("Blue giant", "#68aaff", "circle", 8),
    "white_star": ("White star", "#eaf7ff", "circle", 6),
    "wolf_rayet": ("Wolf–Rayet star", "#e98cff", "cross", 7),
    "neutron_star": ("Neutron star", "#80eaff", "diamond", 4),
    "pulsar": ("Pulsar", "#55ddff", "pulsar", 5),
    "black_hole": ("Black hole", "#bb91ff", "black_hole", 6),
    "binary_star": ("Binary star", "#ffd56a", "binary", 6),
}
STAR_TYPE_LABELS = {
    details[0]: star_type for star_type, details in STAR_TYPES.items()
}


def _theme_color(color: str | tuple[str, str], is_dark: bool) -> str:
    if isinstance(color, str):
        return color
    return color[1 if is_dark else 0]


def app_data_directory() -> Path:
    """Return the per-user application data directory."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    if os.name == "nt":
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME


def database_path() -> Path:
    return app_data_directory() / DATABASE_FILENAME


def empty_project() -> dict[str, Any]:
    return {"formatVersion": 2, "coordinateUnit": "light-years", "systems": []}


def create_unique_system_id(existing_ids: set[str]) -> str:
    """Allocate a persistent system ID without accepting a collision."""
    for _attempt in range(10):
        candidate = uuid.uuid4().hex
        if candidate not in existing_ids:
            return candidate
    raise RuntimeError("Could not allocate a unique system ID after 10 attempts.")


def find_system_by_id(
    systems: list[dict[str, Any]], system_id: str
) -> dict[str, Any] | None:
    """Resolve a saved system by its stable ID for future related records."""
    return next((system for system in systems if system["id"] == system_id), None)


def is_coordinate(value: Any) -> bool:
    return (
        type(value) is int
        and -MAX_COORDINATE_LIGHTYEARS <= value <= MAX_COORDINATE_LIGHTYEARS
    )


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically replace a JSON file without leaving a partial database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(data, temp_file, indent=2, ensure_ascii=False)
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
    except OSError:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def export_project_archive(path: Path, data: dict[str, Any]) -> None:
    """Write a validated project database to a single-file .planetdata archive."""
    project = _validate_systems(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
        with zipfile.ZipFile(
            temp_path, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr(
                DATABASE_FILENAME,
                json.dumps(project, indent=2, ensure_ascii=False) + "\n",
            )
        os.replace(temp_path, path)
    except (OSError, RuntimeError, zipfile.BadZipFile):
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _parse_database_contents(contents: str) -> tuple[dict[str, Any], bool]:
    try:
        data = json.loads(contents)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not read the database:\n{exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("The database file must contain a JSON object.")

    version = data.get("formatVersion")
    if version == 1:
        old_systems = data.get("systems")
        if not isinstance(old_systems, list):
            raise ValueError("The previous database's systems list is invalid.")
        migrated_systems = []
        for system in old_systems:
            if not isinstance(system, dict):
                raise ValueError("The previous database contains an invalid system.")
            if not all(
                type(system.get(axis)) is int
                for axis in ("x", "y", "z")
            ):
                raise ValueError("The previous database contains invalid coordinates.")
            migrated_systems.append(
                {
                    **system,
                    "x": system["x"] * LIGHTYEARS_PER_GRID_STEP,
                    "y": system["y"] * LIGHTYEARS_PER_GRID_STEP,
                    "z": system["z"] * LIGHTYEARS_PER_GRID_STEP,
                }
            )
        return _validate_systems({"systems": migrated_systems}), True

    if version != 2 or data.get("coordinateUnit") != "light-years":
        raise ValueError("This database has an unsupported format or coordinate unit.")
    return _validate_systems(data), False


def load_project_archive(path: Path) -> dict[str, Any]:
    """Read a .planetdata archive without extracting its contents to disk."""
    try:
        with zipfile.ZipFile(path, mode="r") as archive:
            entries = archive.infolist()
            if len(entries) != 1 or entries[0].filename != DATABASE_FILENAME:
                raise ValueError(
                    f"The archive must contain only {DATABASE_FILENAME}."
                )
            entry = entries[0]
            if entry.flag_bits & 0x1:
                raise ValueError("Encrypted project archives are not supported.")
            if entry.file_size > MAX_PROJECT_ARCHIVE_BYTES:
                raise ValueError("The project archive database is too large.")
            with archive.open(entry) as database_file:
                contents = database_file.read(MAX_PROJECT_ARCHIVE_BYTES + 1)
            if len(contents) > MAX_PROJECT_ARCHIVE_BYTES:
                raise ValueError("The project archive database is too large.")
        return _parse_database_contents(contents.decode("utf-8"))[0]
    except (
        OSError,
        UnicodeDecodeError,
        zipfile.BadZipFile,
        RuntimeError,
        NotImplementedError,
        zlib.error,
    ) as exc:
        raise ValueError(f"Could not read the project archive:\n{exc}") from exc


def _validate_systems(data: dict[str, Any]) -> dict[str, Any]:
    systems = data.get("systems")
    if not isinstance(systems, list):
        raise ValueError("The database's systems list is invalid.")

    seen_ids: set[str] = set()
    seen_locations: set[tuple[int, int, int]] = set()
    for system in systems:
        if not isinstance(system, dict):
            raise ValueError("The database contains an invalid system record.")
        system_id = system.get("id")
        name = system.get("name")
        x, y, z = (system.get(axis) for axis in ("x", "y", "z"))
        if (
            not isinstance(system_id, str)
            or not system_id
            or system_id in seen_ids
            or not isinstance(name, str)
            or not name.strip()
            or len(name) > 80
            or not all(is_coordinate(value) for value in (x, y, z))
            or (x, y, z) in seen_locations
            or (
                "starType" in system
                and (
                    not isinstance(system["starType"], str)
                    or system["starType"] not in STAR_TYPES
                )
            )
        ):
            raise ValueError("The database contains an invalid or duplicate system.")
        seen_ids.add(system_id)
        seen_locations.add((x, y, z))

    return {
        "formatVersion": 2,
        "coordinateUnit": "light-years",
        "systems": systems,
    }


def load_database(path: Path) -> tuple[dict[str, Any], bool]:
    """Load a current database, migrating version-one grid coordinates if needed."""
    if not path.exists():
        return empty_project(), False

    try:
        contents = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read the database:\n{exc}") from exc

    return _parse_database_contents(contents)


def load_legacy_database(data_directory: Path) -> dict[str, Any]:
    """Read the previous folder-based database for one-time AppData migration."""
    settings_path = data_directory / LEGACY_SETTINGS_FILENAME
    if not settings_path.is_file():
        return empty_project()
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read the previous project settings:\n{exc}") from exc

    if not isinstance(settings, dict):
        raise ValueError("The previous project settings file is invalid.")
    directory_value = settings.get("projectDirectory")
    if not isinstance(directory_value, str) or not directory_value:
        return empty_project()

    previous_path = Path(directory_value) / DATABASE_FILENAME
    if not previous_path.is_file():
        return empty_project()
    data, _migrated = load_database(previous_path)
    return data


def project_isometric(
    x: float,
    y: float,
    z: float,
    center_x: float,
    center_y: float,
    spacing: float,
) -> tuple[float, float]:
    """Project light-year coordinates; one grid division represents 1,000 light-years."""
    x_units = x / LIGHTYEARS_PER_GRID_STEP
    y_units = y / LIGHTYEARS_PER_GRID_STEP
    z_units = z / LIGHTYEARS_PER_GRID_STEP
    return (
        center_x + (x_units - y_units) * math.sqrt(3.0) * spacing / 2.0,
        center_y + (x_units + y_units) * spacing / 2.0 - z_units * spacing,
    )


def screen_to_ground_units(
    screen_x: float,
    screen_y: float,
    center_x: float,
    center_y: float,
    spacing: float,
) -> tuple[float, float]:
    delta_x = (screen_x - center_x) / (math.sqrt(3.0) * spacing / 2.0)
    delta_y = (screen_y - center_y) / (spacing / 2.0)
    return (delta_x + delta_y) / 2.0, (delta_y - delta_x) / 2.0


def snap_to_grid(
    screen_x: float,
    screen_y: float,
    center_x: float,
    center_y: float,
    spacing: float,
) -> tuple[int, int] | None:
    """Snap to the nearest visible, unbounded ground-plane grid intersection."""
    subdivision_factor = grid_subdivision_factor(spacing)
    grid_step = LIGHTYEARS_PER_GRID_STEP / subdivision_factor
    unit_x, unit_y = screen_to_ground_units(
        screen_x, screen_y, center_x, center_y, spacing
    )
    base_x = round(unit_x * subdivision_factor)
    base_y = round(unit_y * subdivision_factor)

    nearest: tuple[int, int, float] | None = None
    for x in range(base_x - 2, base_x + 3):
        for y in range(base_y - 2, base_y + 3):
            point_x, point_y = project_isometric(
                x * grid_step,
                y * grid_step,
                0,
                center_x,
                center_y,
                spacing,
            )
            distance = math.hypot(point_x - screen_x, point_y - screen_y)
            if nearest is None or distance < nearest[2]:
                nearest = (x, y, distance)

    if nearest is None or nearest[2] > spacing / subdivision_factor * 0.6:
        return None
    return round(nearest[0] * grid_step), round(nearest[1] * grid_step)


def viewport_ground_bounds(
    width: int,
    height: int,
    center_x: float,
    center_y: float,
    spacing: float,
) -> tuple[int, int, int, int]:
    corners = [
        screen_to_ground_units(x, y, center_x, center_y, spacing)
        for x, y in ((0, 0), (width, 0), (0, height), (width, height))
    ]
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return (
        math.floor(min(xs)) - 2,
        math.ceil(max(xs)) + 2,
        math.floor(min(ys)) - 2,
        math.ceil(max(ys)) + 2,
    )


def fit_view_to_systems(
    systems: list[dict[str, Any]],
    width: int,
    height: int,
    min_spacing: float = MIN_SPACING,
    max_spacing: float = MAX_SPACING,
    padding: float = 112.0,
) -> tuple[tuple[float, float, float], float]:
    """Find a view centered on saved systems and scaled to fit their projected bounds."""
    if not systems:
        return (0.0, 0.0, 0.0), max_spacing

    coordinates = [
        (system["x"] / LIGHTYEARS_PER_GRID_STEP,
         system["y"] / LIGHTYEARS_PER_GRID_STEP,
         system["z"] / LIGHTYEARS_PER_GRID_STEP)
        for system in systems
    ]
    projected = [
        ((x - y) * math.sqrt(3.0) / 2.0, (x + y) / 2.0 - z)
        for x, y, z in coordinates
    ]
    span_x = max(point[0] for point in projected) - min(
        point[0] for point in projected
    )
    span_y = max(point[1] for point in projected) - min(
        point[1] for point in projected
    )
    available_width = max(min(width - 2.0 * padding, width * 0.9), 1.0)
    available_height = max(min(height - 2.0 * padding, height * 0.9), 1.0)

    scale_limits = [max_spacing]
    if span_x > 0.0:
        scale_limits.append(available_width / span_x)
    if span_y > 0.0:
        scale_limits.append(available_height / span_y)
    spacing = min(max_spacing, max(min_spacing, min(scale_limits)))
    center = tuple(
        sum(point[axis] for point in coordinates) / len(coordinates)
        * LIGHTYEARS_PER_GRID_STEP
        for axis in range(3)
    )
    return (center[0], center[1], center[2]), spacing


def pan_to_center_coordinates(x: float, y: float, z: float, spacing: float) -> tuple[float, float]:
    projected_x, projected_y = project_isometric(x, y, z, 0.0, 0.0, spacing)
    return -projected_x, -projected_y


def format_lightyears(value: int | float) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value:+,} ly"


def grid_subdivision_factor(spacing: float) -> int:
    """Return the base-grid subdivision count for the current zoom."""
    return LIGHTYEARS_PER_GRID_STEP // grid_interval_lightyears(spacing)


def grid_interval_lightyears(spacing: float) -> int:
    """Choose a whole-number, familiar grid interval at the current zoom."""
    target_interval = min(
        LIGHTYEARS_PER_GRID_STEP,
        LIGHTYEARS_PER_GRID_STEP * INITIAL_SPACING / spacing,
    )
    return min(
        NICE_GRID_INTERVALS_LIGHTYEARS,
        key=lambda interval: abs(math.log(interval / target_interval)),
    )


def grid_dash_pattern(spacing: float) -> tuple[int, int]:
    """Scale vertical-guide dash and gap lengths to one grid interval."""
    dash_length = max(
        1,
        round(spacing * grid_interval_lightyears(spacing) / LIGHTYEARS_PER_GRID_STEP),
    )
    return dash_length, dash_length


def _system_is_dark() -> bool:
    try:
        return darkdetect.theme() == "Dark"
    except (OSError, RuntimeError):
        return True


def apply_native_titlebar_theme(root: ctk.CTk, is_dark: bool) -> None:
    """Keep the Windows native title bar in sync without replacing system chrome."""
    if os.name != "nt":
        return
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
        set_attribute = dwmapi.DwmSetWindowAttribute
        set_attribute.restype = ctypes.c_long
        set_attribute.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        )
        value = ctypes.c_int(1 if is_dark else 0)
        hwnd = ctypes.c_void_p(root.winfo_id())
        for attribute in (20, 19):
            result = set_attribute(
                hwnd,
                attribute,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if result == 0:
                return
    except (AttributeError, OSError):
        return


class PlanetDatabaseApp:
    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1260x820")
        self.root.minsize(1000, 680)
        if os.name == "nt":
            self.root.iconbitmap(str(APP_ICON_PATH))

        self.data_path = database_path()
        self.project_data = empty_project()
        self.selected_system_id: str | None = None
        self._hovered_system_id: str | None = None
        self._hover_label_bounds: tuple[int, int, int, int] | None = None
        self._drag_moved = False
        self.spacing = INITIAL_SPACING
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._drag_origin: tuple[int, int, float, float] | None = None
        self._theme = "Dark" if _system_is_dark() else "Light"
        self.canvas_background = _theme_color(CANVAS_BACKGROUND, self._theme == "Dark")
        self._undo_history: list[dict[str, Any]] = []
        self._redo_history: list[dict[str, Any]] = []
        self._history_limit = 100

        self.x_var = tk.StringVar(value="0")
        self.y_var = tk.StringVar(value="0")
        self.z_var = tk.StringVar(value="0")
        self.name_var = tk.StringVar()
        self.star_type_var = tk.StringVar(
            value=STAR_TYPES[DEFAULT_STAR_TYPE][0]
        )
        self.id_var = tk.StringVar()
        self.status_var = tk.StringVar()

        self._build_ui()
        self.root.bind("<Control-s>", self._on_shortcut_save)
        self.root.bind("<Control-z>", self._on_shortcut_undo)
        self.root.bind("<Control-y>", self._on_shortcut_redo)
        self._load_startup_database()
        self._sync_system_theme()
        self.root.after(500, self._poll_system_theme)
        self.root.after(100, self._maximize_window)

    def _maximize_window(self) -> None:
        try:
            if os.name == "nt":
                self.root.state("zoomed")
            else:
                self.root.attributes("-zoomed", True)
        except tk.TclError:
            return
        self.root.after(150, self._fit_database_view)

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self.root, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(16, 8))
        ctk.CTkLabel(
            header,
            text="Planetary Database",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            header,
            text=(
                f"v{APP_VERSION}  ·  "
                f"BASE GRID INTERVAL = {LIGHTYEARS_PER_GRID_STEP:,} LY"
            ),
            text_color=ACCENT,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="right", pady=(5, 0))

        body = ctk.CTkFrame(self.root, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        sidebar = ctk.CTkFrame(body, width=320, corner_radius=10, fg_color=PANEL)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        ctk.CTkLabel(
            sidebar,
            text="STAR SYSTEM",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=MUTED,
        ).pack(anchor="w", padx=18, pady=(18, 8))
        ctk.CTkLabel(
            sidebar,
            text="Coordinates are stored in light-years in your AppData database.",
            text_color=MUTED,
            font=ctk.CTkFont(size=10),
            wraplength=276,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 14))

        coordinate_fields = ctk.CTkFrame(sidebar, fg_color="transparent")
        coordinate_fields.pack(fill="x", padx=18)
        self.coordinate_entries: dict[str, ctk.CTkEntry] = {}
        for column, axis, variable in (
            (0, "X · LY", self.x_var),
            (1, "Y · LY", self.y_var),
            (2, "Z · LY", self.z_var),
        ):
            field = ctk.CTkFrame(coordinate_fields, fg_color="transparent")
            field.grid(row=0, column=column, sticky="ew", padx=(0, 8))
            coordinate_fields.grid_columnconfigure(column, weight=1)
            ctk.CTkLabel(
                field,
                text=axis,
                text_color=MUTED,
                font=ctk.CTkFont(size=10, weight="bold"),
            ).pack(anchor="w", pady=(0, 5))
            entry = ctk.CTkEntry(field, textvariable=variable, width=82)
            entry.pack(fill="x")
            self._bind_shortcuts(entry)
            self.coordinate_entries[axis[0].lower()] = entry

        ctk.CTkLabel(
            sidebar,
            text="SYSTEM NAME",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", padx=18, pady=(16, 5))
        name_entry = ctk.CTkEntry(sidebar, textvariable=self.name_var)
        name_entry.pack(fill="x", padx=18)
        self._bind_shortcuts(name_entry)
        ctk.CTkLabel(
            sidebar,
            text="STAR TYPE",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", padx=18, pady=(12, 5))
        self.star_type_menu = ctk.CTkOptionMenu(
            sidebar,
            variable=self.star_type_var,
            values=list(STAR_TYPE_LABELS),
            fg_color=("#d7e3eb", "#172431"),
            button_color=ACCENT,
            button_hover_color=("#00677d", "#a0eff8"),
            text_color=TEXT,
            dropdown_fg_color=PANEL,
            dropdown_text_color=TEXT,
        )
        self.star_type_menu.pack(fill="x", padx=18)
        ctk.CTkLabel(
            sidebar,
            text="STABLE SYSTEM ID",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", padx=18, pady=(12, 5))
        id_row = ctk.CTkFrame(sidebar, fg_color="transparent")
        id_row.pack(fill="x", padx=18)
        ctk.CTkEntry(
            id_row,
            textvariable=self.id_var,
            state="readonly",
            font=ctk.CTkFont(family="Consolas", size=10),
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(
            id_row,
            text="COPY",
            width=54,
            command=self._copy_system_id,
        ).pack(side="right")
        ctk.CTkButton(
            sidebar,
            text="SAVE SYSTEM",
            fg_color=ACCENT,
            text_color=("#ffffff", "#071016"),
            hover_color=("#00677d", "#a0eff8"),
            command=self._save_system,
        ).pack(fill="x", padx=18, pady=(10, 6))
        ctk.CTkButton(
            sidebar,
            text="NEW LOCATION",
            fg_color=("gray80", "#172431"),
            text_color=TEXT,
            command=self._new_location,
        ).pack(fill="x", padx=18)
        ctk.CTkButton(
            sidebar,
            text="DELETE SYSTEM",
            fg_color=("#f1d8d6", "#48201f"),
            text_color=("#8d2824", "#ffd9d6"),
            hover_color=("#e6b9b5", "#6a2926"),
            command=self._delete_system,
        ).pack(fill="x", padx=18, pady=(6, 0))
        history_buttons = ctk.CTkFrame(sidebar, fg_color="transparent")
        history_buttons.pack(fill="x", padx=18, pady=(6, 0))
        ctk.CTkButton(
            history_buttons,
            text="UNDO  Ctrl+Z",
            fg_color=("gray80", "#172431"),
            text_color=TEXT,
            command=self._undo,
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(
            history_buttons,
            text="REDO  Ctrl+Y",
            fg_color=("gray80", "#172431"),
            text_color=TEXT,
            command=self._redo,
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))
        archive_buttons = ctk.CTkFrame(sidebar, fg_color="transparent")
        archive_buttons.pack(fill="x", padx=18, pady=(6, 0))
        ctk.CTkButton(
            archive_buttons,
            text="EXPORT",
            fg_color=("gray80", "#172431"),
            text_color=TEXT,
            command=self._export_project,
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(
            archive_buttons,
            text="IMPORT",
            fg_color=("gray80", "#172431"),
            text_color=TEXT,
            command=self._import_project,
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        ctk.CTkFrame(sidebar, height=2, fg_color=GRID).pack(
            fill="x", padx=18, pady=16
        )
        ctk.CTkLabel(
            sidebar,
            text="SAVED SYSTEMS",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", padx=18, pady=(0, 7))
        self.system_list = ctk.CTkScrollableFrame(
            sidebar,
            fg_color="transparent",
            scrollbar_button_color=GRID,
            scrollbar_button_hover_color=ACCENT,
        )
        self.system_list.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.system_rows: dict[str, ctk.CTkButton] = {}

        map_panel = ctk.CTkFrame(body, corner_radius=10, fg_color=PANEL)
        map_panel.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.canvas = tk.Canvas(
            map_panel,
            background=self.canvas_background,
            highlightthickness=1,
            highlightbackground="#1a2734",
        )
        self.canvas.pack(fill="both", expand=True, padx=8, pady=8)
        self.canvas.bind("<Configure>", lambda _event: self._draw_grid())
        self.canvas.bind("<Button-3>", self._on_canvas_click)
        self.canvas.bind("<ButtonPress-1>", self._start_pan)
        self.canvas.bind("<B1-Motion>", self._move_pan)
        self.canvas.bind("<ButtonRelease-1>", self._end_pan)
        self.canvas.bind("<ButtonPress-2>", self._start_pan)
        self.canvas.bind("<B2-Motion>", self._move_pan)
        self.canvas.bind("<ButtonRelease-2>", self._end_pan)
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)

        ctk.CTkLabel(
            self.root,
            textvariable=self.status_var,
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=10),
        ).pack(fill="x", padx=20, pady=(0, 8))

    def _load_startup_database(self) -> None:
        try:
            if self.data_path.exists():
                data, migrated = load_database(self.data_path)
                if migrated:
                    atomic_write_json(self.data_path, data)
                self.project_data = data
                status = "Database loaded from AppData."
                if migrated:
                    status = "Older database migrated to light-year coordinates in AppData."
            else:
                data = self._load_legacy_database()
                self.project_data = data
                atomic_write_json(self.data_path, data)
                status = "New database created in AppData."
                if data["systems"]:
                    status = "Previous systems migrated to the AppData database in light-years."
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not load database", str(exc), parent=self.root)
            status = f"Database error: {exc}"

        self._refresh_systems()
        self._draw_grid()
        self.status_var.set(f"{status}  {self.data_path}")

    def _load_legacy_database(self) -> dict[str, Any]:
        return load_legacy_database(app_data_directory())

    def _refresh_systems(self) -> None:
        for row in self.system_rows.values():
            row.destroy()
        self.system_rows.clear()

        for system in sorted(
            self.project_data["systems"],
            key=lambda item: (
                item["x"],
                item["y"],
                item["z"],
                item["name"].casefold(),
            ),
        ):
            system_id = system["id"]
            star_type = STAR_TYPES.get(
                system.get("starType", DEFAULT_STAR_TYPE),
                STAR_TYPES[DEFAULT_STAR_TYPE],
            )[0]
            coordinates = (
                f"{star_type} · X {system['x']:,} · Y {system['y']:,} "
                f"· Z {system['z']:,} ly"
            )
            row = ctk.CTkButton(
                self.system_list,
                text=f"{system['name']}\n{coordinates}",
                anchor="w",
                height=48,
                fg_color=(
                    ("#c8dce4", "#12313b")
                    if system_id == self.selected_system_id
                    else ("#e4e9ef", "#101923")
                ),
                text_color=TEXT,
                hover_color=("#c3d5df", "#173441"),
                command=lambda selected_id=system_id: self._select_system_by_id(
                    selected_id
                ),
            )
            row.pack(fill="x", padx=3, pady=3)
            self.system_rows[system_id] = row

    def _select_system_by_id(self, system_id: str) -> None:
        system = find_system_by_id(self.project_data["systems"], system_id)
        if system is not None:
            self._select_system(system)

    def _select_system(self, system: dict[str, Any]) -> None:
        self.selected_system_id = system["id"]
        self._hovered_system_id = None
        self.id_var.set(system["id"])
        self.x_var.set(str(system["x"]))
        self.y_var.set(str(system["y"]))
        self.z_var.set(str(system["z"]))
        self.name_var.set(system["name"])
        self.star_type_var.set(
            STAR_TYPES.get(
                system.get("starType", DEFAULT_STAR_TYPE),
                STAR_TYPES[DEFAULT_STAR_TYPE],
            )[0]
        )
        self.status_var.set(
            f"Selected {system['name']} at "
            f"({system['x']:,}, {system['y']:,}, {system['z']:,}) light-years."
        )
        self._focus_coordinates(system["x"], system["y"], system["z"], MAX_SPACING)
        self._refresh_systems()
        self._draw_grid()

    def _on_canvas_select_click(self, event: tk.Event[tk.Canvas]) -> None:
        center_x, center_y = self._canvas_center()
        marker = self._nearest_system(event.x, event.y, center_x, center_y)
        if marker is not None:
            self._select_system(marker)

    def _on_canvas_motion(self, event: tk.Event[tk.Canvas]) -> None:
        center_x, center_y = self._canvas_center()
        marker = self._nearest_system(event.x, event.y, center_x, center_y)
        hovered_id = marker["id"] if marker is not None else None
        if (
            hovered_id is None
            and self._hovered_system_id is not None
            and self._hover_label_bounds is not None
        ):
            left, top, right, bottom = self._hover_label_bounds
            if left <= event.x <= right and top <= event.y <= bottom:
                hovered_id = self._hovered_system_id
        if hovered_id != self._hovered_system_id:
            self._hovered_system_id = hovered_id
            self._draw_grid()

    def _on_canvas_click(self, event: tk.Event[tk.Canvas]) -> None:
        center_x, center_y = self._canvas_center()
        marker = self._nearest_system(event.x, event.y, center_x, center_y)
        if marker is not None:
            self._select_system(marker)
            return

        location = snap_to_grid(
            event.x, event.y, center_x, center_y, self.spacing
        )
        if location is None:
            self.status_var.set(
                "Click near a visible grid intersection to choose X and Y."
            )
            return

        self.selected_system_id = None
        self.id_var.set("")
        self.x_var.set(str(location[0]))
        self.y_var.set(str(location[1]))
        self.z_var.set("0")
        self.name_var.set("")
        self.star_type_var.set(STAR_TYPES[DEFAULT_STAR_TYPE][0])
        self._refresh_systems()
        self.status_var.set(
            f"Location selected at "
            f"({location[0]:,}, {location[1]:,}, 0) light-years. Set Z and name it."
        )
        self._draw_grid()

    def _nearest_system(
        self, screen_x: float, screen_y: float, center_x: float, center_y: float
    ) -> dict[str, Any] | None:
        nearest: dict[str, Any] | None = None
        nearest_distance = 15.0
        for system in self.project_data["systems"]:
            x, y = project_isometric(
                system["x"],
                system["y"],
                system["z"],
                center_x,
                center_y,
                self.spacing,
            )
            distance = math.hypot(x - screen_x, y - screen_y)
            if distance < nearest_distance:
                nearest = system
                nearest_distance = distance
        return nearest

    def _read_coordinate(self, variable: tk.StringVar, axis: str) -> int:
        try:
            value = int(variable.get().replace(",", "").strip())
        except ValueError as exc:
            raise ValueError(f"{axis} must be a whole number of light-years.") from exc
        if not is_coordinate(value):
            raise ValueError(
                f"{axis} must be between "
                f"{-MAX_COORDINATE_LIGHTYEARS:,} and {MAX_COORDINATE_LIGHTYEARS:,} light-years."
            )
        return value

    def _save_system(self) -> None:
        name = self.name_var.get().strip()
        if not name or len(name) > 80:
            messagebox.showerror(
                "System name required",
                "Enter a system name between 1 and 80 characters.",
                parent=self.root,
            )
            return

        star_type = STAR_TYPE_LABELS.get(self.star_type_var.get())
        if star_type is None:
            messagebox.showerror(
                "Invalid star type",
                "Choose a star type from the list.",
                parent=self.root,
            )
            return

        try:
            x = self._read_coordinate(self.x_var, "X")
            y = self._read_coordinate(self.y_var, "Y")
            z = self._read_coordinate(self.z_var, "Z")
        except ValueError as exc:
            messagebox.showerror("Invalid coordinates", str(exc), parent=self.root)
            return

        location = (x, y, z)
        for system in self.project_data["systems"]:
            if (
                (system["x"], system["y"], system["z"]) == location
                and system["id"] != self.selected_system_id
            ):
                messagebox.showerror(
                    "Location already used",
                    f"A system already exists at ({x:,}, {y:,}, {z:,}) light-years.",
                    parent=self.root,
                )
                return

        systems = [dict(system) for system in self.project_data["systems"]]
        updated = (
            find_system_by_id(systems, self.selected_system_id)
            if self.selected_system_id is not None
            else None
        )
        if updated is None:
            existing_ids = {system["id"] for system in systems}
            try:
                updated = {"id": create_unique_system_id(existing_ids)}
            except RuntimeError as exc:
                messagebox.showerror("Could not create system ID", str(exc), parent=self.root)
                self.status_var.set(str(exc))
                return
            systems.append(updated)
        updated.update(
            {
                "name": name,
                "x": x,
                "y": y,
                "z": z,
                "starType": star_type,
            }
        )
        updated_data = {
            "formatVersion": 2,
            "coordinateUnit": "light-years",
            "systems": systems,
        }

        try:
            atomic_write_json(self.data_path, updated_data)
        except OSError as exc:
            messagebox.showerror("Could not save system", str(exc), parent=self.root)
            self.status_var.set(f"Could not save database: {exc}")
            return

        if updated_data != self.project_data:
            self._undo_history.append(copy.deepcopy(self.project_data))
            del self._undo_history[:-self._history_limit]
            self._redo_history.clear()
        self.project_data = updated_data
        self.selected_system_id = updated["id"]
        self.id_var.set(updated["id"])
        self._focus_coordinates(x, y, z, MAX_SPACING)
        self._refresh_systems()
        self.status_var.set(
            f"Saved {name} at ({x:,}, {y:,}, {z:,}) light-years."
        )
        self._draw_grid()

    def _delete_system(self) -> None:
        if self.selected_system_id is None:
            self.status_var.set("Select a saved system before deleting it.")
            return
        system = find_system_by_id(
            self.project_data["systems"], self.selected_system_id
        )
        if system is None:
            self.status_var.set("The selected system no longer exists.")
            return
        if not messagebox.askyesno(
            "Delete system?",
            f"Delete {system['name']} permanently from the database?",
            parent=self.root,
        ):
            return

        updated_data = {
            **self.project_data,
            "systems": [
                dict(item)
                for item in self.project_data["systems"]
                if item["id"] != system["id"]
            ],
        }
        try:
            atomic_write_json(self.data_path, updated_data)
        except OSError as exc:
            messagebox.showerror("Could not delete system", str(exc), parent=self.root)
            self.status_var.set(f"Could not delete system: {exc}")
            return

        self._undo_history.append(copy.deepcopy(self.project_data))
        del self._undo_history[:-self._history_limit]
        self._redo_history.clear()
        self.project_data = updated_data
        self.selected_system_id = None
        self._hovered_system_id = None
        self.id_var.set("")
        self.name_var.set("")
        self.star_type_var.set(STAR_TYPES[DEFAULT_STAR_TYPE][0])
        self._refresh_systems()
        if self.project_data["systems"]:
            self._fit_database_view()
        else:
            self._draw_grid()
        self.status_var.set(f"Deleted {system['name']}.")

    def _new_location(self) -> None:
        self.selected_system_id = None
        self._hovered_system_id = None
        self.id_var.set("")
        self.name_var.set("")
        self.star_type_var.set(STAR_TYPES[DEFAULT_STAR_TYPE][0])
        self._refresh_systems()
        self.status_var.set("Choose X, Y, and Z in light-years for a new system.")
        self._draw_grid()

    def _copy_system_id(self) -> None:
        system_id = self.id_var.get()
        if not system_id:
            self.status_var.set("Save or select a system to copy its ID.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(system_id)
        self.status_var.set(f"Copied system ID {system_id}.")

    def _export_project(self) -> None:
        archive_path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export Planet Database",
            defaultextension=".planetdata",
            filetypes=(("Planet Database project", "*.planetdata"),),
            initialfile="planet-database.planetdata",
        )
        if not archive_path:
            return
        try:
            export_project_archive(Path(archive_path), self.project_data)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not export project", str(exc), parent=self.root)
            self.status_var.set(f"Could not export project: {exc}")
            return
        self.status_var.set(f"Project exported to {archive_path}")

    def _import_project(self) -> None:
        archive_path = filedialog.askopenfilename(
            parent=self.root,
            title="Import Planet Database",
            filetypes=(("Planet Database project", "*.planetdata"),),
        )
        if not archive_path:
            return
        try:
            imported_data = load_project_archive(Path(archive_path))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not import project", str(exc), parent=self.root)
            self.status_var.set(f"Could not import project: {exc}")
            return

        current_count = len(self.project_data["systems"])
        imported_count = len(imported_data["systems"])
        if not messagebox.askyesno(
            "Replace current database?",
            (
                f"Import {imported_count} systems from this archive and replace "
                f"the current database of {current_count} systems?"
            ),
            parent=self.root,
        ):
            return

        try:
            atomic_write_json(self.data_path, imported_data)
        except OSError as exc:
            messagebox.showerror("Could not import project", str(exc), parent=self.root)
            self.status_var.set(f"Could not import project: {exc}")
            return

        if imported_data != self.project_data:
            self._undo_history.append(copy.deepcopy(self.project_data))
            del self._undo_history[:-self._history_limit]
            self._redo_history.clear()
        self.project_data = imported_data
        self.selected_system_id = None
        self.id_var.set("")
        self.name_var.set("")
        self.star_type_var.set(STAR_TYPES[DEFAULT_STAR_TYPE][0])
        self.x_var.set("0")
        self.y_var.set("0")
        self.z_var.set("0")
        self._refresh_systems()
        if imported_data["systems"]:
            self._fit_database_view()
        else:
            self._draw_grid()
        self.status_var.set(
            f"Imported {imported_count} systems from {Path(archive_path).name}."
        )

    def _focus_coordinates(
        self,
        x: float,
        y: float,
        z: float,
        spacing: float | None = None,
    ) -> None:
        if spacing is not None:
            self.spacing = min(MAX_SPACING, max(MIN_SPACING, spacing))
        self.pan_x, self.pan_y = pan_to_center_coordinates(
            x, y, z, self.spacing
        )

    def _fit_database_view(self) -> None:
        systems = self.project_data["systems"]
        if not systems or not hasattr(self, "canvas"):
            return
        center, spacing = fit_view_to_systems(
            systems,
            max(self.canvas.winfo_width(), 2),
            max(self.canvas.winfo_height(), 2),
        )
        self._focus_coordinates(*center, spacing)
        self._draw_grid()

    def _apply_history(self, undo: bool) -> None:
        source = self._undo_history if undo else self._redo_history
        destination = self._redo_history if undo else self._undo_history
        if not source:
            self.status_var.set("Nothing to undo." if undo else "Nothing to redo.")
            return

        action = "undo" if undo else "redo"
        if not messagebox.askyesno(
            f"Confirm {action}",
            (
                f"{'Undo' if undo else 'Redo'} the last saved change made "
                "during this session?\n\nUndo and redo history is cleared "
                "when the app closes."
            ),
            parent=self.root,
        ):
            return

        target = source[-1]
        try:
            atomic_write_json(self.data_path, target)
        except OSError as exc:
            messagebox.showerror(
                f"Could not {action}", str(exc), parent=self.root
            )
            self.status_var.set(f"Could not {action}: {exc}")
            return

        source.pop()
        destination.append(copy.deepcopy(self.project_data))
        del destination[:-self._history_limit]
        self.project_data = copy.deepcopy(target)
        if self.selected_system_id is not None:
            selected = find_system_by_id(
                self.project_data["systems"], self.selected_system_id
            )
        else:
            selected = None

        if selected is None:
            self.selected_system_id = None
            self.id_var.set("")
            self.name_var.set("")
            self.star_type_var.set(STAR_TYPES[DEFAULT_STAR_TYPE][0])
            if self.project_data["systems"]:
                selected = self.project_data["systems"][-1]
                self.selected_system_id = selected["id"]

        if selected is not None:
            self._select_system(selected)
        else:
            self._refresh_systems()
            self._draw_grid()
        self.status_var.set(
            "Undid the last saved change." if undo else "Redid the saved change."
        )

    def _undo(self) -> None:
        self._apply_history(undo=True)

    def _redo(self) -> None:
        self._apply_history(undo=False)

    def _on_shortcut_save(self, _event: tk.Event[tk.Misc]) -> str:
        self._save_system()
        return "break"

    def _on_shortcut_undo(self, _event: tk.Event[tk.Misc]) -> str:
        self._undo()
        return "break"

    def _on_shortcut_redo(self, _event: tk.Event[tk.Misc]) -> str:
        self._redo()
        return "break"

    def _bind_shortcuts(self, widget: ctk.CTkEntry) -> None:
        widget.bind("<Control-s>", self._on_shortcut_save)
        widget.bind("<Control-z>", self._on_shortcut_undo)
        widget.bind("<Control-y>", self._on_shortcut_redo)

    def _canvas_center(self) -> tuple[float, float]:
        return (
            max(self.canvas.winfo_width(), 2) / 2 + self.pan_x,
            max(self.canvas.winfo_height(), 2) / 2 + self.pan_y,
        )

    def _draw_grid(self) -> None:
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        self._hover_label_bounds = None
        width = max(self.canvas.winfo_width(), 2)
        height = max(self.canvas.winfo_height(), 2)
        center_x, center_y = self._canvas_center()
        minimum_x, maximum_x, minimum_y, maximum_y = viewport_ground_bounds(
            width, height, center_x, center_y, self.spacing
        )
        subdivision_factor = grid_subdivision_factor(self.spacing)
        grid_step = LIGHTYEARS_PER_GRID_STEP / subdivision_factor
        minimum_x *= subdivision_factor
        maximum_x *= subdivision_factor
        minimum_y *= subdivision_factor
        maximum_y *= subdivision_factor
        maximum_lines = 3000
        x_coordinates = range(minimum_x, maximum_x + 1)
        y_coordinates = range(minimum_y, maximum_y + 1)
        if len(x_coordinates) + len(y_coordinates) > maximum_lines:
            return

        for fixed_x in x_coordinates:
            start = project_isometric(
                fixed_x * grid_step,
                minimum_y * grid_step,
                0,
                center_x,
                center_y,
                self.spacing,
            )
            end = project_isometric(
                fixed_x * grid_step,
                maximum_y * grid_step,
                0,
                center_x,
                center_y,
                self.spacing,
            )
            is_y_axis = fixed_x == 0
            is_major_line = fixed_x % subdivision_factor == 0
            self.canvas.create_line(
                *start,
                *end,
                fill=self._palette(
                    ACCENT if is_y_axis else GRID if is_major_line else SUBGRID
                ),
                width=2.5 if is_y_axis else 1,
            )

        for fixed_y in y_coordinates:
            start = project_isometric(
                minimum_x * grid_step,
                fixed_y * grid_step,
                0,
                center_x,
                center_y,
                self.spacing,
            )
            end = project_isometric(
                maximum_x * grid_step,
                fixed_y * grid_step,
                0,
                center_x,
                center_y,
                self.spacing,
            )
            is_x_axis = fixed_y == 0
            is_major_line = fixed_y % subdivision_factor == 0
            self.canvas.create_line(
                *start,
                *end,
                fill=self._palette(
                    ACCENT if is_x_axis else GRID if is_major_line else SUBGRID
                ),
                width=2.5 if is_x_axis else 1,
            )

        origin_x, origin_y = project_isometric(
            0, 0, 0, center_x, center_y, self.spacing
        )
        if -40 <= origin_x <= width + 40:
            self._draw_axis_z(origin_x, origin_y, height, subdivision_factor)
        self._draw_axis_labels(
            origin_x,
            origin_y,
            minimum_x,
            maximum_x,
            minimum_y,
            maximum_y,
            subdivision_factor,
        )
        self._draw_systems(center_x, center_y)
        self._draw_canvas_legend(width, height)

    def _draw_axis_z(
        self,
        origin_x: float,
        origin_y: float,
        height: int,
        subdivision_factor: int,
    ) -> None:
        grid_step = LIGHTYEARS_PER_GRID_STEP / subdivision_factor
        subdivision_spacing = self.spacing / subdivision_factor
        lowest_z = math.floor((origin_y - height) / subdivision_spacing)
        highest_z = math.ceil(origin_y / subdivision_spacing)
        self.canvas.create_line(
            origin_x,
            origin_y - highest_z * subdivision_spacing,
            origin_x,
            origin_y - lowest_z * subdivision_spacing,
            fill=self._palette(ACCENT),
            width=3,
            arrow=tk.LAST,
        )
        stride = max(1, math.ceil(52.0 / subdivision_spacing))
        for z_units in range(lowest_z, highest_z + 1):
            screen_y = origin_y - z_units * subdivision_spacing
            if z_units % stride == 0:
                lightyears = z_units * grid_step
                self.canvas.create_line(
                    origin_x - 3,
                    screen_y,
                    origin_x + 3,
                    screen_y,
                    fill="#496d80",
                )
                self.canvas.create_text(
                    origin_x + 7,
                    screen_y,
                    text=format_lightyears(lightyears),
                    fill=self._palette(MUTED),
                    anchor="w",
                    font=("Segoe UI", 8),
                )
        self.canvas.create_text(
            origin_x + 8,
            origin_y - highest_z * subdivision_spacing - 4,
            text="Z+ · LY",
            fill=self._palette(MUTED),
            anchor="sw",
            font=("Segoe UI", 8, "bold"),
        )

    def _draw_axis_labels(
        self,
        origin_x: float,
        origin_y: float,
        minimum_x: int,
        maximum_x: int,
        minimum_y: int,
        maximum_y: int,
        subdivision_factor: int,
    ) -> None:
        grid_step = LIGHTYEARS_PER_GRID_STEP / subdivision_factor
        stride = max(
            1,
            math.ceil(
                135.0
                / (math.sqrt(3.0) * self.spacing / subdivision_factor / 2.0)
            ),
        )
        for value in range(minimum_x, maximum_x + 1):
            if value == 0 or value % stride:
                continue
            screen_x, screen_y = project_isometric(
                value * grid_step,
                0,
                0,
                origin_x,
                origin_y,
                self.spacing,
            )
            if -20 <= screen_x <= self.canvas.winfo_width() + 20:
                self.canvas.create_text(
                    screen_x,
                    screen_y + 10,
                    text=format_lightyears(value * grid_step),
                    fill=self._palette(MUTED),
                    anchor="n",
                    font=("Segoe UI", 8),
                )

        for value in range(minimum_y, maximum_y + 1):
            if value == 0 or value % stride:
                continue
            screen_x, screen_y = project_isometric(
                0, value * grid_step,
                0,
                origin_x,
                origin_y,
                self.spacing,
            )
            if -20 <= screen_x <= self.canvas.winfo_width() + 20:
                self.canvas.create_text(
                    screen_x,
                    screen_y + 10,
                    text=format_lightyears(value * grid_step),
                    fill=self._palette(MUTED),
                    anchor="n",
                    font=("Segoe UI", 8),
                )

        self.canvas.create_text(
            origin_x + self.spacing * 1.2,
            origin_y + self.spacing * 0.7,
            text="X+",
            fill=self._palette(ACCENT),
            anchor="w",
            font=("Segoe UI", 9, "bold"),
        )
        self.canvas.create_text(
            origin_x - self.spacing * 1.2,
            origin_y + self.spacing * 0.7,
            text="Y+",
            fill=self._palette(ACCENT),
            anchor="e",
            font=("Segoe UI", 9, "bold"),
        )

    def _draw_systems(self, center_x: float, center_y: float) -> None:
        hovered_system: dict[str, Any] | None = None
        for system in self.project_data["systems"]:
            self._draw_vertical_guide(
                system["x"],
                system["y"],
                system["z"],
                center_x,
                center_y,
            )
            screen_x, screen_y = project_isometric(
                system["x"],
                system["y"],
                system["z"],
                center_x,
                center_y,
                self.spacing,
            )
            selected = system["id"] == self.selected_system_id
            star_type = system.get("starType", DEFAULT_STAR_TYPE)
            self._draw_star_marker(
                star_type,
                screen_x,
                screen_y,
                selected=selected,
            )
            if system["id"] == self._hovered_system_id:
                hovered_system = system

        if hovered_system is not None:
            hovered_x, hovered_y = project_isometric(
                hovered_system["x"],
                hovered_system["y"],
                hovered_system["z"],
                center_x,
                center_y,
                self.spacing,
            )
            self._draw_system_name(
                hovered_system["name"],
                hovered_x,
                hovered_y,
                hovered_system.get("starType", DEFAULT_STAR_TYPE),
            )

        if self.selected_system_id is None:
            try:
                coordinates = tuple(
                    self._read_coordinate(variable, axis)
                    for variable, axis in (
                        (self.x_var, "X"),
                        (self.y_var, "Y"),
                        (self.z_var, "Z"),
                    )
                )
            except ValueError:
                return
            self._draw_vertical_guide(
                *coordinates,
                center_x,
                center_y,
            )
            screen_x, screen_y = project_isometric(
                *coordinates, center_x, center_y, self.spacing
            )
            self.canvas.create_oval(
                screen_x - 7,
                screen_y - 7,
                screen_x + 7,
                screen_y + 7,
                fill=self.canvas_background,
                outline=self._palette(ACCENT),
                width=2,
            )

    def _draw_star_marker(
        self,
        star_type: str,
        screen_x: float,
        screen_y: float,
        *,
        selected: bool,
    ) -> None:
        _label, color, shape, radius = STAR_TYPES.get(
            star_type, STAR_TYPES[DEFAULT_STAR_TYPE]
        )
        fill = self._palette(color)
        outline = self._palette(TEXT) if selected else self._palette(color)
        if selected:
            self.canvas.create_oval(
                screen_x - radius - 4,
                screen_y - radius - 4,
                screen_x + radius + 4,
                screen_y + radius + 4,
                outline=self._palette(ACCENT),
                width=1,
            )

        if shape == "diamond":
            self.canvas.create_polygon(
                screen_x,
                screen_y - radius,
                screen_x + radius,
                screen_y,
                screen_x,
                screen_y + radius,
                screen_x - radius,
                screen_y,
                fill=fill,
                outline=outline,
                width=2 if selected else 1,
            )
        elif shape == "ring":
            self.canvas.create_oval(
                screen_x - radius,
                screen_y - radius,
                screen_x + radius,
                screen_y + radius,
                fill=self.canvas_background,
                outline=fill,
                width=2,
            )
            self.canvas.create_oval(
                screen_x - 1.5,
                screen_y - 1.5,
                screen_x + 1.5,
                screen_y + 1.5,
                fill=fill,
                outline="",
            )
        elif shape == "cross":
            self.canvas.create_line(
                screen_x - radius,
                screen_y - radius,
                screen_x + radius,
                screen_y + radius,
                fill=fill,
                width=2,
            )
            self.canvas.create_line(
                screen_x - radius,
                screen_y + radius,
                screen_x + radius,
                screen_y - radius,
                fill=fill,
                width=2,
            )
            self.canvas.create_oval(
                screen_x - 2,
                screen_y - 2,
                screen_x + 2,
                screen_y + 2,
                fill=fill,
                outline="",
            )
        elif shape == "pulsar":
            self.canvas.create_line(
                screen_x - radius - 3,
                screen_y,
                screen_x + radius + 3,
                screen_y,
                fill=fill,
                width=1,
            )
            self.canvas.create_line(
                screen_x,
                screen_y - radius - 3,
                screen_x,
                screen_y + radius + 3,
                fill=fill,
                width=1,
            )
            self.canvas.create_oval(
                screen_x - radius,
                screen_y - radius,
                screen_x + radius,
                screen_y + radius,
                fill=fill,
                outline=outline,
            )
            self.canvas.create_oval(
                screen_x - 1.5,
                screen_y - 1.5,
                screen_x + 1.5,
                screen_y + 1.5,
                fill=self.canvas_background,
                outline="",
            )
        elif shape == "black_hole":
            self.canvas.create_oval(
                screen_x - radius,
                screen_y - radius,
                screen_x + radius,
                screen_y + radius,
                fill=self.canvas_background,
                outline=fill,
                width=2,
            )
            self.canvas.create_oval(
                screen_x - radius / 2,
                screen_y - radius / 2,
                screen_x + radius / 2,
                screen_y + radius / 2,
                fill="#05070b",
                outline="",
            )
        elif shape == "binary":
            self.canvas.create_oval(
                screen_x - radius,
                screen_y - radius / 2,
                screen_x,
                screen_y + radius / 2,
                fill=fill,
                outline=outline,
                width=1,
            )
            self.canvas.create_oval(
                screen_x,
                screen_y - radius / 2,
                screen_x + radius,
                screen_y + radius / 2,
                fill=self._palette(STAR_TYPES["blue_giant"][1]),
                outline=outline,
                width=1,
            )
        else:
            self.canvas.create_oval(
                screen_x - radius,
                screen_y - radius,
                screen_x + radius,
                screen_y + radius,
                fill=fill,
                outline=outline,
                width=2 if selected else 1,
            )

    def _draw_system_name(
        self, name: str, screen_x: float, screen_y: float, star_type: str
    ) -> None:
        radius = STAR_TYPES.get(star_type, STAR_TYPES[DEFAULT_STAR_TYPE])[3]
        label = self.canvas.create_text(
            screen_x + radius + 7,
            screen_y - radius - 5,
            text=name,
            fill=self._palette(TEXT),
            anchor="sw",
            font=("Segoe UI", 9),
        )
        bounds = self.canvas.bbox(label)
        if bounds is not None:
            padding = 3
            self._hover_label_bounds = (
                bounds[0] - padding,
                bounds[1] - padding,
                bounds[2] + padding,
                bounds[3] + padding,
            )
            background = self.canvas.create_rectangle(
                bounds[0] - padding,
                bounds[1] - padding,
                bounds[2] + padding,
                bounds[3] + padding,
                fill=self._palette(PANEL),
                outline=self._palette(GRID),
                width=1,
            )
            self.canvas.tag_lower(background, label)

    def _draw_vertical_guide(
        self,
        x: int,
        y: int,
        z: int,
        center_x: float,
        center_y: float,
    ) -> None:
        if z == 0:
            return
        ground_x, ground_y = project_isometric(
            x, y, 0, center_x, center_y, self.spacing
        )
        system_x, system_y = project_isometric(
            x, y, z, center_x, center_y, self.spacing
        )
        self.canvas.create_line(
            ground_x,
            ground_y,
            system_x,
            system_y,
            fill=self._palette(MUTED),
            width=1,
            dash=grid_dash_pattern(self.spacing),
        )
        self.canvas.create_oval(
            ground_x - 2,
            ground_y - 2,
            ground_x + 2,
            ground_y + 2,
            fill=self._palette(MUTED),
            outline="",
        )

    def _draw_canvas_legend(self, width: int, height: int) -> None:
        self.canvas.create_text(
            14,
            14,
            text=(
                f"INFINITE GRID  ·  DIVISION = "
                f"{LIGHTYEARS_PER_GRID_STEP / grid_subdivision_factor(self.spacing):,} LY"
            ),
            fill=self._palette(MUTED),
            anchor="nw",
            font=("Segoe UI", 9, "bold"),
        )
        self.canvas.create_text(
            width - 14,
            height - 12,
            text=(
                "LEFT-CLICK SYSTEM TO EDIT  ·  RIGHT-CLICK TO PLACE  ·  "
                "LEFT-DRAG TO PAN  ·  SCROLL TO ZOOM"
            ),
            fill=self._palette(MUTED),
            anchor="se",
            font=("Segoe UI", 8),
        )

    def _start_pan(self, event: tk.Event[tk.Canvas]) -> None:
        self._drag_origin = (event.x, event.y, self.pan_x, self.pan_y)
        self._drag_moved = False

    def _move_pan(self, event: tk.Event[tk.Canvas]) -> None:
        if self._drag_origin is None:
            return
        start_x, start_y, initial_pan_x, initial_pan_y = self._drag_origin
        if math.hypot(event.x - start_x, event.y - start_y) < 4:
            return
        self._drag_moved = True
        self.pan_x = initial_pan_x + event.x - start_x
        self.pan_y = initial_pan_y + event.y - start_y
        self._draw_grid()

    def _end_pan(self, event: tk.Event[tk.Canvas]) -> None:
        if event.num == 1 and not self._drag_moved:
            self._on_canvas_select_click(event)
        self._drag_origin = None
        self._drag_moved = False

    def _on_mouse_wheel(self, event: tk.Event[tk.Canvas]) -> str:
        old_spacing = self.spacing
        zoom_factor = 1.1 if event.delta > 0 else 1 / 1.1
        self.spacing = min(MAX_SPACING, max(MIN_SPACING, old_spacing * zoom_factor))
        if self.spacing == old_spacing:
            return "break"

        center_x, center_y = self._canvas_center()
        ground_x, ground_y = screen_to_ground_units(
            event.x, event.y, center_x, center_y, old_spacing
        )
        world_x = ground_x * LIGHTYEARS_PER_GRID_STEP
        world_y = ground_y * LIGHTYEARS_PER_GRID_STEP
        base_x = max(self.canvas.winfo_width(), 2) / 2
        base_y = max(self.canvas.winfo_height(), 2) / 2
        projected_x, projected_y = project_isometric(
            world_x, world_y, 0, base_x, base_y, self.spacing
        )
        self.pan_x = event.x - projected_x
        self.pan_y = event.y - projected_y
        self._draw_grid()
        return "break"

    def _palette(self, color: str | tuple[str, str]) -> str:
        return _theme_color(color, self._theme == "Dark")

    def _sync_system_theme(self) -> None:
        appearance = "Dark" if _system_is_dark() else "Light"
        ctk.set_appearance_mode("system")
        self._theme = appearance
        self.canvas_background = _theme_color(
            CANVAS_BACKGROUND, appearance == "Dark"
        )
        apply_native_titlebar_theme(self.root, appearance == "Dark")
        self.canvas.configure(background=self.canvas_background)
        self._draw_grid()

    def _poll_system_theme(self) -> None:
        appearance = "Dark" if _system_is_dark() else "Light"
        if appearance != self._theme:
            self._sync_system_theme()
        self.root.after(1500, self._poll_system_theme)


def main() -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("dark-blue")
    root = ctk.CTk()
    PlanetDatabaseApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
