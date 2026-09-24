"""
equity_agent.py
Stap C.1: de EERSTE domain agent die op analyst_agent.ai's bestaande output
voortbouwt, in plaats van (zoals B.1/B.2) een eigen databron te
implementeren. Letterlijk het stappenplan: "dunne adapter die
analyst_agent.py's bestaande output in het A-contract giet".

SCOPE-AFBAKENING (bewust): dit bestand is de ADAPTER -- een pure,
deterministische omzetting van analyst_agent.ai's bekende output-vorm
(dezelfde velden als diens reporting/lineage.py::build_lineage_manifest()
gebruikt: verified_metrics, altman/piotroski/reverse-DCF-resultaten, plus
de al-gegenereerde rapporttekst) naar Claims/DomainOutput. Het roept
analyst_agent.ai NIET zelf aan (geen subprocess, geen cross-repo import) --
HOE de output van een analyst_agent.ai-run hier terechtkomt (bestand,
subprocess, API) is de daadwerkelijke koppeling ("later gekoppeld als
equity-subagent", zie CLAUDE.md) en een apart, infrastructureel vraagstuk
dat nog niet is dichtgetimmerd. AnalystAgentReport hieronder is het
contract daarvoor: wie die koppeling later bouwt, hoeft alleen deze vorm
te vullen.

GEEN EIGEN LLM-DEEP-DIVE HIER (in tegenstelling tot B.1/B.2): het
genereren van de rapporttekst gebeurde al, mét analyst_agent.ai's eigen
4-reviewer-QC -- dat IS de deep-dive, niet nog eens dunnetjes overgedaan
(zie CLAUDE.md: "Geen 4-parallelle-reviewers-QC hier overnemen"). We nemen
`needs_review` 1-op-1 over in plaats van onze eigen qc.apply_qc() er
overheen te draaien.

TICKER-NAMESPACING (nieuw t.o.v. B.1/B.2, let op): "equity" heeft -- anders
dan monetary_policy/currency -- meerdere gelijktijdige instanties (elke
ticker), en verschillende tickers delen dezelfde metric_key-namen (bijv.
"sec_operating_margin" voor zowel NKE als AAPL). Zonder namespacing zou
triggers.trigger_engine.evaluate_surprise() de nieuwe marge van de ene
ticker per ongeluk vergelijken met de vorige marge van een ANDERE ticker
(load_latest_claims() filtert alleen op domain+metric_key, niet op ticker).
Oplossing: elke ticker krijgt zijn EIGEN domain-string, "equity:<TICKER>"
i.p.v. één plat "equity" -- dit werkt zonder enige aanpassing elders (in
manager.py, synthesizer.py, storage/schema.py) omdat "domain" in dit hele
systeem altijd al een kale string was, geen vaste enum. Zie equity_domain().

EQUITY_METRIC_SPECS-tolerances zijn illustratieve plaatshouders, zelfde
voorbehoud als B.1/B.2 -- zie agents/base.py's docstring en
docs/roadmap.md sectie H.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from agents.base import MetricSpec, evaluate_deltas
from contract.output_contract import Claim, Confidence, DomainOutput, Mode, now_utc
from storage.schema import load_latest_claims, save_domain_output
from triggers.trigger_engine import TriggerEvent

DOMAIN_PREFIX = "equity"

# Zelfde selectie, labels en afleiding-toelichting als analyst_agent.ai's
# reporting/lineage.py::_VERIFIED_METRIC_FIELDS -- dit IS de bestaande
# herkomst-informatie, bewust 1-op-1 overgenomen, geen nieuwe interpretatie.
VERIFIED_METRIC_FIELDS = [
    ("sec_operating_margin", "Operating margin", "OperatingIncomeLoss / Revenues"),
    ("sec_net_margin", "Net margin", "NetIncomeLoss / Revenues"),
    ("sec_free_cashflow", "Vrije kasstroom", "Operating cash flow - capex"),
    ("sec_revenue_yoy_growth", "Omzetgroei YoY", "Revenues, twee opeenvolgende jaren"),
    ("sec_net_income_yoy_growth", "Nettowinstgroei YoY", "NetIncomeLoss, twee opeenvolgende jaren"),
    ("sec_ebitda", "EBITDA", "OperatingIncomeLoss + D&A"),
    ("sec_net_debt", "Net schuld", "Langlopende + kortlopende schuld min cash"),
    ("sec_net_debt_to_ebitda", "Net debt/EBITDA", "Net schuld gedeeld door EBITDA"),
    ("sec_interest_coverage_ratio", "Rentedekking", "EBIT / rentelasten"),
    ("sec_normalized_ev_to_ebitda", "Genormaliseerde EV/EBITDA", "Market cap + net schuld, gedeeld door EBITDA"),
    ("sec_cash_conversion_cycle_days", "Cash conversion cycle", "DSO + DIO - DPO"),
    ("sec_roic", "ROIC", "NOPAT / geinvesteerd kapitaal (aanname: 25% belastingtarief)"),
]

# Bewust een kleine subset van VERIFIED_METRIC_FIELDS -- alleen de metrics
# waarvoor een afwijking t.o.v. de vorige analyse van dezelfde ticker
# op zichzelf al betekenisvol is. Tolerances zijn illustratieve
# plaatshouders (zie moduledocstring).
EQUITY_METRIC_SPECS = {
    "sec_operating_margin": MetricSpec(label="Operating margin", tolerance=0.02, severity="medium"),
    "sec_net_margin": MetricSpec(label="Net margin", tolerance=0.02, severity="medium"),
    "sec_net_debt_to_ebitda": MetricSpec(label="Net debt/EBITDA", tolerance=0.5, severity="high"),
    "sec_interest_coverage_ratio": MetricSpec(label="Rentedekking", tolerance=1.0, severity="high"),
    "sec_roic": MetricSpec(label="ROIC", tolerance=0.02, severity="medium"),
}


def equity_domain(ticker: str) -> str:
    """De per-ticker domain-string -- zie moduledocstring ('TICKER-
    NAMESPACING') voor waarom dit niet gewoon 'equity' is."""
    return f"{DOMAIN_PREFIX}:{ticker.upper()}"


@dataclass
class AnalystAgentReport:
    """De velden die de adapter nodig heeft uit een AFGERONDE
    analyst_agent.ai-run voor één ticker -- geen kopie van elk intern
    object uit die pipeline, alleen wat hier daadwerkelijk gebruikt wordt.
    `needs_review`/`review_issues` komen 1-op-1 van analyst_agent.ai's eigen
    QC (zie moduledocstring: wij draaien hier geen eigen review overheen)."""

    ticker: str
    generated_at: datetime
    verified_metrics: dict
    altman_result: dict | None = None
    piotroski_result: dict | None = None
    reverse_dcf_result: dict | None = None
    report_text: str | None = None
    needs_review: bool = False
    review_issues: list[str] = field(default_factory=list)


def adapt_to_claims(report: AnalystAgentReport) -> list[Claim]:
    """Zelfde selectie-logica als lineage.py::build_lineage_manifest(), maar
    naar Claim-objecten (met metric_key voor de delta-trigger, en RAUWE
    numerieke waarden i.p.v. lineage.py's kant-en-klaar geformatteerde
    percentage-strings -- formatteren voor weergave is een taak van de
    output-laag, sectie G, niet van deze data-laag). Ontbrekende/foutieve
    brondata wordt overgeslagen, niet gegokt -- zelfde gedrag als het
    origineel."""
    domain = equity_domain(report.ticker)
    claims: list[Claim] = []

    def add(metric_key, label, value, source, note=None):
        if value is None:
            return
        claims.append(
            Claim(
                domain=domain,
                claim=label,
                value=value,
                source=source,
                confidence=Confidence.HIGH,
                analysis_time=report.generated_at,
                metric_key=metric_key,
                note=note,
            )
        )

    for key, label, note in VERIFIED_METRIC_FIELDS:
        entry = report.verified_metrics.get(key) if report.verified_metrics else None
        if isinstance(entry, dict) and "value" in entry:
            add(key, label, entry["value"], "SEC EDGAR", note=note)

    if report.altman_result and "error" not in report.altman_result:
        add(
            "altman_z_score", "Altman Z-Score", report.altman_result.get("z_score"), "SEC EDGAR",
            note="Berekend uit 5 SEC-balans-/resultatenposten",
        )

    if report.piotroski_result and "error" not in report.piotroski_result:
        # Waarde is "score/max_score" (bijv. "7/9") -- geen los, vergelijkbaar
        # cijfer, dus BEWUST geen metric_key (zie output_contract.py:
        # checkable_claims() is voor cijfers die later automatisch tegen een
        # drempel gecontroleerd kunnen worden; een geformatteerde breuk-string
        # is dat niet).
        claims.append(
            Claim(
                domain=domain,
                claim="Piotroski F-Score",
                value=f"{report.piotroski_result['score']}/{report.piotroski_result['max_score']}",
                source="SEC EDGAR",
                confidence=Confidence.HIGH,
                analysis_time=report.generated_at,
                note="9-punts checklist over twee opeenvolgende jaren SEC-data",
            )
        )

    if report.reverse_dcf_result and "error" not in report.reverse_dcf_result:
        add("reverse_dcf_wacc", "WACC (reverse-DCF)", report.reverse_dcf_result.get("wacc"), "Berekend (CAPM)")
        add(
            "reverse_dcf_implied_growth", "Geïmpliceerde FCF-groei",
            report.reverse_dcf_result.get("implied_annual_fcf_growth"), "Berekend (reverse-DCF)",
        )

    return claims


def adapt_narrative_claim(report: AnalystAgentReport) -> Claim:
    """De al-gegenereerde rapporttekst als één kwalitatieve claim -- zelfde
    vorm als agents.base.run_deep_dive()'s narrative-claim, zodat de
    synthesizer (B.3) equity-output identiek kan behandelen als een B.1/B.2
    deep-dive, ook al is de tekst hier niet door ONZE eigen LLM-call
    geschreven."""
    return Claim(
        domain=equity_domain(report.ticker),
        claim="analyst_agent.ai volledige analyse",
        value=report.report_text or "(geen rapporttekst meegegeven)",
        source="analyst_agent.ai",
        confidence=Confidence.LOW if report.needs_review else Confidence.HIGH,
        analysis_time=report.generated_at,
    )


def ingest_report(
    conn,
    report: AnalystAgentReport,
    metric_specs: dict[str, MetricSpec] | None = None,
    now=None,
) -> tuple[DomainOutput | None, DomainOutput | None, list[TriggerEvent]]:
    """Zet één afgeronde analyst_agent.ai-run om in twee DomainOutputs --
    MONITORING (de losse, machine-checkbare claims, needs_review altijd
    False: dit zijn deterministisch berekende cijfers) en DEEP_DIVE
    (dezelfde claims + de narratieve rapporttekst, needs_review 1-op-1 van
    analyst_agent.ai overgenomen) -- en berekent delta-triggers t.o.v. de
    vorige analyse van DEZELFDE ticker via agents.base.evaluate_deltas().

    Analoog aan agents.base.run_monitoring(), maar zonder eigen fetch/
    data-health (die pull gebeurde al, door analyst_agent.ai, buiten dit
    systeem). Geeft (None, None, []) terug als er geen enkele claim uit de
    verified_metrics te bouwen viel -- geen gok, gewoon niets om op te
    slaan of te vergelijken."""
    now = now or now_utc()
    metric_specs = metric_specs if metric_specs is not None else EQUITY_METRIC_SPECS
    domain = equity_domain(report.ticker)

    claims = adapt_to_claims(report)
    if not claims:
        return None, None, []

    # Vorige observaties per metric OPHALEN VOORDAT de nieuwe claims worden
    # opgeslagen -- zelfde reden als run_monitoring: anders vergelijk je een
    # claim met zichzelf.
    previous_by_metric = {
        c.metric_key: load_latest_claims(conn, domain, metric_key=c.metric_key)
        for c in claims
        if c.metric_key is not None
    }

    monitoring_output = DomainOutput(domain=domain, mode=Mode.MONITORING, generated_at=now, claims=claims)
    save_domain_output(conn, monitoring_output)

    triggers = evaluate_deltas(domain, claims, metric_specs, previous_by_metric, now=now)

    narrative_claim = adapt_narrative_claim(report)
    deep_dive_output = DomainOutput(
        domain=domain,
        mode=Mode.DEEP_DIVE,
        generated_at=now,
        claims=claims + [narrative_claim],
        needs_review=report.needs_review,
        review_issues=list(report.review_issues),
    )
    save_domain_output(conn, deep_dive_output)

    return monitoring_output, deep_dive_output, triggers
