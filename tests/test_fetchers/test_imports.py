def test_circuit_breaker_import():
    from cockpit.data.fetchers import CircuitBreaker
    cb = CircuitBreaker(name="test")
    assert cb.name == "test"
    assert not cb.is_open()


def test_fetcher_classes_import():
    from cockpit.data.fetchers import FREDFetcher, ECBFetcher, YFinanceFetcher
    assert FREDFetcher is not None
    assert ECBFetcher is not None
    assert YFinanceFetcher is not None


def test_snb_functions_import():
    from cockpit.data.fetchers import fetch_sight_deposits, fetch_saron
    assert callable(fetch_sight_deposits)
    assert callable(fetch_saron)
