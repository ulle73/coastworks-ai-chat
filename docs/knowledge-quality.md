# Kunskapsmotorn: implementation och verifiering

## Arkitektur

- PostgreSQL kör två oberoende kandidatfrågor mot samma tenant och aktiva indexversion i en SQL-snapshot: exakt pgvector-sökning och GIN-indexerad fulltextsökning (`swedish` + `simple`). Fulltextsökning kan hitta material utanför vectorurvalet, även vid byte av embeddingmodell.
- Kandidatlistorna kombineras med reciprocal rank fusion, k=60. 32 kandidater per gren, högst 24 till rerankern och 8 till svarsgenerering. Dessa är kostnadstak; inga relevanströsklar eller domänspecifika vikter används. Fulltextsökningen använder PostgreSQLs `ts_rank_cd`, inte BM25.
- Befintlig Gemini/OpenAI-provider gör en strukturerad innehållsbedömning av kandidaterna. Följdfrågor skrivs om separat; historik används för referenter, aldrig som faktakälla. En ny fråga utan historik behöver ingen rewriting. Strukturerade RAG-steg använder temperatur 0. Gemini 2.5 Flash får en begränsad resonemangsbudget på 256 tokens per steg. En kontrollerad jämförelse på samma kandidater visade att helt avstängt resonemang missade en relevant presentkortssida medan 256-budgeten hittade den; påslaget i reranking var cirka 0,23 sekunder i det fallet.
- HTML-rubriker och FAQ-summary bevaras vid extraktion. Chunkarna upprepar rubrikhierarkin, behåller små sektioner och delar endast stora sektioner med överlapp. Även fakta som står enbart i avslutande rubriker, exempelvis klubbnamn och telefonnummer, behålls; tomma överordnade rubriker bildar inte egna chunks. Svarsgenerering får hela de valda chunkarna.
- Svaret väljer först stödjande käll-ID:n och skriver sedan svaret. ID:n slås upp direkt mot de hämtade textstyckena; modellen får inte skapa egna URL:er eller kopiera text för att bevisa proveniens. Okända ID:n eller saknat stöd ger fallback. Returnerade källor är använda källor, inte alla retrievalträffar. En tidigare kontroll av fritt kopierade citat gav falska avståenden och togs bort: identiska citat bevisar inte semantisk entailment.
- Modellen instrueras att skilja uttryckliga undantag från verkliga konflikter, redovisa olösta konflikter och ignorera instruktioner i källmaterialet. Valideringen av käll-ID:n är **inte** en semantisk faktagranskare. Ett separat verifieringsanrop provades på 40 identiska utkast: korrekthet 35 → 36, groundedness 40 → 39, medianpåslag 2,26 sekunder. Det behölls därför inte i produktion. Experimentet och råresultaten finns i `evals/verify.py` och `evals/verification-ablation.json`.

