import { useEffect, useState, type FormEvent } from "react";
import { ArrowRight, Check, LoaderCircle } from "lucide-react";
import { api, type Bot } from "./api";
import { Chat } from "./Chat";
import { Install } from "./Install";
import { Managed } from "./Managed";
import { Access } from "./Access";

function Preview({
  botId,
  onReset,
  confirmed,
}: {
  botId: string;
  onReset: () => void;
  confirmed: boolean;
}) {
  const [bot, setBot] = useState<Bot>();
  const [error, setError] = useState("");
  const [install, setInstall] = useState(confirmed);
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await api<Bot>(`/api/bots/${botId}`);
        if (stopped) return;
        setBot(result);
        setError("");
        if (!["ready", "failed"].includes(result.state))
          timer = setTimeout(poll, 1800);
      } catch (e) {
        if (!stopped) setError((e as Error).message);
      }
    }
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [botId]);
  const loading = bot && !["ready", "failed"].includes(bot.state);
  return (
    <main className="workspace">
      <button className="text-button back" onClick={onReset}>
        Till startsidan
      </button>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!bot && !error && <p role="status">Hämtar din assistent…</p>}
      {loading && (
        <div className="progress">
          <LoaderCircle className="spin" size={32} />
          <h1>Vi lär känna ditt företag.</h1>
          <p>
            {bot.state === "queued"
              ? "Din hemsida står på tur."
              : bot.state === "reading"
                ? "Vi läser det som finns på din hemsida."
                : "Vi kontrollerar att assistenten har fått med sig innehållet."}
          </p>
          <ol>
            {["Läser din hemsida", "Förbereder svaren", "Redo att prata"].map(
              (s, i) => (
                <li
                  key={s}
                  className={
                    i === 0 || (bot.state === "checking" && i === 1)
                      ? "current"
                      : ""
                  }
                >
                  {i === 0 && bot.state === "checking" ? (
                    <Check size={18} />
                  ) : (
                    <span>{i + 1}</span>
                  )}
                  {s}
                </li>
              ),
            )}
          </ol>
          <p className="small">
            Ofta tar det ungefär en minut. Vissa hemsidor behöver lite längre
            tid.
          </p>
        </div>
      )}
      {bot?.state === "failed" && (
        <div className="progress">
          <h1>Vi behöver lite hjälp här.</h1>
          <p>{bot.message}</p>
          <div className="actions">
            <button onClick={onReset}>Testa en annan hemsida</button>
            <a className="button secondary" href="#managed">
              Låt oss hjälpa dig
            </a>
          </div>
        </div>
      )}
      {bot?.state === "ready" &&
        (install ? (
          <Install bot={bot} confirmed={confirmed} />
        ) : (
          <>
            <div className="preview-title">
              <span className="ready-mark">
                <Check size={16} /> Redo att prova
              </span>
              <h1>Hälsa på din nya assistent.</h1>
              <p>
                Ställ samma frågor som dina kunder. Svaren kommer från{" "}
                {new URL(bot.url).hostname}.
              </p>
            </div>
            <Chat
              endpoint={`/api/bots/${botId}/chat`}
              site={new URL(bot.url).hostname}
            />
            <div className="install-cta">
              <button onClick={() => setInstall(true)}>
                Lägg till på min hemsida <ArrowRight size={18} />
              </button>
              <p className="small">
                Nöjd med svaren? Nästa steg är en enda rad kod.
              </p>
            </div>
          </>
        ))}
    </main>
  );
}

function Embed() {
  const botId = location.pathname.split("/")[2];
  const [token, setToken] = useState("");
  useEffect(() => {
    function receive(e: MessageEvent) {
      if (
        e.source !== window.parent ||
        e.data?.type !== "cw:session" ||
        e.data.bot !== botId ||
        typeof e.data.token !== "string"
      )
        return;
      setToken(e.data.token);
    }
    window.addEventListener("message", receive);
    window.parent.postMessage({ type: "cw:ready", bot: botId }, "*");
    return () => window.removeEventListener("message", receive);
  }, [botId]);
  return (
    <div className="embed">
      {token ? (
        <Chat endpoint={`/api/widget/${botId}/chat`} token={token} />
      ) : (
        <p role="status">Öppnar chatten…</p>
      )}
    </div>
  );
}

