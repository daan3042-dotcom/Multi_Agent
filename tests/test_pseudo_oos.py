"""
test_pseudo_oos.py
De pseudo-OOS-run (roadmap 4.4): `scoring/pseudo_oos.py` en `pseudo_oos.py`. 02-10-2026.

De kern die hier bewaakt wordt: DE AGENT ZIET OP EEN DATUM NOOIT IETS WAT NA DIE DATUM BEKEND WERD, en de echte
database wordt nooit aangeraakt. De tests draaien tegen een bron-database met alle reeksen van de vijf voorspellende
agents (dag-, week- en maandfrequentie, met waarnemingen ná het venster), niet tegen een lege.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from contract import resolution as res
from contract.output_contract import Claim, Confidence, DomainOutput, Mode
from runtime.daily import default_agents
from scoring import evidence_sheet as es
from scoring import pseudo_oos as po
from storage.schema import init_db, save_domain_output

ROOT = Path(__file__).resolve().parent.parent
UTC = timezone.utc
EINDE = date(2026, 10, 1)  # de laatste waarneming in de bron (de back-fill van 29-09 + live)
TOEKOMST_PIEK = 987654.0  # een waarde die nergens in een prompt mag verschijnen vóór zij bekend is
FOMC_VENSTER = (date(2026, 7, 29), date(2026, 9, 16))


def _dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _reeksdagen(key: str) -> list[date]:
    """Waarnemingsdata op de manier van de bron: dagreeks (werkdagen), weekreeks (zaterdag) of maandreeks (de 1e)."""
    lag = po.vertraging_voor(key)
    if lag in (6,):
        d = date(2025, 1, 4)
        uit = []
        while d <= EINDE:
            uit.append(d)
            d += timedelta(days=7)
        return uit
    if lag in (35, 38, 45):
        uit, j, m = [], 2024, 1
        while date(j, m, 1) <= EINDE:
            uit.append(date(j, m, 1))
            m, j = (1, j + 1) if m == 12 else (m + 1, j)
        return uit
    d = date(2025, 9, 1)
    uit = []
    while d <= EINDE:
        if d.weekday() < 5:
            uit.append(d)
        d += timedelta(days=1)
    return uit


def _waarden(key: str, n: int) -> list[float]:
    basis = 3.0 + (sum(map(ord, key)) % 50) / 10
    if key == "fed_funds_target_upper":
        return [4.5] * (n - 40) + [4.25] * 40  # een stap, zodat de FOMC-context iets te tonen heeft
    return [basis + 0.01 * i + ((i * 7) % 11) * 0.05 for i in range(n)]


def _bouw_bron(pad: str, piek_op: date | None = None) -> str:
    """Een bron-database zoals de back-fill die achterlaat: per reeks claims met analysis_time = source_time."""
    from agents import currency_agent, economic_agent, financial_agent, monetary_policy_agent, sector_agent

    modules = {"monetary_policy": monetary_policy_agent, "currency": currency_agent, "financial": financial_agent,
               "sector": sector_agent, "economic": economic_agent}
    conn = init_db(pad)
    for spec in default_agents():
        if not spec.forecasts:
            continue
        sleutels = set(modules[spec.domain].METRIC_SPECS) | {t.metric_key for t in spec.forecast_targets}
        sleutels |= {t.benchmark_metric_key for t in spec.forecast_targets if t.benchmark_metric_key}
        for key in sorted(sleutels):
            dagen = _reeksdagen(key)
            waarden = _waarden(key, len(dagen))
            claims = []
            for d, w in zip(dagen, waarden):
                if piek_op and key == "10y_treasury_yield" and d == piek_op:
                    w = TOEKOMST_PIEK
                claims.append(Claim(domain=spec.domain, claim=f"Reeks {key}", value=w, source="bron",
                                    confidence=Confidence.HIGH, analysis_time=_dt(d), source_time=_dt(d), metric_key=key))
            save_domain_output(conn, DomainOutput(domain=spec.domain, mode=Mode.MONITORING, generated_at=_dt(dagen[0]), claims=claims))
    conn.close()
    return pad


@pytest.fixture
def fomc_kalender(monkeypatch):
    """De besluitdagen van juli en september 2026 erbij, zoals DD ze na controle toevoegt (hier alleen om te testen)."""
    kal = tuple(sorted(set(res.FOMC_MEETING_DATES) | set(FOMC_VENSTER)))
    monkeypatch.setattr(res, "FOMC_MEETING_DATES", kal)
    monkeypatch.setattr(es, "FOMC_MEETING_DATES", kal)  # de evidence-sheet bindt de naam bij het importeren
    return kal


@pytest.fixture(scope="module")
def bronnen(tmp_path_factory):
    """Eén bron met een piek op de eerste september-dag (na de eerste voorspeldata), eenmalig gebouwd."""
    map_ = tmp_path_factory.mktemp("bron")
    return str(_bouw_bron(str(map_ / "bron.db"), piek_op=date(2026, 9, 1)))


@pytest.fixture
def kopie(bronnen, tmp_path):
    doel = str(tmp_path / "pseudo_oos.db")
    po.bereid_voor(bronnen, doel)
    conn = sqlite3.connect(doel)
    yield conn
    conn.close()


def _hash(pad: str) -> str:
    return hashlib.sha256(Path(pad).read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# Planning en de vertragingstabel
# --------------------------------------------------------------------------


def test_het_venster_is_dertien_maandagen_om_0715_utc():
    datums = po.voorspeldata()
    assert len(datums) == 13
    assert datums[0] == datetime(2026, 7, 6, 7, 15, tzinfo=UTC) and datums[-1] == datetime(2026, 9, 28, 7, 15, tzinfo=UTC)
    assert all(d.weekday() == 0 for d in datums)


def test_elke_reeks_van_de_voorspellende_agents_heeft_een_publicatievertraging():
    """Een reeks zonder vertraging zou ongecorrigeerd te vroeg zichtbaar zijn. Komt er een reeks bij, dan faalt dit."""
    assert [k for k in sorted(po.benodigde_reeksen(default_agents())) if po.vertraging_voor(k) is None] == []


def test_afgeleide_relatieve_sterkte_volgt_zijn_basisreeks():
    assert po.vertraging_voor("xlk_technology_rel_spy") == po.vertraging_voor("xlk_technology")
    assert po.vertraging_voor("bestaat_niet") is None


def test_maandreeksen_hebben_een_vertraging_van_minstens_een_maand():
    """FEDFUNDS bleek op de echte data een maandgemiddelde (866 waarnemingen sinds 1954) en stond op 1 dag: op 6 juli was de
    julistand zichtbaar. Alle maandreeksen moeten minstens een maand vertraging hebben."""
    for key in ("fed_funds_rate", "cpi_inflation_index", "unemployment_rate", "nonfarm_payrolls"):
        assert po.PUBLICATIE_VERTRAGING_DAGEN[key] >= 30, key


def test_de_werkelijke_frequentie_komt_uit_de_afstand_tussen_de_waarnemingen():
    dag = [date(2026, 1, 5) + timedelta(days=i) for i in range(0, 60)]
    week = [date(2026, 1, 3) + timedelta(days=7 * i) for i in range(20)]
    maand = [date(2024 + i // 12, i % 12 + 1, 1) for i in range(30)]
    assert po.werkelijke_frequentie(dag) == (1, "dagreeks")
    assert po.werkelijke_frequentie(week) == (2, "weekreeks")
    assert po.werkelijke_frequentie(maand) == (30, "maandreeks")
    assert po.werkelijke_frequentie(maand[:4]) is None  # te weinig om te oordelen


def test_een_te_korte_vertraging_voor_een_maandreeks_breekt_de_voorbereiding_af(bronnen, tmp_path, monkeypatch):
    """Precies de fout van 02-10: een maandreeks met een vertraging van 1 dag. De voorbereiding moet dat zelf vangen."""
    monkeypatch.setitem(po.PUBLICATIE_VERTRAGING_DAGEN, "fed_funds_rate", 1)
    doel = tmp_path / "kopie.db"
    with pytest.raises(po.PseudoOosFout, match=r"fed_funds_rate: 1 dagen, maar het is een maandreeks \(minimaal 30 dagen\)"):
        po.bereid_voor(bronnen, str(doel))
    assert not doel.exists()


def test_de_vertragingen_zijn_aannemelijk_per_frequentie():
    t = po.PUBLICATIE_VERTRAGING_DAGEN
    assert all(t[k] >= 1 for k in t)  # niets is dezelfde dag bekend: de run draait voor de beurs opent
    assert t["nonfarm_payrolls"] == t["unemployment_rate"]  # dezelfde publicatie
    assert t["cpi_inflation_index"] > t["nonfarm_payrolls"] > t["initial_claims"] > t["vix"]  # maand > week > dag


# --------------------------------------------------------------------------
# Voorbereiden: een kopie, de bron blijft onaangeroerd
# --------------------------------------------------------------------------


def test_voorbereiden_verschuift_alleen_in_de_kopie_en_laat_de_bron_ongemoeid(bronnen, tmp_path):
    voor = _hash(bronnen)
    doel = str(tmp_path / "kopie.db")
    rapport = po.bereid_voor(bronnen, doel)
    assert _hash(bronnen) == voor  # de echte database is niet gewijzigd
    assert rapport.totaal_verschoven > 1000 and "nonfarm_payrolls" in rapport.verschoven

    kopie = sqlite3.connect(doel)
    bron = sqlite3.connect(f"file:{bronnen}?mode=ro", uri=True)
    q = "SELECT source_time, analysis_time FROM claims WHERE metric_key = ? ORDER BY source_time LIMIT 1"
    s_k, a_k = kopie.execute(q, ("nonfarm_payrolls",)).fetchone()
    s_b, a_b = bron.execute(q, ("nonfarm_payrolls",)).fetchone()
    assert s_k == s_b and a_b == s_b  # de bron: analysis_time = source_time (back-fill)
    assert datetime.fromisoformat(a_k) - datetime.fromisoformat(s_k) == timedelta(days=38)
    kopie.close(); bron.close()


def test_eigen_live_claims_worden_niet_verschoven(tmp_path):
    pad = str(tmp_path / "bron.db")
    conn = init_db(pad)
    obs, gezien = _dt(date(2026, 9, 30)), datetime(2026, 9, 30, 21, 0, tzinfo=UTC)
    save_domain_output(conn, DomainOutput(domain="financial", mode=Mode.MONITORING, generated_at=gezien, claims=[
        Claim(domain="financial", claim="VIX", value=15.0, source="live", confidence=Confidence.HIGH,
              analysis_time=gezien, source_time=obs, metric_key="vix")]))
    conn.close()
    doel = str(tmp_path / "kopie.db")
    rapport = po.bereid_voor(pad, doel)
    assert rapport.niet_verschoven == {"vix": 1} and rapport.verschoven == {}
    assert sqlite3.connect(doel).execute("SELECT analysis_time FROM claims").fetchone()[0] == gezien.isoformat()


def test_voorbereiden_weigert_overschrijven_dezelfde_database_en_een_ontbrekende_bron(bronnen, tmp_path):
    doel = str(tmp_path / "kopie.db")
    po.bereid_voor(bronnen, doel)
    with pytest.raises(po.PseudoOosFout, match="bestaat al"):
        po.bereid_voor(bronnen, doel)
    with pytest.raises(po.PseudoOosFout, match="niet gevonden"):
        po.bereid_voor(str(tmp_path / "weg.db"), str(tmp_path / "x.db"))
    with pytest.raises(po.PseudoOosFout, match="bestaat al"):
        po.bereid_voor(bronnen, bronnen)  # de bron bestaat natuurlijk al: nooit overschrijven


def test_een_reeks_zonder_vertraging_breekt_de_voorbereiding_af_zonder_halve_kopie(bronnen, tmp_path, monkeypatch):
    monkeypatch.delitem(po.PUBLICATIE_VERTRAGING_DAGEN, "vix")
    doel = tmp_path / "kopie.db"
    with pytest.raises(po.PseudoOosFout, match="vix"):
        po.bereid_voor(bronnen, str(doel))
    assert not doel.exists()


def test_alleen_een_voorbereide_database_wordt_gebruikt(bronnen):
    conn = sqlite3.connect(f"file:{bronnen}?mode=ro", uri=True)
    assert not po.is_voorbereid(conn)
    with pytest.raises(po.PseudoOosFout, match="geen voorbereide"):
        po._vereis_voorbereid(conn)
    with pytest.raises(po.PseudoOosFout, match="geen voorbereide"):
        po.draai(conn, MagicMock(), default_agents(), po.voorspeldata()[:1])
    conn.close()


# --------------------------------------------------------------------------
# Het kernpunt: niets uit de toekomst
# --------------------------------------------------------------------------

D0 = datetime(2026, 7, 6, 7, 15, tzinfo=UTC)  # maandag


def _laatste(conn, key, d):
    h = po.zichtbare_geschiedenis(conn, key, d)
    return h[-1].source_time.date() if h else None


def test_een_dagreeks_toont_de_vrijdag_en_niet_de_maandag_zelf(kopie):
    assert _laatste(kopie, "vix", D0) == date(2026, 7, 3)  # vrijdag; de maandag (07-06) is pas morgen bekend


def test_een_maandreeks_verschijnt_pas_na_de_publicatievertraging(kopie):
    # De waarde met datum 1 juli (juni of juli?) is op 6 juli niet bekend: payrolls van de maand verschijnen ~5 weken later.
    assert _laatste(kopie, "nonfarm_payrolls", D0) == date(2026, 5, 1)
    assert _laatste(kopie, "nonfarm_payrolls", datetime(2026, 7, 9, 7, 15, tzinfo=UTC)) == date(2026, 6, 1)  # 1 jun + 38 d
    assert _laatste(kopie, "cpi_inflation_index", D0) == date(2026, 5, 1)  # 1 mei + 45 d = 15 jun < 6 jul < 1 jun + 45 d = 16 jul


def test_een_weekreeks_toont_de_week_van_vorige_week_pas_na_de_publicatie(kopie):
    assert _laatste(kopie, "initial_claims", D0) == date(2026, 6, 27)  # zaterdag + 6 d = vrijdag 3 juli < maandag 6 juli
    assert _laatste(kopie, "initial_claims", datetime(2026, 7, 8, 7, 15, tzinfo=UTC)) == date(2026, 6, 27)  # 4 juli+6 = 10 juli


def test_claims_op_datum_geeft_per_reeks_de_laatste_bekende_en_niets_uit_de_toekomst(kopie):
    claims = {c.metric_key: c for c in po.claims_op_datum(kopie, "monetary_policy", D0)}
    assert claims["10y_treasury_yield"].source_time.date() == date(2026, 7, 3)
    assert claims["unemployment_rate"].source_time.date() == date(2026, 5, 1)
    assert all(c.source_time.date() < D0.date() for c in claims.values())
    assert all(c.analysis_time <= D0 for c in claims.values())


def test_een_claim_met_een_waarnemingsdatum_na_de_voorspeldatum_is_nooit_zichtbaar(kopie):
    """Dubbele veiligheid: ook een fout in de data (waarneming van 20 juli, 'gezien' op 1 juli) mag niet doorlekken."""
    save_domain_output(kopie, DomainOutput(domain="financial", mode=Mode.MONITORING, generated_at=_dt(date(2026, 7, 1)), claims=[
        Claim(domain="financial", claim="Reeks vix", value=555.5, source="fout", confidence=Confidence.HIGH,
              analysis_time=_dt(date(2026, 7, 1)), source_time=_dt(date(2026, 7, 20)), metric_key="vix")]))
    vix = {c.metric_key: c for c in po.claims_op_datum(kopie, "financial", D0)}["vix"]
    assert vix.source_time.date() == date(2026, 7, 3) and vix.value != 555.5


def test_de_prompt_bevat_geen_waarde_uit_de_toekomst(kopie):
    """De piek (987654) staat in de bron op 1 september. Op 6 juli, 3 augustus en 31 augustus mag hij nergens in de prompt
    staan, op 7 september wel (dan is hij bekend)."""
    spec = next(a for a in default_agents() if a.domain == "monetary_policy")
    for d in (datetime(2026, 7, 6, 7, 15, tzinfo=UTC), datetime(2026, 8, 3, 7, 15, tzinfo=UTC), datetime(2026, 8, 31, 7, 15, tzinfo=UTC)):
        systeem, gebruiker = po.bouw_prompt(kopie, spec, d)
        assert "987654" not in systeem + gebruiker, d
    _, na = po.bouw_prompt(kopie, spec, datetime(2026, 9, 7, 7, 15, tzinfo=UTC))
    assert "987654" in na


def test_de_evidence_sheet_en_de_baselines_gebruiken_dezelfde_zichtbaarheid(kopie):
    """Niet alleen de claims: ook de spreiding en de baselines kijken niet vooruit."""
    from scoring.baselines import baseline_predictions

    spec = next(a for a in default_agents() if a.domain == "financial")
    claims = po.claims_op_datum(kopie, spec.domain, D0)
    sheet = es.build_evidence_sheet(kopie, list(spec.forecast_targets), claims, D0)
    assert "2026-07-06" in sheet and "2026-07-03" in sheet  # 'bekend op' en de laatste waarneming
    r = baseline_predictions(kopie, spec.domain, spec.forecast_targets, D0)
    assert r.predictions  # er is genoeg historie, en alle gebruikte waarnemingen waren bekend


# --------------------------------------------------------------------------
# Draaien met een nep-model
# --------------------------------------------------------------------------


def _model_dat_antwoordt(weglaten: set[str] = frozenset(), kapot: bool = False):
    """Een nep-client die de gevraagde structuur uit de prompt leest en een geldig antwoord geeft."""
    client = MagicMock()
    prompts: list[str] = []

    def create(**kw):
        tekst = kw["messages"][0]["content"]
        prompts.append(tekst)
        regels = re.findall(r'\{"metric_key": "(\w+)", "horizon_n": (\d+), ([^}]*)\}', tekst)
        uit = []
        for key, n, rest in regels:
            if key in weglaten:
                continue
            if '"probability"' in rest:
                uit.append(f'{{"metric_key": "{key}", "horizon_n": {n}, "probability": 0.3}}')
            else:
                uit.append(f'{{"metric_key": "{key}", "horizon_n": {n}, "q10": 1, "q25": 2, "q50": 3, "q75": 4, "q90": 5}}')
        blok = MagicMock()
        blok.type = "text"
        blok.text = "oeps geen json" if kapot else '{"forecasts": [' + ",".join(uit) + "]}"
        return MagicMock(content=[blok])

    client.messages.create.side_effect = create
    client.prompts = prompts
    return client


def test_draaien_levert_pseudo_oos_voorspellingen_met_de_datum_van_het_verleden(kopie, fomc_kalender):
    agents = default_agents()
    datums = po.voorspeldata()[:2]
    uitkomsten = po.draai(kopie, _model_dat_antwoordt(), agents, datums)
    assert len(uitkomsten) == 2 * 5 and all(u.gekregen == u.verwacht and not u.issues for u in uitkomsten)

    cohorten = dict(kopie.execute("SELECT cohort, COUNT(*) FROM predictions GROUP BY cohort").fetchall())
    assert set(cohorten) == {"pseudo_oos"}  # alles, ook de baselines, onder het eigen cohort
    llm = kopie.execute("SELECT COUNT(*) FROM predictions WHERE agent NOT LIKE 'baseline:%'").fetchone()[0]
    assert llm == 2 * 57  # 57 LLM-voorspellingen per ronde
    # De baselines draaien ook, zonder ridge, onder dezelfde datum:
    baselines = {r[0] for r in kopie.execute("SELECT DISTINCT agent FROM predictions WHERE agent LIKE 'baseline:%'")}
    assert baselines == {"baseline:persistence", "baseline:climatology"}
    aangemaakt = {r[0] for r in kopie.execute("SELECT DISTINCT created_at FROM predictions")}
    assert aangemaakt == {d.isoformat() for d in datums}  # geen enkele voorspelling met de datum van vandaag


def test_ridge_wordt_in_de_pseudo_oos_run_nooit_aangeroepen(kopie, fomc_kalender, monkeypatch):
    """Ridge wordt op alle historie gefit en kent het venster dus al. Na de freeze staan er bevroren modellen in de
    database; die mogen hier nooit meedoen."""
    from scoring import baseline_round as br

    aanroepen = []
    monkeypatch.setattr(br, "ridge_predictions", lambda *a, **k: aanroepen.append(a) or br.BaselineRoundResult("x", (), (), ()))
    uitkomsten = po.draai(kopie, _model_dat_antwoordt(), default_agents(), po.voorspeldata()[:1])
    assert aanroepen == [] and not any(u.domain.startswith("baseline:") for u in uitkomsten)


def test_het_cohort_wordt_na_afloop_hersteld_ook_na_een_fout(kopie, fomc_kalender, monkeypatch):
    import os

    monkeypatch.setenv("MI_COHORT", "dry_run")
    po.draai(kopie, _model_dat_antwoordt(), default_agents(), po.voorspeldata()[:1])
    assert os.environ["MI_COHORT"] == "dry_run"
    monkeypatch.delenv("MI_COHORT")
    with pytest.raises(RuntimeError):
        with po.pseudo_oos_cohort():
            assert os.environ["MI_COHORT"] == "pseudo_oos"
            raise RuntimeError("boem")
    assert "MI_COHORT" not in os.environ


def test_een_hervatting_schrijft_niets_dubbel(kopie, fomc_kalender):
    agents = default_agents()
    datums = po.voorspeldata()[:1]
    po.draai(kopie, _model_dat_antwoordt(), agents, datums)
    n1 = kopie.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    client = _model_dat_antwoordt()
    po.draai(kopie, client, agents, datums)
    assert kopie.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == n1
    client.messages.create.assert_not_called()  # en er is niets betaald


def test_het_model_ziet_de_prompt_van_die_datum(kopie, fomc_kalender):
    client = _model_dat_antwoordt()
    po.draai(kopie, client, default_agents(), po.voorspeldata()[:1])
    tekst = "\n".join(client.prompts)
    assert "bekend op 2026-07-06" in tekst
    assert "987654" not in tekst
    assert "2026-07-29" in tekst  # de eerstvolgende FOMC-besluitdag, niet 28 oktober


def test_gemiste_voorspellingen_komen_in_het_rapport_en_boven_vijf_procent_staat_er_een_vlag(kopie, fomc_kalender, capsys):
    agents = default_agents()
    po.draai(kopie, _model_dat_antwoordt(weglaten={"vix"}), agents, po.voorspeldata()[:3])
    r = {a.domain: a for a in po.rapport(kopie, agents)}
    assert r["financial"].verwacht == 3 * 12 and r["financial"].gekregen == 3 * 9  # vix: 3 horizonnen per ronde ontbreken
    assert r["financial"].gemist_aandeel == pytest.approx(0.25)
    assert r["currency"].gemist_aandeel == 0.0 and r["sector"].gemist_aandeel == 0.0


def test_een_onparseerbaar_antwoord_telt_volledig_als_gemist(kopie, fomc_kalender):
    agents = default_agents()
    uitkomsten = po.draai(kopie, _model_dat_antwoordt(kapot=True), agents, po.voorspeldata()[:1])
    assert all(u.gekregen == 0 and u.issues for u in uitkomsten)
    assert all(a.gemist_aandeel == 1.0 for a in po.rapport(kopie, agents))


def test_zonder_de_fomc_besluitdagen_weigert_de_run_te_starten(kopie, monkeypatch):
    """Met een kalender die pas op 28 oktober begint (zoals vóór 02-10) zou de agent op 6 juli de verkeerde vergadering zien."""
    monkeypatch.setattr(res, "FOMC_MEETING_DATES", tuple(d for d in res.FOMC_MEETING_DATES if d >= date(2026, 10, 1)))
    client = _model_dat_antwoordt()
    with pytest.raises(po.PseudoOosFout, match="FOMC-kalender mist besluitdagen rond 2026-07-06"):
        po.draai(kopie, client, default_agents(), po.voorspeldata())
    client.messages.create.assert_not_called()
    assert kopie.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0


def test_de_echte_kalender_dekt_het_hele_venster():
    """Zonder monkeypatch: met 29 juli en 16 september erin is er voor elke van de dertien maandagen een besluitdag binnen acht weken."""
    po.controleer_fomc_kalender(po.voorspeldata())
    assert date(2026, 7, 29) in res.FOMC_MEETING_DATES and date(2026, 9, 16) in res.FOMC_MEETING_DATES


def test_de_fomc_doelen_wikkelen_af_op_de_echte_besluitdagen_van_juli_en_september():
    """Met de uitkomsten uit de persberichten: 29 juli ongewijzigd (3,75), 16 september verhoogd (4,00). Een voorspelling
    van 6 juli (horizon 1) loopt tot 29 juli, een van 3 augustus (horizon 1) tot 16 september, en horizon 2 vanaf 6 juli ook."""
    from contract.resolution import Observation, direction_after_fomc

    def obs(dag, waarde, gezien=None):
        d = _dt(dag)
        return Observation(source_time=d, value=waarde, first_seen=gezien or d, claim_id=int(d.timestamp()) % 100000)

    reeks = [obs(date(2026, 6, 30), 3.75), obs(date(2026, 7, 30), 3.75), obs(date(2026, 8, 3), 3.75),
             obs(date(2026, 9, 14), 3.75), obs(date(2026, 9, 17), 4.00)]
    juli = datetime(2026, 7, 6, 7, 15, tzinfo=UTC)
    aug = datetime(2026, 8, 3, 7, 15, tzinfo=UTC)
    assert direction_after_fomc(reeks, juli, 1).value == 0.0  # 29 juli: ongewijzigd telt als niet hoger
    assert direction_after_fomc(reeks, juli, 2).value == 1.0  # 16 september: verhoogd
    assert direction_after_fomc(reeks, aug, 1).value == 1.0   # eerstvolgende na 3 augustus is 16 september


def test_de_fomc_controle_accepteert_een_gat_van_zeven_weken_en_weigert_negen():
    datums = [datetime(2026, 7, 6, 7, 15, tzinfo=UTC)]
    po.controleer_fomc_kalender(datums, kalender=[date(2026, 8, 30)])  # 55 dagen
    with pytest.raises(po.PseudoOosFout):
        po.controleer_fomc_kalender(datums, kalender=[date(2026, 9, 2)])  # 58 dagen
    with pytest.raises(po.PseudoOosFout, match="geen"):
        po.controleer_fomc_kalender(datums, kalender=[date(2026, 7, 1)])  # alleen in het verleden


def test_afwikkelen_wikkelt_af_wat_afgelopen_is_en_laat_de_rest_wachten(kopie, fomc_kalender):
    agents = default_agents()
    po.draai(kopie, _model_dat_antwoordt(), agents, po.voorspeldata()[:1])  # 6 juli
    r = po.afwikkelen(kopie, datetime(2026, 10, 2, 12, 0, tzinfo=UTC))
    assert r.errors == [] and r.resolved > 0
    rap = {a.domain: a for a in po.rapport(kopie, agents)}
    assert rap["currency"].afgewikkeld == 9  # 5, 21 en 63 handelsdagen vanaf 6 juli zijn allemaal voorbij (63 hd = ~1 okt)
    assert all(a.verwacht >= a.gekregen for a in rap.values())


# --------------------------------------------------------------------------
# Kosten, het script en alleen-lezen
# --------------------------------------------------------------------------


def test_de_kostenschatting_komt_uit_echte_promptlengtes_en_belt_het_model_niet(kopie):
    s = po.schat_kosten(kopie, default_agents(), po.voorspeldata(), "claude-sonnet-5-5")
    assert s.aanroepen == 13 * 5 and s.input_tokens > 13 * 5 * 500 and s.output_tokens > 13 * 5 * 300
    assert 0 < s.kosten_usd < 20  # een paar dollar, ver onder de maandgrens van 200
    assert s.model == "claude-sonnet-5-5"


def _script():
    spec = importlib.util.spec_from_file_location("pseudo_oos_script", ROOT / "pseudo_oos.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_het_script_draaien_zonder_ja_is_een_droge_run(bronnen, tmp_path, fomc_kalender):
    script = _script()
    regels: list[str] = []
    doel = str(tmp_path / "k.db")
    assert script.main(["voorbereiden", "--bron", bronnen, "--doel", doel], uit=regels.append) == 0
    assert any("Kopie gemaakt" in r for r in regels) and any("De echte database is niet gewijzigd" in r for r in regels)

    def mag_niet(conn):
        raise AssertionError("er mag geen client gemaakt worden zonder --ja")

    regels.clear()
    assert script.main(["draaien", "--db", doel], client_fabriek=mag_niet, uit=regels.append) == 0
    assert any("droge run" in r and "niets aangeroepen" in r for r in regels)
    assert sqlite3.connect(doel).execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0


def test_het_script_draaien_met_ja_gebruikt_de_client_en_rapporteert(bronnen, tmp_path, fomc_kalender):
    script = _script()
    doel = str(tmp_path / "k.db")
    script.main(["voorbereiden", "--bron", bronnen, "--doel", doel], uit=lambda r: None)
    regels: list[str] = []
    client = _model_dat_antwoordt(weglaten={"vix"})
    code = script.main(["draaien", "--db", doel, "--ja", "--van", "2026-07-06", "--tot", "2026-07-13"],
                       client_fabriek=lambda conn: client, uit=regels.append)
    assert code == 0 and client.messages.create.call_count == 2 * 5
    regels.clear()
    script.main(["rapport", "--db", doel], uit=regels.append)
    tekst = "\n".join(regels)
    assert "financial" in tekst and "meer dan 5% gemist" in tekst and "heroverwegen" in tekst


def test_het_script_weigert_de_echte_database_zonder_voorbereiding(bronnen, capsys):
    script = _script()
    assert script.main(["draaien", "--db", bronnen, "--ja"], client_fabriek=lambda c: MagicMock()) == 1
    assert "geen voorbereide pseudo-OOS-database" in capsys.readouterr().err


def test_het_script_audit_en_prompt_tonen_wat_het_model_zou_zien(bronnen, tmp_path):
    script = _script()
    doel = str(tmp_path / "k.db")
    script.main(["voorbereiden", "--bron", bronnen, "--doel", doel], uit=lambda r: None)
    regels: list[str] = []
    script.main(["audit", "--db", doel], uit=regels.append)
    tekst = "\n".join(regels)
    assert "nonfarm_payrolls" in tekst and "2026-05-01" in tekst and "GEEN DATA" not in tekst
    regels.clear()
    script.main(["prompt", "--db", doel, "--agent", "sector", "--datum", "2026-07-06"], uit=regels.append)
    assert "=== GEBRUIKERSPROMPT (sector, 2026-07-06) ===" in regels[0] and "bekend op 2026-07-06" in regels[0]


def test_de_module_opent_de_bron_alleen_lezend():
    tekst = (ROOT / "src" / "scoring" / "pseudo_oos.py").read_text()
    assert 'f"file:{bron_pad}?mode=ro"' in tekst
    # de bron wordt alleen via backup gekopieerd; er staat geen schrijfopdracht op de bron-verbinding
    assert "bron_conn.execute" not in tekst and "bron_conn.commit" not in tekst
