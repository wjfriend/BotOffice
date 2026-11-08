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
    "desk": [PROPS / "Furniture" / "office_furniture_desk_straight_01.png"],
    "chair": [PROPS / "Furniture" / "office_furniture_chair_task_01.png"],
    "plant": [PROPS / "Decor" / "office_decor_plant_broadleaf_01.png"],
    "plant_palm": [PROPS / "Decor" / "office_decor_plant_palm_01.png"],
    "plant_snake": [PROPS / "Decor" / "office_decor_plant_snake_01.png"],
    "printer": [PROPS / "Electronics" / "office_electronics_printer_small_01.png"],
    "copier": [PROPS / "Electronics" / "office_electronics_copier_multifunction_01.png"],
    "fridge": [PROPS / "Decor" / "office_decor_refrigerator_compact_01.png"],
    "shelf": [PROPS / "Furniture" / "office_furniture_cabinet_filing_tall_01.png"],
    "cabinet": [PROPS / "Furniture" / "office_furniture_credenza_low_01.png"],
    "clock": [PROPS / "Electronics" / "office_electronics_clock_wall_01.png"],
    "lamp": [PROPS / "Electronics" / "office_electronics_lamp_floor_01.png"],
    "monitor": [PROPS / "Electronics" / "office_electronics_monitor_single_off_01.png"],
    "laptop": [PROPS / "Electronics" / "office_electronics_laptop_open_off_01.png"],
    "partition": [PROPS / "Decor" / "office_decor_partition_fabric_01.png"],
    "reception": [PROPS / "Furniture" / "office_furniture_counter_reception_curved_01.png"],
    "bin": [PROPS / "Props" / "office_props_wastebasket_small_01.png"],
    "box": [PROPS / "Props" / "office_props_archive_box_01.png"],
    "mug": [PROPS / "Props" / "office_props_mug_01.png"],
    "papers": [PROPS / "Props" / "office_props_papers_stack_01.png"],
    # The 16x16 sample covers what the 3/4 pack leaves out.
    "door": [SAMPLE / "door_wood.png"],
    "whiteboard": [SAMPLE / "whiteboard.png"],
    "cooler": [SAMPLE / "water_dispenser.png"],
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
