"use client";

import React, { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Loader2,
  MessageSquarePlus,
  Moon,
  Phone,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { usePatientContext } from "@/components/providers/PatientProvider";
import { apiClient } from "@/services/api";
import type { ChatMessageOut, ChatSessionOut, ChatTurnResponse } from "@/types/glycadence";

const SUGGESTED_CHIPS = [
  "Which lunches kept my sugar steady?",
  "Did I have any lows overnight?",
  "Plan Ramadan suhoor and iftar for me",
  "What should I ask my doctor at my next visit?",
];

const HELPER_BADGES = [
  { name: "Rhythm", desc: "Checking your daily glucose curve" },
  { name: "Plate", desc: "Looking at your past meals" },
  { name: "Dose Diary", desc: "Checking your medicine schedule" },
  { name: "Kindred", desc: "Reviewing sleep and stress notes" },
  { name: "Safety Check", desc: "Verifying every number and rule" },
];

function AskCadieContent() {
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get("q");
  const { activePatientId } = usePatientContext();

  const [sessions, setSessions] = useState<ChatSessionOut[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessageOut[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [lastTurnMeta, setLastTurnMeta] = useState<ChatTurnResponse | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);
  const [showSheet, setShowSheet] = useState(false);
  const [forClinicians, setForClinicians] = useState(false);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const autoSentRef = React.useRef(false);

  const loadSessions = useCallback(async () => {
    if (!activePatientId) return;
    try {
      const list = await apiClient.listChatSessions(activePatientId, searchQuery || undefined);
      setSessions(list);
      if (list.length > 0 && !activeSessionId) {
        setActiveSessionId(list[0].id);
      }
    } finally {
      setSessionsLoaded(true);
    }
  }, [activePatientId, searchQuery, activeSessionId]);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  const loadMessages = useCallback(async () => {
    if (!activePatientId || !activeSessionId) {
      setMessages([]);
      return;
    }
    const list = await apiClient.getChatMessages(activePatientId, activeSessionId);
    setMessages(list);
  }, [activePatientId, activeSessionId]);

  useEffect(() => {
    void loadMessages();
  }, [loadMessages]);

  const sendMessageText = useCallback(
    async (text: string) => {
      if (!activePatientId || !text.trim() || sending) return;
      setSending(true);
      setChatError(null);
      try {
        let sid = activeSessionId || (sessions.length > 0 ? sessions[0].id : "");
        if (!sid) {
          const created = await apiClient.createChatSession(activePatientId, text.trim().slice(0, 60));
          sid = created.id;
        }
        setActiveSessionId(sid);
        const turn = await apiClient.sendChatMessage(activePatientId, sid, text.trim(), "auto");
        setLastTurnMeta(turn);
        setMessages((prev) => [...prev, turn.patient_message, turn.cadie_message]);
        void loadSessions();
      } catch (err) {
        setChatError(err instanceof Error ? err.message : "Could not reach Cadie right now.");
      } finally {
        setSending(false);
      }
    },
    [activePatientId, activeSessionId, sessions, sending, loadSessions]
  );

  useEffect(() => {
    if (initialQuery && activePatientId && sessionsLoaded && !autoSentRef.current) {
      autoSentRef.current = true;
      void sendMessageText(initialQuery);
    }
  }, [initialQuery, activePatientId, sessionsLoaded, sendMessageText]);

  async function handleNewChat() {
    if (!activePatientId) return;
    const created = await apiClient.createChatSession(activePatientId, "Conversation with Cadie");
    setActiveSessionId(created.id);
    setMessages([]);
    setLastTurnMeta(null);
    void loadSessions();
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;
    const msg = input;
    setInput("");
    void sendMessageText(msg);
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 min-h-[78vh]">
      {/* Left Column: Persistent Chat History */}
      <aside className="lg:col-span-4 gc-card p-4 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h1 className="font-display text-lg font-semibold">Conversations</h1>
          <button
            type="button"
            onClick={() => void handleNewChat()}
            className="inline-flex items-center gap-1.5 rounded-[12px] bg-[#FF4D4D] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#e84141]"
          >
            <MessageSquarePlus className="h-3.5 w-3.5" />
            New
          </button>
        </div>

        <div className="relative">
          <Search className="h-3.5 w-3.5 text-[var(--text-muted)] absolute left-3 top-3" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search saved chats..."
            className="w-full rounded-[12px] border border-[var(--border-clay)] bg-[var(--bg-page)] pl-8 pr-3 py-2 text-xs focus:border-[#FF4D4D] focus:outline-none"
          />
        </div>

        <div className="flex-1 space-y-1.5 overflow-y-auto max-h-[58vh]">
          {sessions.length === 0 ? (
            <p className="text-xs text-[var(--text-muted)] p-2">No saved conversations yet. Say hello to Cadie!</p>
          ) : (
            sessions.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setActiveSessionId(s.id)}
                className={`w-full text-left rounded-[14px] p-3 text-xs transition-colors border ${
                  s.id === activeSessionId
                    ? "bg-[var(--bg-muted)] border-[#FF4D4D]/50 font-medium"
                    : "border-transparent hover:bg-[var(--bg-muted)]/60"
                }`}
              >
                <div className="font-semibold truncate">{s.title}</div>
                {s.last_message_preview && (
                  <div className="text-[var(--text-muted)] truncate mt-0.5">{s.last_message_preview}</div>
                )}
              </button>
            ))
          )}
        </div>
      </aside>

      {/* Main Chat Pane */}
      <section className="lg:col-span-8 gc-card p-5 flex flex-col justify-between">
        <div className="space-y-4 overflow-y-auto max-h-[62vh] pr-1">
          {messages.length === 0 && !sending && (
            <div className="py-10 text-center space-y-4">
              <div className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-[#FF4D4D]/15 text-[#FF4D4D]">
                <Sparkles className="h-6 w-6" />
              </div>
              <h2 className="font-display text-xl font-semibold">Ask Cadie anything</h2>
              <p className="text-sm text-[var(--text-muted)] max-w-md mx-auto">
                Cadie checks your glucose history, meals, medicines, and wellbeing notes, and remembers what you share.
              </p>
              <div className="flex flex-wrap justify-center gap-2 pt-2">
                {SUGGESTED_CHIPS.map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    onClick={() => void sendMessageText(chip)}
                    className="rounded-full border border-[var(--border-clay)] bg-[var(--bg-page)] px-3.5 py-1.5 text-xs font-medium hover:border-[#FF4D4D]"
                  >
                    {chip}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => (
            <div key={m.id} className={m.role === "patient" ? "flex justify-end" : "flex justify-start"}>
              {m.role === "patient" ? (
                <div className="max-w-[82%] rounded-2xl rounded-tr-sm bg-[#2B1E2F] text-white dark:bg-[#F2A93B] dark:text-[#2B1E2F] px-4 py-2.5 text-sm">
                  {m.content}
                </div>
              ) : (
                <div className="max-w-[92%] space-y-3">
                  <div className="rounded-2xl rounded-tl-sm border border-[var(--border-clay)] bg-[var(--bg-page)] p-4 space-y-3">
                    <p className="text-sm leading-relaxed">{m.content}</p>

                    {/* Structured Rich Cards */}
                    {(m.cards ?? []).map((card, idx) => {
                      const ctype = String(card.type || "");
                      if (ctype === "urgent_card") {
                        const steps = (card.steps as string[]) ?? [];
                        return (
                          <div
                            key={idx}
                            className="rounded-2xl border-2 border-[#8E2C5A] bg-[#8E2C5A]/10 p-4 space-y-2"
                          >
                            <div className="flex items-center gap-2 font-bold text-[#8E2C5A]">
                              <AlertTriangle className="h-5 w-5" />
                              <span>Urgent Safety Guidance (15-15 Rule)</span>
                            </div>
                            <ul className="list-disc pl-5 text-xs space-y-1">
                              {steps.map((st, i) => (
                                <li key={i}>{st}</li>
                              ))}
                            </ul>
                            {typeof card.emergency_contact_name === "string" && (
                              <div className="pt-1 flex items-center gap-2 text-xs font-semibold text-[#8E2C5A]">
                                <Phone className="h-3.5 w-3.5" />
                                Contact: {card.emergency_contact_name}
                                {card.emergency_contact_phone ? ` (${String(card.emergency_contact_phone)})` : ""}
                              </div>
                            )}
                          </div>
                        );
                      }

                      if (ctype === "meal_card") {
                        return (
                          <Link
                            key={idx}
                            href={`/meals/${String(card.recipe_id)}`}
                            className="flex items-center gap-3 rounded-xl border border-[var(--border-clay)] bg-[var(--bg-card)] p-2.5 hover:border-[#FF4D4D]"
                          >
                            <img
                              src={String(card.image_url)}
                              alt={String(card.name)}
                              className="h-14 w-14 rounded-xl object-cover shrink-0"
                            />
                            <div className="flex-1 min-w-0 text-xs">
                              <div className="font-semibold truncate">{String(card.name)}</div>
                              <div className="text-[var(--text-muted)] mt-0.5">
                                {String(card.carbs_g)}g carbs · {String(card.sugar_g)}g sugar · {String(card.gl_band)} GL
                              </div>
                            </div>
                            <ChevronRight className="h-4 w-4 text-[var(--text-muted)]" />
                          </Link>
                        );
                      }

                      if (ctype === "ramadan_plan_card") {
                        return (
                          <div
                            key={idx}
                            className="rounded-xl border border-[#F2A93B]/50 bg-[#F2A93B]/10 p-3 text-xs space-y-1.5"
                          >
                            <div className="font-semibold flex items-center gap-1.5">
                              <Moon className="h-4 w-4 text-[#F2A93B]" />
                              Roza Guide ({String(card.city)}) — {String(card.risk_tier).toUpperCase()} IDF-DAR tier
                            </div>
                            <div>Suhoor idea: {String(card.suhoor_name)}</div>
                            <div>Iftar idea: {String(card.iftar_name)}</div>
                            <Link href="/fasting" className="font-semibold text-[#FF4D4D] inline-block pt-1 hover:underline">
                              Open full Ramadan planner
                            </Link>
                          </div>
                        );
                      }

                      if (ctype === "sick_day_checklist") {
                        const items = (card.items as string[]) ?? [];
                        return (
                          <div key={idx} className="rounded-xl border border-[#C8553D]/40 bg-[#C8553D]/10 p-3 text-xs space-y-1">
                            <div className="font-semibold text-[#C8553D]">Sick-Day Checklist</div>
                            <ul className="list-disc pl-4 space-y-0.5">
                              {items.map((it, i) => (
                                <li key={i}>{it}</li>
                              ))}
                            </ul>
                          </div>
                        );
                      }

                      return null;
                    })}

                    {/* Plain-English Safety & Behind-This-Answer Row */}
                    <div className="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-[var(--border-clay)]/70 text-[11px] text-[var(--text-muted)]">
                      <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-400 font-medium">
                        <ShieldCheck className="h-3.5 w-3.5" />
                        Checked by Safety Check
                      </span>
                      {lastTurnMeta && lastTurnMeta.cadie_message.id === m.id && (
                        <button
                          type="button"
                          onClick={() => setShowSheet(true)}
                          className="font-semibold text-[#FF4D4D] hover:underline"
                        >
                          Behind this answer
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}

          {/* Compact Temporary Helper Activity Row (ONLY visible while thinking) */}
          {sending && (
            <div className="rounded-2xl border border-[var(--border-clay)] bg-[var(--bg-muted)] p-3.5 space-y-2">
              <div className="flex items-center gap-2 text-xs font-semibold">
                <Loader2 className="h-4 w-4 animate-spin text-[#FF4D4D]" />
                Cadie is checking with her helpers...
              </div>
              <div className="flex flex-wrap gap-2">
                {HELPER_BADGES.map((h) => (
                  <span
                    key={h.name}
                    className="inline-flex items-center gap-1 rounded-full bg-[var(--bg-card)] px-2.5 py-1 text-[11px]"
                  >
                    <CheckCircle2 className="h-3 w-3 text-[#F2A93B]" />
                    <strong>{h.name}:</strong> {h.desc}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Chat Composer */}
        {chatError && (
          <div className="mt-2 rounded-xl border border-[#8E2C5A]/40 bg-[#8E2C5A]/10 px-3 py-2 text-xs text-[#8E2C5A]">
            {chatError}
          </div>
        )}
        <form onSubmit={handleSubmit} className="mt-4 pt-3 border-t border-[var(--border-clay)] flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask Cadie a question or share a food preference..."
            className="flex-1 rounded-[14px] border border-[var(--border-clay)] bg-[var(--bg-page)] px-4 py-2.5 text-sm focus:border-[#FF4D4D] focus:outline-none"
          />
          <button
            type="submit"
            disabled={sending}
            aria-label="Send message"
            className="inline-flex items-center justify-center rounded-[14px] bg-[#FF4D4D] h-10 w-11 text-white hover:bg-[#e84141] disabled:opacity-60"
          >
            <Send className="h-4 w-4" />
          </button>
        </form>
      </section>

      {/* "Behind this answer" Sheet Modal */}
      {showSheet && lastTurnMeta && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
          <div className="gc-card w-full max-w-lg p-6 space-y-4 max-h-[85vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h3 className="font-display text-lg font-semibold">Behind this answer</h3>
              <button type="button" onClick={() => setShowSheet(false)} aria-label="Close">
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-2.5">
              {lastTurnMeta.helpers_used.map((h, i) => (
                <div key={i} className="rounded-xl border border-[var(--border-clay)] bg-[var(--bg-page)] p-3 text-xs space-y-1">
                  <div className="flex items-center justify-between font-semibold">
                    <span>{h.helper}</span>
                    {forClinicians && (
                      <span className="font-mono text-[10px] text-[var(--text-muted)]">
                        {h.agent} · {h.duration_ms}ms
                      </span>
                    )}
                  </div>
                  <p className="text-[var(--text-muted)]">{h.summary}</p>
                </div>
              ))}
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-[var(--border-clay)] text-xs">
              <label className="inline-flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={forClinicians}
                  onChange={(e) => setForClinicians(e.target.checked)}
                />
                <span>For clinicians (technical trace)</span>
              </label>
              {forClinicians && (
                <span className="font-mono text-[11px] text-[var(--text-muted)]">
                  writer: {lastTurnMeta.execution_mode}
                </span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function AskCadiePage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm">Loading conversation...</div>}>
      <AskCadieContent />
    </Suspense>
  );
}
