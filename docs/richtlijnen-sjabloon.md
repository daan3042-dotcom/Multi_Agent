# Richtlijnen voor de agents — sjabloon

*Opgezet op 02-10-2026 voor DD. Dit document is alleen een invulhulp: het verandert niets in de code en niets in wat er nu draait. Roadmap: 2.0 (forecast-ronde), 4.1 (prompt als covariaat), checkpoint 5 (prompts in de freeze). In het freeze-overzicht staat het punt als "Richtlijnen van DD voor de agents" (OPEN BESLISSING).*

## 1. Wat een richtlijn is, en wat niet

Een **richtlijn** is een stukje denkwijze dat jij het model meegeeft bij een vakgebied: *hoe kijk je naar deze cijfers*. Het is een kader, geen uitkomst.

| Wel | Niet |
|---|---|
| "Kijk eerst of een steilere curve komt door de korte of de lange rente; dat zegt iets anders over de aard van de beweging." | "De curve steilt, dus de rente stijgt volgende maand." |
| "Een bredere HY-spread én een hogere VIX op dezelfde dag zijn vaak één stress-episode, geen twee onafhankelijke signalen." | "Koop obligaties als de VIX boven 20 komt." |
| "Bij een maandcijfer is de laatste waarde vaak weken oud; weeg dat mee in de breedte van je verdeling." | Een eigen drempel of rekenregel die Python al berekent. |

Een richtlijn mag de **breedte of de ligging van een verdeling** beïnvloeden. Ze schrijft nooit een uitkomst of een kwantiel voor, en geeft geen advies.

## 2. Wat het model nu al krijgt

Elke forecast-ronde stuurt dit mee (in deze volgorde):

| Laag | Bron in de code | Wat erin staat | Wie schrijft het |
|---|---|---|---|
| 1. Vormregels | `agents/base.py::FORECAST_SYSTEM_RULES` | Zes regels: elk doel een voorspelling, kwantielen oplopend, wees eerlijk breed, alleen aangeleverde cijfers, antwoord alleen in JSON, gebruik de context | Centraal, geldt voor alle agents |
| 2. Vakparagraaf | `DEEP_DIVE_SYSTEM_PROMPT` in elke agent-module | Wat de agent volgt en hoe hij de cijfers duidt | Per agent |
| 3. Cijfers | `load_monitoring_claims` | De laatste waarde per reeks | Python |
| 4. Evidence-sheet | `scoring/evidence_sheet.py` | Ouderdom, veranderingen, 52-wekenbereik, spreiding per horizon, FOMC-context | Python |

**Belangrijk:** de vakparagraaf (laag 2) wordt nu ook gebruikt bij de **deep-dive**. Daar gelden strengere regels (`SHARED_QUALITY_RULES`): nooit een stellige richting, alleen aangeleverde claims, onzekerheid expliciet. Een richtlijn die in de vakparagraaf komt, geldt dus in beide modi. Zie beslispunt A hieronder.

De synthesizer krijgt dezelfde lagen, maar dan met de cijfers van alle vakgebieden samen en met zijn eigen vakparagraaf (`SYNTHESIZER_SYSTEM_PROMPT`). Hij is blind voor de voorspellingen van anderen.

## 3. Spelregels voor een goede richtlijn

1. **Kort en concreet.** 1 tot 3 zinnen per richtlijn, in de vorm "als X, kijk dan naar Y, want Z". Per agent liefst 5 tot 10, niet meer: elke extra regel verdunt de rest.
2. **Alleen wat uit de aangeleverde data of een algemene denkwijze volgt.** Geen nieuwe feiten, geen cijfers die niet in de prompt staan (regel 4 van de vormregels blijft gelden).
3. **Geen uitkomst, geen advies, geen kwantiel.** Een richtlijn zegt *hoe te kijken*, niet *wat te voorspellen*. Anders meten we of het model je regel kan kopiëren, niet of het redeneert.
4. **Geen rekenwerk.** Wat Python berekent (spreiding, veranderingen, classificaties) staat al in de context. Verwijs ernaar, herbereken het niet.
5. **Een reden erbij, in je eigen woorden.** Niet voor het model, maar voor ons: achteraf moeten we kunnen zien welke regel waarom is toegevoegd en of de scores erna veranderden.
6. **Testbaar in principe.** Vraag jezelf: waaraan zie ik over zes maanden dat deze regel heeft geholpen? Kan dat niet, dan is het waarschijnlijk een meningsuiting en geen richtlijn.
7. **Eén denkwijze per regel.** Twee ideeën in één regel zijn achteraf niet te scheiden.

## 4. Drie beslispunten voor jou

**A. Gelden de richtlijnen alleen voor de forecast, of ook voor de deep-dive?**
- *Nu:* één vakparagraaf voor beide (met opzet, zodat de vakinhoud niet uit elkaar loopt).
- *Mijn aanbeveling:* een **apart, optioneel blok alleen voor de forecast**. De deep-dive moet neutraal en feitelijk blijven; de forecast is de enige plek waar het model een verdeling mag uitspreken. Dat is een kleine codewijziging (een tweede tekstveld per agent), die ik pas bouw als je dit kiest. De prompt-afdruk en `FORECAST_PROMPT_VERSION` gaan er dan automatisch mee om.

