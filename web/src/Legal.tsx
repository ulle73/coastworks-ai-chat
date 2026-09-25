type LegalKind = "terms" | "privacy";

export function Legal({ kind }: { kind: LegalKind }) {
  const terms = kind === "terms";
  return (
    <>
      <header>
        <a className="wordmark" href="/">coastworks</a>
        <nav aria-label="Huvudmeny">
          <a href="/">Till startsidan</a>
          <a href={terms ? "/integritet" : "/villkor"}>
            {terms ? "Integritet" : "Villkor"}
          </a>
        </nav>
      </header>
      <main className="legal">
        <p className="eyebrow">Senast uppdaterad 25 september 2026</p>
        <h1>{terms ? "Villkor för Coastworks AI-chatbot" : "Integritet hos Coastworks"}</h1>
        {terms ? <Terms /> : <Privacy />}
      </main>
      <footer className="legal-footer">
        <span>coastworks</span>
        <a href="/villkor">Villkor</a>
        <a href="/integritet">Integritet</a>
      </footer>
    </>
  );
}

function Terms() {
  return (
    <div className="legal-copy">
      <section>
        <h2>1. Tjänsten</h2>
        <p>
          Coastworks skapar en AI-assistent av publikt innehåll på den webbadress
          som kunden anger. Tjänsten är avsedd för företag. Kunden ansvarar för
          att få använda webbplatsen och för att installationskoden läggs in på
          en webbplats som kunden kontrollerar.
        </p>
      </section>
      <section>
        <h2>2. Provperiod och abonnemang</h2>
        <p>
          En provassistent kan testas utan kostnad innan publicering. Ett aktivt
          abonnemang krävs för att publicera assistenten och använda widgeten.
          Priset är 399 kronor per chatbot och månad, inklusive moms där den är
          tillämplig. Det exakta totalbeloppet visas i Stripe Checkout innan köp.
        </p>
      </section>
      <section>
        <h2>3. Betalning och uppsägning</h2>
        <p>
          Betalning och kvitton hanteras av Stripe. Abonnemanget förnyas varje
          månad tills det sägs upp i kundportalen. En uppsägning gäller vid den
          redan betalda periodens slut. Kunden behåller åtkomst under den tiden.
        </p>
      </section>
      <section>
        <h2>4. Innehåll och AI-svar</h2>
        <p>
          Kunden ansvarar för webbplatsens innehåll och för hur assistenten
          används. AI-svar kan innehålla fel. Viktiga uppgifter ska kunna
          kontrolleras mot de källor som assistenten visar. Tjänsten får inte
          användas för olagligt, vilseledande eller integritetskränkande innehåll.
        </p>
      </section>
      <section>
        <h2>5. Drift och förändringar</h2>
        <p>
          Vi arbetar för stabil drift men kan behöva göra underhåll eller stoppa
          missbruk. Väsentliga ändringar av pris eller villkor meddelas innan de
          börjar gälla för en ny abonnemangsperiod.
        </p>
      </section>
    </div>
  );
}

function Privacy() {
  return (
    <div className="legal-copy">
      <section>
        <h2>Vilka uppgifter behandlas?</h2>
        <p>
          Vi behandlar den webbadress kunden anger, publikt webbplatsinnehåll,
          e-postadress för ägarskap, tekniska driftuppgifter samt frågor och svar
          i chatbotten. Betalningsuppgifter behandlas av Stripe och lagras inte av
          Coastworks.
        </p>
      </section>
      <section>
        <h2>Varför behandlas uppgifterna?</h2>
        <p>
          Uppgifterna används för att skapa, säkra, leverera och förbättra den
          beställda tjänsten, hantera abonnemang och motverka missbruk. Publikt
          webbplatsinnehåll och frågor skickas till våra drift- och AI-leverantörer
          när det krävs för att skapa ett svar.
        </p>
      </section>
      <section>
        <h2>Lagring</h2>
        <p>
          En obekräftad provassistent sparas normalt i 24 timmar. Samtal sparas i
          högst 30 dagar. Faktura- och bokföringsunderlag kan behöva sparas längre
          enligt lag. Kunden ska inte skriva känsliga personuppgifter i chatten.
        </p>
      </section>
      <section>
        <h2>Delning och skydd</h2>
        <p>
          Uppgifter delas bara med leverantörer som behövs för hosting, e-post,
          AI-svar och betalning. Åtkomst begränsas tekniskt per chatbot och
          betalningskort hanteras i Stripes hostade kassa.
        </p>
      </section>
      <section>
        <h2>Dina rättigheter</h2>
        <p>
          Du kan begära tillgång, rättelse eller radering av personuppgifter och
          invända mot behandling. Använd kontaktvägen som du fick i
          bekräftelsemeddelandet eller kundportalen så kopplar vi ärendet till rätt
          chatbot utan att lämna ut någon annans uppgifter.
        </p>
      </section>
    </div>
  );
}
