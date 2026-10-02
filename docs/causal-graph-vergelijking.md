# DD's graafconcept naast v0 — vergelijking en vragen (02-10-2026)

Hoort bij `docs/roadmap.md` sectie 1.10. DD's concept (23 knopen, 39 pijlrijen) staat ongewijzigd in `docs/causal-graph-dd-concept.md`; de huidige v0 (17 knopen, 41 pijlen) in `docs/causal-graph.md` en `src/contract/graph.py`.
**Er is niets in de code veranderd.** De graaf gaat pas als één nieuwe versie (v1) de code in, nadat DD's graaf en de blinde versie van de partner (9 oktober) zijn samengevoegd.
De agents zien de graaf niet in hun prompts; hij zit alleen in de opslag (elke voorspelling draagt `graph_version`, en 13 doelen dragen een `graph_node`).

## 1. In gewone taal

1. **DD's graaf is een andere soort graaf dan v0.** v0 is een lijst van toestanden die we kunnen *meten* (elke knoop heeft reeksen). DD's graaf beschrijft hoe de economie *werkt*, met mechanismen uit drie episodes (2020–22, 2008, 2023–24): schokken, schuldopbouw, huishoudbalans, begroting, verwachtingen. Dat maakt hem rijker, maar minder meetbaar.
2. **Ongeveer de helft is al toetsbaar met wat we hebben.** Van de ~42 pijlen (in machine-vorm geteld) hebben er 19 aan beide kanten een knoop waarvoor wij nu een reeks ophalen; 18 aan één kant; 5 aan geen. Tien van de 23 knopen hebben geen enkele reeks bij ons (zie 5).
3. **DD's pijlen zijn voorwaardelijk** ("werkt alleen als de huishoudbalans intact is"). v0 heeft bewust geen voorwaarden (alleen een teken, `?` bij betwist). Voorwaarden opnemen is een ontwerpbeslissing, en ze moeten dan een meetbaar getal worden.
4. **Er ontbreekt in het document één ding dat v0 wel heeft:** per knoop wat "hoog" betekent. Zonder die kolom is het teken van een pijl niet eenduidig (bij `labor_market` staat "krapte of zwakte", bij `policy_rate` "niveau én verandering").
5. **De bestaande reeksen passen vrijwel allemaal ergens** (zie 5; alleen de vijf voedselgrondstoffen hadden in v0 ook geen knoop), dus er hoeft niets weg bij de overstap, behalve dat een paar knopen bij ons nu geen reeks hebben.

## 2. Knopen: v0 naast DD

| v0 | DD | Verschil |
|---|---|---|
| `growth` | `growth` | Zelfde id; DD's definitie breder (bedrijfsinvesteringen en huizenmarkt); meetreeks "open — partner" |
| `labor_tightness` | `labor_market` | Zelfde concept, andere naam; DD: "krapte of zwakte" (twee richtingen) |
| `inflation_persistence` + `inflation_expectations` | `inflation` | **Samengevoegd** tot één knoop (DD: "inclusief inflatieverwachtingen"); kop- en kerninflatie staan als aparte pijlen (A3a/A3b) |
| `policy_stance` | `policy_rate` | DD: niveau én verandering zijn twee werkingen (A7 traag, D1 direct) |
| `policy_expectations` | `policy_expectation` | Zelfde; DD voegt "verrassing" toe; metrics FedWatch en speeches (bij ons niet beschikbaar) |
| `financial_conditions` + `credit_risk_premium` | `credit_conditions` | **Samengevoegd** (NFCI, HY-spread, yield curve, SOFR-spreads) |
| `risk_appetite` | `tail_uncertainty` + `sentiment_flows` | **Gesplitst, en de as is omgekeerd**: v0 "hoog = meer risicobereidheid", DD `tail_uncertainty` "hoog = onzekerder over het uiterste" |
| `dollar` | `dollar` | Zelfde; DD: twee regimes (renteverschil in rust, vlucht in crisis) |
| `energy_prices` + `industrial_metals` | `commodities` | **Samengevoegd** |
| `equity_valuation` | `valuation` (+ `equities`) | DD heeft zowel waardering (open metric) als aandelen als knoop; v0 had aandelen/sectorrotatie bewust als *uitkomst* (laag 3) |
| `earnings_growth` | (`corporate_strength`, `growth_driver`) | Geen directe tegenhanger: winstgroei komt bij DD uit balanssterkte en een structurele groeidrijver |
| `liquidity` | `stimulus_vs_damage` | **Verwant, niet gelijk**: DD bedoelt "nieuw geld afgezet tegen de schade" (Fed-balans, TGA, stimulus), v0 bedoelt systeemliquiditeit |
| `term_premium` | `long_rate` | Geen termijnpremie bij DD; wel de lange rente zelf (DGS10) |
| `wage_growth` | — | **Vervalt** bij DD |

