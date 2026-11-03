# Planet Database

A native Qt Quick desktop prototype for exploring a deterministic, procedural galaxy. The first slice renders one million GPU-drawn stars and lets you name a system at a selected star.

## Requirements

- CMake 3.21 or newer
- Qt 6.5 or newer with Quick, Quick Controls, Widgets, and OpenGL
- A C++17 compiler and an OpenGL 3.3-capable graphics driver

## Build

On Windows, after installing Qt, double-click `Build-PlanetDatabase.cmd` to configure and compile a Release build. You can also run it from PowerShell:

```powershell
.\Build-PlanetDatabase.cmd
```

The script searches standard `C:\Qt` installations and the `CMAKE_PREFIX_PATH` environment variable for Qt 6.

To build manually:

```powershell
cmake -S . -B build
cmake --build build --config Release
```

Run the generated `PlanetDatabase` executable from the build directory (on Windows, typically `build\Release\PlanetDatabase.exe`).

## Use

- The entire galaxy remains visible while the cyan wireframe marks the working sector. Its cube is one quarter of the galaxy's width, or about one-sixteenth of the face-on galaxy's bounding-box area.
- Left-drag to orbit the camera, right- or middle-drag to move the working sector, and scroll to zoom.
- Click a star inside the cyan cube to select it; stars outside the sector cannot be edited.
- Choose a project folder, then name and save a system at the selected star.
- The chosen folder contains `planet-database.json`. It stores the galaxy seed and named systems; the million generated star positions are recreated from the seed rather than written out individually.
- The selected project folder is remembered in a `settings.ini` file under Qt's AppData location and reopened the next time the app starts.

Planet and moon records are not part of this initial rendering prototype yet.
