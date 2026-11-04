from __future__ import annotations

import ctypes
import copy
import heapq
import json
import math
import os
import tempfile
import tkinter as tk
import uuid
import zipfile
import zlib
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk
import darkdetect


APP_NAME = "Planet Database"
APP_VERSION = "0.10.0"
APP_ICON_PATH = Path(__file__).with_name("icons") / "planet-database.ico"
DATABASE_FILENAME = "planet-systems.json"
APP_SETTINGS_FILENAME = "app-settings.json"
LEGACY_SETTINGS_FILENAME = "settings.json"
LIGHTYEARS_PER_GRID_STEP = 1_000
INITIAL_SPACING = 16.0
MIN_SPACING = 8.0
MAX_SPACING = 32768.0
GRID_LINE_SPACING_FACTOR = 2
DEFAULT_CAMERA_YAW = math.radians(-45.0)
DEFAULT_CAMERA_ELEVATION = math.acos(math.sqrt(2.0 / 3.0))
MIN_CAMERA_ELEVATION = math.radians(8.0)
MAX_CAMERA_ELEVATION = math.radians(88.0)
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
PANEL = ("#f5f5f5", "#171717")
APP_BACKGROUND = ("#e9e9e9", "#0b0b0b")
CANVAS_BACKGROUND = ("#f8f8f8", "#070707")
GRID = ("#c9c9c9", "#333333")
SUBGRID = ("#e1e1e1", "#202020")
TEXT = ("#252525", "#ededed")
MUTED = ("#6b6b6b", "#a5a5a5")
ACCENT = ("#656565", "#b6b6b6")
MAX_COORDINATE_LIGHTYEARS = 10**15
DEFAULT_STAR_TYPE = "yellow_dwarf"
STAR_TYPES: dict[str, tuple[str, str, str, int]] = {
    "yellow_dwarf": ("Yellow dwarf", "#f6c94b", "circle", 5),
    "red_dwarf": ("Red dwarf", "#e05c52", "circle", 4),
    "orange_dwarf": ("Orange dwarf", "#ee9147", "circle", 5),
    "brown_dwarf": ("Brown dwarf", "#a96f58", "circle", 4),
    "white_dwarf": ("White dwarf", "#eaf7ff", "circle", 6),
    "red_giant": ("Red giant", "#e45845", "circle", 8),
    "orange_giant": ("Orange giant", "#f08c3d", "circle", 8),
    "blue_giant": ("Blue giant", "#68aaff", "circle", 8),
    "wolf_rayet": ("Wolf–Rayet star", "#e98cff", "cross", 7),
    "neutron_star": ("Neutron star", "#80eaff", "diamond", 4),
    "pulsar": ("Pulsar", "#55ddff", "pulsar", 5),
    "black_hole": ("Black hole", "#bb91ff", "black_hole", 6),
    "binary_star": ("Binary star", "#ffd56a", "binary", 6),
    "trinary_star": ("Trinary star", "#ffd56a", "trinary", 7),
}
STAR_TYPE_LABELS = {
    details[0]: star_type for star_type, details in STAR_TYPES.items()
}


def _theme_color(color: str | tuple[str, str], is_dark: bool) -> str:
    if isinstance(color, str):
        return color
    return color[1 if is_dark else 0]


def nearest_systems(
    systems: list[dict[str, Any]],
    coordinates: tuple[int | float, int | float, int | float],
    *,
    exclude_id: str | None = None,
    limit: int = 4,
) -> list[tuple[dict[str, Any], float]]:
    x, y, z = coordinates
    return heapq.nsmallest(
        limit,
        (
            (
                system,
                math.dist((x, y, z), (system["x"], system["y"], system["z"])),
            )
            for system in systems
            if system["id"] != exclude_id
        ),
        key=lambda item: item[1],
    )


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


def app_settings_path() -> Path:
    return app_data_directory() / APP_SETTINGS_FILENAME


def default_app_settings() -> dict[str, Any]:
    return {"panelWidths": {"catalog": 310, "editor": 350}}


