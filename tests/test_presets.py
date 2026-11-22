from dataclasses import replace

import pytest

from core.preset_manager import PresetManager


def test_preset_crud_and_persistence(tmp_path):
    manager = PresetManager(tmp_path / "nested" / "presets.json")
    assert manager.all() == {}
    seed = PresetManager().all()["Gym_High_Energy"]
    manager.create("تمارين", seed)
    manager.duplicate("تمارين", "Copy")
    manager.update("Copy", replace(seed, font_size=70))
    assert PresetManager(manager.path).all()["Copy"].font_size == 70
    with pytest.raises(ValueError, match="already exists"):
        manager.create("Copy", seed)
    manager.delete("تمارين")
    assert list(manager.all()) == ["Copy"]
    with pytest.raises(ValueError, match="at least one"):
        manager.delete("Copy")


def test_validation_rejects_bad_values():
    seed = PresetManager().all()["Gym_High_Energy"]
    with pytest.raises(ValueError, match="font_size"):
        replace(seed, font_size=300)
    with pytest.raises(ValueError, match="#RRGGBB"):
        replace(seed, text_color="red")
