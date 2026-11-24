"""
WorkSafe BC Safety Assistant - RAG-Powered AI Knowledge Assistant
AI Builders Bootcamp - Final Project (based on the Lesson 19 RAG chatbot)

Run:  streamlit run app.py
"""

import sys
import time

# Streamlit Community Cloud has an old sqlite3; ChromaDB needs a newer one.
try:
    __import__("pysqlite3")
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

import pandas as pd
import streamlit as st
from openai import OpenAI

import rag_utils as rag

# ============================================================
# PAGE SETUP
# ============================================================

st.set_page_config(page_title=rag.ASSISTANT_NAME, page_icon="🦺", layout="wide")

st.markdown("""
<style>
  .block-container {max-width: 1100px; padding-top: 1.5rem;}
  .hero {background: linear-gradient(135deg, #1e3a5f 0%, #0b2440 100%); color: white;
         border-left: 8px solid #f5a300; border-radius: 16px; padding: 1.2rem 1.5rem; margin-bottom: .8rem;}
  .hero h1 {margin: 0; font-size: 1.8rem; color: white;}
  .hero p {margin: .3rem 0 0 0; opacity: .9;}
  .info {border: 1px solid rgba(120,120,120,.25); border-top: 4px solid #f5a300; border-radius: 12px;
         padding: .7rem .9rem; font-size: .9rem; min-height: 105px;}
  .source-card {border: 1px solid rgba(120,120,120,.25); border-left: 4px solid #f5a300;
                border-radius: 10px; padding: .6rem .9rem; margin-bottom: .5rem; font-size: .92rem;}
  .muted {opacity: .65; font-size: .85rem;}
</style>
<div class="hero">
  <h1>🦺 WorkSafe BC Safety Assistant</h1>
  <p>Ask workplace health and safety questions. Every answer comes from official WorkSafeBC guides,
     with the document and page.</p>
</div>
""", unsafe_allow_html=True)

# Application identity: purpose + type of documents
c1, c2, c3 = st.columns(3)
c1.markdown("<div class='info'><b>🎯 Purpose</b><br>Help workers, supervisors and safety committee members "
            "find WorkSafeBC guidance in seconds instead of searching long PDFs.</div>", unsafe_allow_html=True)
c2.markdown("<div class='info'><b>📚 Knowledge base</b><br>4 official WorkSafeBC guides (PDF, 344 pages): "
            "committees, lockout, WHMIS, incident investigations.</div>", unsafe_allow_html=True)
c3.markdown("<div class='info'><b>🛡️ Grounded</b><br>Answers only from the documents, cites the page, "
            "and says so when the documents don't cover a question.</div>", unsafe_allow_html=True)
st.caption("⚠️ Educational tool. Always confirm with the OHS Regulation, WorkSafeBC and your employer's procedures.")

# ============================================================
# API KEY (from .streamlit/secrets.toml or Streamlit Cloud secrets - never in the code)
# ============================================================

try:
    api_key = st.secrets.get("OPENAI_API_KEY")
except Exception:
    api_key = None

if not api_key:
    st.error("🔑 OpenAI API key missing. Add it to `.streamlit/secrets.toml`:")
    st.code('OPENAI_API_KEY = "your-key-here"', language="toml")
    st.stop()


@st.cache_resource(show_spinner=False)
def get_client(key: str) -> OpenAI:
    return OpenAI(api_key=key)


client = get_client(api_key)

# ============================================================
# KNOWLEDGE BASE (embedded once, then loaded from ChromaDB)
# ============================================================


@st.cache_resource(show_spinner=False)
def load_knowledge_base():
    start = time.perf_counter()
    records, errors = rag.load_knowledge_base()
    if not records:
        raise ValueError("The knowledge base is empty: no text could be loaded. " + " | ".join(errors))
    chunks = rag.build_chunks(records)
    collection, embedded_now = rag.build_or_load_collection(client, chunks)
    documents = pd.DataFrame(chunks).groupby("source").size().reset_index(name="Chunks")
    documents["Document"] = documents["source"].map(lambda s: rag.DOCUMENT_TITLES.get(s, s))
    return {
        "collection": collection,
        "chunk_count": len(chunks),
        "documents": documents[["Document", "Chunks"]],
        "errors": errors,
        "embedded_now": embedded_now,
        "seconds": time.perf_counter() - start,
    }


try:
    with st.status("Loading the knowledge base… (the first run embeds the documents, about 1 minute)",
                   expanded=False) as status:
        kb = load_knowledge_base()
        status.update(label=f"Knowledge base ready: {len(kb['documents'])} documents, "
                            f"{kb['chunk_count']} chunks", state="complete")
