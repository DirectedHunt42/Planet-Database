from __future__ import annotations

import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from main import (
    APP_SETTINGS_FILENAME,
    DATABASE_FILENAME,
    DEFAULT_CAMERA_ELEVATION,
    DEFAULT_CAMERA_YAW,
    LIGHTYEARS_PER_GRID_STEP,
    MAX_CAMERA_ELEVATION,
    MAX_SPACING,
    MIN_CAMERA_ELEVATION,
    MIN_SPACING,
    MUTED,
    PlanetDatabaseApp,
    STAR_TYPES,
    app_settings_path,
    create_unique_system_id,
    database_path,
    default_app_settings,
    empty_project,
    export_project_archive,
    fit_view_to_systems,
    find_system_by_id,
    grid_dash_pattern,
    grid_display_interval_lightyears,
    grid_interval_lightyears,
    grid_subdivision_factor,
    is_coordinate,
    load_app_settings,
    load_database,
    load_legacy_database,
    load_project_archive,
    nearest_systems,
    pan_to_center_coordinates,
    project_3d,
    project_isometric,
    screen_to_ground_units,
    snap_to_grid,
    _parse_database_contents,
    viewport_ground_bounds,
)


class DatabaseTests(unittest.TestCase):
    def test_application_settings_are_stored_in_appdata(self) -> None:
        with patch.dict(
            "os.environ", {"APPDATA": r"C:\Users\Tester\AppData\Roaming"}
        ):
            expected = (
                Path(r"C:\Users\Tester\AppData\Roaming")
                / "Planet Database"
                / APP_SETTINGS_FILENAME
            )
            self.assertEqual(app_settings_path(), expected)

    def test_missing_application_settings_use_resizable_panel_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / APP_SETTINGS_FILENAME
            self.assertEqual(load_app_settings(path), default_app_settings())

    def test_saved_panel_widths_load_and_invalid_widths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / APP_SETTINGS_FILENAME
            path.write_text(
                json.dumps({"panelWidths": {"catalog": 420, "editor": 480}}),
                encoding="utf-8",
            )
            self.assertEqual(
                load_app_settings(path),
                {"panelWidths": {"catalog": 420, "editor": 480}},
            )
            path.write_text(
                json.dumps({"panelWidths": {"catalog": True}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "catalog panel width"):
                load_app_settings(path)

    def test_nearest_systems_uses_3d_distance_and_excludes_selected(self) -> None:
        systems = [
            {"id": "z-near", "name": "Near in Z", "x": 0, "y": 0, "z": 3},
            {"id": "y-near", "name": "Near in Y", "x": 0, "y": 4, "z": 0},
            {"id": "x-near", "name": "Near in X", "x": 5, "y": 0, "z": 0},
            {"id": "self", "name": "Current", "x": 1, "y": 1, "z": 1},
            {"id": "far", "name": "Far", "x": 100, "y": 100, "z": 100},
        ]

        nearest = nearest_systems(
            systems, (1, 1, 1), exclude_id="self", limit=4
        )

        self.assertEqual(
            [system["id"] for system, _distance in nearest],
            ["z-near", "y-near", "x-near", "far"],
        )
        for (_system, distance), expected in zip(
            nearest, (math.sqrt(6), math.sqrt(11), math.sqrt(18), math.sqrt(29_403))
        ):
            self.assertAlmostEqual(distance, expected)

    def test_white_star_records_migrate_to_white_dwarf(self) -> None:
        contents = json.dumps(
            {
                "formatVersion": 2,
                "coordinateUnit": "light-years",
                "systems": [
                    {
                        "id": "star",
                        "name": "White Star",
                        "x": 0,
                        "y": 0,
                        "z": 0,
                        "starType": "white_star",
                    }
                ],
            }
        )

        data, migrated = _parse_database_contents(contents)

        self.assertTrue(migrated)
        self.assertEqual(data["systems"][0]["starType"], "white_dwarf")

    def test_stellar_types_include_trinary_and_reuse_white_star_marker(self) -> None:
        self.assertNotIn("white_star", STAR_TYPES)
        self.assertEqual(STAR_TYPES["white_dwarf"][2], "circle")
        self.assertEqual(STAR_TYPES["trinary_star"][0], "Trinary star")
        self.assertEqual(STAR_TYPES["trinary_star"][2], "trinary")

    def test_database_is_stored_in_appdata(self) -> None:
        with patch.dict(
            "os.environ", {"APPDATA": r"C:\Users\Tester\AppData\Roaming"}
        ):
            expected = (
                Path(r"C:\Users\Tester\AppData\Roaming")
                / "Planet Database"
                / DATABASE_FILENAME
            )
            self.assertEqual(database_path(), expected)

    def test_missing_database_starts_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data, migrated = load_database(Path(temporary_directory) / DATABASE_FILENAME)

        self.assertEqual(data, empty_project())
        self.assertFalse(migrated)

    def test_previous_grid_coordinates_are_migrated_to_lightyears(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / DATABASE_FILENAME
            old_data = {
                "formatVersion": 1,
                "systems": [
                    {"id": "system-1", "name": "The Quiet Star", "x": -4, "y": 2, "z": 7}
                ],
            }
            path.write_text(json.dumps(old_data), encoding="utf-8")

            data, migrated = load_database(path)

        self.assertTrue(migrated)
        self.assertEqual(data["formatVersion"], 2)
        self.assertEqual(data["coordinateUnit"], "light-years")
        self.assertEqual(
            (data["systems"][0]["x"], data["systems"][0]["y"], data["systems"][0]["z"]),
            (-4_000, 2_000, 7_000),
        )
        self.assertEqual(data["systems"][0]["id"], "system-1")

    def test_previous_selected_folder_is_imported_into_appdata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            appdata = Path(temporary_directory) / "appdata"
            previous_folder = Path(temporary_directory) / "previous-project"
            appdata.mkdir()
            previous_folder.mkdir()
            (appdata / "settings.json").write_text(
                json.dumps({"projectDirectory": str(previous_folder)}),
                encoding="utf-8",
            )
            (previous_folder / DATABASE_FILENAME).write_text(
                json.dumps(
                    {
                        "formatVersion": 1,
                        "systems": [
                            {"id": "legacy-id", "name": "Legacy", "x": 3, "y": -2, "z": 1}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            data = load_legacy_database(appdata)

        self.assertEqual(data["systems"][0]["id"], "legacy-id")
        self.assertEqual(
            (data["systems"][0]["x"], data["systems"][0]["y"], data["systems"][0]["z"]),
            (3_000, -2_000, 1_000),
        )

    def test_duplicate_ids_and_duplicate_locations_are_rejected(self) -> None:
        cases = (
            [
                {"id": "same", "name": "First", "x": 0, "y": 0, "z": 0},
                {"id": "same", "name": "Second", "x": 1, "y": 0, "z": 0},
            ],
            [
                {"id": "first", "name": "First", "x": 0, "y": 0, "z": 0},
                {"id": "second", "name": "Second", "x": 0, "y": 0, "z": 0},
            ],
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / DATABASE_FILENAME
            for systems in cases:
                path.write_text(
                    json.dumps(
                        {
                            "formatVersion": 2,
                            "coordinateUnit": "light-years",
                            "systems": systems,
                        }
                    ),
                    encoding="utf-8",
                )
                with self.subTest(systems=systems), self.assertRaisesRegex(
                    ValueError, "duplicate system"
                ):
                    load_database(path)

    def test_system_notes_are_optional_text_and_reject_invalid_values(self) -> None:
        contents = {
            "formatVersion": 2,
            "coordinateUnit": "light-years",
            "systems": [
                {
                    "id": "star",
                    "name": "Star",
                    "x": 0,
                    "y": 0,
                    "z": 0,
                    "notes": "A quiet system.",
                }
            ],
        }
        loaded = _parse_database_contents(json.dumps(contents))[0]
        self.assertEqual(
            loaded["systems"][0]["notes"],
            "A quiet system.",
        )
        contents["systems"][0]["notes"] = ["not text"]
        with self.assertRaisesRegex(ValueError, "invalid or duplicate system"):
            _parse_database_contents(json.dumps(contents))

    def test_coordinates_allow_up_to_five_decimal_places(self) -> None:
        for value in (0, -12, 1.23456, -0.00001, 1.230000):
            with self.subTest(value=value):
                self.assertTrue(is_coordinate(value))
        for value in (1.234567, float("inf"), float("nan"), True, "1.25"):
            with self.subTest(value=value):
                self.assertFalse(is_coordinate(value))

    def test_coordinate_editor_parses_five_decimals_and_rejects_six(self) -> None:
        app = PlanetDatabaseApp.__new__(PlanetDatabaseApp)

        self.assertEqual(
            app._read_coordinate(SimpleNamespace(get=lambda: "-1,234.12345"), "X"),
            -1_234.12345,
        )
        with self.assertRaisesRegex(ValueError, "no more than 5 decimal places"):
            app._read_coordinate(SimpleNamespace(get=lambda: "0.123456"), "X")

    def test_database_round_trips_fractional_lightyear_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / DATABASE_FILENAME
            data = {
                "formatVersion": 2,
                "coordinateUnit": "light-years",
                "systems": [
                    {
                        "id": "fractional-star",
                        "name": "Fractional Star",
                        "x": 1.23456,
                        "y": -0.00001,
                        "z": 2,
                    }
                ],
            }
            path.write_text(json.dumps(data), encoding="utf-8")

            loaded, _migrated = load_database(path)

        self.assertEqual(
            (loaded["systems"][0]["x"], loaded["systems"][0]["y"],
             loaded["systems"][0]["z"]),
            (1.23456, -0.00001, 2),
        )

    def test_unknown_star_type_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / DATABASE_FILENAME
            for star_type in ("invented_type", ["invalid"], None):
                with self.subTest(star_type=star_type):
                    path.write_text(
                        json.dumps(
                            {
                                "formatVersion": 2,
                                "coordinateUnit": "light-years",
                                "systems": [
                                    {
                                        "id": "star",
                                        "name": "Unknown Type",
                                        "x": 0,
                                        "y": 0,
                                        "z": 0,
                                        "starType": star_type,
                                    }
                                ],
                            }
                        ),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        ValueError, "invalid or duplicate system"
                    ):
                        load_database(path)

    def test_unique_id_generation_retries_on_conflict(self) -> None:
        existing = "conflicting-id"
        with patch(
            "main.uuid.uuid4",
            side_effect=[
                SimpleNamespace(hex=existing),
                SimpleNamespace(hex="new-system-id"),
            ],
        ) as generate_uuid:
            allocated = create_unique_system_id({existing})

        self.assertEqual(allocated, "new-system-id")
        self.assertEqual(generate_uuid.call_count, 2)

    def test_unique_id_generation_fails_if_all_candidates_conflict(self) -> None:
        existing = {"conflict"}
        with patch("main.uuid.uuid4", return_value=SimpleNamespace(hex="conflict")):
            with self.assertRaisesRegex(RuntimeError, "unique system ID"):
                create_unique_system_id(existing)

    def test_existing_id_is_not_reused_for_another_system(self) -> None:
        existing_ids = {"first-system"}
        new_id = create_unique_system_id(existing_ids)

        self.assertNotIn(new_id, existing_ids)
        existing_ids.add(new_id)
        self.assertEqual(len(existing_ids), 2)

    def test_systems_can_be_referenced_by_persistent_id(self) -> None:
        system = {"id": "system-1", "name": "The Quiet Star", "x": 0, "y": 0, "z": 0}
        self.assertIs(find_system_by_id([system], "system-1"), system)
        self.assertIsNone(find_system_by_id([system], "missing"))

    def test_project_archive_round_trips_validated_systems(self) -> None:
        project = {
            "formatVersion": 2,
            "coordinateUnit": "light-years",
            "systems": [
                {
                    "id": "stable-id",
                    "name": "Far Star",
                    "x": 125_000,
                    "y": -80_000,
                    "z": 250,
                    "starType": "blue_giant",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "backup.planetdata"
            export_project_archive(path, project)

            self.assertTrue(zipfile.is_zipfile(path))
            self.assertEqual(load_project_archive(path), project)

    def test_project_archive_rejects_unexpected_members(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "unsafe.planetdata"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../outside.json", "{}")
            with self.assertRaisesRegex(ValueError, "must contain only"):
                load_project_archive(path)


class InfiniteLightyearGridTests(unittest.TestCase):
    def test_isometric_round_trip_snaps_beyond_the_initial_view(self) -> None:
        center = (580.0, 380.0)
        expected = (125_000, -80_000)
        position = project_isometric(*expected, 0, *center, 28.0)

        self.assertEqual(snap_to_grid(*position, *center, 28.0), expected)

    def test_one_grid_step_is_one_thousand_lightyears(self) -> None:
        origin = project_isometric(0, 0, 0, 0, 0, 20.0)
        one_step = project_isometric(LIGHTYEARS_PER_GRID_STEP, 0, 0, 0, 0, 20.0)

        self.assertAlmostEqual(one_step[0] - origin[0], 10.0 * 3**0.5)
        self.assertAlmostEqual(one_step[1] - origin[1], 10.0)

    def test_grid_subdivision_increases_with_zoom(self) -> None:
        self.assertEqual(grid_subdivision_factor(16.0), 1)
        self.assertEqual(grid_subdivision_factor(31.9), 2)
        self.assertEqual(grid_subdivision_factor(32.0), 2)
        self.assertEqual(grid_subdivision_factor(63.9), 4)
        self.assertEqual(grid_subdivision_factor(64.0), 4)
        self.assertEqual(grid_subdivision_factor(512.0), 40)
        self.assertEqual(MAX_SPACING, 32768.0)
        self.assertEqual(grid_subdivision_factor(MAX_SPACING), 1000)

    def test_grid_intervals_are_round_whole_lightyear_values(self) -> None:
        self.assertEqual(
            [
                grid_interval_lightyears(zoom)
                for zoom in (16, 32, 64, 128, 256, 512, 4096, MAX_SPACING)
            ],
            [1_000, 500, 250, 100, 50, 25, 5, 1],
        )
        self.assertEqual(1_000 % grid_interval_lightyears(MAX_SPACING), 0)

    def test_visible_grid_interval_is_double_placement_interval(self) -> None:
        for zoom in (16, 32, 64, 128, 512, MAX_SPACING):
            with self.subTest(zoom=zoom):
                self.assertEqual(
                    grid_display_interval_lightyears(zoom),
                    2 * grid_interval_lightyears(zoom),
                )

    def test_grid_renderer_draws_every_other_subdivision(self) -> None:
        app = PlanetDatabaseApp.__new__(PlanetDatabaseApp)
        app.canvas = Mock()
        app.canvas.winfo_width.return_value = 800
        app.canvas.winfo_height.return_value = 600
        app.spacing = 64.0
        app.pan_x = 0.0
        app.pan_y = 0.0
        app._hover_label_bounds = None
        app._palette = lambda color: color
        app._draw_axis_z = Mock()
        app._draw_axis_labels = Mock()
        app._draw_systems = Mock()
        app._draw_canvas_legend = Mock()
        center = app._canvas_center()
        subdivision_factor = grid_subdivision_factor(app.spacing)
        bounds = viewport_ground_bounds(
            800, 600, *center, app.spacing, subdivision_factor
        )
        expected_line_count = sum(
            1 for index in range(bounds[0], bounds[1] + 1) if index % 2 == 0
        ) + sum(
            1 for index in range(bounds[2], bounds[3] + 1) if index % 2 == 0
        )

        app._draw_grid()

        self.assertEqual(app.canvas.create_line.call_count, expected_line_count)

    def test_catalog_context_click_opens_the_full_system_editor(self) -> None:
        app = PlanetDatabaseApp.__new__(PlanetDatabaseApp)
        system = {"id": "star", "name": "Star", "notes": "A quiet system."}
        app.project_data = {"systems": [system]}
        app._select_system = Mock()

        result = app._on_catalog_context_click(None, "star")

        app._select_system.assert_called_once_with(system, show_notes_only=False)
        self.assertEqual(result, "break")

    def test_panel_mouse_wheel_scrolls_only_the_nearest_nested_frame(self) -> None:
        class FakeCanvas:
            def __init__(self, master=None):
                self.master = master
                self.scroll_units = []

            def yview_scroll(self, units, _mode):
                self.scroll_units.append(units)

        class FakeScrollable:
            def __init__(self, canvas):
                self._parent_canvas = canvas

            @staticmethod
            def winfo_exists():
                return True

        app = PlanetDatabaseApp.__new__(PlanetDatabaseApp)
        outer_canvas = FakeCanvas()
        inner_canvas = FakeCanvas(master=outer_canvas)
        app._scrollable_frames = [
            FakeScrollable(outer_canvas),
            FakeScrollable(inner_canvas),
        ]

        result = app._on_panel_mouse_wheel(
            SimpleNamespace(widget=inner_canvas, delta=-120)
        )

        self.assertEqual(result, "break")
        self.assertEqual(inner_canvas.scroll_units, [3])
        self.assertEqual(outer_canvas.scroll_units, [])

    def test_panel_mouse_wheel_over_notes_scrolls_the_notes_text(self) -> None:
        class FakeText:
            def __init__(self):
                self.scroll_units = []

            def yview_scroll(self, units, _mode):
                self.scroll_units.append(units)

        app = PlanetDatabaseApp.__new__(PlanetDatabaseApp)
        notes_panel = SimpleNamespace(master=None)
        text_widget = SimpleNamespace(master=notes_panel)
        notes_panel._textbox = FakeText()
        app.notes_text = notes_panel
        app._scrollable_frames = []

        result = app._on_panel_mouse_wheel(
            SimpleNamespace(widget=text_widget, delta=-120)
        )

        self.assertEqual(result, "break")
        self.assertEqual(notes_panel._textbox.scroll_units, [3])

    def test_subdivision_bounds_stay_viewport_sized_at_max_zoom(self) -> None:
        bounds = viewport_ground_bounds(
            1200, 800, 600, 400, MAX_SPACING, subdivisions=1000
        )
        x_lines = bounds[1] - bounds[0] + 1
        y_lines = bounds[3] - bounds[2] + 1

        self.assertLess(x_lines + y_lines, 200)

    def test_snapping_uses_zoomed_subdivisions(self) -> None:
        center = (580.0, 380.0)
        expected = (250, -500)
        position = project_isometric(*expected, 0, *center, 64.0)

        self.assertEqual(snap_to_grid(*position, *center, 64.0), expected)

    def test_snapping_supports_fractional_lightyear_grid_intervals(self) -> None:
        center = (580.0, 380.0)
        expected = (125, -250)
        position = project_isometric(*expected, 0, *center, 512.0)

        self.assertEqual(snap_to_grid(*position, *center, 512.0), expected)

    def test_vertical_guide_dashes_match_the_grid_pixel_interval(self) -> None:
        self.assertEqual(grid_dash_pattern(16.0), (16, 16))
        self.assertEqual(grid_dash_pattern(64.0), (16, 16))
        self.assertEqual(grid_dash_pattern(512.0), (13, 13))

    def test_vertical_guide_runs_from_ground_grid_to_elevated_star(self) -> None:
        app = PlanetDatabaseApp.__new__(PlanetDatabaseApp)
        app.spacing = 64.0
        app.canvas = SimpleNamespace(create_line=Mock(), create_oval=Mock())
        app._palette = lambda color: color
        center = (300.0, 200.0)
        coordinates = (1_000, -500, 250)

        app._draw_vertical_guide(*coordinates, *center)

        ground_point = project_isometric(
            coordinates[0], coordinates[1], 0, *center, app.spacing
        )
        star_point = project_isometric(*coordinates, *center, app.spacing)
        app.canvas.create_line.assert_called_once_with(
            *ground_point,
            *star_point,
            fill=MUTED,
            width=1,
            dash=grid_dash_pattern(app.spacing),
        )
        app.canvas.create_oval.assert_called_once_with(
            ground_point[0] - 2,
            ground_point[1] - 2,
            ground_point[0] + 2,
            ground_point[1] + 2,
            fill=MUTED,
            outline="",
        )

    def test_add_preview_is_visible_only_during_system_placement(self) -> None:
        for is_adding, expected_lines, expected_ovals in (
            (False, 0, 0),
            (True, 1, 2),
        ):
            with self.subTest(is_adding=is_adding):
                app = PlanetDatabaseApp.__new__(PlanetDatabaseApp)
                app.project_data = {"systems": []}
                app.selected_system_id = None
                app._is_adding_system = is_adding
                app._hovered_system_id = None
                app.spacing = 64.0
                app.canvas_background = "#000000"
                app.canvas = SimpleNamespace(
                    create_line=Mock(),
                    create_oval=Mock(),
                )
                app.x_var = SimpleNamespace(get=lambda: "1000")
                app.y_var = SimpleNamespace(get=lambda: "-500")
                app.z_var = SimpleNamespace(get=lambda: "250")
                app._palette = lambda color: color
                app._draw_vertical_guide = lambda x, y, z, center_x, center_y: (
                    PlanetDatabaseApp._draw_vertical_guide(
                        app, x, y, z, center_x, center_y
                    )
                )

                app._draw_systems(300.0, 200.0)

                self.assertEqual(app.canvas.create_line.call_count, expected_lines)
                self.assertEqual(app.canvas.create_oval.call_count, expected_ovals)

    def test_right_click_preserves_z_when_repositioning_new_system(self) -> None:
        for is_adding, initial_z, expected_z in (
            (True, "1250", "1250"),
            (False, "900", "0"),
        ):
            with self.subTest(is_adding=is_adding):
                app = PlanetDatabaseApp.__new__(PlanetDatabaseApp)
                app._is_adding_system = is_adding
                app.selected_system_id = None
                app.spacing = 64.0
                app.x_var = SimpleNamespace(set=Mock())
                app.y_var = SimpleNamespace(set=Mock())
                app.z_var = SimpleNamespace(get=lambda: initial_z, set=Mock())
                app.id_var = SimpleNamespace(set=Mock())
                app.name_var = SimpleNamespace(set=Mock())
                app.star_type_var = SimpleNamespace(set=Mock())
                app.status_var = SimpleNamespace(set=Mock())
                app._canvas_center = Mock(return_value=(300.0, 200.0))
                app._nearest_system = Mock(return_value=None)
                app._refresh_systems = Mock()
                app._open_star_editor = Mock()
                app._show_system_editor = Mock()
                app._set_notes_text = Mock()
                app._update_nearest_references = Mock()
                app._draw_grid = Mock()
                event = SimpleNamespace(x=400, y=250)

                with patch("main.snap_to_grid", return_value=(2_000, -500)):
                    app._on_canvas_click(event)

                app.z_var.set.assert_called_once_with(expected_z)

    def test_visible_grid_bounds_move_with_pan(self) -> None:
        original = viewport_ground_bounds(1200, 800, 600, 400, 20.0)
        panned = viewport_ground_bounds(1200, 800, 600_000, -400_000, 20.0)

        self.assertGreater(panned[0], original[0] + 1_000)
        self.assertGreater(panned[2], original[2] + 1_000)

    def test_auto_focus_centers_a_system_far_from_origin(self) -> None:
        coordinates = (125_000_000, -80_000_000, 4_000_000)
        spacing = 32.0
        pan = pan_to_center_coordinates(*coordinates, spacing)
        screen_position = project_isometric(
            *coordinates, 600 + pan[0], 400 + pan[1], spacing
        )

        self.assertAlmostEqual(screen_position[0], 600)
        self.assertAlmostEqual(screen_position[1], 400)

    def test_initial_fit_centers_a_distant_cluster_and_preserves_its_scale(self) -> None:
        systems = [
            {"x": 500_000, "y": -300_000, "z": 20_000},
            {"x": 502_000, "y": -299_000, "z": 21_000},
        ]
        center, spacing = fit_view_to_systems(systems, 1200, 800)

        self.assertEqual(center, (501_000, -299_500, 20_500))
        self.assertGreaterEqual(spacing, MIN_SPACING)
        self.assertLessEqual(spacing, MAX_SPACING)

    def test_single_system_fit_uses_the_increased_zoom_limit(self) -> None:
        _center, spacing = fit_view_to_systems(
            [{"x": 0, "y": 0, "z": 0}], 1200, 800
        )

        self.assertEqual(spacing, MAX_SPACING)


class ThreeDimensionalCameraTests(unittest.TestCase):
    def test_default_camera_preserves_the_previous_isometric_projection(self) -> None:
        coordinates = (125_000, -80_000, 12_500)
        expected = project_isometric(*coordinates, 580, 380, 28)
        actual = project_3d(
            *coordinates,
            580,
            380,
            28,
            DEFAULT_CAMERA_YAW,
            DEFAULT_CAMERA_ELEVATION,
        )[:2]

        self.assertAlmostEqual(actual[0], expected[0])
        self.assertAlmostEqual(actual[1], expected[1])

    def test_map_surfaces_render_after_camera_rotation(self) -> None:
        app = PlanetDatabaseApp.__new__(PlanetDatabaseApp)
        app.canvas = Mock()
        app.canvas.winfo_width.return_value = 800
        app.canvas.winfo_height.return_value = 600
        app.canvas.bbox.return_value = None
        app.spacing = 32.0
        app.camera_yaw = 0.75
        app.camera_elevation = math.radians(52)
        app.pan_x = 0.0
        app.pan_y = 0.0
        app.project_data = {
            "systems": [
                {
                    "id": "rendered",
                    "name": "Rendered system",
                    "x": 1_000,
                    "y": -2_000,
                    "z": 500,
                    "starType": "yellow_dwarf",
                }
            ]
        }
        app.selected_system_id = None
        app._is_adding_system = False
        app._hovered_system_id = None
        app._hover_label_bounds = None
        app.canvas_background = "#000000"
        app._palette = lambda color: color

        app._draw_grid()

        self.assertTrue(app.canvas.create_line.called)
        self.assertTrue(app.canvas.create_oval.called)
        self.assertTrue(app.canvas.create_text.called)

    def test_ground_projection_round_trips_at_multiple_camera_angles(self) -> None:
        expected = (125_000.0, -80_000.0)
        for yaw, elevation in (
            (DEFAULT_CAMERA_YAW, DEFAULT_CAMERA_ELEVATION),
            (0.25, MIN_CAMERA_ELEVATION),
            (1.7, math.radians(42)),
            (-2.4, MAX_CAMERA_ELEVATION),
        ):
            with self.subTest(yaw=yaw, elevation=elevation):
                position = project_3d(
                    *expected,
                    0,
                    580.0,
                    380.0,
                    28.0,
                    yaw,
                    elevation,
                )
                ground = screen_to_ground_units(
                    position[0],
                    position[1],
                    580.0,
                    380.0,
                    28.0,
                    yaw,
                    elevation,
                )

                self.assertAlmostEqual(
                    ground[0] * LIGHTYEARS_PER_GRID_STEP, expected[0]
                )
                self.assertAlmostEqual(
                    ground[1] * LIGHTYEARS_PER_GRID_STEP, expected[1]
                )

    def test_vertical_axis_stays_screen_vertical_as_camera_rotates(self) -> None:
        ground = project_3d(4_000, -2_000, 0, 100, 200, 32, 0.9, 0.6)
        elevated = project_3d(4_000, -2_000, 3_000, 100, 200, 32, 0.9, 0.6)

        self.assertAlmostEqual(elevated[0], ground[0])
        expected_height = -96.0 * (
            math.cos(0.6) / math.cos(DEFAULT_CAMERA_ELEVATION)
        )
        self.assertAlmostEqual(elevated[1] - ground[1], expected_height)

    def test_grid_snapping_follows_the_rotated_ground_plane(self) -> None:
        expected = (125_000, -80_000)
        yaw = 1.2
        elevation = math.radians(24)
        screen_position = project_3d(
            *expected,
            0,
            580,
            380,
            64,
            yaw,
            elevation,
        )[:2]

        self.assertEqual(
            snap_to_grid(*screen_position, 580, 380, 64, yaw, elevation),
            expected,
        )

    def test_middle_drag_keeps_nearest_stars_ground_point_fixed(self) -> None:
        app = PlanetDatabaseApp.__new__(PlanetDatabaseApp)
        app.canvas = SimpleNamespace(
            winfo_width=Mock(return_value=1000),
            winfo_height=Mock(return_value=700),
        )
        app.spacing = 32.0
        app.camera_yaw = DEFAULT_CAMERA_YAW
        app.camera_elevation = DEFAULT_CAMERA_ELEVATION
        app.pan_x = 140.0
        app.pan_y = -90.0
        app.project_data = {
            "systems": [{"id": "pivot", "x": 50_000, "y": -30_000, "z": 4_000}]
        }
        app._draw_grid = Mock()

        initial_center = app._canvas_center()
        pivot_screen = project_3d(
            50_000,
            -30_000,
            0,
            *initial_center,
            app.spacing,
            app.camera_yaw,
            app.camera_elevation,
        )[:2]
        app._start_rotate(SimpleNamespace(x=100, y=100))
        app._move_rotate(SimpleNamespace(x=160, y=145))

        rotated_center = app._canvas_center()
        rotated_pivot_screen = project_3d(
            50_000,
            -30_000,
            0,
            *rotated_center,
            app.spacing,
            app.camera_yaw,
            app.camera_elevation,
        )[:2]

        self.assertAlmostEqual(rotated_pivot_screen[0], pivot_screen[0])
        self.assertAlmostEqual(rotated_pivot_screen[1], pivot_screen[1])
        self.assertNotEqual(app.camera_yaw, DEFAULT_CAMERA_YAW)
        self.assertNotEqual(app.camera_elevation, DEFAULT_CAMERA_ELEVATION)
        app._end_rotate(SimpleNamespace())
        self.assertIsNone(app._rotation_origin)

    def test_zoom_stays_anchored_to_the_ground_point_under_the_cursor(self) -> None:
        app = PlanetDatabaseApp.__new__(PlanetDatabaseApp)
        app.canvas = SimpleNamespace(
            winfo_width=Mock(return_value=1000),
            winfo_height=Mock(return_value=700),
        )
        app.spacing = 32.0
        app.camera_yaw = 0.9
        app.camera_elevation = math.radians(30)
        app.pan_x = 120.0
        app.pan_y = -45.0
        app._draw_grid = Mock()
        event = SimpleNamespace(delta=120, x=370, y=290)
        center_x, center_y = app._canvas_center()
        ground_x, ground_y = screen_to_ground_units(
            event.x,
            event.y,
            center_x,
            center_y,
            app.spacing,
            app.camera_yaw,
            app.camera_elevation,
        )

        app._on_mouse_wheel(event)

        new_center = app._canvas_center()
        zoomed_position = project_3d(
            ground_x * LIGHTYEARS_PER_GRID_STEP,
            ground_y * LIGHTYEARS_PER_GRID_STEP,
            0,
            *new_center,
            app.spacing,
            app.camera_yaw,
            app.camera_elevation,
        )[:2]
        self.assertAlmostEqual(zoomed_position[0], event.x)
        self.assertAlmostEqual(zoomed_position[1], event.y)


if __name__ == "__main__":
    unittest.main()
    load_app_settings,
