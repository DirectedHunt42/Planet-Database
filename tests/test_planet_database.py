from __future__ import annotations

import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from main import (
    APP_SETTINGS_FILENAME,
    DATABASE_FILENAME,
    LIGHTYEARS_PER_GRID_STEP,
    MAX_SPACING,
    MIN_SPACING,
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
    grid_interval_lightyears,
    grid_subdivision_factor,
    load_app_settings,
    load_database,
    load_legacy_database,
    load_project_archive,
    nearest_systems,
    pan_to_center_coordinates,
    project_isometric,
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

    def test_grid_intervals_are_round_whole_lightyear_values(self) -> None:
        self.assertEqual(
            [grid_interval_lightyears(zoom) for zoom in (16, 32, 64, 128, 256, 512)],
            [1_000, 500, 250, 100, 50, 25],
        )
        self.assertEqual(1_000 % grid_interval_lightyears(512), 0)

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


if __name__ == "__main__":
    unittest.main()
    load_app_settings,
