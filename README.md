# Planet Database

A lightweight desktop app for mapping named star systems onto an isometric 3D-coordinate grid. The view is 2D/isometric, while each saved system keeps its full integer **(X, Y, Z)** location.

## Run

Requires Python 3.10 or newer. The app uses only the Python standard library, including Tkinter.

```powershell
python main.py
```

In VS Code, select the installed Python interpreter and run `main.py`, or run `python main.py` in the integrated terminal.

## Use

- Click a grid point to select its X/Y coordinates. Set Z and give the system a name, then save.
- Click an existing system marker to select and rename it or edit its coordinates.
- Drag with the right mouse button to pan; scroll to zoom.
- Choose a project folder. Star-system data is saved as `planet-systems.json` in that folder, and the folder choice is remembered in `%APPDATA%\Planet Database\settings.json`.

All three integer coordinates are stored independently of the isometric drawing, so a future 3D view can use the same positions.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The previous C++/Qt prototype is preserved in [archive/PlanetDatabase-Cpp-2026-11-03.zip](archive/PlanetDatabase-Cpp-2026-11-03.zip).
