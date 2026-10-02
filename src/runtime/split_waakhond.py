"""
runtime/split_waakhond.py
De waakhond voor aandelensplitsingen (roadmap 1.5/4.5, 02-10-2026). ALLEEN LEZEN en alleen waarschuwen: hij wijzigt niets.

De correctie voor splitsingen staat in een lijst (`contract/corporate_actions.py::SPLITSINGEN`), met opzet expliciet en niet afgeleid. Een
lijst kan achterlopen: een nieuwe splitsing staat er pas in als iemand hem toevoegt. Deze waakhond zoekt daarom in de ETF-reeksen
(de sector-ETF's en SPY) naar een sprong van meer dan ~35% tussen twee opeenvolgende waarnemingen, en meldt drie dingen:

  ONVERKLAARD   een sprong die niet in de lijst staat: waarschijnlijk een nieuwe splitsing die nog moet worden toegevoegd.
  AFWIJKEND     een geregistreerde splitsing waarvan de sprong in de data niet bij de opgegeven verhouding past (een typefout in de verhouding).
  ONBEVESTIGD   een geregistreerde splitsing waar de data aan beide kanten wel waarnemingen heeft maar geen sprong op die datum toont
                (een typefout in de datum): dan corrigeert de lijst een sprong die er niet is, en maakt hij de reeks fout.

Een sector-ETF beweegt nooit 35% in één dag; een gewone beweging, ook die van een crashdag, blijft ruim binnen de grenzen.
De waakhond draait bij elke dagelijkse run (alleen een logregel; een fout hier laat de run nooit mislukken) en staat in `freeze_status.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from contract.corporate_actions import SPLITSINGEN, Splitsing
from contract.resolution import eerste_prints

GRENS_LAAG = 0.65
GRENS_HOOG = 1.55
AFWIJKING_TOEGESTAAN = 0.15  # de gemeten sprong mag 15% van de geregistreerde verhouding afwijken (de koers beweegt die dag ook)


@dataclass(frozen=True)
class Sprong:
    metric_key: str
    vorige_datum: date
    datum: date  # de eerste waarnemingsdag na de sprong
    voor: float
    na: float

    @property
    def verhouding(self) -> float:
        """Nieuwe aandelen per oud aandeel zoals de sprong het laat zien (koers halveert -> ongeveer 2)."""
        return self.voor / self.na


@dataclass
class Beoordeling:
    onverklaard: list[Sprong]
    afwijkend: list[tuple[Sprong, Splitsing]]
    onbevestigd: list[Splitsing]

    @property
    def is_schoon(self) -> bool:
        return not (self.onverklaard or self.afwijkend or self.onbevestigd)


def etf_sleutels() -> list[str]:
    """De reeksen waarin een splitsing kan voorkomen: de sector-ETF's en de SPY-benchmark."""
    from agents import sector_agent

    return list(sector_agent.SECTOR_ETFS)


def _eerste_prints(conn, key: str):
    from scoring.resolver import observations_for

    return eerste_prints(observations_for(conn, key, corrigeer_splitsingen=False))  # de ruwe reeks: juist díe moeten we beoordelen


def vind_sprongen(conn, sleutels: list[str] | None = None) -> list[Sprong]:
    """Elke sprong buiten de grenzen tussen twee opeenvolgende waarnemingsdagen in de ruwe reeks."""
    uit = []
    for key in sleutels if sleutels is not None else etf_sleutels():
        prints = sorted(_eerste_prints(conn, key), key=lambda o: o.source_time)
        for a, b in zip(prints, prints[1:]):
            if a.value > 0 and b.value > 0 and not GRENS_LAAG < b.value / a.value < GRENS_HOOG:
                uit.append(Sprong(key, a.source_time.date(), b.source_time.date(), a.value, b.value))
    return uit


def beoordeel(conn, sleutels: list[str] | None = None, splitsingen: tuple[Splitsing, ...] | None = None) -> Beoordeling:
    lijst = SPLITSINGEN if splitsingen is None else splitsingen
    sleutels = sleutels if sleutels is not None else etf_sleutels()
    sprongen = vind_sprongen(conn, sleutels)
    onverklaard, afwijkend, gezien = [], [], set()
    for sp in sprongen:
        passend = [s for s in lijst if s.metric_key == sp.metric_key and sp.vorige_datum < s.datum <= sp.datum]
        if not passend:
            onverklaard.append(sp)
            continue
        s = passend[0]
        gezien.add((s.metric_key, s.datum))
        if abs(sp.verhouding / s.verhouding - 1) > AFWIJKING_TOEGESTAAN:
            afwijkend.append((sp, s))
    onbevestigd = []
    for s in lijst:
        if s.metric_key not in sleutels or (s.metric_key, s.datum) in gezien:
            continue
        data = [o.source_time.date() for o in _eerste_prints(conn, s.metric_key)]
        if any(d < s.datum for d in data) and any(d >= s.datum for d in data):
            onbevestigd.append(s)
    return Beoordeling(onverklaard, afwijkend, onbevestigd)


def waarschuwingen(conn, sleutels: list[str] | None = None, splitsingen: tuple[Splitsing, ...] | None = None) -> list[str]:
    """De logregels, leeg als alles klopt."""
    b = beoordeel(conn, sleutels, splitsingen)
    regels = []
    for sp in b.onverklaard:
        regels.append(
            f"Mogelijke splitsing NIET geregistreerd: {sp.metric_key} {sp.vorige_datum} -> {sp.datum}, {sp.voor:.2f} -> {sp.na:.2f} "
            f"(verhouding {sp.verhouding:.2f}). Voeg hem toe aan SPLITSINGEN in contract/corporate_actions.py, alleen als het echt een splitsing is."
        )
    for sp, s in b.afwijkend:
        regels.append(
            f"Geregistreerde splitsing past niet bij de data: {s.metric_key} {s.datum} staat op verhouding {s.verhouding:g}, "
            f"de sprong in de data is {sp.verhouding:.2f} ({sp.voor:.2f} -> {sp.na:.2f})."
        )
    for s in b.onbevestigd:
        regels.append(
            f"Geregistreerde splitsing niet bevestigd door de data: {s.metric_key} {s.datum} (verhouding {s.verhouding:g}); er is geen sprong "
            f"op die datum, dus de correctie maakt de reeks mogelijk fout. Controleer de datum."
        )
    return regels
