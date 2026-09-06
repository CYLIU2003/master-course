"""The merged reference directory must remain usable by runtime consumers."""

from pathlib import Path

from bff.services.ice_vehicle_reference import ICE_VEHICLE_REFERENCE
from src import engine_bus_extractor, scenario_overlay

ROOT = Path(__file__).resolve().parents[1]


def test_default_reference_locations_resolve():
    assert not (ROOT / 'constant').exists()
    assert engine_bus_extractor._project_root() == ROOT
    assert scenario_overlay._DEFAULT_INPUT_TEMPLATE_PATH.is_file()
    assert scenario_overlay.default_overlay_seed()
    for reference in ICE_VEHICLE_REFERENCE.values():
        document = reference['source'].split(':', 1)[0]
        assert (ROOT / document).is_file()


def test_default_excel_extraction_after_merge(tmp_path):
    result = engine_bus_extractor.run_extraction(output_dir=tmp_path)
    assert result['raw']
    assert result['normalized']
    assert result['simulation_library']
    assert {row['manufacturer'] for row in result['raw']} == {'Isuzu', 'Hino', 'MitsubishiFuso'}
