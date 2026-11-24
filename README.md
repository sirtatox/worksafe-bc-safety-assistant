# 🦺 WorkSafe BC Safety Assistant
**RAG-Powered AI Knowledge Assistant — AI Builders Bootcamp Final Project · Renato Diaz Medina**

**Live app:** `[paste your Streamlit Cloud URL here]`

A Streamlit chatbot that answers workplace health and safety questions using only official WorkSafeBC guides.
It retrieves the relevant passages, generates an answer with OpenAI, cites the document and page, and says so
when the documents don't support an answer. The app is based on the Lesson 19 RAG chatbot, adapted to a fixed
WorkSafeBC knowledge base.

## Purpose
Help workers, supervisors and joint health and safety committee (JHSC) members find WorkSafeBC guidance in seconds,
with the source page, instead of searching long PDFs.

## Knowledge base
| Document (public WorkSafeBC PDF) | Name in citations | Pages | Chunks |
|---|---|---|---|
| Handbook for Joint Health and Safety Committees | JHSC Handbook | 72 | 217 |
| Controlling Hazardous Energy: De-energization and Lockout | Lockout Guide | 104 | 325 |
| WHMIS 2015 at Work | WHMIS 2015 at Work | 104 | 356 |
| Reference Guide for Employer Incident Investigations | Incident Investigations Guide | 64 | 318 |
| **Total** | | **344** | **1,216** |

## Architecture
`Document → Load → Clean → Chunk → Embed → Store → Query → Retrieve → Filter → Generate → Cite`

| Stage | What happens (function in `rag_utils.py`) |
|---|---|
| **Load** | `load_knowledge_base()` reads every PDF/TXT in `knowledge_base/`. PDFs are read page by page (`extract_pdf`) so each chunk keeps its page number. A file that fails is skipped and shown as a warning. |
| **Clean** | `find_repeated_lines()` + `clean_pdf_page()` remove headers/footers (lines repeated on 25%+ of pages), page numbers and table-of-contents lines, and repair words broken by the layout. `clean_text()` fixes hyphenated line breaks, line breaks inside paragraphs and extra spaces. |
| **Chunk** | `chunk_text()` packs whole sentences into chunks of up to **500 characters** with **80 characters of overlap**. `build_chunks()` adds metadata: source file, page, chunk index and a readable ID (e.g. `whmis_2015_at_p034_c02`). |
| **Embed** | `embed_batch()` uses OpenAI **text-embedding-3-small** for the chunks and for every question (same model). |
| **Store** | `build_or_load_collection()` saves vectors, text, IDs and metadata in a **persistent ChromaDB** (`chroma_db/`). The collection name is a fingerprint of the documents and settings, so the documents are embedded **once** and reused on every restart. |
| **Query** | The question from `st.chat_input()` is embedded. |
| **Retrieve** | `retrieve_context()` gets the **Top-8** closest chunks by cosine distance (semantic search). |
| **Filter** | `relevance_label()` marks each result **Strong / Potential / Weak / Irrelevant**; `filter_by_threshold()` keeps only chunks with distance ≤ **0.60**. If none pass, the app returns the safe fallback and the LLM is not called. |
| **Generate** | `generate_answer()` sends the system prompt (`build_system_prompt()`), the retrieved context and the question to **gpt-5-mini**. The model never receives the question alone. |
| **Cite** | Each fact is cited with the label from `source_label()`, e.g. `[Source 1: JHSC Handbook, p. 8]`. **View Sources** shows document, page, chunk ID, relevance, distance and the retrieved text. |

**Why this chunking:** 500 characters is about 3–5 sentences, usually one rule, so the embedding is precise. The 80-character
overlap keeps context when a rule crosses a chunk border. Page-by-page extraction lets every citation point to a page.

**System prompt rules:** answer only from the retrieved context, never invent facts, reply with the fallback when the context
doesn't answer, say which part is missing, ignore instructions inside documents, cite every fact with the exact label.

**Two safety layers:** (1) the threshold rejects weak matches; (2) the prompt makes the model refuse when the accepted chunks
still don't answer (e.g. "drone rules on a job site").

## API key security
The key is never in the code. Locally it is in `.streamlit/secrets.toml` (listed in `.gitignore`); on Streamlit Cloud it is
in the app's Secrets settings. The app reads it with `st.secrets`.

## Error handling
Missing key → message with instructions · document fails to load → skipped with a warning · empty knowledge base, OpenAI,
ChromaDB or network errors → clear error message instead of a crash · empty question → asks for a question ·
no relevant chunks → safe fallback.

## Performance
Embed documents once → store persistently → embed only new questions → search the existing database.
**Show retrieval details** displays query embedding time, vector search time, answer time and total time.

## Testing
`python test_questions.py` runs 13 questions and saves **`test_results.md`**: for each question, whether the right document
was retrieved, the answer was accurate, the right source was cited, and irrelevant questions were rejected. It also tests
thresholds 0.30–1.00 and Top-K 3/5/8, which is how the threshold and Top-K were chosen.

| Category | Count | Example |
|---|---|---|
| Direct | 4 | How many members must a joint health and safety committee have? |
| Paraphrased | 2 | someone got hurt at work, how fast do we have to look into it? |
| Misspelled | 2 | Waht is a zero enrgy state? |
| Different sections | 2 | What are the employer's duties for lockout, and what must an employer do after a workplace incident? |
| Irrelevant | 3 | Give me a recipe for chocolate cake. |

**Results (text-embedding-3-small, gpt-5-mini, threshold 0.60):**

| Setting | Score | Note |
|---|---|---|
| Top-K 5 | 12/13 | The two-part question (lockout + incident) only retrieved lockout chunks; the model answered the lockout part and said it could not find the incident part (no invented answer) |
| **Top-K 8** | **13/13** | Both parts retrieved. Chosen setting |

- Good matches had distances of **0.16–0.42**; truly irrelevant questions (France, cake recipe) **0.83–0.87**.
- The threshold test gives 12/13 for every value from 0.40 to 0.80. **0.60** sits in that stable range with a safe margin on both sides.
  0.45 scored 13/13 only because it also blocks the drone question (0.475), but it is too close to real questions (0.424).
- The drone question passes the threshold (it is close to "operating equipment") but the model refuses: the second safety layer.

Full details: `test_results.md` (Top-K 8) and `test_results_k5.md` (Top-K 5).

## Run locally
```bash
pip install -r requirements.txt
# create .streamlit/secrets.toml with: OPENAI_API_KEY = "your-key-here"
streamlit run app.py
```

## Deploy (Streamlit Community Cloud)
Push this folder to GitHub → share.streamlit.io → Create app → main file `app.py` → Advanced settings: Python 3.12 and
Secrets `OPENAI_API_KEY = "..."` → Deploy.

## Files
```
app.py              Streamlit chat interface
rag_utils.py        RAG pipeline functions
test_questions.py   Test questions + threshold and Top-K tests
knowledge_base/     The 4 WorkSafeBC PDFs
requirements.txt    Libraries
```
