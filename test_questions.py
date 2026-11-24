"""
Test questions for the WorkSafe BC Safety Assistant (README "Testing" section).

For each question it records:
  Retrieved - did the accepted chunks come from the right document?
  Accurate  - does the answer contain the expected fact?
  Cited     - does the answer cite the right document?
  Rejected  - for irrelevant questions, did it refuse instead of guessing?
It also tests several thresholds and Top-K values (retrieval only).

Run:  python test_questions.py      -> Top-K from rag_utils.py (8), writes test_results.md
      python test_questions.py 5    -> try another Top-K, writes test_results_k5.md
"""

import sys
import tomllib
from datetime import datetime
from pathlib import Path

from openai import OpenAI

import rag_utils as rag

JHSC = "JHSC Handbook"
LOCKOUT = "Lockout Guide"
WHMIS = "WHMIS 2015 at Work"
INCIDENT = "Incident Investigations Guide"

# (category, question, expected documents (any of), words the answer must contain (any of))
# expected documents = [] means the question must be REJECTED
TESTS = [
    ("Direct", "How many members must a joint health and safety committee have?", [JHSC], ["four", "4"]),
    ("Direct", "How many hours of training do new joint committee members need?", [JHSC], ["eight", "8"]),
    ("Direct", "What is a zero-energy state?", [LOCKOUT], ["energy sources", "removed", "discharged", "residual"]),
    ("Direct", "What information must a WHMIS supplier label include?", [WHMIS], ["product identifier"]),
    ("Paraphrased", "My workplace has 25 employees, do we need a safety committee?", [JHSC], ["20"]),
    ("Paraphrased", "someone got hurt at work, how fast do we have to look into it?", [INCIDENT, JHSC],
     ["48", "immediately"]),
    ("Misspelled", "Waht is a zero enrgy state?", [LOCKOUT], ["energy sources", "removed", "discharged", "residual"]),
    ("Misspelled", "how mnay hours of trainning do new comittee members need?", [JHSC], ["eight", "8"]),
    ("Different sections", "What are the employer's duties for lockout, and what must an employer do after "
     "a workplace incident?", [LOCKOUT, INCIDENT, JHSC], ["investigat"]),
    ("Different sections", "What training do new joint committee members need, and what is the committee's "
     "role in incident investigations?", [JHSC], ["investigat"]),
    ("Irrelevant", "What is the capital of France?", [], []),
    ("Irrelevant", "Give me a recipe for chocolate cake.", [], []),
    ("Irrelevant", "What is the WorkSafeBC rule for operating drones over a job site?", [], []),
]


def yes_no(value):
    return "✅" if value is True else "❌" if value is False else "–"


def main():
    top_k = int(sys.argv[1]) if len(sys.argv) > 1 else rag.TOP_K
    out_file = "test_results.md" if top_k == rag.TOP_K else f"test_results_k{top_k}.md"
    key = tomllib.loads(Path(".streamlit/secrets.toml").read_text(encoding="utf-8"))["OPENAI_API_KEY"]
    client = OpenAI(api_key=key)
    records, errors = rag.load_knowledge_base()
    chunks = rag.build_chunks(records)
    collection, embedded_now = rag.build_or_load_collection(client, chunks)
    print(f"{len(chunks)} chunks ({'embedded now' if embedded_now else 'loaded from ChromaDB'})"
          f" | threshold {rag.THRESHOLD} | Top-K {top_k}\n")

    rows, retrievals, passed = [], {}, 0
    for number, (category, question, docs, words) in enumerate(TESTS, start=1):
        retrievals[question] = rag.retrieve_context(client, collection, question, top_k=10, threshold=2.0)["rows"]
        retrieval = rag.retrieve_context(client, collection, question, top_k=top_k)
        accepted = rag.filter_by_threshold(retrieval["rows"])
        answer = rag.generate_answer(client, question, accepted)["answer"]
        best = retrieval["rows"][0]["distance"]

        if docs:   # should answer
            titles = {rag.DOCUMENT_TITLES.get(r["source"]) for r in accepted}
            retrieved = any(d in titles for d in docs)
            accurate = answer != rag.FALLBACK and any(w.lower() in answer.lower() for w in words)
            cited = any(d in answer for d in docs)
            rejected = None
            ok = retrieved and accurate and cited
        else:      # should be rejected
            retrieved = accurate = cited = None
            rejected = answer == rag.FALLBACK
            ok = rejected
        passed += ok
        used = ", ".join(sorted({rag.DOCUMENT_TITLES.get(r["source"], r["source"]) for r in accepted})) or "none"
        rows.append((number, category, question, retrieved, accurate, cited, rejected, best, ok, answer, used))
        print(f"{'PASS' if ok else 'FAIL'}  {number:>2}. [{category}] {question}  (best distance {best:.3f})")

    # Threshold and Top-K experiments (retrieval only, no LLM)
    def score(threshold, top_k):
        total = 0
        for category, question, docs, words in TESTS:
            kept = [r for r in retrievals[question][:top_k] if r["distance"] <= threshold]
            titles = {rag.DOCUMENT_TITLES.get(r["source"]) for r in kept}
            total += (any(d in titles for d in docs) if docs else not kept)
        return total

    thresholds = [round(0.30 + 0.05 * i, 2) for i in range(15)]
    sweep = [(t, score(t, top_k)) for t in thresholds]
    topk = [(k, score(rag.THRESHOLD, k)) for k in (3, 5, 8)]
    n = len(TESTS)

    lines = [f"# Test Results — {rag.ASSISTANT_NAME}", "",
             f"Date: {datetime.now():%Y-%m-%d %H:%M} · Embeddings: {rag.EMBEDDING_MODEL} · "
             f"Answers: {rag.GENERATION_MODEL} · Threshold: {rag.THRESHOLD} · Top-K: {top_k}", "",
             f"**Score: {passed}/{n}**", "",
             "| # | Category | Question | Right document retrieved | Accurate answer | Correct source cited | "
             "Correctly rejected | Best distance | Documents used | Result |", "|---|---|---|---|---|---|---|---|---|---|"]
    for number, category, question, retrieved, accurate, cited, rejected, best, ok, answer, used in rows:
        lines.append(f"| {number} | {category} | {question} | {yes_no(retrieved)} | {yes_no(accurate)} | "
                     f"{yes_no(cited)} | {yes_no(rejected)} | {best:.3f} | {used} | {'PASS' if ok else 'FAIL'} |")
    lines += ["", "## Threshold test (retrieval only)", "", "| Threshold | Passed |", "|---|---|"]
    lines += [f"| {t:.2f} | {s}/{n} |" for t, s in sweep]
    lines += ["", f"## Top-K test (threshold {rag.THRESHOLD})", "", "| Top-K | Passed |", "|---|---|"]
    lines += [f"| {k} | {s}/{n} |" for k, s in topk]
    lines += ["", "## Answers", ""]
    for number, category, question, *_, answer, used in rows:
        lines += [f"**{number}. {question}**", "", answer, ""]
    Path(out_file).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nScore: {passed}/{n}")
    print("Thresholds:", "  ".join(f"{t:.2f}={s}" for t, s in sweep))
    print("Top-K:", "  ".join(f"{k}={s}" for k, s in topk))
    print(f"Saved {out_file}")


if __name__ == "__main__":
    main()