export default function App() {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [botId, setBotId] = useState(
    () => sessionStorage.getItem("cw_bot") || "",
  );
  const [confirmed, setConfirmed] = useState(false);
  const [confirmToken, setConfirmToken] = useState(() => {
    const t = new URLSearchParams(location.hash.slice(1)).get("confirm");
    if (t) history.replaceState(null, "", location.pathname);
    return t || "";
  });
  useEffect(() => {
    if (botId) sessionStorage.setItem("cw_bot", botId);
    else sessionStorage.removeItem("cw_bot");
  }, [botId]);
  async function confirm() {
    setBusy(true);
    setError("");
    try {
      const b = await api<Bot>("/api/confirm", { token: confirmToken });
      setBotId(b.id);
      setConfirmed(true);
      setConfirmToken("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const b = await api<{ id: string }>("/api/previews", { url });
      setConfirmed(false);
      setBotId(b.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (location.pathname.startsWith("/embed/")) return <Embed />;
  return (
    <>
      <header>
        <a
          className="wordmark"
          href="/"
          onClick={() => sessionStorage.removeItem("cw_bot")}
        >
          coastworks
        </a>
        <nav aria-label="Huvudmeny">
          <a href="#how">Så fungerar det</a>
          <a href="#managed">Vi hjälper dig</a>
        </nav>
      </header>
      {confirmToken ? (
        <main className="workspace install">
          <h1>Välkommen tillbaka.</h1>
          <p>Bekräfta din e-post för att hämta din installationskod.</p>
          <button disabled={busy} onClick={confirm}>
            Bekräfta och fortsätt <ArrowRight size={18} />
          </button>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </main>
      ) : botId ? (
        <Preview
          botId={botId}
          confirmed={confirmed}
          onReset={() => {
            setBotId("");
            setConfirmed(false);
          }}
        />
      ) : (
        <main>
          <section className="hero">
            <h1>
              Din hemsida.
              <br />
              Din AI-assistent.
            </h1>
            <p className="subtitle">
              Svar på kundernas frågor, direkt från din hemsida.
            </p>
            <form className="url-form" onSubmit={create}>
              <label className="sr-only" htmlFor="website-url">
                Företagets webbadress
              </label>
              <input
                id="website-url"
                inputMode="url"
                autoComplete="url"
                placeholder="https://dittforetag.se"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                required
                maxLength={2048}
              />
              <button disabled={busy}>
                {busy ? "Öppnar din hemsida…" : "Skapa min assistent"}{" "}
                <ArrowRight size={21} />
              </button>
            </form>
            <p className="reassurance">Testa gratis. Inget konto behövs.</p>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
          </section>
          <section id="how" className="steps" aria-label="Så fungerar det">
            <article>
              <span>01</span>
              <h2>Klistra in din webbadress</h2>
              <p>
                Vi läser in din hemsida och förstår innehållet, helt
                automatiskt.
              </p>
            </article>
            <article>
              <span>02</span>
              <h2>Prata med din assistent</h2>
              <p>
                Din AI-assistent svarar på kundernas frågor, direkt från din
                hemsida.
              </p>
            </article>
            <article>
              <span>03</span>
              <h2>Lägg till på din hemsida</h2>
              <p>
                Kopiera en enkel kodsnutt och lägg till assistenten på din
                hemsida.
              </p>
            </article>
          </section>
        </main>
      )}
      <Managed />
      <footer>
        <span>coastworks</span>
        <Access />
        <details>
          <summary>Om dina uppgifter</summary>
          <p>
            En provassistent sparas i 24 timmar. Samtal sparas i högst 30 dagar.
            Skriv inte känsliga personuppgifter i chatten. Webbtext och frågor
            behandlas av våra AI-leverantörer för att skapa svar.
          </p>
        </details>
      </footer>
    </>
  );
}
