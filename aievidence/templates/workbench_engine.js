/* AI Evidence Record: browser engine.
 *
 * A port of ledger.py, gate.py, rules.py, ask.py, the stub adapters and the
 * scenario, so the workbench can run every demo scenario with no server. The
 * hash chain is real SHA-256 over the same canonical JSON Python uses, so a
 * ledger produced here verifies with `aiev verify`, and vice versa.
 *
 * Runs in a browser (window.AIEV) or in Node (module.exports) for tests.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.AIEV = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ---- SHA-256 (synchronous, pure JS, UTF-8 input) -------------------------
  const K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];
  function utf8(str) {
    return new TextEncoder().encode(str);
  }
  function sha256(str) {
    const msg = utf8(str);
    const len = msg.length;
    const padded = new Uint8Array(((len + 9 + 63) >> 6) << 6);
    padded.set(msg);
    padded[len] = 0x80;
    const bits = len * 8;
    const dv = new DataView(padded.buffer);
    dv.setUint32(padded.length - 8, Math.floor(bits / 0x100000000));
    dv.setUint32(padded.length - 4, bits >>> 0);
    const H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    const W = new Uint32Array(64);
    for (let off = 0; off < padded.length; off += 64) {
      for (let i = 0; i < 16; i++) W[i] = dv.getUint32(off + i * 4);
      for (let i = 16; i < 64; i++) {
        const s0 = ((W[i - 15] >>> 7) | (W[i - 15] << 25)) ^ ((W[i - 15] >>> 18) | (W[i - 15] << 14)) ^ (W[i - 15] >>> 3);
        const s1 = ((W[i - 2] >>> 17) | (W[i - 2] << 15)) ^ ((W[i - 2] >>> 19) | (W[i - 2] << 13)) ^ (W[i - 2] >>> 10);
        W[i] = (W[i - 16] + s0 + W[i - 7] + s1) >>> 0;
      }
      let [a, b, c, d, e, f, g, h] = H;
      for (let i = 0; i < 64; i++) {
        const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
        const ch = (e & f) ^ (~e & g);
        const t1 = (h + S1 + ch + K[i] + W[i]) >>> 0;
        const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
        const maj = (a & b) ^ (a & c) ^ (b & c);
        const t2 = (S0 + maj) >>> 0;
        h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + b) >>> 0; H[2] = (H[2] + c) >>> 0; H[3] = (H[3] + d) >>> 0;
      H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0; H[6] = (H[6] + g) >>> 0; H[7] = (H[7] + h) >>> 0;
    }
    return H.map((x) => x.toString(16).padStart(8, "0")).join("");
  }

  // ---- canonical JSON (matches aievidence.ledger.canonical) -----------------
  function canonical(o) {
    if (o === null || o === undefined) return "null";
    if (Array.isArray(o)) return "[" + o.map(canonical).join(",") + "]";
    if (typeof o === "object") {
      return "{" + Object.keys(o).sort().map((k) => JSON.stringify(k) + ":" + canonical(o[k])).join(",") + "}";
    }
    return JSON.stringify(o);
  }
  // Pretty form, matching Python json.dumps(sort_keys=True, ensure_ascii=False) one line per event.
  function pretty(o) {
    if (o === null || o === undefined) return "null";
    if (Array.isArray(o)) return "[" + o.map(pretty).join(", ") + "]";
    if (typeof o === "object") {
      return "{" + Object.keys(o).sort().map((k) => JSON.stringify(k) + ": " + pretty(o[k])).join(", ") + "}";
    }
    return JSON.stringify(o);
  }
  const GENESIS = "0".repeat(64);
  const EVENT_TYPES = ["ai_output", "review", "promote", "reject", "correction", "endorsement", "model_change"];
  function eventHash(e) {
    const body = {};
    for (const k of Object.keys(e)) if (k !== "hash") body[k] = e[k];
    return sha256(canonical(body));
  }
  function nowIso() {
    return new Date().toISOString();
  }
  function clone(o) {
    return JSON.parse(JSON.stringify(o));
  }
  function secondsBetween(a, b) {
    return Math.round(((Date.parse(b) - Date.parse(a)) / 1000) * 1000) / 1000;
  }

  // ---- Ledger -----------------------------------------------------------------
  class Ledger {
    constructor(events) {
      this.events = events ? clone(events) : [];
    }
    get length() { return this.events.length; }
    get headHash() { return this.events.length ? this.events[this.events.length - 1].hash : GENESIS; }
    get(seq) { return this.events.find((e) => e.seq === seq) || null; }
    append(event_type, { study_id, record_ref, field, agent, payload, ts }) {
      if (!EVENT_TYPES.includes(event_type)) throw new Error("unknown event_type " + event_type);
      if (!["model", "human", "system"].includes(agent && agent.kind)) throw new Error("bad agent.kind");
      if (!agent.id) throw new Error("agent.id is required");
      const last = this.events[this.events.length - 1];
      const event = {
        seq: (last ? last.seq : 0) + 1,
        ts: ts || nowIso(),
        event_type, study_id, record_ref,
        field: field === undefined ? null : field,
        agent, payload,
        prev_hash: last ? last.hash : GENESIS,
      };
      event.hash = eventHash(event);
      this.events.push(event);
      return event;
    }
    verify() { return verifyEvents(this.events); }
    tamper(seq, path, value, rehash) {
      const e = this.get(seq);
      if (!e) throw new Error("no event with seq " + seq);
      const before = clone(e);
      const parts = path.split(".");
      let cur = e;
      for (const p of parts.slice(0, -1)) { if (cur[p] === undefined || cur[p] === null) cur[p] = {}; cur = cur[p]; }
      cur[parts[parts.length - 1]] = value;
      if (rehash) e.hash = eventHash(e);
      return [before, clone(e)];
    }
    toJSONL() { return this.events.map(pretty).join("\n") + "\n"; }
  }
  function verifyEvents(events) {
    let prev = GENESIS;
    for (let i = 0; i < events.length; i++) {
      const e = events[i], expected = i + 1;
      const fail = (seq, reason) => ({ ok: false, event_count: events.length, head_hash: prev, first_broken_seq: seq, reason, text: "BROKEN at seq " + seq + ": " + reason });
      if (e.seq !== expected) return fail(expected, "expected seq " + expected + ", found " + e.seq);
      if (e.prev_hash !== prev) return fail(e.seq, "prev_hash does not match the preceding event");
      if (eventHash(e) !== e.hash) return fail(e.seq, "stored hash does not match event content");
      prev = e.hash;
    }
    return { ok: true, event_count: events.length, head_hash: prev, first_broken_seq: null, reason: "chain intact", text: "OK: " + events.length + " events, head " + prev.slice(0, 16) + "…" };
  }

  // ---- Adapters ----------------------------------------------------------------
  function inputsHash(record, fields) {
    const sub = {};
    for (const f of fields) sub[f] = record[f] === undefined ? null : record[f];
    return sha256(canonical(sub));
  }
  function normalise(text) {
    return String(text || "").toLowerCase().trim().replace(/[^a-z0-9/ ]+/g, " ").replace(/\s+/g, " ").trim();
  }
  function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
  class StubCoder {
    constructor(spec, version) {
      this.model_id = "stub-coder";
      this.model_version = version || "1.0.0";
      this.prompt_hash = sha256(spec.prompt_template);
      this.dictionary = spec.dictionary;
      this.input_fields = spec.input_fields;
      this.keys = Object.keys(spec.dictionary).sort((a, b) => b.length - a.length);
    }
    run(record) {
      const norm = normalise(record.AETERM);
      const ih = inputsHash(record, this.input_fields);
      const hits = this.keys.filter((k) => new RegExp("\\b" + escapeRe(k) + "\\b").test(norm));
      if (hits.length) {
        const term = this.dictionary[hits[0]];
        const others = [...new Set(hits.slice(1).map((h) => this.dictionary[h]))].filter((t) => t !== term).sort();
        if (others.length) {
          return { value: term, confidence: 0.62, rationale: "verbatim mentions more than one event (" + term + "; also " + others.join(", ") + "); coded the first and recommend splitting", inputs_hash: ih };
        }
        return { value: term, confidence: hits[0] === norm ? 0.96 : 0.88, rationale: "dictionary match on '" + hits[0] + "'", inputs_hash: ih };
      }
      return { value: null, confidence: 0, rationale: "no match; needs manual coding", inputs_hash: ih };
    }
  }
  class StubQueryGen {
    constructor(spec) {
      this.model_id = "stub-querygen";
      this.model_version = "1.0.0";
      this.prompt_hash = sha256(spec.prompt_template);
      this.input_fields = spec.input_fields;
    }
    run(r) {
      const ih = inputsHash(r, this.input_fields);
      const start = r.AESTDTC || "", end = r.AEENDTC || "";
      if (start && end && end < start) return { value: "AE end date " + end + " is before start date " + start + ". Please confirm both dates.", confidence: 1, rationale: "rule: end-before-start", inputs_hash: ih };
      if (String(r.AESER || "").toUpperCase() === "Y" && !String(r.AESEV || "").trim()) return { value: "Event is marked serious but severity is blank. Please provide AESEV.", confidence: 1, rationale: "rule: serious-without-severity", inputs_hash: ih };
      const consent = r.RFICDTC || "";
      if (start && consent && start < consent) return { value: "AE start date " + start + " is before informed consent " + consent + ". Please confirm the date or document as medical history.", confidence: 1, rationale: "rule: ae-before-consent", inputs_hash: ih };
      return { value: null, confidence: 1, rationale: "no query", inputs_hash: ih };
    }
  }

  // ---- Gate --------------------------------------------------------------------
  class GateError extends Error {}
  function agentOf(reviewer) {
    return { kind: "human", id: reviewer.id, version: null, credential: reviewer.credential || "" };
  }
  class Gate {
    constructor(ledger, study_id, store) {
      this.ledger = ledger; this.study_id = study_id; this.store = store || null;
    }
    _for(ref, field) { return this.ledger.events.filter((e) => e.record_ref === ref && (field == null || e.field === field)); }
    latestOutput(ref, field) { const o = this._for(ref, field).filter((e) => e.event_type === "ai_output"); return o.length ? o[o.length - 1] : null; }
    reviewFor(output) { const r = this._for(output.record_ref, output.field).filter((e) => e.event_type === "review" && e.seq > output.seq); return r.length ? r[r.length - 1] : null; }
    status(ref, field) {
      const out = this.latestOutput(ref, field);
      if (!out) return "NONE";
      const later = this._for(ref, field).filter((e) => e.seq > out.seq).map((e) => e.event_type);
      if (later.includes("promote")) return "PROMOTED";
      if (later.includes("reject")) return "REJECTED";
      if (later.includes("review")) return "REVIEWED";
      return "QUARANTINED";
    }
    quarantine(adapter, ref, field, record, ts) {
      const out = adapter.run(record);
      return this.ledger.append("ai_output", {
        study_id: this.study_id, record_ref: ref, field,
        agent: { kind: "model", id: adapter.model_id, version: adapter.model_version, credential: null },
        payload: { value: out.value, confidence: out.confidence, rationale: out.rationale, inputs_hash: out.inputs_hash, prompt_hash: adapter.prompt_hash, status: "QUARANTINED" },
        ts,
      });
    }
    review(ref, field, reviewer, decision, opts) {
      opts = opts || {};
      if (!["approve", "edit", "reject"].includes(decision)) throw new GateError("decision must be approve, edit or reject");
      const out = this.latestOutput(ref, field);
      if (!out) throw new GateError("nothing to review: no ai_output for " + ref + " " + field);
      const st = this.status(ref, field);
      if (st === "PROMOTED" || st === "REJECTED") throw new GateError(ref + " " + field + " is already " + st + "; use a correction");
      if (decision === "edit" && !opts.edited_value) throw new GateError("decision 'edit' requires an edited value");
      if (!reviewer.display_name) throw new GateError("signature manifestation requires the reviewer's printed name");
      const ts = opts.ts || nowIso();
      let secs = opts.review_seconds;
      if (secs === undefined || secs === null) secs = secondsBetween(out.ts, ts);
      const meaning = { approve: "Approved for promotion to " + field, edit: "Edited and approved for promotion to " + field, reject: "Rejected; not to be promoted to " + field }[decision];
      return this.ledger.append("review", {
        study_id: this.study_id, record_ref: ref, field, agent: agentOf(reviewer), ts,
        payload: { decision, reviewed_seq: out.seq, proposed_value: out.payload.value, edited_value: decision === "edit" ? opts.edited_value : null, review_seconds: secs, note: opts.note || null, signature: { printed_name: reviewer.display_name, signed_at: ts, meaning } },
      });
    }
    promote(ref, field, opts) {
      opts = opts || {};
      const out = this.latestOutput(ref, field);
      if (!out) throw new GateError("nothing to promote: no ai_output for " + ref + " " + field);
      if (this.status(ref, field) === "PROMOTED") throw new GateError(ref + " " + field + " is already promoted");
      const review = this.reviewFor(out);
      const approving = review && ["approve", "edit"].includes(review.payload.decision);
      if (!approving && !opts.force) throw new GateError(ref + " " + field + " has no approving review (seq " + out.seq + " is " + this.status(ref, field) + "); the gate refuses. Force it and EX-01 will flag it.");
      const value = approving && review.payload.decision === "edit" ? review.payload.edited_value : out.payload.value;
      const agent = approving ? { kind: "human", id: review.agent.id, version: null, credential: review.agent.credential } : { kind: "system", id: "aievidence-gate", version: null, credential: null };
      const ev = this.ledger.append("promote", { study_id: this.study_id, record_ref: ref, field, agent, ts: opts.ts, payload: { value, source_seq: out.seq, review_seq: approving ? review.seq : null, forced: !approving } });
      if (this.store) this.store.apply(ref, field, value, ev.seq);
      return ev;
    }
    reject(ref, field, opts) {
      opts = opts || {};
      const out = this.latestOutput(ref, field);
      if (!out) throw new GateError("nothing to reject");
      const review = this.reviewFor(out);
      if (!review || review.payload.decision !== "reject") throw new GateError("reject requires a review with decision 'reject'");
      return this.ledger.append("reject", { study_id: this.study_id, record_ref: ref, field, ts: opts.ts, agent: { kind: "human", id: review.agent.id, version: null, credential: review.agent.credential }, payload: { source_seq: out.seq, review_seq: review.seq, note: review.payload.note || null } });
    }
    endorse(ref, investigator, ts) {
      ts = ts || nowIso();
      return this.ledger.append("endorsement", { study_id: this.study_id, record_ref: ref, field: null, agent: agentOf(investigator), ts, payload: { scope: "record", signature: { printed_name: investigator.display_name, signed_at: ts, meaning: "Investigator endorsement of reported data for " + ref } } });
    }
    correct(ref, field, new_value, by, reason, ts) {
      const prior = this._for(ref, field).filter((e) => e.event_type === "promote" || e.event_type === "correction");
      if (!prior.length) throw new GateError("nothing to correct: " + ref + " " + field + " was never promoted");
      const sup = prior[prior.length - 1];
      const ev = this.ledger.append("correction", { study_id: this.study_id, record_ref: ref, field, agent: agentOf(by), ts, payload: { value: new_value, previous_value: sup.payload.value, supersedes_seq: sup.seq, reason } });
      if (this.store) this.store.apply(ref, field, new_value, ev.seq);
      return ev;
    }
    declareModelChange(model_id, old_version, new_version, by, reason, ts) {
      return this.ledger.append("model_change", { study_id: this.study_id, record_ref: "MODEL:" + model_id, field: null, agent: agentOf(by), ts, payload: { model_id, old_version, new_version, reason } });
    }
  }

  // ---- Dataset store (in memory) --------------------------------------------------
  class MemoryStore {
    constructor(data) { this.ae = data.ae; this.cm = data.cm; this.dm = data.dm; this.queries = data.queries || []; }
    apply(ref, field, value, seq) {
      const [domain, usubjid, rseq] = ref.split(":");
      if (field === "QUERY") { this.queries.push({ record_ref: ref, query_text: value, ledger_seq: seq }); return; }
      const rows = { AE: this.ae, CM: this.cm, DM: this.dm }[domain] || [];
      const seqCol = { AE: "AESEQ", CM: "CMSEQ" }[domain];
      const row = rows.find((r) => r.USUBJID === usubjid && (!seqCol || rseq == null || String(r[seqCol]) === String(rseq)));
      if (row) row[field] = value == null ? "" : String(value);
    }
  }

  // ---- Rules ------------------------------------------------------------------------
  const SEV = { critical: 0, major: 1, minor: 2 };
  function fmt(tpl, vars) { return tpl.replace(/\{(\w+)\}/g, (_, k) => (vars[k] === undefined ? "{" + k + "}" : vars[k])); }
  function evaluate(events, profile, reviewersById, vr) {
    vr = vr || verifyEvents(events);
    const F = (id, ref, seq, vars) => { const s = profile.rules[id]; return { id, name: s.name, record_ref: ref, seq, severity: s.severity, citation: s.citation, explanation: fmt(s.explanation, Object.assign({ seq, record_ref: ref }, vars)) }; };
    const by = (t) => events.filter((e) => e.event_type === t);
    const out = [];
    const R = {
      "EX-01": () => by("promote").forEach((p) => {
        const outs = events.filter((e) => e.event_type === "ai_output" && e.record_ref === p.record_ref && e.field === p.field && e.seq < p.seq);
        const src = outs.length ? outs[outs.length - 1].seq : 0;
        const ok = events.some((e) => e.event_type === "review" && e.record_ref === p.record_ref && e.field === p.field && e.seq > src && e.seq < p.seq && ["approve", "edit"].includes(e.payload.decision));
        if (!ok) out.push(F("EX-01", p.record_ref, p.seq, { field: p.field }));
      }),
      "EX-02": () => { const th = Number((profile.thresholds || {}).rubber_stamp_seconds || 5); by("review").forEach((r) => { const s = r.payload.review_seconds; if (s != null && Number(s) < th) out.push(F("EX-02", r.record_ref, r.seq, { reviewer: r.agent.id, review_seconds: s, threshold: th })); }); },
      "EX-03": () => { const declared = {}; events.forEach((e) => { if (e.event_type === "model_change") declared[e.payload.model_id] = e.payload.new_version; else if (e.event_type === "ai_output") { const m = e.agent.id, v = e.agent.version; if (!(m in declared)) declared[m] = v; else if (v !== declared[m]) out.push(F("EX-03", e.record_ref, e.seq, { model_id: m, version: v, declared: declared[m] })); } }); },
      "EX-04": () => { const end = {}; by("endorsement").forEach((e) => (end[e.record_ref] = end[e.record_ref] || []).push(e.seq)); events.forEach((e) => { if (e.event_type !== "promote" && e.event_type !== "correction") return; const seqs = end[e.record_ref] || []; const before = seqs.filter((s) => s < e.seq), after = seqs.filter((s) => s > e.seq); if (before.length && !after.length) out.push(F("EX-04", e.record_ref, e.seq, { event_type: e.event_type, endorsed_seq: before[before.length - 1] })); }); },
      "EX-05": () => by("review").forEach((r) => { const rid = r.agent.id || "", cred = String(r.agent.credential || "").trim(); let problem = null; if (reviewersById && !(rid in reviewersById)) problem = "is not in the reviewer directory"; else if (!cred) problem = "has no credential recorded"; else if (reviewersById && String(reviewersById[rid].credential || "").trim() !== cred) problem = "signed with a credential that does not match the reviewer directory"; if (problem) out.push(F("EX-05", r.record_ref, r.seq, { reviewer: rid || "(no id)", problem })); }),
      "EX-06": () => { const req = profile.required_ai_output_fields || []; by("ai_output").forEach((e) => { const present = { inputs_hash: e.payload.inputs_hash, prompt_hash: e.payload.prompt_hash, model_id: e.agent.id, model_version: e.agent.version }; const missing = req.filter((f) => !present[f]); if (missing.length) out.push(F("EX-06", e.record_ref, e.seq, { missing: missing.join(", ") })); }); },
      "EX-07": () => { if (!vr.ok) out.push(F("EX-07", "LEDGER", vr.first_broken_seq || 0, { reason: vr.reason })); },
    };
    for (const id of Object.keys(profile.rules)) if (R[id]) R[id]();
    return out.sort((a, b) => (SEV[a.severity] - SEV[b.severity]) || a.id.localeCompare(b.id) || a.seq - b.seq);
  }

  // ---- Ask ------------------------------------------------------------------------------
  function who(e) {
    const a = e.agent;
    if (a.kind === "model") return "model " + a.id + " v" + a.version;
    if (a.kind === "human") return a.id + " (" + (a.credential || "NO CREDENTIAL") + ")";
    return "system " + a.id;
  }
  function what(e) {
    const p = e.payload, t = e.event_type, f = e.field;
    const q = (v) => (v === null || v === undefined ? "None" : typeof v === "string" ? "'" + v + "'" : String(v));
    if (t === "ai_output") {
      let s = "proposed " + f + " = " + q(p.value) + (typeof p.confidence === "number" ? " (confidence " + p.confidence.toFixed(2) + ")" : "");
      if (p.rationale) s += "; rationale: " + p.rationale;
      s += "; inputs_hash " + String(p.inputs_hash || "?").slice(0, 12) + "…, prompt_hash " + String(p.prompt_hash || "?").slice(0, 12) + "…";
      return s + " -> QUARANTINED";
    }
    if (t === "review") { const sig = p.signature || {}; let s = p.decision.toUpperCase() + " after " + p.review_seconds + "s; signed '" + sig.meaning + "' by " + sig.printed_name; if (p.edited_value != null) s += "; edited to " + q(p.edited_value); if (p.note) s += "; note: " + p.note; return s; }
    if (t === "promote") return "wrote " + f + " = " + q(p.value) + " to the dataset" + (p.forced ? " WITHOUT A REVIEW (forced)" : " (review seq " + p.review_seq + ")");
    if (t === "reject") return "rejected " + f + "; value not written (review seq " + p.review_seq + ")";
    if (t === "correction") return "corrected " + f + " from " + q(p.previous_value) + " to " + q(p.value) + ", supersedes seq " + p.supersedes_seq + ": " + p.reason;
    if (t === "endorsement") return "investigator endorsement: '" + (p.signature || {}).meaning + "'";
    if (t === "model_change") return "declared " + p.model_id + " " + p.old_version + " -> " + p.new_version + ": " + p.reason;
    return JSON.stringify(p);
  }
  function chain(events, ref, field) {
    const sel = events.filter((e) => e.record_ref === ref && (field == null || e.field === field));
    const lines = sel.map((e) => ({ seq: e.seq, ts: e.ts, kind: e.event_type, who: who(e), what: what(e) }));
    const status = {}, verdicts = [];
    const fields = [...new Set(sel.filter((e) => e.field).map((e) => e.field))].sort();
    for (const f of fields) {
      const fe = sel.filter((e) => e.field === f);
      const outs = fe.filter((e) => e.event_type === "ai_output");
      if (!outs.length) { status[f] = "NONE"; continue; }
      const last = outs[outs.length - 1];
      const later = fe.filter((e) => e.seq > last.seq).map((e) => e.event_type);
      if (later.includes("promote")) {
        status[f] = "PROMOTED";
        const promo = fe.find((e) => e.event_type === "promote" && e.seq > last.seq);
        const reviews = fe.filter((e) => e.event_type === "review" && e.seq > last.seq && e.seq < promo.seq);
        if (!reviews.some((r) => ["approve", "edit"].includes(r.payload.decision))) verdicts.push(f + ": PROMOTED WITHOUT REVIEW at seq " + promo.seq + ". No human signed this value.");
        else { const r = reviews[reviews.length - 1]; verdicts.push(f + ": promoted at seq " + promo.seq + " after " + r.agent.id + " signed at seq " + r.seq + " (" + r.payload.decision + ", " + r.payload.review_seconds + "s)."); }
      } else if (later.includes("reject")) { status[f] = "REJECTED"; verdicts.push(f + ": rejected; the AI value was never written."); }
      else if (later.includes("review")) { status[f] = "REVIEWED"; verdicts.push(f + ": reviewed, not yet promoted."); }
      else { status[f] = "QUARANTINED"; verdicts.push(f + ": AI output at seq " + last.seq + " is still in quarantine; no human has looked at it."); }
    }
    const endorsed = sel.filter((e) => e.event_type === "endorsement");
    if (endorsed.length) verdicts.push("Investigator endorsed this record at seq " + endorsed[endorsed.length - 1].seq + ".");
    return { record_ref: ref, lines, status_by_field: status, verdicts };
  }
  function renderChain(c) {
    const out = ["Record " + c.record_ref + ": " + c.lines.length + " events"];
    for (const l of c.lines) { out.push("  seq " + String(l.seq).padStart(4) + "  " + l.ts + "  " + l.kind.padEnd(12) + " " + l.who); out.push("            " + l.what); }
    out.push("");
    for (const f of Object.keys(c.status_by_field)) out.push("  " + f + ": " + c.status_by_field[f]);
    for (const v of c.verdicts) out.push("  * " + v);
    return out.join("\n");
  }

  // ---- Scenario -------------------------------------------------------------------------
  function mulberry32(seed) { let a = seed >>> 0; return function () { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  function clock(start) { let t = Date.parse(start); return { tick(s) { t += s * 1000; return new Date(t).toISOString(); } }; }
  const EDITS = {
    "AE:AIEV-001-1017:1": ["Vomiting", "Verbatim bundles nausea and vomiting; vomiting is the reportable event."],
    "AE:AIEV-001-1023:1": ["Alanine aminotransferase increased", "Lab line shows ALT only; use the specific term."],
  };
  /** Re-run the planted scenario over the embedded study. Returns {ledger, store, summary}. */
  function runScenario(data, plants, opts) {
    opts = opts || {};
    const rng = mulberry32(opts.seed || 7);
    const randint = (a, b) => a + Math.floor(rng() * (b - a + 1));
    const store = new MemoryStore({ ae: clone(data.ae).map((r) => Object.assign(r, { AEDECOD: "" })), cm: clone(data.cm), dm: clone(data.dm), queries: [] });
    const ledger = new Ledger([]);
    const gate = new Gate(ledger, data.study_id, store);
    const R = Object.fromEntries(data.reviewers.map((r) => [r.id, r]));
    const rmehta = R.rmehta, jokafor = R.jokafor, pi = R.pi_site01;
    const coder = new StubCoder(data.adapters.stub_coder, "1.0.0");
    const querygen = new StubQueryGen(data.adapters.stub_querygen);
    const clk = clock(opts.clock_start || "2026-09-14T09:00:00Z");
    let ai_outputs = 0, reviewed = 0, promoted = 0, pending = 0;
    store.ae.forEach((ae, i) => {
      if (i === plants.version_bump_after) {
        if (plants.declare_change) gate.declareModelChange("stub-coder", coder.model_version, plants.version_bump_to, rmehta, "revalidated dictionary; change controlled", clk.tick(600));
        coder.model_version = plants.version_bump_to;
      }
      const ref = "AE:" + ae.USUBJID + ":" + ae.AESEQ;
      gate.quarantine(coder, ref, "AEDECOD", ae, clk.tick(randint(30, 240)));
      ai_outputs++;
      if (ref === plants.unreviewed_promotion) { gate.promote(ref, "AEDECOD", { force: true, ts: clk.tick(45) }); promoted++; return; }
      if ((plants.leave_pending || []).includes(ref)) { pending++; return; }
      const reviewer = i % 2 === 0 ? rmehta : jokafor;
      const secs = ref === plants.rubber_stamp_record ? plants.rubber_stamp_seconds : randint(40, 300);
      const edit = EDITS[ref];
      if (edit) gate.review(ref, "AEDECOD", reviewer, "edit", { edited_value: edit[0], note: edit[1], review_seconds: secs, ts: clk.tick(secs) });
      else gate.review(ref, "AEDECOD", reviewer, "approve", { review_seconds: secs, ts: clk.tick(secs) });
      reviewed++;
      gate.promote(ref, "AEDECOD", { ts: clk.tick(5) }); promoted++;
    });
    for (const ae of store.ae) {
      const dm = store.dm.find((d) => d.USUBJID === ae.USUBJID) || {};
      const rec = Object.assign({}, ae, { RFICDTC: dm.RFICDTC });
      if (querygen.run(rec).value === null) continue;
      const ref = "AE:" + ae.USUBJID + ":" + ae.AESEQ;
      gate.quarantine(querygen, ref, "QUERY", rec, clk.tick(randint(30, 120))); ai_outputs++;
      const secs = randint(60, 180);
      gate.review(ref, "QUERY", rmehta, "approve", { review_seconds: secs, ts: clk.tick(secs) }); reviewed++;
      gate.promote(ref, "QUERY", { ts: clk.tick(5) }); promoted++;
    }
    for (const ref of plants.endorse || []) gate.endorse(ref, pi, clk.tick(3600));
    return { ledger, store, summary: { events: ledger.length, ai_outputs, reviewed, promoted, pending } };
  }

  return { sha256, canonical, pretty, eventHash, GENESIS, nowIso, Ledger, verifyEvents, Gate, GateError, MemoryStore, StubCoder, StubQueryGen, inputsHash, evaluate, chain, renderChain, runScenario, clone };
});
