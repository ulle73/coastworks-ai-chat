# Spårbar återanvändning

Källrepo: `https://github.com/ulle73/coastworks-sitechat`, lokal sökväg `C:\dev\costworks-chatbots\coastworks-sitechat`, commit `6dd244efc5e79e3cd919e7359ebb68039c952174`. Angiven `../coastworks-sitechat` saknades; korrekt remote verifierades på den befintliga checkouten. Den checkouten var ren och har inte ändrats.

Inspektionen begränsades till crawl/rendering, index/RAG, modellfabriker, chat/embed och säkerhet samt deras tester och konfiguration. Ingen gammal frontend/dashboard kopierades.

| Befintlig del | Ny plats / beslut |
|---|---|
| `core/crawl_target.py` | Kopierad till samma modul: publika adresser, DNS-validering vid anslutning och SSRF-skydd. |
| `crawling/classification.py` | Kopierad och regressionstester återanvända. Kompletterad orchestration för Next/partiell rendering. |
| `crawling/cloudflare.py` | Kopierad: stateless content-API, bounded retries, länkkanonisering, samma origin och textextraktion. HTTP-bodygräns tillagd. Nya `Renderer` tolkar JSON-envelope och validerar metadata. Gamla hela crawl-metoden används inte som säkerhetsgräns; nya orchestratorn äger robots/kvalitet/deadline. |
| `providers/factory.py` | `get_llm` och `get_embeddings` återanvända. Konfigurationen begränsar stödet till Gemini och OpenAI. Ingen FAISS/provider-konfiguration kopierad. |
| `IndexerService._create_chunks` | Återanvänd i `app/chunking.py`, samma 1000/200-delning, metadata, source_type och tenantbinding. |
| `IndexerService` publiceringsprincip | Bevarad kandidat→validering→aktiv version, men utförd i en PostgreSQL-transaktion. Kopiering av Mongo/FAISS-lagring skulle bibehålla flera felkänsliga publiceringssteg. |
| `RAGEngine` | Bevarar begränsad historik, hämtning från aktiv tenantversion, kompakt källkontext och källänkar. Den hårt Mongo-kopplade klassen och L2-specifika trösklar kopieras inte; pgvector använder cosinus. |
| Chat API | Bevarar strikt site-binding och serverskapad samtalsidentitet. Anonym provcookie och signerade widgetsessioner ersätter gammal kontocentrisk väg. |
| Widget/embed | Samma enradiga installationskontrakt och origin-policy. Ny, liten iframe-loader eftersom gammal widget har beroenden till gammal plattformskonfiguration. |
| Säkerhet | Publika DNS-adresser och origin-kontroll återanvänds; nya produktgränser får CSRF, e-posttoken, privat preview, installationsbevis och gemensamma kostnadstak. |

Detta är selektiv kodåteranvändning och återanvändning av verifierade kontrakt, inte en kopia av hela RAG-backenden. En ny lagringsadapter och produkt-API är avsiktliga arkitekturbyten. Källans rättigheter/licens behöver fortsatt hanteras av repoägaren; ingen ny generell open-source-licens har lagts på återanvänd kod.
