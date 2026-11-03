from __future__ import annotations

import json
import math
import os
import tempfile
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any


APP_NAME = "Planet Database"
PROJECT_FILENAME = "planet-systems.json"
SETTINGS_FILENAME = "settings.json"
GRID_RADIUS = 8
MAX_COORDINATE = 1_000_000
INITIAL_SPACING = 28.0
MIN_SPACING = 12.0
MAX_SPACING = 56.0
BACKGROUND = "#070b12"
PANEL = "#0b111b"
GRID = "#263849"
TEXT = "#e3edf5"
MUTED = "#7990a4"
ACCENT = "#6de3f5"


def app_data_directory() -> Path:
    """Return a per-user settings directory, using Roaming AppData on Windows."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    if os.name == "nt":
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME


def project_file_path(directory: Path) -> Path:
    return directory / PROJECT_FILENAME


def is_coordinate(value: Any) -> bool:
    return type(value) is int and -MAX_COORDINATE <= value <= MAX_COORDINATE


def empty_project() -> dict[str, Any]:
    return {"formatVersion": 1, "systems": []}


def load_project(directory: Path) -> dict[str, Any]:
    """Load and validate project data without discarding malformed files."""
    path = project_file_path(directory)
    if not path.exists():
        return empty_project()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read the project file:\n{exc}") from exc

    if not isinstance(data, dict) or data.get("formatVersion") != 1:
        raise ValueError("This folder contains an unsupported project file.")

    systems = data.get("systems")
    if not isinstance(systems, list):
        raise ValueError("The project's systems list is invalid.")

    seen_ids: set[str] = set()
    seen_locations: set[tuple[int, int, int]] = set()
    for system in systems:
        if not isinstance(system, dict):
            raise ValueError("The project contains an invalid system record.")
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
        ):
            raise ValueError("The project contains an invalid or duplicate system.")
        seen_ids.add(system_id)
        seen_locations.add((x, y, z))

    return {"formatVersion": 1, "systems": systems}


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Replace a JSON file atomically so an interrupted save leaves the old file intact."""
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
            temp_path.unlink(missing_ok=True)
        raise


def save_project(directory: Path, data: dict[str, Any]) -> None:
    atomic_write_json(project_file_path(directory), data)


def project_isometric(
    x: float,
    y: float,
    z: float,
    center_x: float,
    center_y: float,
    spacing: float,
) -> tuple[float, float]:
    """Project world XYZ onto a screen while preserving Z in the stored model."""
    return (
        center_x + (x - y) * math.sqrt(3.0) * spacing / 2.0,
        center_y + (x + y) * spacing / 2.0 - z * spacing,
    )


def snap_to_grid(
    screen_x: float,
    screen_y: float,
    center_x: float,
    center_y: float,
    spacing: float,
) -> tuple[int, int] | None:
    """Find the nearest visible grid intersection at ground level."""
    grid_points = (
        (x, y, *project_isometric(x, y, 0, center_x, center_y, spacing))
        for x in range(-GRID_RADIUS, GRID_RADIUS + 1)
        for y in range(-GRID_RADIUS, GRID_RADIUS + 1)
    )
    nearest = min(
        grid_points,
        key=lambda point: (point[2] - screen_x) ** 2 + (point[3] - screen_y) ** 2,
    )
    distance = math.hypot(nearest[2] - screen_x, nearest[3] - screen_y)
    if distance > spacing * 0.42:
        return None
    return nearest[0], nearest[1]


class PlanetDatabaseApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Planet Database")
        self.root.geometry("1260x820")
        self.root.minsize(1000, 680)
        self.root.configure(bg=BACKGROUND)

        self.project_directory: Path | None = None
        self.project_data = empty_project()
        self.selected_system_id: str | None = None
        self.spacing = INITIAL_SPACING
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._drag_origin: tuple[int, int, float, float] | None = None

        self.x_var = tk.StringVar(value="0")
        self.y_var = tk.StringVar(value="0")
        self.z_var = tk.StringVar(value="0")
        self.name_var = tk.StringVar()
        self.folder_var = tk.StringVar(value="No project folder selected")
        self.status_var = tk.StringVar(value="Choose a project folder to get started.")

        self._configure_theme()
        self._build_ui()
        self._restore_last_project()

    def _configure_theme(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "TFrame",
            background=PANEL,
        )
        style.configure(
            "TLabel",
            background=PANEL,
            foreground=TEXT,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Heading.TLabel",
            background=PANEL,
            foreground=TEXT,
            font=("Segoe UI", 17, "bold"),
        )
        style.configure(
            "Section.TLabel",
            background=PANEL,
            foreground=MUTED,
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "TButton",
            background="#132431",
            foreground="#b7eaf0",
            padding=(10, 8),
            font=("Segoe UI", 9, "bold"),
        )
        style.map("TButton", background=[("active", "#1a3848")])
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="#071016",
        )
        style.map("Accent.TButton", background=[("active", "#a0eff8")])
        style.configure(
            "TEntry",
            fieldbackground="#0e1722",
            foreground=TEXT,
            insertcolor=TEXT,
            padding=7,
        )
        style.configure(
            "TSpinbox",
            fieldbackground="#0e1722",
            foreground=TEXT,
            insertcolor=TEXT,
            padding=6,
        )
        style.configure(
            "Treeview",
            background="#0e1722",
            fieldbackground="#0e1722",
            foreground=TEXT,
            rowheight=27,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background="#14212e",
            foreground=MUTED,
            font=("Segoe UI", 9, "bold"),
            padding=5,
        )
        style.map("Treeview", background=[("selected", "#164354")])

    def _build_ui(self) -> None:
        header = ttk.Frame(self.root, padding=(22, 16))
        header.pack(fill="x")
        ttk.Label(header, text="ORRERY", style="Heading.TLabel").pack(side="left")
        ttk.Label(header, text="3D COORDINATE ATLAS", style="Section.TLabel").pack(
            side="left", padx=(14, 0), pady=(4, 0)
        )

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        sidebar = ttk.Frame(body, padding=18, width=290)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        ttk.Label(sidebar, text="PROJECT FOLDER", style="Section.TLabel").pack(
            anchor="w"
        )
        folder_label = ttk.Label(
            sidebar,
            textvariable=self.folder_var,
            wraplength=248,
            justify="left",
        )
        folder_label.pack(anchor="w", fill="x", pady=(8, 10))
        ttk.Button(
            sidebar, text="CHOOSE PROJECT FOLDER", command=self._choose_project_folder
        ).pack(fill="x")

        ttk.Separator(sidebar).pack(fill="x", pady=18)
        ttk.Label(sidebar, text="STAR SYSTEM", style="Section.TLabel").pack(
            anchor="w", pady=(0, 10)
        )

        coordinates = ttk.Frame(sidebar)
        coordinates.pack(fill="x")
        for column, axis, variable in (
            (0, "X", self.x_var),
            (1, "Y", self.y_var),
            (2, "Z", self.z_var),
        ):
            field = ttk.Frame(coordinates)
            field.grid(row=0, column=column, sticky="ew", padx=(0, 8))
            coordinates.columnconfigure(column, weight=1)
            ttk.Label(field, text=axis, style="Section.TLabel").pack(anchor="w")
            ttk.Spinbox(
                field,
                from_=-MAX_COORDINATE,
                to=MAX_COORDINATE,
                increment=1,
                textvariable=variable,
                width=7,
            ).pack(fill="x", pady=(5, 0))

        ttk.Label(sidebar, text="SYSTEM NAME", style="Section.TLabel").pack(
            anchor="w", pady=(16, 5)
        )
        ttk.Entry(sidebar, textvariable=self.name_var).pack(fill="x")

        self.save_button = ttk.Button(
            sidebar,
            text="SAVE SYSTEM",
            style="Accent.TButton",
            command=self._save_system,
        )
        self.save_button.pack(fill="x", pady=(12, 6))
        ttk.Button(sidebar, text="NEW LOCATION", command=self._new_location).pack(
            fill="x"
        )

        ttk.Separator(sidebar).pack(fill="x", pady=18)
        ttk.Label(sidebar, text="SAVED SYSTEMS", style="Section.TLabel").pack(
            anchor="w", pady=(0, 8)
        )
        self.system_tree = ttk.Treeview(
            sidebar,
            columns=("x", "y", "z"),
            show="tree headings",
            selectmode="browse",
            height=12,
        )
        self.system_tree.heading("#0", text="SYSTEM")
        self.system_tree.heading("x", text="X")
        self.system_tree.heading("y", text="Y")
        self.system_tree.heading("z", text="Z")
        self.system_tree.column("#0", width=128, stretch=True)
        for axis in ("x", "y", "z"):
            self.system_tree.column(axis, width=38, stretch=False, anchor="center")
        self.system_tree.pack(fill="both", expand=True)
        self.system_tree.bind("<<TreeviewSelect>>", self._on_system_selected)

        map_panel = ttk.Frame(body, padding=10)
        map_panel.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.canvas = tk.Canvas(
            map_panel,
            background="#060a10",
            highlightthickness=1,
            highlightbackground="#1a2734",
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self._draw_grid())
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<ButtonPress-3>", self._start_pan)
        self.canvas.bind("<B3-Motion>", self._move_pan)
        self.canvas.bind("<ButtonPress-2>", self._start_pan)
        self.canvas.bind("<B2-Motion>", self._move_pan)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)

        ttk.Label(
            self.root,
            textvariable=self.status_var,
            anchor="w",
            padding=(18, 8),
        ).pack(fill="x")

    def _settings_path(self) -> Path:
        return app_data_directory() / SETTINGS_FILENAME

    def _restore_last_project(self) -> None:
        settings_path = self._settings_path()
        if not settings_path.exists():
            return
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(settings, dict):
                raise ValueError("The saved project folder setting is invalid.")
            saved_directory = settings.get("projectDirectory")
            if not isinstance(saved_directory, str) or not saved_directory:
                raise ValueError("The saved project folder setting is invalid.")
            directory = Path(saved_directory)
            if not directory.is_dir():
                self.status_var.set("The saved project folder is unavailable. Choose a folder.")
                return
            self._open_project_folder(directory, remember=False)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            self.status_var.set(f"Could not restore the last project: {exc}")

    def _choose_project_folder(self) -> None:
        initial = str(self.project_directory or Path.home())
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Choose project folder",
            initialdir=initial,
            mustexist=True,
        )
        if selected:
            self._open_project_folder(Path(selected))

    def _open_project_folder(self, directory: Path, remember: bool = True) -> None:
        try:
            data = load_project(directory)
            if not project_file_path(directory).exists():
                save_project(directory, data)
            if remember:
                atomic_write_json(
                    self._settings_path(),
                    {"settingsVersion": 1, "projectDirectory": str(directory.resolve())},
                )
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not open project", str(exc), parent=self.root)
            self.status_var.set(f"Could not open project: {exc}")
            return

        self.project_directory = directory
        self.project_data = data
        self.folder_var.set(str(directory))
        self.selected_system_id = None
        self.name_var.set("")
        self._refresh_systems()
        self._draw_grid()
        self.status_var.set("Project ready. Click a grid point to choose X and Y.")

    def _refresh_systems(self) -> None:
        self.system_tree.delete(*self.system_tree.get_children())
        for system in sorted(
            self.project_data["systems"],
            key=lambda item: (item["x"], item["y"], item["z"], item["name"].casefold()),
        ):
            system_id = system["id"]
            self.system_tree.insert(
                "",
                "end",
                iid=system_id,
                text=system["name"],
                values=(system["x"], system["y"], system["z"]),
            )

    def _on_system_selected(self, _event: tk.Event[tk.Misc]) -> None:
        selection = self.system_tree.selection()
        if not selection:
            return
        system_id = selection[0]
        system = self._find_system(system_id)
        if system is not None:
            self._select_system(system)

    def _find_system(self, system_id: str) -> dict[str, Any] | None:
        return next(
            (system for system in self.project_data["systems"] if system["id"] == system_id),
            None,
        )

    def _select_system(self, system: dict[str, Any]) -> None:
        self.selected_system_id = system["id"]
        self.x_var.set(str(system["x"]))
        self.y_var.set(str(system["y"]))
        self.z_var.set(str(system["z"]))
        self.name_var.set(system["name"])
        self.status_var.set(
            f"Selected {system['name']} at ({system['x']}, {system['y']}, {system['z']})."
        )
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
            self.status_var.set("Click a visible grid intersection to choose X and Y.")
            return

        self.selected_system_id = None
        self.system_tree.selection_remove(self.system_tree.selection())
        self.x_var.set(str(location[0]))
        self.y_var.set(str(location[1]))
        self.z_var.set("0")
        self.name_var.set("")
        self.status_var.set(
            f"Location selected at ({location[0]}, {location[1]}, 0). Set Z and name the system."
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
            value = int(variable.get())
        except ValueError as exc:
            raise ValueError(f"{axis} must be a whole number.") from exc
        if not is_coordinate(value):
            raise ValueError(f"{axis} must be between -{MAX_COORDINATE} and {MAX_COORDINATE}.")
        return value

    def _save_system(self) -> None:
        if self.project_directory is None:
            messagebox.showinfo(
                "Choose a project folder",
                "Choose a project folder before saving systems.",
                parent=self.root,
            )
            return

        name = self.name_var.get().strip()
        if not name or len(name) > 80:
            messagebox.showerror(
                "System name required",
                "Enter a system name between 1 and 80 characters.",
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
                    f"A system already exists at ({x}, {y}, {z}).",
                    parent=self.root,
                )
                return

        updated_systems = [dict(system) for system in self.project_data["systems"]]
        updated = next(
            (
                system
                for system in updated_systems
                if system["id"] == self.selected_system_id
            ),
            None,
        )
        if updated is None:
            updated = {"id": uuid.uuid4().hex}
            updated_systems.append(updated)
        updated.update({"name": name, "x": x, "y": y, "z": z})
        updated_data = {"formatVersion": 1, "systems": updated_systems}

        try:
            save_project(self.project_directory, updated_data)
        except OSError as exc:
            messagebox.showerror("Could not save system", str(exc), parent=self.root)
            self.status_var.set(f"Could not save system: {exc}")
            return

        self.project_data = updated_data
        self.selected_system_id = updated["id"]
        self._refresh_systems()
        self.system_tree.selection_set(self.selected_system_id)
        self.system_tree.see(self.selected_system_id)
        self.status_var.set(f"Saved {name} at ({x}, {y}, {z}).")
        self._draw_grid()

    def _new_location(self) -> None:
        self.selected_system_id = None
        self.system_tree.selection_remove(self.system_tree.selection())
        self.name_var.set("")
        self.status_var.set("Choose X, Y, and Z for a new system.")
        self._draw_grid()

    def _canvas_center(self) -> tuple[float, float]:
        width = max(self.canvas.winfo_width(), 2)
        height = max(self.canvas.winfo_height(), 2)
        return (
            width / 2 + self.pan_x,
            height / 2 + GRID_RADIUS * self.spacing / 2 + self.pan_y,
        )

    def _draw_grid(self) -> None:
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), 2)
        height = max(self.canvas.winfo_height(), 2)
        center_x, center_y = self._canvas_center()
        radius = GRID_RADIUS
        font = ("Segoe UI", 9)

        for fixed_x in range(-radius, radius + 1):
            points: list[float] = []
            for variable_y in (-radius, radius):
                points.extend(
                    project_isometric(
                        fixed_x, variable_y, 0, center_x, center_y, self.spacing
                    )
                )
            self.canvas.create_line(*points, fill=GRID, width=1)

        for fixed_y in range(-radius, radius + 1):
            points = []
            for variable_x in (-radius, radius):
                points.extend(
                    project_isometric(
                        variable_x, fixed_y, 0, center_x, center_y, self.spacing
                    )
                )
            self.canvas.create_line(*points, fill=GRID, width=1)

        origin_x, origin_y = project_isometric(
            0, 0, 0, center_x, center_y, self.spacing
        )
        top_x, top_y = project_isometric(
            0, 0, radius, center_x, center_y, self.spacing
        )
        self.canvas.create_line(
            origin_x, origin_y, top_x, top_y, fill="#2f5668", dash=(3, 5), width=1
        )
        self.canvas.create_text(
            top_x + 12,
            top_y,
            text="Z+",
            fill=MUTED,
            anchor="w",
            font=font,
        )

        for value in range(-radius, radius + 1):
            x_x, x_y = project_isometric(value, 0, 0, center_x, center_y, self.spacing)
            y_x, y_y = project_isometric(0, value, 0, center_x, center_y, self.spacing)
            self.canvas.create_oval(
                x_x - 2, x_y - 2, x_x + 2, x_y + 2, fill="#4a6579", outline=""
            )
            self.canvas.create_oval(
                y_x - 2, y_y - 2, y_x + 2, y_y + 2, fill="#4a6579", outline=""
            )
        self.canvas.create_text(
            origin_x + (radius + 0.6) * math.sqrt(3) * self.spacing / 2,
            origin_y + (radius + 0.6) * self.spacing / 2,
            text="X+",
            fill="#84b4c8",
            anchor="w",
            font=font,
        )
        self.canvas.create_text(
            origin_x - (radius + 0.6) * math.sqrt(3) * self.spacing / 2,
            origin_y + (radius + 0.6) * self.spacing / 2,
            text="Y+",
            fill="#84b4c8",
            anchor="e",
            font=font,
        )

        selected_coordinates = self._current_coordinates()
        for system in self.project_data["systems"]:
            sx, sy = project_isometric(
                system["x"], system["y"], system["z"], center_x, center_y, self.spacing
            )
            selected = system["id"] == self.selected_system_id
            radius_px = 7 if selected else 5
            self.canvas.create_oval(
                sx - radius_px,
                sy - radius_px,
                sx + radius_px,
                sy + radius_px,
                fill=ACCENT if selected else "#a5c9ed",
                outline="#d4fbff" if selected else "#708ca8",
                width=2 if selected else 1,
            )
            self.canvas.create_text(
                sx + 10,
                sy - 9,
                text=system["name"],
                fill="#d2e6f4",
                anchor="sw",
                font=("Segoe UI", 9),
            )

        if selected_coordinates is not None and self.selected_system_id is None:
            sx, sy = project_isometric(
                *selected_coordinates, center_x, center_y, self.spacing
            )
            self.canvas.create_oval(
                sx - 7,
                sy - 7,
                sx + 7,
                sy + 7,
                fill="#0c2530",
                outline=ACCENT,
                width=2,
            )

        self.canvas.create_text(
            16,
            16,
            text="ISOMETRIC VIEW  ·  INTEGER X / Y / Z",
            fill=MUTED,
            anchor="nw",
            font=("Segoe UI", 9, "bold"),
        )
        self.canvas.create_text(
            width - 16,
            height - 14,
            text="CLICK GRID TO PLACE   ·   RIGHT-DRAG TO PAN   ·   SCROLL TO ZOOM",
            fill=MUTED,
            anchor="se",
            font=("Segoe UI", 8),
        )

    def _current_coordinates(self) -> tuple[int, int, int] | None:
        try:
            return (
                int(self.x_var.get()),
                int(self.y_var.get()),
                int(self.z_var.get()),
            )
        except ValueError:
            return None

    def _start_pan(self, event: tk.Event[tk.Canvas]) -> None:
        self._drag_origin = (event.x, event.y, self.pan_x, self.pan_y)

    def _move_pan(self, event: tk.Event[tk.Canvas]) -> None:
        if self._drag_origin is None:
            return
        start_x, start_y, original_pan_x, original_pan_y = self._drag_origin
        self.pan_x = original_pan_x + event.x - start_x
        self.pan_y = original_pan_y + event.y - start_y
        self._draw_grid()

    def _on_mouse_wheel(self, event: tk.Event[tk.Canvas]) -> str:
        self.spacing = min(
            MAX_SPACING,
            max(MIN_SPACING, self.spacing * (1.1 if event.delta > 0 else 1 / 1.1)),
        )
        self._draw_grid()
        return "break"


def main() -> None:
    root = tk.Tk()
    PlanetDatabaseApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
