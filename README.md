# Coastworks AI Chat

**Webbadress → prova en assistent utan konto → bekräfta e-post → en rad installationskod.**

Ett nytt produktrepo med FastAPI, en separat worker, PostgreSQL/pgvector och ett litet React-gränssnitt. Ingen dashboard och ingen registrering före provchatten. Källrepot `ulle73/coastworks-sitechat` är läst men inte ändrat.

## Kör lokalt

Kopiera `.env.example` till `.env`, eller använd den redan lokalt skapade, ignorerade filen. Den innehåller bara uttryckligen återanvända modell/renderingsinställningar och en ny sessionshemlighet; inga gamla databaser eller kunddata.

```powershell
docker compose up --build
```

Öppna `http://localhost:8000`. Lokal e-post fångas i Mailpit på `http://localhost:8025`. Bekräftelselänken konsumeras först när du trycker på bekräftelseknappen, så att mejlskannrar inte förbrukar den.

För utveckling med en redan tillgänglig PostgreSQL med pgvector:

```powershell
uv sync --frozen
npm ci --prefix web
npm run build --prefix web
uv run python -m app.db
uv run python -m app.server
# I en separat terminal:
uv run python -m app.worker
```

`APP_ORIGIN` måste exakt matcha adressen i webbläsaren. Standard är `http://localhost:8000`. `python -m app.server` väljer en psycopg-kompatibel event loop även på Windows. Docker använder Linux. Utvecklingsservern för frontend kan köras separat med `npm run dev --prefix web`; sätt då backendens `APP_ORIGIN=http://127.0.0.1:5173`.

## Verifiera

```powershell
uv run ruff check --config pyproject.toml app tests
uv run pytest -q
npm run build --prefix web
cd web
npx playwright install chromium
npm test
```

Databastester kräver en **separat databas vars namn innehåller `test`**. De tömmer testtabeller. Sätt `DATABASE_URL` till den databasen och `RUN_DB_TESTS=1` innan `uv run pytest -q`. CI kör PostgreSQL/pgvector och webbläsartester. De vanliga webbläsartesterna använder kontrollerade API-svar; de bevisar UI-flödet, inte externa leverantörers tillgänglighet.

## Dokumentation

- [Arkitektur och viktiga avvägningar](docs/ARCHITECTURE.md)
- [Vad som faktiskt återanvänds](docs/REUSE.md)
- [Drift, kostnadsgränser och lansering](docs/OPERATIONS.md)
- [Managed som levererad tjänst](docs/MANAGED.md)
- [Verifieringsresultat och kvarvarande produktionsgrindar](docs/VERIFICATION.md)
- [Design och visuell kontroll](docs/design/DESIGN.md)

Målet är cirka en minut på vanliga företagssidor. Det är ingen garanti. Ett misslyckat eller tunt underlag ger ett begripligt fel och erbjudande om hjälp, aldrig en låtsasfärdig bot.

## Knowledge quality

Hybrid retrieval, ingestion profiles, eval methodology, measured results and rollout requirements are documented in [docs/knowledge-quality.md](docs/knowledge-quality.md). Run the reproducible provider eval with `uv run python -m evals.run --check` against an isolated test database.
