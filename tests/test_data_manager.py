from cockpit.data.manager import DataManager


def test_data_manager_init():
    dm = DataManager(fred_api_key="test-key")
    assert dm is not None
