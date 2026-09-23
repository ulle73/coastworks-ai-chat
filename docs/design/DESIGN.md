# Design och visuell kontroll

Koncept: `concept.png`, genererat med inbyggda imagegen. Brief: svensk URL-först-produkt, redaktionell serif, vitgrön bakgrund, mörkgrön handling, inget konto i första steget, tre öppna steg och ett separat Managed-band. Inga dekorativa bilder behövs i produkten.

Tokens: bakgrund `#fafbf9`, text/primär handling `#163b30`, Managed `#dce8dd`, dämpad text `#647572`, linjer `#c9d2cd`. Georgia för rubriker och system-sans för UI; inga externa typsnittsanrop. 10px knappradie och 18px chattradie. Reducerad rörelse respekteras.

Designen är vald som arbetsreferens inom uppdraget; användaren har inte separat designgodkänt den. Referensen har granskats mot faktisk rendering med `view_image`. IAB öppnade inte inom timeout, därför användes Playwright Chromium.

| Kontroll | Koncept och implementering |
|---|---|
| Hierarki | Stor tvådelad rubrik, ett dominerande URL-fält, en tydlig handling. |
| Copy | Huvudrubrik, stödtext, primär knapp och kravlöst testbudskap bevarade. |
| Layout | Öppen trekolumnssektion, linje, brett Managed-band; ingen dashboard eller kortmatris. |
| Färg | Samma ljusa bakgrund, mörkgröna text/knappar och ljusgröna tjänsteband. |
| Typografi | Serif/sans-kontrast bevarad; systemfonter är avsiktlig anpassning för självhostad, snabb laddning. |
| Mobil | En kolumn och fullbreddsinput/knapp. Huvudrubrikens storlek justerad efter screenshot för att undvika olycklig brytning vid AI-assistent. |
| Interaktion | Verklig API-väg, pollad status, provchatt, källänkar, e-poststeg, kopiera kod och installationskontroll. |

Avsiktliga avvikelser: ”i din ton” i konceptets steg 2 ändras till ”direkt från din hemsida” eftersom en automatisk toninlärning inte är implementerad. Integritetsinformation läggs till i sidfoten. Fel/arbetsstatus, e-postbekräftelse och installationskontroll förlänger samma visuella system med nödvändiga produktsteg.

Desktop kontrolleras vid 1440×1100, nära konceptets 1435×1096, och mobil vid 390×844. Screenshots är granskningsbevis, inte bilder som används som UI. Innehåll, kontroller och text är riktig HTML/React.