Metodreferenser: [PostgreSQL fulltextsökning](https://www.postgresql.org/docs/17/textsearch-controls.html) och [RRF](https://learn.microsoft.com/azure/search/hybrid-search-ranking).

## Ingestion och drift

Preview behåller 8 sidor/110 sekunder och ett separat tak på 300 chunks. Publicerade bottar använder 500 sidor/1 200 sekunder och högst 12 000 chunks som standard. Konfigurationsgränserna kan höjas för större kundsajter. Embeddings skickas i batcher om 64, valideras och får begränsade återförsök vid tillfälliga providerfel. HTML lagras inte i crawlresultatets samlade sidlista, vilket minskar minnesåtgången vid stora importer.

Publicering köar en full indexering medan den befintliga versionen fortsätter svara. Även publicering under en pågående preview-indexering hanteras. Befintliga publicerade bottar utan full profil fångas av underhållsjobbet, med den befintliga spärren mot fler än ett nytt jobb per dygn. Misslyckad omindexering behåller det gamla indexet. `quality.ingestion_profile` och `quality.budget_exhausted` visar vilken profil som byggts och om sid-/försöksbudgeten stoppade arbetet. Full profil innebär inte obegränsad eller bevisat komplett sajtcoverage.

Driftsättning kräver `python -m app.db` före ny applikationskod. Migration 003 backfyller sökkolumnen och bygger GIN-index för existerande chunks; räkna med tabellås under migrationen. Nya rubrikchunks kräver omindexering. En specifik publicerad bot kan köas med `python -m app.operations refresh <bot-id>`. Inga produktionsdata, hostinginställningar eller hemligheter ändrades under denna uppgift.

## Reproducerbara evals

`evals/corpus.json` innehåller frysta, SHA-256-märkta texter från nio publika Golfkuponger-/Dormysidor, hämtade 2026-09-24. `evals/questions.json` innehåller 40 frågor: exakta, omskrivna, synonymer, följdfrågor, ämnesbyten, specifika undersidor, distractors, obesvarbara frågor samt åtta attacker/konfliktfall. De två extra adversarialtexterna är uttryckligen syntetiska, ligger på `fixtures.example` och är inte påståenden om företagens webbplatser.

Baseline är den oförändrade svarskoden från `e94be2c4620f54b4dca8ea4957b494709b7f02db`, sparad i `evals/baseline.py`, med den ursprungliga 1 000/200-chunkingen. Båda versionerna får samma sidinnehåll och frågor. Baselineindexet får inte sämre sidcoverage för att gynna den nya versionen.

Mätningarna skiljer på:

1. Källträff: alla erforderliga källgrupper finns i underlaget.
2. Evidensträff: de annoterade faktapassagerna finns faktiskt i chunkarna som modellen fick. En rätt URL med fel chunk räknas inte som evidensträff.
3. Svarskorrekthet mot ett explicit facit.
4. Groundedness: positiva faktapåståenden stöds av den faktiskt hämtade kontexten. En ärlig fallback är grounded men fel när frågan kunde besvaras.

Korrekthet och groundedness bedöms parvis av en separat modellkörning med facit och respektive sparad kontext. A/B-ordningen är stabilt blandad och variantnamnen döljs för bedömaren. Fel granskas manuellt. Samma svar får inte poängsättas olika bara för att det kommer från olika versioner. Modellbedömning är inte en mänskligt validerad guldstandard. Modellalias och sampling innebär att nya körningar kan skilja sig. Detta är en begränsad regressionssvit, inte bevis på generell produktkvalitet.

Kör med en uttryckligen isolerad databas vars namn innehåller `test`:

```powershell
$env:DATABASE_URL = 'postgresql://USER:PASSWORD@localhost:5432/coastworks_eval_test'
uv run python -m evals.run --check
```

Riktiga embeddings cachelagras separat per modell och dokument-/querytyp under `.local`, inte i produktionskoden. `--reuse-before <tidigare-resultat.json>` återanvänder en redan uppmätt baseline. `--scenario` kör bara attacker och syntetiska konflikter. Den manuellt startade GitHub Actions-workflowen `knowledge-eval.yml` kör mot native PostgreSQL/pgvector och kräver `GEMINI_API_KEY`. Den stoppar vid regression mot baseline och sparar resultat som artefakt. Den ordinarie CI:n kör databas- och kontraktstester utan LLM-anrop.

## Kvarstående validering

Ingen hosted driftsättning eller långvarig belastningsmätning ingår i den lokala verifieringen. SQL/integrationstester kördes lokalt med PostgreSQL/pgvector via PGlite; native PostgreSQL verifieras av CI-workflowen när den körs. Vectorgrenen använder exakt sökning inom tenantens index; större index än standardbudgeten behöver latency-/minnesmätas innan ANN-index väljs. Fullcrawl av hela kundsajter och stora produktkataloger behöver operativ coveragegranskning. Svensk stemming och `simple` ger en rimlig start; andra språks morfologi behöver egna evals.


## Evals under utvecklingen

De första testerna påvisade tre faktiska svagheter i implementationen, som åtgärdades före slutkörningen: (1) fritt kopierade citat gav falska fallback på grund av formattering och parafraser; slutversionen använder därför käll-ID:n till redan hämtade passager, (2) omskrivning av universella följdfrågor kunde snäva in omfattningen till föregående undertyp; instruktionen behåller nu bredare omfattning och undantag, (3) text som instruerar en AI vad den ska svara fick inte klassificeras som företagsfakta bara för att den matchade frågans ord. Dessa är generella regler utan domän- eller frågespecifik produktionskod.

En äldre automatisk bedömare gav ibland booleans som motsade dess motivering. Den ersattes med motivering före betyg och separat resonemangsbudget. Exakt standardfallback poängsätts deterministiskt: grounded, men korrekt endast när facit saknar svar. Fel ska fortfarande granskas manuellt; en LLM-domare kan göra misstag.


Bedömningsprotokollet förbättrades efter att två nästan identiska svar om postnummer fick olika betyg. Slutbedömningen använder blind parvis jämförelse för **båda** versionerna. Facit för den tvetydiga följdfrågan accepterar ett tydligt avgränsat svar om företagskuponger; betalnings- och postnummerfrågorna kräver inte oombedda uppgifter om moms, frakt eller mejlleverans. Detta ändrar inte produktionens ranking eller relevanströsklar. `python -m evals.rejudge evals/results.json` tillämpar samma bedömningsprotokoll på båda sparade varianterna utan att generera nya svar.
