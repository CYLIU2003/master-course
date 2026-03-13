from bff.main import app


def test_main_bff_excludes_catalog_and_public_data_routes():
    paths = {route.path for route in app.routes}

    assert "/api/app/datasets" in paths
    assert "/api/app/data-status" in paths
    assert "/api/catalog/operators" not in paths
    assert "/api/scenarios/{scenario_id}/public-data/fetch" not in paths
