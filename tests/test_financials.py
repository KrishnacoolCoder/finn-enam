from app.financials import growth,quarter_ok

def test_growth():
    assert growth(120,100)==20
    assert growth(100,0) is None
    assert growth(None,100) is None

def test_quarters():
    assert quarter_ok('2026-Q3')
    assert not quarter_ok('2026-Q5')