**Nieuw bij DD (geen v0-knoop):** `external_shock`, `household_balance`, `policy_room`, `fiscal`, `debt_buildup`, `collateral_prices`, `financial_institutions`, `corporate_strength`, `growth_driver`.

## 3. Pijlen

- **39 rijen**, in machine-vorm ongeveer **42 pijlen** (v0: 41): twee rijen wijzen buiten de graaf (C8 naar opkomende landen, C9 naar buitenlandse markten); vier rijen zijn samengesteld of tweerichtings (C6 twee bronnen, D1 en D10 lopen via een tussenknoop, B2 is een lus); A3a en A3b zijn twee rijen voor hetzelfde paar met verschillende vertraging.
- **Lussen:** `collateral_prices` ↔ `debt_buildup` (B2) en `fiscal` ↔ `long_rate` (C3/C4); v0 heeft er meer, omdat zijn financiële-conditiesblok veel tweerichtingspijlen bevat die niet te toetsen zijn.
- **Geen sterkte, geen "toetsbaar", vertraging in woorden** ("direct", "6–18 mnd", "open"): v0 heeft sterkte, zekerheid, toetsbaarheid en vertraging in dagen.
- **Voorwaardelijke pijlen** (A4, A5/A6, A7, C2, C3, C6/C7, D3, D4, D8, D9): DD's kern; zie vraag 3.

## 4. Wat een machine-leesbare versie nog nodig heeft

1. Per knoop: wat "hoog" betekent (vraag 1).
2. Per pijl: vertraging in dagen (venster), sterkte en toetsbaarheid (die laatste kan ik voorstellen op basis van de reeksen).
3. Per knoop: welke reeksen (nu 4 "open", 2 niet meetbaar: `external_shock`, `sentiment_flows`).
4. Per voorwaarde: een meetbaar getal (bijvoorbeeld "huishoudbalans intact" = spaarquote boven X).

## 5. Welke knoop kan door welke reeks bediend worden (VOORSTEL van mij, niet van DD)

