# Causale Graaf — de economische machine, expliciet

**Status: leeg sjabloon, in te vullen in fase 1 (zie `docs/roadmap.md`,
sectie 1.10).** Dit is handwerk voor DD en zijn partner, geen codeerwerk
en geen LLM-werk. Het invullen hiervan is het intellectuele deel van het
project waar de edge vandaan moet komen; de rest is infrastructuur.

## Waarom dit bestand bestaat

Zonder gedeeld model produceert elke domain agent zijn eigen
vrijzwevende analyse. De currency agent kan dan stilzwijgend het
tegendeel beweren van de monetary agent zonder dat iemand het merkt — de
synthesizer plakt het dicht met vloeiend Nederlands. Met een gedeelde
graaf wordt tegenstrijdigheid een **meetbaar conflict op een knoop** in
plaats van een stijlkwestie.

Dit is ook wat een Dalio-achtig systeem onderscheidt van een verzameling
losse analisten: de causale structuur is expliciet en door mensen
geschreven, de inferentie is deterministisch en reproduceerbaar, en het
taalmodel voedt hem alleen met waarnemingen. Het LLM raakt de kansen
nooit aan.

## Wat dit bestand NIET is

- **Geen Bayesiaans netwerk.** De kansen op de pijlen komen pas in fase 5
  (roadmap 3.4), uit zes maanden gescoorde data. Nu alleen de structuur:
  welke knopen, welke pijlen, welke richting, welke vertraging.
- **Geen volledig model van de economie.** 15 tot 25 knopen is genoeg.
  Meer knopen betekent meer parameters, en met ~10–15 echte cycli in
  bruikbare data is overfitten de standaarduitkomst, niet het risico.
- **Geen lijst van alles wat we meten.** Een knoop is een *concept*
  (kredietimpuls), niet een reeks (`TOTBKCR`). De reeks staat in de
  metric-kolom.

## Werkwijze

1. Schrijf eerst de knopen op, met de hand, zonder naar de bestaande
   agents te kijken. Wat zijn de grootheden waarin je over de economie
   denkt?
2. Trek daarna pas de pijlen. Per pijl: welke richting, hoe lang duurt
   het, en hoe zou je zien dat hij werkt?
3. Kijk pas als laatste welke bestaande agent welke knoop bedient. Gaten
   die dan zichtbaar worden zijn informatie — ze bepalen welke agent
   daarna gebouwd wordt (dit is hoe de economic agent bovenaan fase 4
   terechtkwam).
4. Wat je niet eens wordt, laat je expliciet als open staan onderaan.
   Een pijl waar jullie het niet over eens zijn, is interessanter dan een
   pijl waar je je overheen praat.

---

## Knopen

Vul in. De voorbeeldrij toont alleen het formaat en mag weg.

| id | Knoop | Wat het is | Waarneembare metric(s) | Bediend door |
|---|---|---|---|---|
| `credit_impulse` | *(voorbeeld — vervangen)* Kredietimpuls | Verandering in het tempo van kredietgroei, niet het niveau | *(reeks invullen)* | *(agent invullen)* |
| | | | | |

Suggesties voor knooptypen om over te beginnen (geen voorschrift):
groei, inflatie, kredietimpuls, liquiditeit, beleidsstance, financiële
condities, risicopremie, dollar, termijnpremie, arbeidsmarktkrapte,
grondstofprijzen, winstgroei.

## Pijlen

| Van | Naar | Richting | Vertraging | Hoe zie je dat hij werkt | Zekerheid |
|---|---|---|---|---|---|
| `credit_impulse` | `growth` | + | ~2 kwartalen | *(invullen)* | hoog / midden / laag |
| | | | | | |

**Richting**: `+` (versterkt), `−` (dempt), of `?` (omstreden — hoort
dan ook onderaan bij de open punten).

**Vertraging**: in kwartalen of maanden, met een bandbreedte als je die
niet scherp hebt. Dit veld bepaalt straks de horizonnen waarop agents
mogen voorspellen, dus een ruwe schatting is beter dan leeg.

**Zekerheid**: jullie eigen inschatting, niet die van de literatuur. Dit
wordt later de prior in 3.4, dus "laag" invullen is geen zwakte maar
informatie.

## Dekking per agent

Invullen ná de twee tabellen hierboven. Een knoop die door niemand
bediend wordt is geen fout — het is de input voor de prioritering van
fase 4.

| Agent | Bedient knopen | Gaten |
|---|---|---|
| monetary_policy | | |
| currency | | |
| financial | | |
| sector | | |
| commodity | | |
| equity (adapter) | | |
| economic *(nog te bouwen)* | | |
| news *(nog te bouwen)* | | |

## Open punten / oneens

Pijlen of knopen waar DD en zijn partner het niet over eens zijn, of
waar de literatuur verdeeld is. Expliciet laten staan — dit zijn de
plekken waar de data straks iets interessants gaat zeggen.

- *(invullen)*

---

## Versiebeheer

Vanaf T₀ (10-11-2026) is deze graaf semi-bevroren. Elke wijziging krijgt
een versienummer hieronder en start effectief een nieuw cohort in de
scoring (roadmap 4.5). Reden: als de structuur verschuift terwijl er
gemeten wordt, is er geen track record meer maar een overfit.

| Versie | Datum | Wat er veranderde | Waarom |
|---|---|---|---|
| v0 | *(datum fase 1)* | Eerste versie | — |
