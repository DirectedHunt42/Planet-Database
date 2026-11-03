# Planet Database

A lightweight desktop app for mapping named star systems on an isometric grid. The display is 2D; each system retains independent **X, Y, and Z coordinates in light-years**, so the same data can be used in a future 3D view.

**Current version: 0.4.0.** The app displays its version in the header. Versions follow Semantic Versioning: feature releases advance the minor number, and fixes advance the patch number. The version is maintained in `main.py` and updated as the app changes.

## Run

Requires Python 3.10 or newer and the CustomTkinter dependency:

```powershell
python -m pip install -r requirements.txt
python main.py
```

The window opens maximized after initialization. The header reads “Planetary Database”; the SVG icon design and converted Windows ICO are in the [icons](./icons/) folder. CustomTkinter follows the Windows system light/dark theme, and its native title bar stays enabled so Windows can draw the standard caption and controls.

## Map and systems

- **The base grid interval is 1,000 light-years.** Zooming in uses round-number intervals down to 25 light-years at maximum zoom; placement snaps to the visible subdivisions. Vertical guide dash lengths track the active interval. The map is general-purpose and is not tied to any particular galaxy.
- The isometric grid is drawn for the visible area and continues as you pan and zoom.
- Right-click a grid intersection to choose X and Y; enter Z separately. Systems with nonzero Z show a vertical guide from their map position down to the ground plane.
- Map labels stay hidden until you hover over a marker. Left-click a saved marker to load its name, type, and coordinates for editing; use **DELETE SYSTEM** for confirmed removal.
- Select a stellar class when creating or editing a system. The map uses small shape-and-color markers for yellow, orange, red, brown, and white dwarfs; red, orange, and blue giants; white stars; Wolf–Rayet stars; neutron stars; pulsars; black holes; and binary stars. Older records without a star type display as yellow dwarfs.
- Left-drag to pan the map; the middle mouse button can also pan. Scroll to zoom.
- Zoom in up to 8 times farther than before; the grid continues subdividing to match.
- On startup, the view automatically frames saved systems instead of assuming they are near the origin. Selecting or saving a system recenters and zooms in on it.
- Each system gets a unique, persistent ID (shown in the sidebar with a copy button) that can be used to attach planet, moon, or other records later.
- Keyboard shortcuts: **Ctrl+S** saves the current system, **Ctrl+Z** undoes a saved change, and **Ctrl+Y** redoes it. Undo/redo ask for confirmation, update the AppData database, and support up to 100 saved changes during the current session only; history clears when the app closes.
- **Export** creates a compressed `.planetdata` project archive; **Import** loads one after confirmation, replacing the current database. An import can be undone with **Ctrl+Z** during the current session.

The database is stored automatically at `%APPDATA%\Planet Database\planet-systems.json`. Previous project-folder data is imported there on first launch when the old folder setting and database are present; older grid coordinates are converted to light-years.

The previous C++/Qt prototype is preserved in [archive/PlanetDatabase-Cpp-2026-11-03.zip](archive/PlanetDatabase-Cpp-2026-11-03.zip).

The `.planetdata` file icon design is available as [SVG](./icons/planetdata-file-icon.svg) and [Windows ICO](./icons/planetdata-file-icon.ico) for a future file-association setup.

### Icons

App icon: ![Planetary Database app icon](./icons/planet-database-icon.svg)

Stellar marker styles available in the type selector:

![Stellar type marker styles](./icons/stellar-types.svg)

## Tests

```powershell
python -m unittest discover -s tests -v
```
