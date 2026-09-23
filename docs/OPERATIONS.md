# Drift

## Produktionsmiljö

- Kör API och worker som separata icke-root-processer. Samma image, olika kommando. Containerfiler och Compose finns; Compose är en lokal utvecklingsmiljö, inte en färdig offentlig TLS-driftsättning.
- Använd managed PostgreSQL med pgvector, TLS, säkerhetskopiering och testad återställning. Migreringsrollen får skapa schema/extension. API/worker ska ha en separat icke-superuser-roll med bara nödvändiga CRUD-rättigheter och sekvensåtkomst. Endast backend har databasåtkomst.
- Kör `python -m app.db` som migreringsjobb före rollout. Migreringarna har versionsregister och advisory lock. De körs aldrig automatiskt per API-request.
- Sätt `ENVIRONMENT=production`, exakt HTTPS `APP_ORIGIN`, slumpmässig `SECRET_KEY` på minst 40 tecken, modellnycklar, dedikerad Cloudflare-token och SMTP med STARTTLS. Production vägrar standardhemlighet och lokal avsändare.
- Lägg API bakom en TLS-proxy med request-/connectionbegränsning. Koden använder inte godtycklig `X-Forwarded-For`. Om proxyklientens IP behövs, starta uvicorn med `--proxy-headers --forwarded-allow-ips=EXAKT_PROXY_IP`; använd aldrig `*`. Utan detta blir IP-gränsen gemensam för proxyn, säkert men mer begränsande.
- Proxy får inte cachelagra `/api/*`. `/embed/*` behöver iframe-stöd; övriga appen nekar framing. Widgets kräver kundens CSP-tillåtelse för `script-src`, `frame-src` och `connect-src` till appens origin.
- Migrera och worker får bara egress till offentlig HTTP(S), databasen och nödvändiga providers. Nätverkspolicy kompletterar crawlerns URL/DNS-skydd.

## Hälsa, återhämtning och larm

`/health/live` bevisar API-process. `/health/ready` bevisar databas/schemaåtkomst, inte renderer/modell/e-post eller worker. Följ antal väntande jobb, äldsta jobbs ålder, failure codes, senaste `finished_at`, senaste `refreshed_at`, svarslatens och använda kostnadsräknare. `jobs` och `bots.quality` är den beständiga sanningen. Loggar innehåller jobb/bot-ID och säker felkod, aldrig råa providerfel eller dokumentinnehåll.

Om worker dör återtas leasen efter 60 sekunder. Tre kraschförsök avslutas som fel. Misslyckad refresh lämnar föregående index aktivt. Schemalagd refresh körs högst en gång per dygn vid fel, normalt varje vecka. Jobbloopens SQL bör övervakas; en databasincident får processen att avsluta och plattformens restart-policy måste starta om den.

Indexpublicering är en databastransaktion. SQL-fel eller avbruten transaktion lämnar tidigare version intakt. Vid fel: läs säker felkod, åtgärda källan/provider och köa om med `app.operations refresh`. En ägare kan ta bort sin bot med autentiserad `DELETE /api/bots/{id}`; samtliga index, jobb, meddelanden och källor tas bort med FK-cascade. Stäng widgeten omedelbart med `unpublish`.

## Begränsningar och datalivscykel

Anonyma botar rensas efter 24 timmar. Samtal rensas efter 30 dagar. Använda/utgångna e-posttoken och gamla kvotfönster rensas av worker. Stängda Managed-förfrågningar rensas efter 90 dagar; öppna förfrågningar kräver operatörens hantering. Säkerhetskopior behöver separat retention.

Gränserna är anropsbudgetar, inte bokförda valutabelopp. En bot på max 8 sidor, max 300 chunks och max 4 renderingar har en begränsad arbetsmängd; priser beror fortfarande på vald provider/modell. Mät faktiskt tokenantal, renderad tid och lyckade assistenter per kund. Ändra inte globala kostnadstak innan kapacitet och faktura har följts upp.

Cloudflare-kvoter gäller kontot och kan skilja sig från lokal renderingstakt. Vid många workers: sätt kontoövergripande limiter i driftlagret och mät 429-frekvens innan autoskalning. Första lanseringen bör använda en worker.

## Lanseringsgrind

1. Kör CI mot riktig PostgreSQL/pgvector och testa två separata workers, kill/restart och återtagning av leases.
2. Kör hela URL→chat→riktigt mejl→installerat script→domänverifiering→widget i den avsedda hostingmiljön, inklusive riktig browser-CORS och kundens CSP.
3. Mät statiska, React/Next/Vue-, robots-blockerade, skyddade, långsamma och innehållsfattiga sidor. Publicera inte ett generellt enminutslöfte från ett enda lyckat test.
4. Testa säkerhetskopiering/återställning, larm och ansvarig Managed-operatör.
5. Färdigställ avsändardomän, företagets kontaktuppgifter, användarvillkor, integritetstext, personuppgiftsbiträdesavtal och leverantörernas databehandlingsregioner.

Ingen automatisk betalning eller prenumerationsdebitering ingår. Erbjudandena skiljs genom leveransansvar och arbetsflöde, inte påhittade priser.
