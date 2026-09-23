Bygg ett helt nytt production-ready repo för en extremt enkel self-service AI-chatbot för företag.

Återanvänd så mycket stabil och relevant teknik som möjligt från `ulle73/coastworks-sitechat`, framför allt RAG/knowledge base, chat, embeddings, widget/embed, säkerhet och fungerande backendlogik. Bygg inte om fungerande delar utan anledning.

## Högsta prioritet

Produkten ska vara extremt friktionsfri.

Målbild:

**Skriv din webbadress → prata med din färdiga AI-assistent ungefär en minut senare → lägg den på hemsidan med en rad kod.**

Flödet:

1. Startsidan domineras av ett fält för företagets URL.
2. Användaren anger sin hemsida.
3. Vi crawlar sidan och bygger automatiskt botten.
4. Användaren testar botten direkt utan konto.
5. Först när de väljer **”Lägg till på min hemsida”** behöver de ange e-post/skapa konto.
6. De får en enkel embed-kod och en mycket kort installationsguide.

Dölj all teknisk komplexitet. Användaren ska inte behöva förstå crawling, RAG, embeddings, knowledge bases eller prompts.

## Crawler

Crawlern i `coastworks-sitechat` fungerar sådär och har framför allt problem med JavaScript-renderade webbplatser.

Lös detta på det **bästa, billigaste och mest hållbara sättet**. Välj själv teknik och arkitektur enligt best practice. Vi har även tillgång till Apify och deras scrapers om det är lämpligt.

Botten får inte markeras som färdig om webbplatsen inte har kunnat läsas tillräckligt bra.

## Två erbjudanden

**Self-service:** Botten använder automatiskt information från kundens publika hemsida. Så få inställningar som möjligt.

**Managed:** Vi sätter upp, kvalitetssäkrar och underhåller botten åt kunden och kan komplettera med dokument, intern information, produktdata, FAQ och andra datakällor.

Managed ska vara en tjänst, inte bara Self-service med fler funktioner.

## Ett bra resultat

Användaren förstår produkten direkt, kan testa innan registrering och går från URL till fungerande bot med minimal friktion.

Systemet ska samtidigt vara production-ready, säkert, multi-tenant, kostnadseffektivt och robust.

## Ett dåligt resultat

En traditionell SaaS-produkt med lång onboarding, dashboard, massa inställningar och tekniska begrepp.

Registrering innan användaren fått testa botten.

Att bygga om fungerande Coastworks-kod i onödan.

Att rapportera botten som färdig trots att hemsidan inte har kunnat läsas ordentligt.

Inspektera först `coastworks-sitechat`. Återanvänd det som är bra, ersätt det som behöver ersättas och fatta tekniska beslut enligt best practice.

Produktmålet och den friktionsfria användarupplevelsen väger tyngre än den befintliga arkitekturen.
