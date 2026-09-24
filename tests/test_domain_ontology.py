import pytest
from contract.domain_ontology import DomainCategory, classify_domain


@pytest.mark.parametrize(
    "domain,expected",
    [
        ("monetary_policy", [DomainCategory.RATES, DomainCategory.MACRO]),
        ("currency", [DomainCategory.FX]),
        ("financial", [DomainCategory.CREDIT, DomainCategory.MACRO]),
        ("sector", [DomainCategory.SECTORS, DomainCategory.EQUITIES]),
        ("commodity", [DomainCategory.COMMODITIES]),
        ("equity:AAPL", [DomainCategory.EQUITIES, DomainCategory.COMPANIES]),
    ],
)
def test_classify_domain_known_domains(domain, expected):
    assert classify_domain(domain) == expected


def test_classify_domain_unknown_domain_raises():
    with pytest.raises(ValueError):
        classify_domain("nonsense")