def load_app_settings(path: Path | None = None) -> dict[str, Any]:
    settings_path = path or app_settings_path()
    if not settings_path.exists():
        return default_app_settings()
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read application settings:\n{exc}") from exc
    if not isinstance(settings, dict):
        raise ValueError("The application settings file must contain a JSON object.")

    panel_widths = settings.get("panelWidths", {})
    if not isinstance(panel_widths, dict):
        raise ValueError("The application panel width settings are invalid.")
    defaults = default_app_settings()["panelWidths"]
    widths: dict[str, int] = {}
    for panel, default in defaults.items():
        width = panel_widths.get(panel, default)
        minimum = 220 if panel == "catalog" else 290
        if type(width) is not int or not minimum <= width <= 900:
            raise ValueError(f"The saved {panel} panel width is invalid.")
        widths[panel] = width
    return {"panelWidths": widths}


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
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return False
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return False
    return (
        decimal_value.is_finite()
        and -MAX_COORDINATE_LIGHTYEARS
        <= decimal_value
        <= MAX_COORDINATE_LIGHTYEARS
        and decimal_value.normalize().as_tuple().exponent >= -5
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
    systems = data.get("systems")
    if isinstance(systems, list):
        migrated_systems = [
            {**system, "starType": "white_dwarf"}
            if isinstance(system, dict) and system.get("starType") == "white_star"
            else system
            for system in systems
        ]
        if migrated_systems != systems:
            return _validate_systems({**data, "systems": migrated_systems}), True
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
    seen_locations: set[tuple[int | float, int | float, int | float]] = set()
    for system in systems:
        if not isinstance(system, dict):
            raise ValueError("The database contains an invalid system record.")
        system_id = system.get("id")
        name = system.get("name")
        notes = system.get("notes", "")
        x, y, z = (system.get(axis) for axis in ("x", "y", "z"))
        if (
            not isinstance(system_id, str)
            or not system_id
            or system_id in seen_ids
            or not isinstance(name, str)
            or not name.strip()
            or len(name) > 80
            or not isinstance(notes, str)
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


def project_3d(
    x: float,
    y: float,
    z: float,
    center_x: float,
    center_y: float,
    spacing: float,
    yaw: float = DEFAULT_CAMERA_YAW,
    elevation: float = DEFAULT_CAMERA_ELEVATION,
) -> tuple[float, float, float]:
    """Project a 3D light-year coordinate into camera space and return depth."""
    x_units = x / LIGHTYEARS_PER_GRID_STEP
    y_units = y / LIGHTYEARS_PER_GRID_STEP
    z_units = z / LIGHTYEARS_PER_GRID_STEP
    sin_yaw = math.sin(yaw)
    cos_yaw = math.cos(yaw)
    sin_elevation = math.sin(elevation)
    cos_elevation = math.cos(elevation)
    scale = spacing / math.cos(DEFAULT_CAMERA_ELEVATION)
    screen_x = center_x + scale * (cos_yaw * x_units + sin_yaw * y_units)
    screen_y = center_y - scale * (
        sin_yaw * sin_elevation * x_units
        - cos_yaw * sin_elevation * y_units
        + cos_elevation * z_units
    )
    depth = (
        -sin_yaw * cos_elevation * x_units
        + cos_yaw * cos_elevation * y_units
        + sin_elevation * z_units
    )
    return screen_x, screen_y, depth


def screen_to_ground_units(
    screen_x: float,
    screen_y: float,
    center_x: float,
    center_y: float,
    spacing: float,
    yaw: float = DEFAULT_CAMERA_YAW,
    elevation: float = DEFAULT_CAMERA_ELEVATION,
) -> tuple[float, float]:
    scale = spacing / math.cos(DEFAULT_CAMERA_ELEVATION)
    projected_x = (screen_x - center_x) / scale
    projected_y = -(screen_y - center_y) / (scale * math.sin(elevation))
    sin_yaw = math.sin(yaw)
    cos_yaw = math.cos(yaw)
    return (
        cos_yaw * projected_x + sin_yaw * projected_y,
        sin_yaw * projected_x - cos_yaw * projected_y,
    )


def snap_to_grid(
    screen_x: float,
    screen_y: float,
    center_x: float,
    center_y: float,
    spacing: float,
    yaw: float = DEFAULT_CAMERA_YAW,
    elevation: float = DEFAULT_CAMERA_ELEVATION,
) -> tuple[int, int] | None:
    """Snap to the nearest visible, unbounded ground-plane grid intersection."""
    subdivision_factor = grid_subdivision_factor(spacing)
    grid_step = LIGHTYEARS_PER_GRID_STEP / subdivision_factor
    unit_x, unit_y = screen_to_ground_units(
        screen_x, screen_y, center_x, center_y, spacing, yaw, elevation
    )
    base_x = round(unit_x * subdivision_factor)
    base_y = round(unit_y * subdivision_factor)

    nearest: tuple[int, int, float] | None = None
    for x in range(base_x - 2, base_x + 3):
        for y in range(base_y - 2, base_y + 3):
            point_x, point_y, _depth = project_3d(
                x * grid_step,
                y * grid_step,
                0,
                center_x,
                center_y,
                spacing,
                yaw,
                elevation,
            )
            distance = math.hypot(point_x - screen_x, point_y - screen_y)
            if nearest is None or distance < nearest[2]:
                nearest = (x, y, distance)

    grid_x, grid_y, _depth = project_3d(
        grid_step, 0, 0, 0, 0, spacing, yaw, elevation
    )
    x_spacing = math.hypot(grid_x, grid_y)
    grid_x, grid_y, _depth = project_3d(
        0, grid_step, 0, 0, 0, spacing, yaw, elevation
    )
    y_spacing = math.hypot(grid_x, grid_y)
    if nearest is None or nearest[2] > min(x_spacing, y_spacing) * 0.6:
        return None
    return round(nearest[0] * grid_step), round(nearest[1] * grid_step)


def viewport_ground_bounds(
    width: int,
    height: int,
    center_x: float,
    center_y: float,
    spacing: float,
    subdivisions: int = 1,
    yaw: float = DEFAULT_CAMERA_YAW,
    elevation: float = DEFAULT_CAMERA_ELEVATION,
) -> tuple[int, int, int, int]:
    corners = [
        screen_to_ground_units(x, y, center_x, center_y, spacing, yaw, elevation)
        for x, y in ((0, 0), (width, 0), (0, height), (width, height))
    ]
    xs = [point[0] * subdivisions for point in corners]
    ys = [point[1] * subdivisions for point in corners]
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
    yaw: float = DEFAULT_CAMERA_YAW,
    elevation: float = DEFAULT_CAMERA_ELEVATION,
) -> tuple[tuple[float, float, float], float]:
    """Find a view centered on saved systems and scaled to fit their projected bounds."""
    if not systems:
        return (0.0, 0.0, 0.0), max_spacing

    coordinates = [
        (
            system["x"] / LIGHTYEARS_PER_GRID_STEP,
            system["y"] / LIGHTYEARS_PER_GRID_STEP,
            system["z"] / LIGHTYEARS_PER_GRID_STEP,
        )
        for system in systems
    ]
    projected = [
        project_3d(
            x * LIGHTYEARS_PER_GRID_STEP,
            y * LIGHTYEARS_PER_GRID_STEP,
            z * LIGHTYEARS_PER_GRID_STEP,
            0.0,
            0.0,
            1.0,
            yaw,
            elevation,
        )[:2]
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


def pan_to_center_coordinates(
    x: float,
    y: float,
    z: float,
    spacing: float,
    yaw: float = DEFAULT_CAMERA_YAW,
    elevation: float = DEFAULT_CAMERA_ELEVATION,
) -> tuple[float, float]:
    projected_x, projected_y, _depth = project_3d(
        x, y, z, 0.0, 0.0, spacing, yaw, elevation
    )
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


def grid_display_interval_lightyears(spacing: float) -> int:
    """Return the visible grid-line spacing without changing placement precision."""
    return grid_interval_lightyears(spacing) * GRID_LINE_SPACING_FACTOR


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
        self.settings_path = app_settings_path()
        self.app_settings_error: str | None = None
        try:
            self.app_settings = load_app_settings(self.settings_path)
        except ValueError as exc:
            self.app_settings = default_app_settings()
            self.app_settings_error = str(exc)
        self.project_data = empty_project()
        self.selected_system_id: str | None = None
        self._is_adding_system = False
        self._hovered_system_id: str | None = None
        self._hover_label_bounds: tuple[int, int, int, int] | None = None
        self._drag_moved = False
        self.spacing = INITIAL_SPACING
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.camera_yaw = DEFAULT_CAMERA_YAW
        self.camera_elevation = DEFAULT_CAMERA_ELEVATION
        self._drag_origin: tuple[int, int, float, float] | None = None
        self._rotation_origin: tuple[
            int, int, float, float, float, float, float, float
        ] | None = None
        self._theme = "Dark" if _system_is_dark() else "Light"
        self.canvas_background = _theme_color(CANVAS_BACKGROUND, self._theme == "Dark")
        self._undo_history: list[dict[str, Any]] = []
        self._redo_history: list[dict[str, Any]] = []
        self._history_limit = 100
        self.editor_panel: ctk.CTkFrame | None = None
        self.editor_content: ctk.CTkScrollableFrame | None = None
        self.editor_header: ctk.CTkFrame | None = None
        self.notes_panel: ctk.CTkFrame | None = None
        self._editor_pack_info: dict[tk.Widget, dict[str, Any]] = {}
        self._scrollable_frames: list[ctk.CTkScrollableFrame] = []
        self._notes_view = False
        self.nearest_system_labels: list[ctk.CTkLabel] = []
        self._nearest_refresh_after: str | None = None
        self._settings_save_after: str | None = None

        self.x_var = tk.StringVar(value="0")
        self.y_var = tk.StringVar(value="0")
        self.z_var = tk.StringVar(value="0")
        self.name_var = tk.StringVar()
        self.star_type_var = tk.StringVar(
            value=STAR_TYPES[DEFAULT_STAR_TYPE][0]
        )
        self.id_var = tk.StringVar()
        self.status_var = tk.StringVar()

        self.root.configure(fg_color=APP_BACKGROUND)
        self._build_ui()
        self.root.bind("<Control-s>", self._on_shortcut_save)
        self.root.bind("<Control-z>", self._on_shortcut_undo)
        self.root.bind("<Control-y>", self._on_shortcut_redo)
        self._load_startup_database()
        self._sync_system_theme()
        if self.app_settings_error is not None:
            messagebox.showerror(
                "Could not load application settings",
                f"{self.app_settings_error}\n\nDefault panel sizes will be used.",
                parent=self.root,
            )
        self.root.protocol("WM_DELETE_WINDOW", self._close_app)
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

    def _on_sash_release(self, _event: tk.Event[tk.PanedWindow]) -> None:
        if self._settings_save_after is not None:
            self.root.after_cancel(self._settings_save_after)
        self._settings_save_after = self.root.after(180, self._persist_panel_widths)

    def _persist_panel_widths(self) -> None:
        self._settings_save_after = None
        panes = self.workspace_body.panes()
        if not panes:
            return
        panel_widths = dict(self.app_settings["panelWidths"])
        catalog = self.workspace_body.nametowidget(panes[0]).winfo_width()
        if catalog >= 220:
            panel_widths["catalog"] = min(catalog, 900)
        pane_names = {str(pane) for pane in panes}
        if self.editor_panel is not None and str(self.editor_panel) in pane_names:
            editor = self.editor_panel.winfo_width()
            if editor >= 290:
                panel_widths["editor"] = min(editor, 900)
        settings = {"panelWidths": panel_widths}
        try:
            atomic_write_json(self.settings_path, settings)
        except OSError as exc:
            self.status_var.set(f"Could not save application settings: {exc}")
            messagebox.showerror(
                "Could not save application settings",
                str(exc),
                parent=self.root,
            )
            return
        self.app_settings = settings

    def _close_app(self) -> None:
        if self._settings_save_after is not None:
            try:
                self.root.after_cancel(self._settings_save_after)
            except tk.TclError:
                pass
            self._settings_save_after = None
        self._persist_panel_widths()
        self.root.destroy()

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

        toolbar = ctk.CTkFrame(self.root, fg_color=PANEL, corner_radius=12)
        toolbar.pack(fill="x", padx=16, pady=(2, 12))
        groups = (
            (
                "SYSTEM",
                (
                    ("Add star", self._new_location, True),
                    ("Save system", self._save_system, False),
                ),
            ),
            (
                "HISTORY",
                (
                    ("Undo  ·  Ctrl+Z", self._undo, False),
                    ("Redo  ·  Ctrl+Y", self._redo, False),
                ),
            ),
            (
                "PROJECT",
                (
                    ("Import", self._import_project, False),
                    ("Export", self._export_project, False),
                ),
            ),
        )
        for group_index, (group_name, actions) in enumerate(groups):
            group = ctk.CTkFrame(toolbar, fg_color="transparent")
            group.pack(side="left", padx=(14 if group_index == 0 else 8, 8), pady=8)
            ctk.CTkLabel(
                group,
                text=group_name,
                text_color=MUTED,
                font=ctk.CTkFont(size=9, weight="bold"),
            ).pack(anchor="w", padx=3, pady=(0, 4))
            action_row = ctk.CTkFrame(group, fg_color="transparent")
            action_row.pack()
            for action_index, (label, command, primary) in enumerate(actions):
                button = ctk.CTkButton(
                    action_row,
                    text=label,
                    width=122 if group_name == "SYSTEM" else 116,
                    height=32,
                    fg_color=ACCENT if primary else ("#e5e5e5", "#242424"),
                    text_color=("#ffffff", "#111111") if primary else TEXT,
                    hover_color=("#d2d2d2", "#363636") if primary else ("#d9d9d9", "#333333"),
                    command=command,
                )
                button.pack(side="left", padx=(0, 5 if action_index == 0 else 0))
                if label.startswith("Save"):
                    self.save_toolbar_button = button
                    button.configure(state="disabled")

        body = tk.PanedWindow(
            self.root,
            orient=tk.HORIZONTAL,
            sashwidth=8,
            sashpad=2,
            sashrelief=tk.FLAT,
            sashcursor="sb_h_double_arrow",
            background=_theme_color(APP_BACKGROUND, self._theme == "Dark"),
            borderwidth=0,
            opaqueresize=True,
        )
        body.bind("<ButtonRelease-1>", self._on_sash_release, add="+")
        self.workspace_body = body
        body.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        sidebar = ctk.CTkFrame(body, width=310, corner_radius=12, fg_color=PANEL)
        sidebar.pack_propagate(False)

        ctk.CTkLabel(
            sidebar,
            text="SYSTEM CATALOG",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT,
            justify="center",
        ).pack(fill="x", padx=16, pady=(16, 4))
        ctk.CTkLabel(
            sidebar,
            text="Select a system to focus it and open its editor.",
            text_color=MUTED,
            font=ctk.CTkFont(size=10),
            wraplength=270,
            justify="center",
        ).pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(
            sidebar,
            text="SAVED SYSTEMS",
            text_color=MUTED,
            font=ctk.CTkFont(size=9, weight="bold"),
            justify="center",
        ).pack(fill="x", padx=16, pady=(0, 7))
        self.system_list = ctk.CTkScrollableFrame(
            sidebar,
            fg_color="transparent",
            scrollbar_button_color=GRID,
            scrollbar_button_hover_color=ACCENT,
        )
        self._scrollable_frames.append(self.system_list)
        self._bind_panel_mouse_wheel_tree(self.system_list)
        self.system_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.system_rows: dict[str, ctk.CTkButton] = {}

        map_panel = ctk.CTkFrame(body, corner_radius=10, fg_color=PANEL)
        self.map_panel = map_panel
        self.canvas = tk.Canvas(
            map_panel,
            background=self.canvas_background,
            highlightthickness=0,
            borderwidth=0,
        )
        self.canvas.pack(fill="both", expand=True, padx=4, pady=4)
        self.canvas.bind("<Configure>", lambda _event: self._draw_grid())
        self.canvas.bind("<Button-3>", self._on_canvas_click)
        self.canvas.bind("<ButtonPress-1>", self._start_pan)
        self.canvas.bind("<B1-Motion>", self._move_pan)
        self.canvas.bind("<ButtonRelease-1>", self._end_pan)
        self.canvas.bind("<ButtonPress-2>", self._start_rotate)
        self.canvas.bind("<B2-Motion>", self._move_rotate)
        self.canvas.bind("<ButtonRelease-2>", self._end_rotate)
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        body.add(
            sidebar,
            minsize=220,
            width=self.app_settings["panelWidths"]["catalog"],
            stretch="never",
        )
        body.add(map_panel, minsize=300, stretch="always")

        ctk.CTkLabel(
            self.root,
            textvariable=self.status_var,
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=10),
        ).pack(fill="x", padx=20, pady=(0, 3))

    def _open_star_editor(self) -> None:
        if self.editor_panel is not None and self.editor_panel.winfo_exists():
            pane_names = {
                str(pane) for pane in self.workspace_body.panes()
            }
            if str(self.editor_panel) not in pane_names:
                self.workspace_body.add(
                    self.editor_panel,
                    before=self.map_panel,
                    minsize=290,
                    width=350,
                    stretch="never",
                )
            self._update_star_editor_mode()
            self._update_nearest_references()
            return

        panel = ctk.CTkFrame(
            self.workspace_body,
            width=self.app_settings["panelWidths"]["editor"],
            corner_radius=12,
            fg_color=PANEL,
        )
        self.editor_panel = panel
        panel.pack_propagate(False)
        self.workspace_body.add(
            panel,
            before=self.map_panel,
            minsize=290,
            width=self.app_settings["panelWidths"]["editor"],
            stretch="never",
        )
        content = ctk.CTkScrollableFrame(
            panel,
            fg_color="transparent",
            scrollbar_button_color=GRID,
            scrollbar_button_hover_color=ACCENT,
        )
        self.editor_content = content
        self._scrollable_frames.append(content)
        content.pack(fill="both", expand=True, padx=12, pady=10)
        header = ctk.CTkFrame(content, fg_color="transparent")
        self.editor_header = header
        header.pack(fill="x", pady=(0, 14))
        title = "Edit star system" if self.selected_system_id else "Add star system"
        self.editor_title = ctk.CTkLabel(
            header,
            text=title,
            text_color=TEXT,
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        self.editor_title.pack(side="left")
        ctk.CTkButton(
            header,
            text="Close",
            width=64,
            height=28,
            fg_color=("gray85", "#242424"),
            text_color=TEXT,
            hover_color=("#d9d9d9", "#333333"),
            command=self._close_star_editor,
        ).pack(side="right")
        ctk.CTkLabel(
            content,
            text="Give this location a name, type, and coordinates.",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(0, 18))

        ctk.CTkLabel(
            content,
            text="SYSTEM NAME",
            text_color=MUTED,
            font=ctk.CTkFont(size=9, weight="bold"),
        ).pack(anchor="w", pady=(0, 5))
        name_entry = ctk.CTkEntry(
            content,
            textvariable=self.name_var,
            placeholder_text="e.g. Kepler's Reach",
            fg_color=("#ffffff", "#101010"),
            border_color=("#a0a0a0", "#858585"),
            text_color=TEXT,
            placeholder_text_color=MUTED,
        )
        name_entry.pack(fill="x")
        self._bind_shortcuts(name_entry)

        ctk.CTkLabel(
            content,
            text="STELLAR TYPE",
            text_color=MUTED,
            font=ctk.CTkFont(size=9, weight="bold"),
        ).pack(anchor="w", pady=(14, 5))
        star_type_list = ctk.CTkScrollableFrame(
            content,
            height=130,
            fg_color=("#eeeeee", "#101010"),
            scrollbar_button_color=GRID,
            scrollbar_button_hover_color=ACCENT,
        )
        self._scrollable_frames.append(star_type_list)
        star_type_list.pack(fill="x")
        for star_type_label in STAR_TYPE_LABELS:
            ctk.CTkRadioButton(
                star_type_list,
                text=star_type_label,
                variable=self.star_type_var,
                value=star_type_label,
                text_color=TEXT,
                fg_color=ACCENT,
                hover_color=("#505050", "#d0d0d0"),
            ).pack(anchor="w", fill="x", padx=8, pady=4)

        ctk.CTkLabel(
            content,
            text="POSITION  ·  LIGHT-YEARS",
            text_color=MUTED,
            font=ctk.CTkFont(size=9, weight="bold"),
        ).pack(anchor="w", pady=(16, 5))
        coordinate_fields = ctk.CTkFrame(content, fg_color="transparent")
        coordinate_fields.pack(fill="x")
        self.coordinate_entries: dict[str, ctk.CTkEntry] = {}
        for column, axis, variable in (
            (0, "X", self.x_var),
            (1, "Y", self.y_var),
            (2, "Z", self.z_var),
        ):
            field = ctk.CTkFrame(coordinate_fields, fg_color="transparent")
            field.grid(row=0, column=column, sticky="ew", padx=(0, 7))
            coordinate_fields.grid_columnconfigure(column, weight=1)
            ctk.CTkLabel(
                field, text=axis, text_color=MUTED, font=ctk.CTkFont(size=10, weight="bold")
            ).pack(anchor="w", pady=(0, 5))
            entry = ctk.CTkEntry(
                field,
                textvariable=variable,
                fg_color=("#ffffff", "#101010"),
                border_color=("#a0a0a0", "#858585"),
                text_color=TEXT,
            )
            entry.pack(fill="x")
            self._bind_shortcuts(entry)
            self.coordinate_entries[axis.lower()] = entry

        ctk.CTkLabel(
            content,
            text="STABLE SYSTEM ID",
            text_color=MUTED,
            font=ctk.CTkFont(size=9, weight="bold"),
        ).pack(anchor="w", pady=(14, 5))
        id_row = ctk.CTkFrame(content, fg_color="transparent")
        id_row.pack(fill="x")
        ctk.CTkEntry(
            id_row,
            textvariable=self.id_var,
            state="readonly",
            font=ctk.CTkFont(family="Consolas", size=10),
            fg_color=("#eeeeee", "#101010"),
            border_color=("#a0a0a0", "#858585"),
            text_color=TEXT,
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(
            id_row,
            text="Copy ID",
            width=72,
            fg_color=("#e5e5e5", "#242424"),
            text_color=TEXT,
            hover_color=("#d9d9d9", "#333333"),
            command=self._copy_system_id,
        ).pack(side="right")

        notes_panel = ctk.CTkFrame(content, fg_color=("#eeeeee", "#101010"))
        self.notes_panel = notes_panel
        notes_panel.pack(fill="x", pady=(18, 12))
        notes_header = ctk.CTkFrame(notes_panel, fg_color="transparent")
        notes_header.pack(fill="x", padx=12, pady=(10, 5))
        ctk.CTkLabel(
            notes_header,
            text="NOTES",
            text_color=TEXT,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(side="left")
        self.notes_text = ctk.CTkTextbox(
            notes_panel,
            height=120,
            wrap="word",
            fg_color=("#ffffff", "#080808"),
            border_color=("#a0a0a0", "#444444"),
            text_color=TEXT,
        )
        self.notes_text.pack(fill="x", padx=10, pady=(0, 10))
        self.notes_text.bind("<Control-s>", self._on_shortcut_save)
        self.notes_text.bind("<Control-z>", self._on_shortcut_undo)
        self.notes_text.bind("<Control-y>", self._on_shortcut_redo)

        reference_panel = ctk.CTkFrame(content, fg_color=("#eeeeee", "#101010"))
        reference_panel.pack(fill="x", pady=(18, 12))
        ctk.CTkLabel(
            reference_panel,
            text="NEAREST SYSTEMS",
            text_color=TEXT,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            reference_panel,
            text="Straight-line 3D distance from this position",
            text_color=MUTED,
            font=ctk.CTkFont(size=9),
        ).pack(anchor="w", padx=12, pady=(0, 5))
        self.nearest_system_labels = []
        for _index in range(4):
            reference = ctk.CTkLabel(
                reference_panel,
                text="",
                text_color=TEXT,
                anchor="w",
                font=ctk.CTkFont(size=10),
            )
            reference.pack(fill="x", padx=12, pady=2)
            self.nearest_system_labels.append(reference)
        ctk.CTkFrame(reference_panel, height=6, fg_color="transparent").pack()

        actions = ctk.CTkFrame(content, fg_color="transparent")
        actions.pack(fill="x", pady=(4, 0))
        self.editor_save_button = ctk.CTkButton(
            actions,
            text="Save system  ·  Ctrl+S",
            fg_color=ACCENT,
            text_color=("#ffffff", "#071713"),
            hover_color=("#505050", "#d0d0d0"),
            command=self._save_system,
        )
        self.editor_save_button.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.delete_star_button = ctk.CTkButton(
            actions,
            text="Delete",
            width=84,
            fg_color=("#e5e5e5", "#2a2a2a"),
            text_color=("#555555", "#c8c8c8"),
            hover_color=("#d7d7d7", "#3a3a3a"),
            command=self._delete_system,
        )
        self.delete_star_button.pack(side="right")

        self._editor_pack_info = {
            widget: widget.pack_info() for widget in content.winfo_children()
        }
        self._bind_panel_mouse_wheel_tree(content)
        for variable in (self.x_var, self.y_var, self.z_var):
            variable.trace_add("write", self._schedule_nearest_refresh)
        self.save_toolbar_button.configure(state="normal")
        self._update_star_editor_mode()
        self._update_nearest_references()
        name_entry.focus_set()

    def _update_star_editor_mode(self) -> None:
        if self.editor_panel is None or not self.editor_panel.winfo_exists():
            return
        if self.selected_system_id is None:
            self.editor_title.configure(text="Add star system")
            self.delete_star_button.configure(state="disabled")
            self.notes_text.configure(state="normal")
        else:
            self.editor_title.configure(
                text=self.name_var.get() if self._notes_view else "Edit star system"
            )
            self.delete_star_button.configure(state="normal")
            self.notes_text.configure(
                state="disabled" if self._notes_view else "normal"
            )

    def _show_notes_view(self) -> None:
        if self.editor_content is None or self.notes_panel is None:
            return
        self._notes_view = True
        for widget in self.editor_content.winfo_children():
            widget.pack_forget()
        self.editor_header.pack(fill="x", pady=(0, 14))
        self.notes_panel.pack(fill="both", expand=True, pady=(18, 12))
        self.notes_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.notes_text.configure(state="disabled")
        self._update_star_editor_mode()

    def _show_system_editor(self) -> None:
        if self.editor_content is None:
            return
        self._notes_view = False
        for widget in self.editor_content.winfo_children():
            widget.pack_forget()
        for widget, options in self._editor_pack_info.items():
            widget.pack(**options)
        self._update_star_editor_mode()

    def _set_notes_text(self, notes: str) -> None:
        self.notes_text.configure(state="normal")
        self.notes_text.delete("1.0", "end")
        if notes:
            self.notes_text.insert("1.0", notes)
        self._update_star_editor_mode()

    def _schedule_nearest_refresh(self, *_args: str) -> None:
        if self._nearest_refresh_after is not None:
            try:
                self.root.after_cancel(self._nearest_refresh_after)
            except tk.TclError:
                pass
        self._nearest_refresh_after = self.root.after(
            180, self._update_nearest_references
        )

    def _update_nearest_references(self) -> None:
        self._nearest_refresh_after = None
        if not self.nearest_system_labels:
            return
        valid_coordinates = True
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
            valid_coordinates = False
            results: list[tuple[dict[str, Any], float]] = []
        else:
            results = nearest_systems(
                self.project_data["systems"],
                coordinates,
                exclude_id=self.selected_system_id,
                limit=len(self.nearest_system_labels),
            )
        for index, label in enumerate(self.nearest_system_labels):
            if index < len(results):
                system, distance = results[index]
                label.configure(
                    text=f"{index + 1}.  {system['name']}  ·  {distance:,.0f} ly"
                )
            else:
                label.configure(
                    text=(
                        "No other saved systems yet"
                        if not self.project_data["systems"]
                        else "Enter valid coordinates to compare"
                        if not valid_coordinates
                        else "—"
                    )
                )
        if self._is_adding_system:
            self._draw_grid()

    def _close_star_editor(self) -> None:
        if self._nearest_refresh_after is not None:
            try:
                self.root.after_cancel(self._nearest_refresh_after)
            except tk.TclError:
                pass
            self._nearest_refresh_after = None
        self.save_toolbar_button.configure(state="disabled")
        if self.editor_panel is not None and self.editor_panel.winfo_exists():
            self.workspace_body.forget(self.editor_panel)
        self.selected_system_id = None
        self._is_adding_system = False
        self.id_var.set("")
        self._refresh_systems()
        self._draw_grid()
        self.status_var.set("Editor closed. Select a star to edit, or add one from the map.")

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
                anchor="center",
                height=48,
                fg_color=(
                    ("#e0e0e0", "#303030")
                    if system_id == self.selected_system_id
                    else ("#eeeeee", "#1a1a1a")
                ),
                text_color=TEXT,
                hover_color=("#dddddd", "#2b2b2b"),
                command=lambda selected_id=system_id: self._select_system_by_id(
                    selected_id, show_notes_only=True
                ),
            )
            row.pack(fill="x", padx=3, pady=3)
            row.bind(
                "<Button-3>",
                lambda event, selected_id=system_id: self._on_catalog_context_click(
                    event, selected_id
                ),
            )
            self._bind_panel_mouse_wheel_tree(row)
            self.system_rows[system_id] = row

    def _select_system_by_id(
        self, system_id: str, *, show_notes_only: bool = False
    ) -> None:
        system = find_system_by_id(self.project_data["systems"], system_id)
        if system is not None:
            self._select_system(system, show_notes_only=show_notes_only)

    def _on_catalog_context_click(
        self, _event: tk.Event[ctk.CTkButton], system_id: str
    ) -> str:
        system = find_system_by_id(self.project_data["systems"], system_id)
        if system is not None:
            self._select_system(system, show_notes_only=False)
        return "break"

    def _select_system(
        self, system: dict[str, Any], *, show_notes_only: bool = False
    ) -> None:
        self.selected_system_id = system["id"]
        self._is_adding_system = False
        self._notes_view = show_notes_only
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
        self._open_star_editor()
        self._update_star_editor_mode()
        self._set_notes_text(system.get("notes", ""))
        if show_notes_only:
            self._show_notes_view()
        else:
            self._show_system_editor()

    def _on_canvas_select_click(self, event: tk.Event[tk.Canvas]) -> None:
        center_x, center_y = self._canvas_center()
        marker = self._nearest_system(event.x, event.y, center_x, center_y)
        if marker is not None:
            self._select_system(marker)
        else:
            self._close_star_editor()

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

        vertical_coordinate = self.z_var.get() if self._is_adding_system else "0"
        location = snap_to_grid(
            event.x,
            event.y,
            center_x,
            center_y,
            self.spacing,
            getattr(self, "camera_yaw", DEFAULT_CAMERA_YAW),
            getattr(self, "camera_elevation", DEFAULT_CAMERA_ELEVATION),
        )
        if location is None:
            self.status_var.set(
                "Click near a visible grid intersection to choose X and Y."
            )
            return

        self.selected_system_id = None
        self._is_adding_system = True
        self._notes_view = False
        self.id_var.set("")
        self.x_var.set(str(location[0]))
        self.y_var.set(str(location[1]))
        self.z_var.set(vertical_coordinate)
        self.name_var.set("")
        self.star_type_var.set(STAR_TYPES[DEFAULT_STAR_TYPE][0])
        self._refresh_systems()
        self._open_star_editor()
        self._show_system_editor()
        self._set_notes_text("")
        self.status_var.set(
            f"New star location: "
            f"({location[0]:,}, {location[1]:,}, {vertical_coordinate}) light-years."
        )
        self._update_nearest_references()
        self._draw_grid()

    def _nearest_system(
        self,
        screen_x: float,
        screen_y: float,
        center_x: float,
        center_y: float,
        max_distance: float = 15.0,
    ) -> dict[str, Any] | None:
        nearest: dict[str, Any] | None = None
        nearest_distance = max_distance
        for system in self.project_data["systems"]:
            x, y, _depth = project_3d(
                system["x"],
                system["y"],
                system["z"],
                center_x,
                center_y,
                self.spacing,
                getattr(self, "camera_yaw", DEFAULT_CAMERA_YAW),
                getattr(self, "camera_elevation", DEFAULT_CAMERA_ELEVATION),
            )
            distance = math.hypot(x - screen_x, y - screen_y)
            if distance < nearest_distance:
                nearest = system
                nearest_distance = distance
        return nearest

    def _read_coordinate(
        self, variable: tk.StringVar, axis: str
    ) -> int | float:
        try:
            value = Decimal(variable.get().replace(",", "").strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(
                f"{axis} must be a number with up to 5 decimal places."
            ) from exc
        if not is_coordinate(value):
            raise ValueError(
                f"{axis} must be between "
                f"{-MAX_COORDINATE_LIGHTYEARS:,} and "
                f"{MAX_COORDINATE_LIGHTYEARS:,} light-years, with no more "
                "than 5 decimal places."
            )
        if value == value.to_integral_value():
            return int(value)
        return float(value)

    def _save_system(self) -> None:
        if (
            self.editor_panel is None
            or not self.editor_panel.winfo_exists()
            or not self.editor_panel.winfo_manager()
        ):
            self.status_var.set("Open a star editor before saving.")
            return
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
                "notes": self.notes_text.get("1.0", "end-1c"),
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
        self._is_adding_system = False
        self.id_var.set(updated["id"])
        self._focus_coordinates(x, y, z, MAX_SPACING)
        self._refresh_systems()
        self._update_star_editor_mode()
        self._update_nearest_references()
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
        self._is_adding_system = False
        self._hovered_system_id = None
        self.id_var.set("")
        self.name_var.set("")
        self.star_type_var.set(STAR_TYPES[DEFAULT_STAR_TYPE][0])
        self._close_star_editor()
        self._refresh_systems()
        if self.project_data["systems"]:
            self._fit_database_view()
        else:
            self._draw_grid()
        self.status_var.set(f"Deleted {system['name']}.")

    def _new_location(self) -> None:
        self.selected_system_id = None
        self._is_adding_system = True
        self._notes_view = False
        self._hovered_system_id = None
        self.id_var.set("")
        self.name_var.set("")
        self.star_type_var.set(STAR_TYPES[DEFAULT_STAR_TYPE][0])
        center_x, center_y = self._canvas_center()
        location = snap_to_grid(
            max(self.canvas.winfo_width(), 2) / 2,
            max(self.canvas.winfo_height(), 2) / 2,
            center_x,
            center_y,
            self.spacing,
        )
        self.x_var.set(str(location[0] if location is not None else 0))
        self.y_var.set(str(location[1] if location is not None else 0))
        self.z_var.set("0")
        self._refresh_systems()
        self._open_star_editor()
        self._show_system_editor()
        self._set_notes_text("")
        self.status_var.set("New star at the map center. Set its details and save.")
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
        self._is_adding_system = False
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
            x,
            y,
            z,
            self.spacing,
            self.camera_yaw,
            self.camera_elevation,
        )

    def _fit_database_view(self) -> None:
        systems = self.project_data["systems"]
        if not systems or not hasattr(self, "canvas"):
            return
        center, spacing = fit_view_to_systems(
            systems,
            max(self.canvas.winfo_width(), 2),
            max(self.canvas.winfo_height(), 2),
            yaw=self.camera_yaw,
            elevation=self.camera_elevation,
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

    def _project(
        self,
        x: float,
        y: float,
        z: float,
        center_x: float,
        center_y: float,
    ) -> tuple[float, float, float]:
        return project_3d(
            x,
            y,
            z,
            center_x,
            center_y,
            self.spacing,
            getattr(self, "camera_yaw", DEFAULT_CAMERA_YAW),
            getattr(self, "camera_elevation", DEFAULT_CAMERA_ELEVATION),
        )

    def _draw_grid(self) -> None:
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        self._hover_label_bounds = None
        width = max(self.canvas.winfo_width(), 2)
        height = max(self.canvas.winfo_height(), 2)
        center_x, center_y = self._canvas_center()
        subdivision_factor = grid_subdivision_factor(self.spacing)
        minimum_x, maximum_x, minimum_y, maximum_y = viewport_ground_bounds(
            width,
            height,
            center_x,
            center_y,
            self.spacing,
            subdivision_factor,
            getattr(self, "camera_yaw", DEFAULT_CAMERA_YAW),
            getattr(self, "camera_elevation", DEFAULT_CAMERA_ELEVATION),
        )
        grid_step = LIGHTYEARS_PER_GRID_STEP / subdivision_factor
        maximum_lines = 3000
        x_coordinates = range(minimum_x, maximum_x + 1)
        y_coordinates = range(minimum_y, maximum_y + 1)
        if len(x_coordinates) + len(y_coordinates) > maximum_lines:
            return

        for fixed_x in x_coordinates:
            if fixed_x % GRID_LINE_SPACING_FACTOR and fixed_x != 0:
                continue
            start = self._project(
                fixed_x * grid_step,
                minimum_y * grid_step,
                0,
                center_x,
                center_y,
            )[:2]
            end = self._project(
                fixed_x * grid_step,
                maximum_y * grid_step,
                0,
                center_x,
                center_y,
            )[:2]
            is_y_axis = fixed_x == 0
            is_major_line = fixed_x % (
                subdivision_factor * GRID_LINE_SPACING_FACTOR
            ) == 0
            self.canvas.create_line(
                *start,
                *end,
                fill=self._palette(
                    ACCENT if is_y_axis else GRID if is_major_line else SUBGRID
                ),
                width=2.5 if is_y_axis else 1,
            )

        for fixed_y in y_coordinates:
            if fixed_y % GRID_LINE_SPACING_FACTOR and fixed_y != 0:
                continue
            start = self._project(
                minimum_x * grid_step,
                fixed_y * grid_step,
                0,
                center_x,
                center_y,
            )[:2]
            end = self._project(
                maximum_x * grid_step,
                fixed_y * grid_step,
                0,
                center_x,
                center_y,
            )[:2]
            is_x_axis = fixed_y == 0
            is_major_line = fixed_y % (
                subdivision_factor * GRID_LINE_SPACING_FACTOR
            ) == 0
            self.canvas.create_line(
                *start,
                *end,
                fill=self._palette(
                    ACCENT if is_x_axis else GRID if is_major_line else SUBGRID
                ),
                width=2.5 if is_x_axis else 1,
            )

        origin_x, origin_y, _depth = self._project(0, 0, 0, center_x, center_y)
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
        vertical_scale = self.spacing * (
            math.cos(getattr(self, "camera_elevation", DEFAULT_CAMERA_ELEVATION))
            / math.cos(DEFAULT_CAMERA_ELEVATION)
        )
        subdivision_spacing = vertical_scale / subdivision_factor
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
                    fill=self._palette(ACCENT),
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
        x_axis_point = self._project(
            LIGHTYEARS_PER_GRID_STEP, 0, 0, origin_x, origin_y
        )
        y_axis_point = self._project(
            0, LIGHTYEARS_PER_GRID_STEP, 0, origin_x, origin_y
        )
        x_spacing = math.hypot(
            x_axis_point[0] - origin_x, x_axis_point[1] - origin_y
        ) / subdivision_factor
        y_spacing = math.hypot(
            y_axis_point[0] - origin_x, y_axis_point[1] - origin_y
        ) / subdivision_factor
        x_stride = max(1, math.ceil(135.0 / x_spacing))
        y_stride = max(1, math.ceil(135.0 / y_spacing))
        for value in range(minimum_x, maximum_x + 1):
            if value == 0 or value % x_stride:
                continue
            screen_x, screen_y, _depth = self._project(
                value * grid_step,
                0,
                0,
                origin_x,
                origin_y,
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
            if value == 0 or value % y_stride:
                continue
            screen_x, screen_y, _depth = self._project(
                0,
                value * grid_step,
                0,
                origin_x,
                origin_y,
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

        x_axis_x, x_axis_y, _depth = self._project(
            LIGHTYEARS_PER_GRID_STEP, 0, 0, origin_x, origin_y
        )
        y_axis_x, y_axis_y, _depth = self._project(
            0, LIGHTYEARS_PER_GRID_STEP, 0, origin_x, origin_y
        )
        self.canvas.create_text(
            x_axis_x,
            x_axis_y,
            text="X+",
            fill=self._palette(ACCENT),
            anchor="center",
            font=("Segoe UI", 9, "bold"),
        )
        self.canvas.create_text(
            y_axis_x,
            y_axis_y,
            text="Y+",
            fill=self._palette(ACCENT),
            anchor="center",
            font=("Segoe UI", 9, "bold"),
        )

    def _draw_systems(self, center_x: float, center_y: float) -> None:
        hovered_system: dict[str, Any] | None = None
        projected_systems = sorted(
            self.project_data["systems"],
            key=lambda system: self._project(
                system["x"],
                system["y"],
                system["z"],
                center_x,
                center_y,
            )[2],
        )
        for system in projected_systems:
            self._draw_vertical_guide(
                system["x"],
                system["y"],
                system["z"],
                center_x,
                center_y,
            )
            screen_x, screen_y, _depth = self._project(
                system["x"],
                system["y"],
                system["z"],
                center_x,
                center_y,
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
            hovered_x, hovered_y, _depth = self._project(
                hovered_system["x"],
                hovered_system["y"],
                hovered_system["z"],
                center_x,
                center_y,
            )
            self._draw_system_name(
                hovered_system["name"],
                hovered_x,
                hovered_y,
                hovered_system.get("starType", DEFAULT_STAR_TYPE),
            )

        if self._is_adding_system:
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
            screen_x, screen_y, _depth = self._project(
                *coordinates, center_x, center_y
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
        elif shape == "trinary":
            component_radius = radius / 2
            component_positions = (
                (screen_x - radius / 2, screen_y + radius / 3, fill),
                (
                    screen_x + radius / 2,
                    screen_y + radius / 3,
                    self._palette(STAR_TYPES["red_dwarf"][1]),
                ),
                (
                    screen_x,
                    screen_y - radius / 2,
                    self._palette(STAR_TYPES["blue_giant"][1]),
                ),
            )
            for component_x, component_y, component_color in component_positions:
                self.canvas.create_oval(
                    component_x - component_radius,
                    component_y - component_radius,
                    component_x + component_radius,
                    component_y + component_radius,
                    fill=component_color,
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
        x: float,
        y: float,
        z: float,
        center_x: float,
        center_y: float,
    ) -> None:
        if z == 0:
            return
        ground_x, ground_y, _depth = self._project(x, y, 0, center_x, center_y)
        system_x, system_y, _depth = self._project(x, y, z, center_x, center_y)
        self.canvas.create_line(
            ground_x,
            ground_y,
            system_x,
            system_y,
            fill=self._palette(MUTED),
            width=1,
            dash=grid_dash_pattern(
                self.spacing
                * (
                    math.cos(
                        getattr(
                            self,
                            "camera_elevation",
                            DEFAULT_CAMERA_ELEVATION,
                        )
                    )
                    / math.cos(DEFAULT_CAMERA_ELEVATION)
                )
            ),
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
                f"{grid_display_interval_lightyears(self.spacing):,} LY"
            ),
            fill=self._palette(MUTED),
            anchor="nw",
            font=("Segoe UI", 9, "bold"),
        )
        self.canvas.create_text(
            width - 14,
            height - 12,
            text=(
                "CLICK STAR TO EDIT  ·  RIGHT-CLICK TO ADD  ·  "
                "LEFT-DRAG TO PAN  ·  MIDDLE-DRAG TO ROTATE  ·  SCROLL TO ZOOM"
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

    def _start_rotate(self, event: tk.Event[tk.Canvas]) -> None:
        width = max(self.canvas.winfo_width(), 2)
        height = max(self.canvas.winfo_height(), 2)
        center_x, center_y = self._canvas_center()
        anchor_x = width / 2
        anchor_y = height / 2
        marker = self._nearest_system(
            anchor_x,
            anchor_y,
            center_x,
            center_y,
            max_distance=math.inf,
        )
        if marker is not None:
            pivot_x = marker["x"]
            pivot_y = marker["y"]
        else:
            ground_x, ground_y = screen_to_ground_units(
                anchor_x,
                anchor_y,
                center_x,
                center_y,
                self.spacing,
                self.camera_yaw,
                self.camera_elevation,
            )
            pivot_x = ground_x * LIGHTYEARS_PER_GRID_STEP
            pivot_y = ground_y * LIGHTYEARS_PER_GRID_STEP
        pivot_screen_x, pivot_screen_y, _depth = self._project(
            pivot_x, pivot_y, 0, center_x, center_y
        )
        self._rotation_origin = (
            event.x,
            event.y,
            self.camera_yaw,
            self.camera_elevation,
            pivot_x,
            pivot_y,
            pivot_screen_x,
            pivot_screen_y,
        )

    def _move_rotate(self, event: tk.Event[tk.Canvas]) -> None:
        if self._rotation_origin is None:
            return
        (
            start_x,
            start_y,
            initial_yaw,
            initial_elevation,
            pivot_x,
            pivot_y,
            anchor_x,
            anchor_y,
        ) = self._rotation_origin
        delta_x = event.x - start_x
        delta_y = event.y - start_y
        if math.hypot(delta_x, delta_y) < 3:
            return
        self.camera_yaw = (initial_yaw + delta_x * 0.008) % math.tau
        self.camera_elevation = min(
            MAX_CAMERA_ELEVATION,
            max(
                MIN_CAMERA_ELEVATION,
                initial_elevation + delta_y * 0.008,
            ),
        )
        width = max(self.canvas.winfo_width(), 2)
        height = max(self.canvas.winfo_height(), 2)
        projected_x, projected_y, _depth = self._project(
            pivot_x, pivot_y, 0, 0.0, 0.0
        )
        self.pan_x = anchor_x - width / 2 - projected_x
        self.pan_y = anchor_y - height / 2 - projected_y
        self._draw_grid()

    def _end_rotate(self, _event: tk.Event[tk.Canvas]) -> None:
        self._rotation_origin = None

    def _on_mouse_wheel(self, event: tk.Event[tk.Canvas]) -> str:
        old_spacing = self.spacing
        zoom_factor = 1.1 if event.delta > 0 else 1 / 1.1
        self.spacing = min(MAX_SPACING, max(MIN_SPACING, old_spacing * zoom_factor))
        if self.spacing == old_spacing:
            return "break"

        center_x, center_y = self._canvas_center()
        ground_x, ground_y = screen_to_ground_units(
            event.x,
            event.y,
            center_x,
            center_y,
            old_spacing,
            self.camera_yaw,
            self.camera_elevation,
        )
        world_x = ground_x * LIGHTYEARS_PER_GRID_STEP
        world_y = ground_y * LIGHTYEARS_PER_GRID_STEP
        base_x = max(self.canvas.winfo_width(), 2) / 2
        base_y = max(self.canvas.winfo_height(), 2) / 2
        projected_x, projected_y, _depth = self._project(
            world_x, world_y, 0, base_x, base_y
        )
        self.pan_x = event.x - projected_x
        self.pan_y = event.y - projected_y
        self._draw_grid()
        return "break"

    def _bind_panel_mouse_wheel_tree(self, widget: tk.Misc) -> None:
        tk.Misc.bind(widget, "<MouseWheel>", self._on_panel_mouse_wheel, add="+")
        tk.Misc.bind(
            widget,
            "<Button-4>",
            lambda event: self._on_panel_mouse_wheel(event, direction=-1),
            add="+",
        )
        tk.Misc.bind(
            widget,
            "<Button-5>",
            lambda event: self._on_panel_mouse_wheel(event, direction=1),
            add="+",
        )
        for child in widget.winfo_children():
            self._bind_panel_mouse_wheel_tree(child)

    def _on_panel_mouse_wheel(
        self, event: tk.Event[tk.Misc], *, direction: int | None = None
    ) -> str | None:
        notes_text = getattr(self, "notes_text", None)
        if notes_text is not None and self._widget_is_within(event.widget, notes_text):
            units = self._mouse_wheel_units(event, direction)
            notes_text._textbox.yview_scroll(units, "units")
            return "break"

        candidates: list[tuple[int, ctk.CTkScrollableFrame]] = []
        for frame in self._scrollable_frames:
            if not frame.winfo_exists():
                continue
            distance = 0
            widget: tk.Misc | None = event.widget
            while widget is not None and widget != frame._parent_canvas:
                widget = getattr(widget, "master", None)
                distance += 1
            if widget == frame._parent_canvas:
                candidates.append((distance, frame))
        if not candidates:
            return None
        _distance, scrollable = min(candidates, key=lambda candidate: candidate[0])

        units = self._mouse_wheel_units(event, direction)
        scrollable._parent_canvas.yview_scroll(units, "units")
        return "break"

    @staticmethod
    def _mouse_wheel_units(
        event: tk.Event[tk.Misc], direction: int | None
    ) -> int:
        if direction is not None:
            return direction * 3
        direction = -1 if event.delta > 0 else 1
        return max(1, round(abs(event.delta) / 120 * 3)) * direction

    @staticmethod
    def _widget_is_within(widget: tk.Misc, ancestor: tk.Misc) -> bool:
        while widget is not None:
            if widget == ancestor:
                return True
            widget = getattr(widget, "master", None)
        return False

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
        self.workspace_body.configure(
            background=_theme_color(APP_BACKGROUND, appearance == "Dark")
        )
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