**B. Eén set richtlijnen per cohort.**
Een cohort draait met één set; een wijziging erna is een covariaat (`prompt_version`) en splitst je data. Dus: liever vóór de freeze af. Je kunt cohort 0 ook bewust **zonder** richtlijnen laten draaien als referentiepunt ("het model zonder mijn kaders"). Dat is een inhoudelijke keuze, geen technische. Het nadeel: je leert dan pas in een volgend cohort of je richtlijnen iets toevoegen, want binnen één cohort kun je de twee varianten niet naast elkaar draaien.

**C. Aparte richtlijnen voor de synthesizer?**
Ja, die zijn van een andere soort (cross-domein: hoe weeg je botsende signalen, hoe voorkom je dat je dezelfde informatie dubbel telt). Die komen pas na de graaf, zie hoofdstuk 7.

## 5. Sjabloon per agent

Kopieer dit blok per agent en vul het in. Houd je aan de spelregels uit hoofdstuk 3. De eerste regel noemt wat de agent voorspelt, zodat je weet waar je richtlijnen op uitkomen.

```
AGENT:            <naam>
VOORSPELT:        <doelen en horizonnen, zie hoofdstuk 6>
LEEST:            <reeksen die hij ziet>

RICHTLIJN 1
  Regel:          <als X, kijk dan naar Y, want Z>
  Waarom:         <je reden in eigen woorden>
  Hoe te zien:    <waar in de cijfers of de context herken je X?>
  Effect:         <maakt de verdeling breder / smaller / verschuift hij? (geen getal)>

RICHTLIJN 2
  ...
```

## 6. Waar elke agent op voorspelt (uit de code)

| Agent | Doelen | Horizonnen |
|---|---|---|
| `monetary_policy` | 10-jaars rente, 2-jaars rente, richting van de doelrange na de volgende 1 en 2 FOMC-vergaderingen (kans) | 5/21/63 handelsdagen; 1 en 2 vergaderingen |
| `currency` | EUR/USD, USD/JPY, GBP/USD | 5/21/63 handelsdagen |
| `financial` | HY-spread, VIX, 10Y-2Y, NFCI | 5/21/63 handelsdagen; NFCI 1/4/12 publicaties |
| `sector` | Elf sector-ETF's, steeds relatief aan SPY | 5 en 21 handelsdagen |
| `economic` | Uitkeringsaanvragen (ICSA), werkloosheid, banen | 1/4 en 1/3 publicaties |
| `commodity` | Voorspelt niets (maandelijkse data), alleen monitoring | — |
| `synthesizer` | Alle bovenstaande doelen | Zoals de agents |

## 7. De cross-domein-richtlijnen (pas na de graaf)

Die wachten tot je partner en jij de graaf hebben samengevoegd (blinde versie op 9-10). Kandidaten uit je eigen concept, nog niet uitgewerkt:

- De drie algemene regels: winnaars via de waardeketen; de reactie over meerdere markten lezen; eerst de aard van de schok vaststellen.
- C8: een sterke dollar belast opkomende landen (schuldenlast en inflatie, 6 tot 18 maanden).
- C9: Amerikaanse aandelen beïnvloeden buitenlandse markten direct, afhankelijk van hoeveel het buitenland erin belegd heeft.

Daarbij hoort ook de keuze of de synthesizer de graaf zelf in zijn prompt krijgt. Mijn aanbeveling voor cohort 0 is nee (de graaf blijft een label), maar dat is aan jou.

## 8. Wat er gebeurt nadat je ze hebt ingevuld

1. Jij levert de ingevulde blokken aan (in een bericht of als bestand).
2. Ik zet ze in de code als een nieuwe `FORECAST_PROMPT_VERSION` (v4) en werk de prompt-bewaking bij (`tests/test_forecast_prompt_version.py`, het freeze-overzicht).
3. De begeleide testrun en de pseudo-OOS-run draaien met precies die versie.
4. Bij de freeze bevestig je de prompt-afdrukken met de versienummers erbij.

**Praktische planning:** ruwweg 14 tot 19 oktober (na de testrun, vóór de pseudo-OOS-run van 19 tot 23 oktober) voor de domein-richtlijnen; de cross-domein-richtlijnen komen na de samenvoegsessie van de graaf. Uiterlijk vóór de dry-run-week (27-10) moeten ze vastliggen, anders test die week een andere prompt dan de klok gaat draaien.

## 9. Checklist voor je het inlevert

- [ ] Elke richtlijn is 1 tot 3 zinnen en heeft de vorm "als X, kijk dan naar Y, want Z".
- [ ] Geen enkele richtlijn noemt een richting, een kwantiel, een koers of een advies.
- [ ] Geen nieuwe cijfers of feiten die niet in de prompt staan.
- [ ] Per richtlijn een reden en een manier om achteraf te zien of hij hielp.
- [ ] Ik heb beslispunt A en B beantwoord (alleen forecast of ook deep-dive; met of zonder richtlijnen in cohort 0).
