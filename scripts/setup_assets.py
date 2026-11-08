"""Copy the downloaded art packs into assets/ with the names the scene uses.

The packs themselves stay in resource/ and are NOT committed: their licences
allow shipping them inside a built app, but not redistributing the source
files. Run this after downloading the packs, and before packaging the app.

Run: python scripts/setup_assets.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESOURCE = ROOT / "resource"
ASSETS = ROOT / "assets"

# The 3/4 top-down office pack: furniture, electronics and decor.
PROPS = RESOURCE / "ModernOffice2DProps_v1.0" / "ModernOffice2DProps_v1.0" / "Tiles"

# A 16x16 top-down sample, used only for pieces the 3/4 pack does not have.
SAMPLE = RESOURCE / "modern-office-tileset-16x16-free-sample" / "objects"

# scene name -> source file. First existing source wins.
MAPPING: dict[str, list[Path]] = {
    # --- workstations -----------------------------------------------------
    "desk": [PROPS / "Furniture" / "office_furniture_desk_straight_01.png"],
    "desk_corner": [PROPS / "Furniture" / "office_furniture_desk_corner_l_01.png"],
    "desk_standing": [PROPS / "Furniture" / "office_furniture_desk_standing_01.png"],
    "desk_panel": [PROPS / "Furniture" / "office_furniture_desk_modesty_panel_01.png"],
    "chair": [PROPS / "Furniture" / "office_furniture_chair_task_01.png"],
    "chair_meeting": [PROPS / "Furniture" / "office_furniture_chair_meeting_01.png"],
    "chair_visitor": [PROPS / "Furniture" / "office_furniture_chair_visitor_01.png"],
    "stool": [PROPS / "Furniture" / "office_furniture_stool_high_01.png"],
    "pedestal": [PROPS / "Furniture" / "office_furniture_pedestal_mobile_01.png"],
    # --- storage ----------------------------------------------------------
    "shelf": [PROPS / "Furniture" / "office_furniture_cabinet_filing_tall_01.png"],
    "credenza": [PROPS / "Furniture" / "office_furniture_credenza_low_01.png"],
    "reception": [PROPS / "Furniture" / "office_furniture_counter_reception_curved_01.png"],
    # --- electronics ------------------------------------------------------
    "monitor": [PROPS / "Electronics" / "office_electronics_monitor_single_off_01.png"],
    "laptop": [PROPS / "Electronics" / "office_electronics_laptop_open_off_01.png"],
    "printer": [PROPS / "Electronics" / "office_electronics_printer_small_01.png"],
    "copier": [PROPS / "Electronics" / "office_electronics_copier_multifunction_01.png"],
    "projector": [PROPS / "Electronics" / "office_electronics_projector_01.png"],
    "clock": [PROPS / "Electronics" / "office_electronics_clock_wall_01.png"],
    "lamp_desk": [PROPS / "Electronics" / "office_electronics_lamp_desk_01.png"],
    "lamp_floor": [PROPS / "Electronics" / "office_electronics_lamp_floor_01.png"],
    "shredder": [PROPS / "Electronics" / "office_electronics_shredder_01.png"],
    "tower": [PROPS / "Electronics" / "office_electronics_computer_tower_01.png"],
    "camera": [PROPS / "Electronics" / "office_electronics_camera_security_01.png"],
    # --- decor ------------------------------------------------------------
    "plant": [PROPS / "Decor" / "office_decor_plant_broadleaf_01.png"],
    "plant_palm": [PROPS / "Decor" / "office_decor_plant_palm_01.png"],
    "plant_snake": [PROPS / "Decor" / "office_decor_plant_snake_01.png"],
    "tree": [PROPS / "Decor" / "office_decor_tree_indoor_01.png"],
    "artwork": [PROPS / "Decor" / "office_decor_artwork_abstract_01.png"],
    "partition": [PROPS / "Decor" / "office_decor_partition_fabric_01.png"],
    "fridge": [PROPS / "Decor" / "office_decor_refrigerator_compact_01.png"],
    "umbrella": [PROPS / "Decor" / "office_decor_stand_umbrella_01.png"],
    "bin": [PROPS / "Decor" / "office_decor_bin_waste_01.png"],
    "bin_recycle": [PROPS / "Decor" / "office_decor_bin_recycling_01.png"],
    # --- small props ------------------------------------------------------
    "mug": [PROPS / "Props" / "office_props_mug_01.png"],
    "papers": [PROPS / "Props" / "office_props_papers_stack_01.png"],
    "box": [PROPS / "Props" / "office_props_archive_box_01.png"],
    "frame": [PROPS / "Props" / "office_props_frame_photo_blank_01.png"],
    "succulent": [PROPS / "Props" / "office_props_succulent_small_01.png"],
    "organizer": [PROPS / "Props" / "office_props_organizer_desk_01.png"],
    "notebook": [PROPS / "Props" / "office_props_notebook_closed_01.png"],
    "bottle": [PROPS / "Props" / "office_props_water_bottle_01.png"],
    "headphones": [PROPS / "Props" / "office_props_headphones_01.png"],
    # --- pieces the 3/4 pack does not have --------------------------------
    "cooler": [SAMPLE / "water_dispenser.png"],
    "door": [SAMPLE / "door_wood.png"],
    "whiteboard": [SAMPLE / "whiteboard.png"],
}


def main() -> int:
    if not RESOURCE.exists():
        print(f"resource/ not found at {RESOURCE}")
        return 1
    ASSETS.mkdir(parents=True, exist_ok=True)
    copied = 0
    missing = []
    for name, sources in MAPPING.items():
        source = next((path for path in sources if path.exists()), None)
        if source is None:
            missing.append(name)
            continue
        shutil.copyfile(source, ASSETS / f"{name}.png")
        copied += 1
    print(f"copied {copied} sprites into {ASSETS}")
    if missing:
        print("no source for: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
