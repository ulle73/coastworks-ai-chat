# Abonnemang: 399 kr per chatbot och månad

## Implementerat

Stripe Billing + hosted Checkout, ett fast SEK-pris på 39 900 öre, en månadsperiod och quantity=1. Klienten får aldrig skicka pris, kund-ID eller subscription-ID. Varje chatbot har en egen Stripe Customer och ett eget abonnemang; detta isolerar kundportalen till just den chatboten. Befintlig verifierad ägarsession och Origin-kontroll krävs för Checkout och portal. Anonym provchatt är fortfarande tillgänglig före köp.

Servern kontrollerar prisets belopp, valuta, intervall, momsmodell och live/test-läge. Portalens konfiguration måste tillåta fakturahistorik, betalningsmetodbyte och uppsägning vid periodslut, men inte ändring av pris eller antal. Betalningsmetoder väljs dynamiskt av Stripe. Ingen kortdata passerar vår server och ingen Stripe.js behövs för den hostade kassan.

Betalningsförsök har beständiga idempotensnycklar och serialiseras per bot i PostgreSQL. Öppna kassor återanvänds. Innan en ny kassa skapas kontrolleras kundens faktiska abonnemang, även när webhooken ännu saknas. Ingen åtkomst ges av success-URL, klientparametrar, checkout.completed i sig eller status active utan betald fakturaperiod.

Webhooken `/api/billing/webhook` kontrollerar signatur på rå body och live/test-läge. Den sparar endast händelse-ID och vårt kund-ID i en beständig kö och svarar därefter. Dubbletter är idempotenta. En separat loop i workern hämtar aktuellt Stripe-tillstånd under botens databaslås, så händelser i fel ordning inte återaktiverar ett avslutat abonnemang. Loopens körning är oberoende av långa crawls. Periodisk avstämning var sjätte timme återhämtar missade händelser; kunden kan också begära avstämning från gränssnittet.

Åtkomst kräver active/past_due och en ännu giltig, faktiskt betald fakturaperiod. Misslyckad förnyelse förlänger inte perioden. Uppsägning vid periodslut behåller betald åtkomst; omedelbar cancellation tar bort åtkomsten när avstämningen körts. Både publicering och varje widget-session/chat-anrop kontrolleras på servern. Indexet raderas inte vid betalningsproblem. Schemalagd fullcrawl kräver betald åtkomst när billing är aktiverat. Borttagning av bot stänger öppna kassor och kräver ett avslutat abonnemang efter en sista Stripe-avstämning.

## Verifiering

Kontraktstester använder verkliga Stripe SDK-objekt och kryptografiskt signerade webhookpayloads, med kontrollerade externa API-svar och faktisk lokal PostgreSQL/pgvector via PGlite. De täcker obetald aktivering, periodslut, uppsägning, misslyckad förnyelse, fel antal, samtidigt Checkout, utebliven webhook, fel ordning, återförsök, tenantisolering och CSRF. Browserprovet täcker betalningsretur, serverstyrd aktivering och portal på desktop/mobil. Detta ersätter inte ett riktigt Stripe-sandboxköp med 3DS, förnyelse och uppsägning eller ett live-readback.

## Produktionskonfiguration

SDK: `stripe` 15.6.1 i `uv.lock`; API-version `2026-08-26.dahlia`. Säkerställ samma version på snapshot-webhooken. Migrera 004 före ny kod.

Miljövariabler i backendens hemlighetslager:

| Variabel | Innehåll |
| --- | --- |
| BILLING_ENABLED | true |
| STRIPE_API_KEY | separat restricted live key med minsta nödvändiga rättigheter |
| STRIPE_WEBHOOK_SECRET | live-endpointens signing secret |
| STRIPE_PRICE_ID | aktivt fast SEK-månadspris, 39900 |
| STRIPE_PORTAL_CONFIGURATION_ID | projektets avgränsade portalkonfiguration |
| STRIPE_LIVEMODE | true |
| STRIPE_TAX_BEHAVIOR | inclusive eller exclusive, samma som godkänt pris |
| STRIPE_AUTOMATIC_TAX | true först efter verifierade aktiva registreringar |
| APP_ORIGIN | https://coastworks-ai-chat.vercel.app eller beslutad egen domän |