| DD-knoop | Bestaande reeksen (`GRAPH_MAPPING`) |
|---|---|
| `policy_rate` | `fed_funds_rate`, `fed_funds_target_upper` |
| `long_rate` | `10y_treasury_yield` |
| `policy_expectation` | `2y_treasury_yield` (DD noemt FedWatch/speeches; die hebben we niet) |
| `inflation` | `cpi_inflation_index`, `inflation_expectations_5y`, `inflation_expectations_10y` |
| `stimulus_vs_damage` | `fed_balance_sheet` (deels; de rest van DD's metrics ontbreekt) |
| `labor_market` | `unemployment_rate`, `initial_claims`, (`nonfarm_payrolls`: zie vraag 6) |
| `credit_conditions` | `financial_conditions_index`, `high_yield_credit_spread`, `yield_curve_10y_2y` |
| `tail_uncertainty` | `vix` |
| `dollar` | `eur_usd`, `usd_jpy`, `gbp_usd` |
| `commodities` | `wti`, `brent`, `natural_gas`, `copper`, `aluminum` (de voedselgrondstoffen `wheat`, `corn`, `cotton`, `sugar`, `coffee` hadden in v0 geen knoop; hier zou `commodities` ze kunnen dragen: jouw keuze) |
| `equities` | de elf sector-ETF's, `spy_benchmark` |
| `corporate_strength` | `sec_net_debt_to_ebitda`, `sec_interest_coverage_ratio`, `sec_operating_margin`, `sec_net_margin`, `sec_roic` (equity-adapter, niet in de dagelijkse run) |

**Knopen zonder enige reeks bij ons:** `external_shock`, `household_balance`, `policy_room` (zou afleidbaar zijn: inflatie tegenover 2% en het renteniveau, maar is nu niet gebouwd), `fiscal`, `debt_buildup`, `collateral_prices`, `financial_institutions`, `growth_driver`, `valuation`, `sentiment_flows`.
Volgens CLAUDE.md komen er geen nieuwe agents vóór T₀ (behalve de lean economic agent); die knopen blijven dus in cohort 0 onbediend. `graph_node` is optioneel in cohort 0, dus dat blokkeert niets; het bepaalt wel welke pijlen forward getoetst kunnen worden.

## 6. Wat het in de code raakt (pas bij v1)

- `src/contract/graph.py`: de `Node`-enum, de eigenaar per knoop, de pijlen met teken, vertraging, sterkte, zekerheid, toetsbaarheid; mogelijk een nieuw veld voor voorwaarden. `GRAPH_VERSION` v1.
- De 13 doelen die nu een `graph_node` dragen (v0: `term_premium`, `policy_expectations`, `policy_stance`, `dollar`, `credit_risk_premium`, `risk_appetite`, `financial_conditions`, `labor_tightness`, `growth`): die moeten naar een DD-knoop. **(Ik schreef eerder "tien doelen"; het zijn er dertien.)** Dat verandert de doelen-vingerafdruk, dus `TARGETS_VERSION` v2.
- `GRAPH_MAPPING` in de zeven agent-modules en de controle dat een bezeten knoop wordt bediend (`unserved_owned_nodes`); `tests/test_graph.py` en `tests/test_graph_mapping.py` (nu 17 knopen en 41 pijlen vastgepind).
- De evidence-sheet en de prompts blijven ongemoeid (de graaf zit er niet in).
- De opgeslagen dry-run-voorspellingen onder v0 blijven zoals ze zijn (alleen een ander `graph_version`); het echte cohort begint pas bij T₀ᵇ.

## 7. Vragen aan DD

1. **"Hoog" per knoop:** wat betekent "hoog" voor elke knoop? Vooral `labor_market` (krap), `policy_rate` (niveau of verandering?), `tail_uncertainty`, `household_balance` en `valuation`. Zonder dat is een teken niet eenduidig.
2. **Bewust weggelaten of vergeten:** `wage_growth`, `term_premium`, `liquidity` (als systeemliquiditeit, apart van stimulus) en `earnings_growth` komen in jouw graaf niet voor. Bewust geschrapt, of zit het ergens in?
3. **Voorwaarden:** moeten ze in de graaf zelf komen (bijvoorbeeld "A4 werkt alleen als `household_balance` intact is") of eerst als tekst blijven tot ze een meetbaar getal hebben? Mijn voorstel: als tekst, en een voorwaarde pas een veld als hij meetbaar is.
4. **`equities`:** jij maakt aandelen een knoop met een eigen uitgaande pijl (C9); v0 behandelde aandelen en sectorrotatie als uitkomst, geen oorzaak. Wil je het zo?
5. **Samengestelde pijlen:** mag ik D1 splitsen in `policy_rate → valuation`, `policy_expectation → valuation` en `valuation → equities` (en D10 en C6 evenzo), en A3a en A3b als één pijl met twee vertragingen?
6. **`nonfarm_payrolls` en `growth`:** het doel krijgt in v0 de knoop `growth`; bij jou hoort het bij `labor_market` (banenrevisies). Waar wil je het?
7. **Buiten de graaf:** C8 en C9 wijzen naar het buitenland. Laten we ze buiten de graaf, of krijgen ze een eigen knoop?
8. **De knopen zonder reeks** (zie 5): blijven die in cohort 0 bewust onbediend?

## 8. Volgende stappen

1. DD beantwoordt de vragen (de meeste zijn een kort ja/nee of een keuze).
2. 9 oktober: de blinde versie van de partner. Dan een samenvoegsessie knoop voor knoop; verschillen komen in `docs/causal-graph.md`, "Open punten", met `[DD]` en `[partner]` gemarkeerd.
3. Pas daarna één keer de code in: graaf v1, `TARGETS_VERSION` v2, nieuwe mapping per agent, tests, docs.
