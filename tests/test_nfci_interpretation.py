from analysis.nfci_interpretation import classify_nfci


def test_classify_nfci_positive_is_tighter():
    assert classify_nfci(0.35) == "krapper dan het historisch gemiddelde (sinds 1973)"


def test_classify_nfci_negative_is_looser():
    assert classify_nfci(-0.42) == "ruimer dan het historisch gemiddelde (sinds 1973)"


def test_classify_nfci_zero_is_exactly_average():
    assert classify_nfci(0.0) == "exact op het historisch gemiddelde (sinds 1973)"
