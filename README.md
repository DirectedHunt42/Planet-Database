# Planet Database

A native Qt Quick desktop prototype for exploring a deterministic, procedural galaxy. The first slice renders one million GPU-drawn stars and lets you name a system at a selected star.

## Requirements

- CMake 3.21 or newer
- Qt 6.5 or newer with Quick, Quick Controls, Widgets, and OpenGL
- A C++17 compiler and an OpenGL 3.3-capable graphics driver

## Build

```powershell
cmake -S . -B build
cmake --build build --config Release
```

Run the generated `PlanetDatabase` executable from the build directory (on Windows, typically `build\Release\PlanetDatabase.exe`).

## Use

- Drag the galaxy to pan and scroll to zoom.
- Click a star to select it.
- Choose a project folder, then name and save a system at the selected star.
- The chosen folder contains `planet-database.json`. It stores the galaxy seed and named systems; the million generated star positions are recreated from the seed rather than written out individually.

Planet and moon records are not part of this initial rendering prototype yet.
