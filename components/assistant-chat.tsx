"use client";

import {
  Brain,
  Check,
  LoaderCircle,
  MessageSquarePlus,
  Pencil,
  Send,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { currency } from "@/lib/format";

type Message = { role: "user" | "assistant"; content: string };

type Proposal = {
  id: string;
  kind: string;
  summary: string;
  status: "pending" | "approved" | "rejected" | "failed";
  // Null for kinds where "how many rows" is not the question, such as
  // creating a rule that applies to everything from now on.
  affected: number | null;
  examples: { posted_date: string; merchant: string; amount: string }[];
  result: Record<string, unknown> | null;
};

type Thread = {
  id: string;
  title: string;
  last_message_at: string;
  created_at: string;
  message_count: number;
};

type Memory = {
  id: string;
  fact: string;
  source: "person" | "assistant" | "derived";
  is_active: boolean;
  confirmed_at: string | null;
  created_at: string;
};

const SUGGESTIONS = [
  "What did I spend the most on this month?",
  "Which subscriptions am I paying for?",
  "How does this month compare to my budget?",
  "Anything unusual in my recent transactions?",
];

function when(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  const days = Math.floor((Date.now() - parsed.getTime()) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return parsed.toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function AssistantChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [showMemories, setShowMemories] = useState(false);
  const [newMemory, setNewMemory] = useState("");
  const [editingMemory, setEditingMemory] = useState<string | null>(null);
  const [memoryDraft, setMemoryDraft] = useState("");
  const [suggested, setSuggested] = useState<string | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [applying, setApplying] = useState(false);
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  /**
   * How long the current question has been waiting, in seconds.
   *
   * A 35B model being read into VRAM for the first time that day answers
   * nothing for a minute or more, and a spinner that says "Thinking…" the
   * whole time is indistinguishable from one that has hung. His words: "just
   * turn on the PC for the day and the model is not even loaded, and
   * obviously that's going to take time." So the wait narrates itself.
   */
  const [waited, setWaited] = useState(0);
  const [error, setError] = useState("");
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      apiFetch<{ configured: boolean; model: string | null }>("/system/ai"),
      apiFetch<Thread[]>("/assistant/threads").catch(() => [] as Thread[]),
      apiFetch<Memory[]>("/assistant/memories").catch(() => [] as Memory[]),
    ])
      .then(([status, threadRows, memoryRows]) => {
        if (cancelled) return;
        setConfigured(status.configured);
        setModel(status.model);
        setThreads(threadRows);
        setMemories(memoryRows);
      })
      .catch(() => {
        if (!cancelled) setConfigured(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, thinking]);

  // The counter is reset where the request starts, not here: setting state
  // synchronously inside an effect cascades renders, and the lint rule that
  // catches it is right.
  useEffect(() => {
    if (!thinking) return;
    const started = Date.now();
    const tick = setInterval(
      () => setWaited(Math.round((Date.now() - started) / 1000)),
      1000,
    );
    return () => clearInterval(tick);
  }, [thinking]);

  async function refreshThreads() {
    setThreads(await apiFetch<Thread[]>("/assistant/threads"));
  }

  async function refreshMemories() {
    setMemories(await apiFetch<Memory[]>("/assistant/memories"));
  }

  async function openThread(id: string) {
    setError("");
    setSuggested(null);
    const detail = await apiFetch<{
      id: string;
      title: string;
      messages: Message[];
    }>(`/assistant/threads/${id}`);
    setThreadId(detail.id);
    setMessages(
      detail.messages.map((m) => ({ role: m.role, content: m.content })),
    );
  }

  function startNew() {
    setThreadId(null);
    setMessages([]);
    setSuggested(null);
    setError("");
  }

  async function ask(question: string) {
    const trimmed = question.trim();
    if (!trimmed || thinking) return;
    setMessages((current) => [...current, { role: "user", content: trimmed }]);
    setDraft("");
    setThinking(true);
    setWaited(0);
    setError("");
    setSuggested(null);
    setProposal(null);
    try {
      const result = await apiFetch<{
        thread_id: string;
        title: string;
        reply: string;
        suggested_memory: string | null;
        proposal: Proposal | null;
      }>("/assistant/ask", {
        method: "POST",
        body: JSON.stringify({ question: trimmed, thread_id: threadId }),
      });
      setThreadId(result.thread_id);
      setMessages((current) => [
        ...current,
        { role: "assistant", content: result.reply },
      ]);
      setSuggested(result.suggested_memory);
      setProposal(result.proposal);
      await refreshThreads();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The assistant could not answer.",
      );
    } finally {
      setThinking(false);
    }
  }

  async function keepSuggested() {
    if (!suggested) return;
    await apiFetch("/assistant/memories", {
      method: "POST",
      body: JSON.stringify({ fact: suggested }),
    });
    setSuggested(null);
    await refreshMemories();
  }

  // Approve re-resolves on the server; the count on screen is a preview and
  // may be stale by the time the button is pressed. Whatever comes back is
  // what actually happened, so it replaces the card rather than dismissing it.
  async function decideProposal(action: "approve" | "reject") {
    if (!proposal) return;
    setApplying(true);
    try {
      const result = await apiFetch<Proposal>(
        `/assistant/proposals/${proposal.id}/${action}`,
        { method: "POST" },
      );
      setProposal(action === "approve" ? result : null);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not apply that.",
      );
      setProposal(null);
    } finally {
      setApplying(false);
    }
  }

  async function addMemory(event: FormEvent) {
    event.preventDefault();
    const fact = newMemory.trim();
    if (!fact) return;
    try {
      await apiFetch("/assistant/memories", {
        method: "POST",
        body: JSON.stringify({ fact }),
      });
      setNewMemory("");
      await refreshMemories();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save that");
    }
  }

  async function patchMemory(id: string, body: Record<string, unknown>) {
    await apiFetch(`/assistant/memories/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    await refreshMemories();
  }

  async function removeMemory(id: string) {
    await apiFetch(`/assistant/memories/${id}`, { method: "DELETE" });
    await refreshMemories();
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void ask(draft);
  }

  if (configured === false) {
    return (
      <>
        <div className="page-heading">
          <div>
            <p className="eyebrow">Assistant</p>
            <h1>Ask about your money.</h1>
          </div>
        </div>
        <section className="panel rules-empty">
          <Sparkles size={20} />
          <strong>No local AI endpoint configured</strong>
          <small>
            Set <code>LLM_BASE_URL</code> and <code>LLM_MODEL</code> on the
            backend and worker, then use Settings → AI assistant → Test
            connection to confirm it works.
          </small>
        </section>
      </>
    );
  }

  const unconfirmed = memories.filter((item) => !item.confirmed_at);

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Assistant</p>
          <h1>Ask about your money.</h1>
          <p className="subtle">
            Runs entirely on your own hardware
            {model ? ` (${model})` : ""}. It reads your ledger and answers —
            it cannot change anything.
          </p>
        </div>
        <div className="heading-actions">
          <button
            className="ghost-button"
            onClick={() => setShowMemories((current) => !current)}
            type="button"
          >
            <Brain size={15} /> Memory
            {memories.length ? ` (${memories.length})` : ""}
            {unconfirmed.length ? " •" : ""}
          </button>
          <button className="ghost-button" onClick={startNew} type="button">
            <MessageSquarePlus size={15} /> New
          </button>
        </div>
      </div>

      {showMemories && (
        <article className="panel memory-panel">
          <div className="settings-card-heading">
            <h2>What Raven remembers</h2>
            <p className="subtle">
              Carried into every conversation. Raven suggests these; nothing is
              used until you confirm it, and you can reword or switch off any of
              them. Readable with an API key, so your own agents can share these
              facts without a second copy of your finances living elsewhere.
            </p>
          </div>

          <form className="memory-add" onSubmit={addMemory}>
            <input
              aria-label="Something Raven should remember"
              maxLength={400}
              onChange={(event) => setNewMemory(event.target.value)}
              placeholder="e.g. Southwest charges are reimbursed work travel"
              value={newMemory}
            />
            <button
              className="primary-button"
              disabled={!newMemory.trim()}
              type="submit"
            >
              Remember
            </button>
          </form>

          {memories.length === 0 ? (
            <p className="subtle memory-empty">
              Nothing yet. Tell Raven something durable about your money — a
              goal, or why a merchant is what it is — and it will stop having to
              be explained again.
            </p>
          ) : (
            <ul className="memory-list">
              {memories.map((memory) => (
                <li
                  className={`${memory.is_active ? "" : "off"}${memory.confirmed_at ? "" : " unconfirmed"}`}
                  key={memory.id}
                >
                  {editingMemory === memory.id ? (
                    <form
                      className="memory-edit"
                      onSubmit={(event) => {
                        event.preventDefault();
                        const fact = memoryDraft.trim();
                        if (!fact) return;
                        void patchMemory(memory.id, { fact }).then(() =>
                          setEditingMemory(null),
                        );
                      }}
                    >
                      <input
                        aria-label="Edit this memory"
                        autoFocus
                        maxLength={400}
                        onChange={(event) => setMemoryDraft(event.target.value)}
                        value={memoryDraft}
                      />
                      <button aria-label="Save" type="submit">
                        <Check size={14} />
                      </button>
                      <button
                        aria-label="Cancel"
                        onClick={() => setEditingMemory(null)}
                        type="button"
                      >
                        <X size={14} />
                      </button>
                    </form>
                  ) : (
                    <>
                      <div>
                        <strong>{memory.fact}</strong>
                        <small>
                          {memory.source === "assistant"
                            ? "Raven suggested this"
                            : "You told Raven this"}
                          {memory.confirmed_at ? "" : " · not confirmed yet"}
                          {memory.is_active ? "" : " · switched off"}
                        </small>
                      </div>
                      <div className="memory-actions">
                        {!memory.confirmed_at && (
                          <button
                            aria-label="Confirm this memory"
                            className="ghost-button positive"
                            onClick={() =>
                              void patchMemory(memory.id, { confirmed: true })
                            }
                            type="button"
                          >
                            <Check size={13} />
                          </button>
                        )}
                        <button
                          aria-label={
                            memory.is_active ? "Switch off" : "Switch on"
                          }
                          className="ghost-button"
                          onClick={() =>
                            void patchMemory(memory.id, {
                              is_active: !memory.is_active,
                            })
                          }
                          type="button"
                        >
                          {memory.is_active ? "On" : "Off"}
                        </button>
                        <button
                          aria-label="Edit this memory"
                          className="ghost-button"
                          onClick={() => {
                            setEditingMemory(memory.id);
                            setMemoryDraft(memory.fact);
                          }}
                          type="button"
                        >
                          <Pencil size={13} />
                        </button>
                        <button
                          aria-label="Forget this"
                          className="ghost-button danger"
                          onClick={() => void removeMemory(memory.id)}
                          type="button"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </article>
      )}

      <div className="assistant-layout">
        {threads.length > 0 && (
          <aside className="thread-rail" aria-label="Past conversations">
            <h2>Conversations</h2>
            <ul>
              {threads.map((thread) => (
                <li key={thread.id}>
                  <button
                    className={thread.id === threadId ? "active" : ""}
                    onClick={() => void openThread(thread.id)}
                    type="button"
                  >
                    <strong>{thread.title}</strong>
                    <small>
                      {when(thread.last_message_at)} · {thread.message_count}{" "}
                      messages
                    </small>
                  </button>
                  <button
                    aria-label={`Delete ${thread.title}`}
                    className="ghost-button danger"
                    onClick={() =>
                      void apiFetch(`/assistant/threads/${thread.id}`, {
                        method: "DELETE",
                      }).then(() => {
                        if (thread.id === threadId) startNew();
                        return refreshThreads();
                      })
                    }
                    type="button"
                  >
                    <Trash2 size={12} />
                  </button>
                </li>
              ))}
            </ul>
          </aside>
        )}

        <section className="chat-panel">
          <div className="chat-log">
            {messages.length === 0 && (
              <div className="chat-intro">
                <Sparkles size={18} />
                <strong>Start with a question</strong>
                <div className="chat-suggestions">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      className="ghost-button"
                      key={suggestion}
                      onClick={() => void ask(suggestion)}
                      type="button"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((message, index) => (
              <div className={`chat-turn ${message.role}`} key={index}>
                <span className="chat-role">
                  {message.role === "user" ? "You" : "Raven"}
                </span>
                <div className="chat-bubble">{message.content}</div>
              </div>
            ))}
            {thinking && (
              <div className="chat-turn assistant">
                <span className="chat-role">Raven</span>
                <div className="chat-bubble thinking">
                  <LoaderCircle className="spin" size={13} />{" "}
                  {waited < 12
                    ? "Thinking…"
                    : waited < 45
                      ? `Thinking… ${waited}s — if the model is cold it is still loading`
                      : `Still loading the model — ${waited}s. A large model off a cold disk can take a few minutes; the next question will be quick.`}
                </div>
              </div>
            )}
            {suggested && (
              /* Shown, not stored. A misheard sentence must not quietly become
                 something Raven believes about your money. */
              <div className="memory-suggestion" role="status">
                <Brain size={15} />
                <div>
                  <small>Worth remembering?</small>
                  <strong>{suggested}</strong>
                </div>
                <div className="memory-suggestion-actions">
                  <button
                    className="ghost-button"
                    onClick={() => setSuggested(null)}
                    type="button"
                  >
                    No
                  </button>
                  <button
                    className="primary-button"
                    onClick={() => void keepSuggested()}
                    type="button"
                  >
                    Keep it
                  </button>
                </div>
              </div>
            )}
            {proposal && (
              /* Proposed, not done. The ledger is untouched until this button
                 is pressed, and what it actually changed is reported back
                 rather than assumed. */
              <div className="proposal-card" role="status">
                <div className="proposal-body">
                  <small>
                    {proposal.status === "approved"
                      ? "Done"
                      : "Raven would like to change something"}
                  </small>
                  <strong>{proposal.summary}</strong>
                  {proposal.status === "pending" &&
                    proposal.affected !== null && (
                      <p className="proposal-detail">
                        {proposal.affected === 0
                          ? "Nothing matches that right now — nothing would change."
                          : `${proposal.affected} transaction${proposal.affected === 1 ? "" : "s"} would change:`}
                        {proposal.examples.length > 0 && (
                          <span className="proposal-examples">
                            {proposal.examples.map((row, index) => (
                              <span key={index}>
                                {row.posted_date} · {row.merchant} ·{" "}
                                {currency(Number(row.amount))}
                              </span>
                            ))}
                            {proposal.affected > proposal.examples.length && (
                              <span>
                                …and {proposal.affected - proposal.examples.length} more
                              </span>
                            )}
                          </span>
                        )}
                      </p>
                    )}
                  {proposal.status === "approved" && proposal.result && (
                    <p className="proposal-detail">
                      {typeof proposal.result.categorized === "number"
                        ? `${proposal.result.categorized} transaction${proposal.result.categorized === 1 ? "" : "s"} categorised.`
                        : typeof proposal.result.error === "string"
                          ? proposal.result.error
                          : "Applied."}
                    </p>
                  )}
                </div>
                {proposal.status === "pending" && (
                  <div className="memory-suggestion-actions">
                    <button
                      className="ghost-button"
                      disabled={applying}
                      onClick={() => void decideProposal("reject")}
                      type="button"
                    >
                      No
                    </button>
                    <button
                      className="primary-button"
                      disabled={applying || proposal.affected === 0}
                      onClick={() => void decideProposal("approve")}
                      type="button"
                    >
                      {applying ? "Applying…" : "Approve"}
                    </button>
                  </div>
                )}
              </div>
            )}
            {error && (
              <p className="negative chat-error" role="alert">
                {error}
              </p>
            )}
            <div ref={endRef} />
          </div>

          <form className="chat-composer" onSubmit={submit}>
            <input
              aria-label="Ask the assistant"
              disabled={thinking}
              maxLength={2000}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Ask about spending, bills, budgets…"
              value={draft}
            />
            <button
              className="primary-button"
              disabled={thinking || !draft.trim()}
              type="submit"
            >
              <Send size={15} />
              <span className="sr-only">Send</span>
            </button>
          </form>
        </section>
      </div>

      <p className="chat-disclaimer">
        Answers come from a local model reading your own records. It can be
        wrong — check the numbers before acting, and it does not give
        investment or tax advice.
      </p>
    </>
  );
}
