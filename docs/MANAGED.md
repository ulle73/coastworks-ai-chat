# Managed är en tjänst

Kunden köper uppsättning, kvalitetssäkring och förvaltning. Gränssnittet erbjuder en kort förfrågan, inte en teknisk konfigurationspanel. Förfrågan sparas i databasen och följs upp av en ansvarig person.

## Leverans

1. **Kartläggning:** ansvarig kontakt, målgrupp, de 20 viktigaste frågorna, språk, gränser och när besökaren ska hänvisas till en människa.
2. **Källavtal:** inventera hemsida, dokument, produktdata och FAQ. Interna källor klassas innan inläsning. Kunden godkänner uttryckligen vilka utdrag som får bli publika svar.
3. **Uppsättning:** normalisera till text, märk källor och importera godkänt innehåll. Det är versionsbundet och bevaras vid webbrefresh.
4. **Acceptans:** testa riktiga frågor, obesvarbara frågor, gamla priser, promptinjektion och källspårning. Kunden godkänner svarskvalitet innan widgeten publiceras.
5. **Förvaltning:** överenskommen uppföljningsfrekvens, källägare, incidentkontakt och svarstid. Veckovis automatisk webbrefresh kompletteras av mänsklig granskning av ändrade företagsuppgifter.

## Operatörsverktyg

```powershell
uv run python -m app.operations requests
uv run python -m app.operations request-status REQUEST_UUID contacted
uv run python -m app.operations import-text BOT_UUID approved-faq.txt --title "Vanliga frågor" --source-url https://kund.se/kontakt --approved-public
uv run python -m app.operations refresh BOT_UUID
uv run python -m app.operations unpublish BOT_UUID
```

Dessa kommandon kräver operatörens databasåtkomst. Det finns ingen publik admin-route. `requests` visar personuppgifter avsiktligt till behörig operatör; kör det inte i publika CI-loggar. Råa PDF-/Office-filer, privata sökindex, autentiserade affärssystem och automatiska produktfeeds ingår inte som färdiga anslutningar i denna version. De måste få egna avtal, normalisering och tester; den gemensamma text/index-vägen finns.

Managed-förfrågningar skickas inte automatiskt till en extern CRM eller mejladress. En utsedd operatör behöver bevaka kön. Kunden ska inte få ett underhållslöfte förrän bemanning och leveransvillkor är fastställda.
