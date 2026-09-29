"""
prediction.py
Roadmap 4.1 (fase 2) -- het voorspellingscontract. Dit is blokkade 3 van de
vier uit deel A: zonder deze vorm is er niets te scoren, en zonder scoring
is een half jaar draaien een half jaar meningen verzamelen.

WAAROM DIT ZO STRENG IS. Een voorspelling is pas een voorspelling als hij
achteraf FOUT kan blijken. Alles hieronder dient dat ene doel:

- De regel waarmee hij gescoord wordt zit er al in op het moment van
  voorspellen (`resolution_rule`). Zonder dat veld volgt over zes maanden
  een discussie over wat de agent "eigenlijk bedoelde", en dan is het
  track record waardeloos.
- Een prediction is ONVERANDERLIJK (frozen dataclass, en `save_prediction()`
  in storage/schema.py kent geen update-pad). Achteraf bijstellen is
  precies de fout die dit hele project probeert te vermijden.
- Verplichte velden worden bij CONSTRUCTIE geweigerd, niet pas bij het
  opslaan -- zelfde fail-loud-precedent als output_contract.py::Claim. De
  mechanische QC-eis uit roadmap 4.1 ("weigert een prediction zonder
  kwantielen/kans, regel, horizon of model_id") zit dus hier en niet in
  src/qc/: dat is de veiligheidsgordel voor TEKST, dit is een vormcheck op
  data.

TWEE VORMEN, en de keuze ertussen is niet vrij (27-09-2026):

- `kind=QUANTILE` voor numerieke doelen: q10/q50/q90. Richtings- en
  drempelkansen worden hieruit AFGELEID, niet apart gevraagd -- kwantielen
  bevatten meer informatie per resolutie, en dat is precies wat er te kort
  is (zie deel A, correctie 2: effectieve n per agent op 63 dagen is ~3-4
  episodes in zes maanden, niet ~130).
- `kind=BINARY` alleen waar geen continue waarde bestaat ("FOMC verhoogt
  op 2026-12-10"): een kans tussen 0 en 1 plus een machine-uitvoerbare
  `event_rule`.

HORIZONNEN ZIJN CADANS-BEWUST. Een 5-daagse voorspelling op CPI bestaat
niet -- die reeks komt maandelijks. Vandaar `horizon_kind`:
TRADING_DAYS (5/21/63) voor dagreeksen, RELEASES (1/2/3 volgende prints)
voor week- en maandreeksen.

BEWUST NIET HIER: het produceren van predictions (dat is de forecast-ronde,
2.0), de resolver en de scores (4.5, aparte `evaluations`-tabel), en de
menselijke invoer (4.8). Dit bestand legt alleen de vorm vast.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
import os
from enum import Enum
from typing import Mapping

from contract.graph import GRAPH_VERSION, Node
from contract.resolution import ResolutionMethod

CONTRACT_VERSION = "v0"
"""Versie van DIT contract. Een wijziging hieraan start een nieuw cohort in
de scoring (roadmap 4.5) -- anders vergelijk je voorspellingen die onder
verschillende regels tot stand kwamen. Een modelwissel of promptwijziging
is daarentegen een COVARIAAT binnen hetzelfde cohort (`model_id`,
`prompt_version`), want anders zijn er in mei acht cohorten van drie
weken."""

COHORT_0 = "cohort_0"
"""Het eerste echte cohort, dat vanaf T0-b loopt. Nooit hardcoden als
default: zie `current_cohort()`."""
DRY_RUN_COHORT = "dry_run"
"""Alles wat vóór T₀ᵇ wordt voorspeld: de dry-run, de eerste weken op de VPS.
Bewust géén cohort: contract, prompts en drempels zijn dan nog niet bevroren."""
PSEUDO_OOS_COHORT = "pseudo_oos"
"""Gereserveerd voor de pseudo-out-of-sample-run (4.4)."""
KNOWN_COHORTS = (DRY_RUN_COHORT, PSEUDO_OOS_COHORT, COHORT_0)
COHORT_ENV_VAR = "MI_COHORT"


def current_cohort(environ: Mapping[str, str] | None = None) -> str:
    """Het cohort waaronder NIEUWE voorspellingen nu worden opgeslagen.

    WAAROM DIT UIT DE OMGEVING KOMT. Tot 29-09 stond `cohort_0` als vaste
    default op `Prediction`. Zodra de wekelijkse ronde op de VPS draait,
    zouden de voorspellingen van oktober dan als het ECHTE cohort zijn
    opgeslagen -- vóór de freeze van contract, prompts en drempels. Dat is
    niet achteraf te herstellen: `predictions` heeft bewust geen update-pad,
    dus een verkeerd label is definitief.

    DE DEFAULT IS DE VEILIGE KANT. Zonder `MI_COHORT` (of met een lege
    waarde) is het `dry_run`. Het echte cohort krijg je alleen door het
    BEWUST aan te zetten (`MI_COHORT=cohort_0` in `.env`, op T₀ᵇ). De fout
    die overblijft is dus "vergeten om te schakelen", en die is zichtbaar
    (het staat in het log en in `SELECT cohort, COUNT(*) FROM predictions`)
    en herstelbaar door de klok een dag later te starten -- de andere kant
    (te vroeg cohort_0) is dat niet.

    Een onbekende waarde (een typefout als `cohort0`) is een fout en geen
    stille terugval: anders ontstaat er een zwevend cohort dat niemand
    ooit meet."""
    bron = os.environ if environ is None else environ
    waarde = bron.get(COHORT_ENV_VAR, "").strip()
    if not waarde:
        return DRY_RUN_COHORT
    if waarde not in KNOWN_COHORTS:
        raise ValueError(
            f"{COHORT_ENV_VAR}={waarde!r} is geen bekend cohort. "
            f"Toegestaan: {', '.join(KNOWN_COHORTS)}. Leeg laten betekent {DRY_RUN_COHORT}."
        )
    return waarde


class PredictionKind(str, Enum):
    QUANTILE = "quantile"
    BINARY = "binary"


class HorizonKind(str, Enum):
    """TRADING_DAYS voor dagreeksen (5/21/63), RELEASES voor week- en
    maandreeksen (de volgende 1/2/3 prints). Het onderscheid bestaat omdat
    een horizon in dagen op een maandreeks niet te resolven is."""

    TRADING_DAYS = "trading_days"
    RELEASES = "releases"


@dataclass(frozen=True)
class Prediction:
    """Eén falsifieerbare uitspraak. Onveranderlijk zodra gemaakt.

    `agent` omvat bewust meer dan de domain agents: `human:dd`,
    `human:partner`, `baseline:persistence`, `baseline:climatology`,
    `baseline:ridge` en `synthesizer` gebruiken hetzelfde contract. Zonder
    dat zijn mens en model niet op dezelfde meetlat te leggen, en dat is
    precies wat 4.8 wil.
    """

    agent: str
    domain: str
    target_metric_key: str
    kind: PredictionKind
    horizon_kind: HorizonKind
    horizon_n: int
    resolves_at: datetime
    resolution_rule: str
    resolution_method: ResolutionMethod
    created_at: datetime
    model_id: str
    prompt_version: str

    # Kwantielen (kind=QUANTILE)
    q10: float | None = None
    q50: float | None = None
    q90: float | None = None

    # Binaire gebeurtenis (kind=BINARY)
    probability: float | None = None
    event_rule: str | None = None

    # Herkomst en context
    cohort: str = field(default_factory=current_cohort)
    contract_version: str = CONTRACT_VERSION
    graph_version: str = GRAPH_VERSION
    graph_node: Node | None = None
    causal_chain: tuple[str, ...] = ()
    evidence_claim_ids: tuple[int, ...] = ()
    trigger_version: str | None = None
    trigger_conditioned: bool = False
    regime_at_creation: str | None = None
    market_implied_ref: float | None = None
    benchmark_metric_key: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        for naam in ("agent", "domain", "target_metric_key", "model_id", "prompt_version"):
            if not getattr(self, naam):
                raise ValueError(f"Prediction.{naam} mag niet leeg zijn")

        if not self.resolution_rule:
            raise ValueError(
                "Prediction zonder resolution_rule is ongeldig -- zonder de regel "
                "waarmee hij gescoord wordt, is dit geen voorspelling maar een mening "
                f"(agent={self.agent!r}, target={self.target_metric_key!r})"
            )

        for naam in ("created_at", "resolves_at"):
            waarde = getattr(self, naam)
            if waarde.tzinfo is None:
                raise ValueError(f"Prediction.{naam} moet timezone-aware zijn (gebruik timezone.utc)")
        if self.resolves_at <= self.created_at:
            raise ValueError(
                f"resolves_at ({self.resolves_at.isoformat()}) moet NA created_at "
                f"({self.created_at.isoformat()}) liggen"
            )

        if self.horizon_n <= 0:
            raise ValueError(f"horizon_n moet positief zijn, kreeg {self.horizon_n!r}")

        if self.cohort not in KNOWN_COHORTS:
            raise ValueError(
                f"onbekend cohort {self.cohort!r}; toegestaan: {', '.join(KNOWN_COHORTS)}"
            )

        # De methode is wat de resolver STRAKS uitvoert; de regeltekst is
        # wat een mens leest. Beide staan op de rij, want een voorspelling
        # die alleen tekst draagt is niet deterministisch af te wikkelen,
        # en een die alleen een methode draagt is niet uit te leggen.
        if self.resolution_method is ResolutionMethod.RELATIVE_RETURN and not self.benchmark_metric_key:
            raise ValueError(
                "resolution_method=relative_return vereist een benchmark_metric_key -- "
                "zonder benchmark is er geen relatief rendement te berekenen "
                f"(target={self.target_metric_key!r})"
            )

        if self.kind is PredictionKind.QUANTILE:
            self._valideer_kwantielen()
        else:
            self._valideer_binair()

    def _valideer_kwantielen(self) -> None:
        ontbrekend = [n for n in ("q10", "q50", "q90") if getattr(self, n) is None]
        if ontbrekend:
            raise ValueError(
                f"kind=quantile vereist q10, q50 en q90; ontbreekt: {', '.join(ontbrekend)}"
            )
        if not (self.q10 <= self.q50 <= self.q90):
            raise ValueError(
                f"kwantielen moeten oplopen: q10={self.q10}, q50={self.q50}, q90={self.q90}"
            )
        if self.probability is not None or self.event_rule is not None:
            raise ValueError(
                "kind=quantile mag geen probability/event_rule hebben -- richtings- en "
                "drempelkansen worden uit de kwantielen AFGELEID, niet apart opgegeven "
                "(roadmap deel A, correctie 2)"
            )

    def _valideer_binair(self) -> None:
        if self.probability is None:
            raise ValueError("kind=binary vereist een probability tussen 0 en 1")
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(f"probability moet tussen 0 en 1 liggen, kreeg {self.probability!r}")
        if not self.event_rule:
            raise ValueError(
                "kind=binary vereist een machine-uitvoerbare event_rule "
                '(bijv. "FOMC target range hoger op 2026-12-10")'
            )
        if any(getattr(self, n) is not None for n in ("q10", "q50", "q90")):
            raise ValueError("kind=binary mag geen kwantielen hebben")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["horizon_kind"] = self.horizon_kind.value
        d["graph_node"] = self.graph_node.value if self.graph_node else None
        d["created_at"] = self.created_at.isoformat()
        d["resolves_at"] = self.resolves_at.isoformat()
        d["causal_chain"] = list(self.causal_chain)
        d["evidence_claim_ids"] = list(self.evidence_claim_ids)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