Använd separata test- och livenycklar. Nycklar lagras aldrig i frontend, Git, dokumentation eller loggar. Restricted key behöver läsa Prices, Tax Registrations, portal Configuration och Subscriptions, skapa Customers/Checkout/portal Sessions samt lista och avsluta Checkout Sessions. Ingen behörighet att återbetala eller ändra abonnemang behövs i applikationen.

Webhookens eventlista finns i `app/billing.py:EVENTS`. Registrera mot `https://coastworks-ai-chat-api.onrender.com/api/billing/webhook`. Begränsa leveransen till dessa händelser. Övervaka köålder, antal återförsök, `billing_reconcile_failed`, `billing_contract_failed`, avstämningsålder och workerhälsa. Köfel får inte betraktas som lyckad betalningshantering bara för att webhooken svarar 200.

Moms är ett separat beslut: 399 kr inklusive respektive exklusive moms ger olika debitering. Välj inte momsmodell eller tax code genom antagande. Kontrollera företagets befintliga registreringar och produktens SaaS-tax code innan Stripe Tax slås på. Koden vägrar automatic_tax om inga aktiva registreringar hittas, men det bevisar inte registrering för varje kundland. [Stripes skattedokumentation](https://docs.stripe.com/billing/taxes/collect-taxes) beskriver konfigurationen; registrering hos en myndighet görs inte av denna kod.

## Livekonfiguration och kvarstående aktivering

Verifierat 2026-09-25: Vercel-projekt `coastworks-ai-chat` (`prj_SIAFp3Y8y2oyB0TnRRgxv9juYDtH`) och Render API `srv-daq05sbtqb8s73dvr8dg`, region Frankfurt. `web/vercel.json` proxar `/api/*` till Render. Render deployar automatiskt main och startar med migrering följt av uvicorn. `EMBEDDED_WORKER=true` håller betalningsavstämning och crawlkö i samma process tills en separat worker sätts upp.

Följande liveobjekt finns på Stripe-konto `acct_1TJXJvF8LNRr7WfF`:

- produkt `prod_VK14uf6I8xGSod`, tax code `txcd_10105002` (AIaaS för företagsanvändning)
- pris `price_1UJN2YF8LNRr7WfF7v3lalMM`, 39900 SEK, månadsvis, quantity=1, inclusive
- portal `bpc_1UJN2uF8LNRr7WfFoGWIvSnk`, avgränsad till kontaktuppgifter, betalningsmetod, fakturor och uppsägning vid periodslut
- webhook `we_1UJN3PF8LNRr7WfFAY9S7kV1`, live, API `2026-08-26.dahlia`, med exakt eventlista från `EVENTS`

Webhookhemligheten och objekt-ID:n ligger i Render, men `BILLING_ENABLED=false` tills en live restricted key finns i Render och momsflödet är bekräftat. Stripe Tax hade inga aktiva registreringar vid kontrollen, därför är `STRIPE_AUTOMATIC_TAX=false`; ingen skatteregistrering skapades automatiskt. Render-tjänsten står fortfarande på free-plan, vilket kan försena workern när tjänsten sover. Aktivering kräver därför restricted key, verifierad momsbehandling, en alltid körande Render-plan och därefter ett kontrollerat köpflöde utan att skapa en verklig kunddebitering i ägarens namn.

Referenser: [Checkout](https://docs.stripe.com/api/checkout/sessions/create), [webhooks](https://docs.stripe.com/webhooks), [abonnemangshändelser](https://docs.stripe.com/billing/subscriptions/webhooks), [betalda fakturaperioder](https://docs.stripe.com/api/invoice-line-item/object).