except Exception as exc:
    st.error(f"Could not load the knowledge base. Check the documents, the API key and the internet "
             f"connection. Details: {exc}")
    st.stop()

for problem in kb["errors"]:
    st.warning(f"A document could not be loaded and was skipped: {problem}")

# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("⚙️ Settings")
    st.success("OpenAI API connected")
    top_k = st.slider("Top-K (chunks to retrieve)", 1, 10, rag.TOP_K)
    threshold = st.slider("Relevance threshold (max distance)", 0.10, 1.20, rag.THRESHOLD, 0.05,
                          help="Lower = stricter. If no chunk is closer than this, the assistant "
                               "says it doesn't know instead of guessing.")
    show_details = st.toggle("Show retrieval details", value=False)

    st.subheader("📚 Knowledge base")
    st.caption(f"Embeddings: {rag.EMBEDDING_MODEL} · Answers: {rag.GENERATION_MODEL}")
    st.dataframe(kb["documents"], hide_index=True, width="stretch")

    if st.button("🗑️ Clear chat", width="stretch"):
        st.session_state.messages = []
        st.rerun()

# ============================================================
# CHAT
# ============================================================

if "messages" not in st.session_state:
    st.session_state.messages = []


def show_sources(result: dict):
    if result["fallback"] == "threshold":
        st.caption("⚠️ No document passed the relevance threshold, so no answer was generated.")
    elif result["fallback"] == "llm":
        st.caption("🛡️ Some chunks passed the threshold, but they don't answer the question, "
                   "so the assistant refused instead of guessing.")
    else:
        with st.expander(f"📄 View Sources ({len(result['sources'])})"):
            for n, row in enumerate(result["sources"], start=1):
                st.markdown(
                    f"<div class='source-card'><b>{rag.source_label(n, row)}</b> "
                    f"<span class='muted'>· {row['relevance']} match · distance {row['distance']:.3f} · "
                    f"chunk {row['id']}</span><br>{row['text']}</div>", unsafe_allow_html=True)
    if show_details:
        with st.expander("🧪 Retrieval details"):
            st.dataframe(pd.DataFrame([{
                "Chunk ID": r["id"], "Distance": round(r["distance"], 3), "Relevance": r["relevance"],
                "Status": "✅ accepted" if r["accepted"] else "❌ rejected", "Text": r["text"][:80] + "…",
            } for r in result["candidates"]]), hide_index=True, width="stretch")
            t = result["timings"]
            st.caption(f"Query embedding {t['embedding']*1000:.0f} ms · vector search {t['search']*1000:.0f} ms · "
                       f"answer {t['generation']:.1f} s · total {t['total']:.1f} s")


# Example questions for first-time users
if not st.session_state.messages:
    st.markdown("**Try one of these:**")
    examples = ["When does a workplace need a joint health and safety committee?", "What is a zero-energy state?",
                "What must a WHMIS supplier label include?", "How soon must a preliminary incident investigation be done?"]
    for column, example in zip(st.columns(len(examples)), examples):
        if column.button(example, width="stretch"):
            st.session_state.pending_question = example
            st.rerun()

# Show the conversation so far (kept in st.session_state between reruns)
for message in st.session_state.messages:
    with st.chat_message(message["role"], avatar="🧑" if message["role"] == "user" else "🦺"):
        st.markdown(message["content"])
        if message.get("result"):
            show_sources(message["result"])

question = st.chat_input("Ask a workplace safety question…") or st.session_state.pop("pending_question", None)

if question is not None:
    question = question.strip()
    if len(question) < 3:
        st.warning("Please type a question.")
        st.stop()

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(question)

    with st.chat_message("assistant", avatar="🦺"):
        try:
            start = time.perf_counter()
            with st.spinner("Searching the WorkSafeBC documents…"):
                retrieval = rag.retrieve_context(client, kb["collection"], question, top_k, threshold)
                accepted = rag.filter_by_threshold(retrieval["rows"])
                history = st.session_state.messages[:-1]
                generated = rag.generate_answer(client, question, accepted, history)
            result = {
                "fallback": generated["fallback"],
                "sources": accepted,
                "candidates": retrieval["rows"],
                "timings": {"embedding": retrieval["embedding_time"], "search": retrieval["search_time"],
                            "generation": generated["generation_time"], "total": time.perf_counter() - start},
            }
            st.markdown(generated["answer"])
            show_sources(result)
            st.session_state.messages.append({"role": "assistant", "content": generated["answer"], "result": result})
        except Exception as exc:
            message = ("Sorry, something went wrong while answering (OpenAI or network problem). "
                       f"Please try again. Details: {type(exc).__name__}")
            st.error(message)
            st.session_state.messages.append({"role": "assistant", "content": message})
