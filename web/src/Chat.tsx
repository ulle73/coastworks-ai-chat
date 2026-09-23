import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowUp, MessageCircle } from "lucide-react";
import { api, type Answer } from "./api";

export function Chat({
  endpoint,
  token,
  site,
}: {
  endpoint: string;
  token?: string;
  site?: string;
}) {
  const [messages, setMessages] = useState<
    { role: string; text: string; sources?: Answer["sources"] }[]
  >([]);
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [messages, pending]);
  async function send(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || pending) return;
    const text = question.trim();
    setQuestion("");
    setError("");
    setPending(true);
    setMessages((m) => [...m, { role: "user", text }]);
    try {
      const result = await api<Answer>(endpoint, { message: text }, token);
      setMessages((m) => [
        ...m,
        { role: "assistant", text: result.answer, sources: result.sources },
      ]);
    } catch (e) {
      setError((e as Error).message);
      setQuestion(text);
    } finally {
      setPending(false);
    }
  }
  return (
    <section className="chat" aria-label="Prata med din assistent">
      <div className="chat-heading">
        <span className="assistant-icon">
          <MessageCircle size={20} />
        </span>
        <div>
          <strong>{site || "Din assistent"}</strong>
          <span>AI-assistent · svar från hemsidan</span>
        </div>
      </div>
      <div className="messages" role="log" aria-live="polite">
        <div className="bubble assistant">Hej! Vad vill du veta om oss?</div>
        {messages.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            {m.text}
            {m.sources && m.sources.length > 0 && (
              <div className="sources">
                {m.sources.map((s) => (
                  <a
                    key={s.url}
                    href={s.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {s.title || "Läs mer"}
                  </a>
                ))}
              </div>
            )}
          </div>
        ))}
        {pending && <div className="bubble assistant">Tänker en stund…</div>}
        <div ref={end} />
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <form className="chat-input" onSubmit={send}>
        <input
          aria-label="Din fråga"
          placeholder="Skriv din fråga…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={2000}
        />
        <button
          disabled={pending || !question.trim()}
          aria-label="Skicka fråga"
        >
          <ArrowUp size={20} />
        </button>
      </form>
      <p className="chat-disclaimer">
        AI kan göra misstag. Kontrollera viktiga uppgifter med företaget.
      </p>
    </section>
  );
}
