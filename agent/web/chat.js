const form = document.querySelector("#chat-form");
const input = document.querySelector("#question");
const send = document.querySelector("#send");
const messages = document.querySelector("#messages");
const status = document.querySelector("#status");
const examples = document.querySelector("#examples");
const toolTrace = document.querySelector("#trace-content");
const dialogueTrace = document.querySelector("#dialogue-content");
const traceViews = document.querySelector(".trace-views");
const modeLabel = document.querySelector("#model-mode");
const modeInfo = document.querySelector("#mode-info");
const modeBadge = document.querySelector("#mode-badge");
const loginView = document.querySelector("#login-view");
const chatView = document.querySelector("#chat-view");
const loginForm = document.querySelector("#login-form");
const loginUsername = document.querySelector("#login-username");
const loginPassword = document.querySelector("#login-password");
const loginButton = document.querySelector("#login-button");
const loginStatus = document.querySelector("#login-status");
const logout = document.querySelector("#logout");
const operatorView = document.querySelector("#operator-view");
const operatorForm = document.querySelector("#operator-form");
const operatorFields = document.querySelector("#operator-fields");
const operatorKind = document.querySelector("#operator-kind");
const usageFields = document.querySelector("#usage-fields");
const operatorStatus = document.querySelector("#operator-form-status");
const operatorPreview = document.querySelector("#operator-preview");
const operatorSummary = document.querySelector("#operator-preview-summary");
const operatorConfirm = document.querySelector("#operator-confirm");
const operatorResult = document.querySelector("#operator-result");
const demoIntro = modeInfo.textContent;

let token;
let pending = false;
let operatorDraft;

const usd = new Intl.NumberFormat("tr-TR", { style: "currency", currency: "USD" });
const billingMonth = new Intl.DateTimeFormat("tr-TR", {
  month: "long", year: "numeric", timeZone: "UTC",
});

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function setStatus(text, error = false) {
  status.textContent = text;
  status.dataset.error = String(error);
}

function syncControls() {
  send.disabled = pending || !token;
  examples.querySelectorAll("button").forEach((button) => {
    button.disabled = pending || !token;
  });
}

function addMessage(text, user = false) {
  const message = element("article", user ? "message message-user" : "message");
  message.append(
    element("span", "speaker", user ? "Sen" : "Fatura asistanı"),
    element("p", "", text),
  );
  messages.append(message);
  messages.scrollTop = messages.scrollHeight;
  return message;
}

function showPaymentApproval(message, payment) {
  const date = new Date(0);
  date.setUTCFullYear(payment.year, payment.month - 1, 1);
  const card = element("section", "payment-card");
  card.setAttribute("aria-label", "Simüle ödeme onayı");
  const summary = element("div", "payment-summary");
  const period = element("div");
  period.append(
    element("h3", "", "Simüle ödeme"),
    element("p", "payment-period", billingMonth.format(date) + " faturası"),
  );
  summary.append(period, element("strong", "payment-amount", usd.format(payment.amount)));

  const button = element("button", "payment-confirm", "Ödemeyi onayla");
  button.type = "button";
  const feedback = element("p", "payment-feedback", "Onay 5 dakika geçerli.");
  feedback.setAttribute("role", "status");
  button.addEventListener("click", () => void confirmPayment(payment.confirmation_id, button, feedback));

  card.append(summary, button, feedback);
  message.append(card);
  messages.scrollTop = messages.scrollHeight;
}

async function confirmPayment(confirmationId, button, feedback) {
  if (button.disabled || !token) return;
  const sessionToken = token;
  button.disabled = true;
  feedback.dataset.error = "false";
  feedback.textContent = "Ödeme onaylanıyor…";

  try {
    const reply = await postChat(
      "/api/v1/chat/payments/confirm", { confirmation_id: confirmationId }, sessionToken,
    );
    if (token !== sessionToken) return;
    if (reply.status === 401) {
      endSession("Oturumun süresi doldu. Tekrar giriş yap.");
      return;
    }
    if (reply.status === 404 || reply.status === 409) {
      button.textContent = "Onay kullanılamıyor";
      feedback.dataset.error = "true";
      feedback.textContent = reply.status === 404
        ? "Onay süresi dolmuş veya işlem bulunamadı. Yeni bir ödeme isteği yaz."
        : "Onay kullanılamadı. Sonucu görmek için faturayı tekrar sorgula.";
      return;
    }
    if (!reply.ok) throw new Error("Payment result unavailable");
    const receipt = await reply.json();
    if (token !== sessionToken) return;
    button.textContent = "Onaylandı";
    feedback.textContent = usd.format(receipt.paidAmount)
      + " ödeme kaydedildi. Kalan bakiye " + usd.format(receipt.remainingBalance) + ".";
  } catch {
    if (token !== sessionToken) return;
    button.disabled = false;
    feedback.dataset.error = "true";
    feedback.textContent = "Ödeme sonucu alınamadı. Aynı onayı yeniden dene.";
  }
  messages.scrollTop = messages.scrollHeight;
}

function traceRow(label, title, fields, showCode = false) {
  const item = element("li");
  const details = element("details", "trace-item");
  const summary = element("summary");
  summary.append(
    element("span", "trace-label", label),
    element(showCode ? "code" : "span", "trace-title-line", title),
  );
  const body = element("div", "trace-body");
  fields.forEach(([field, value]) => {
    body.append(element("h3", "", field), element("pre", "", JSON.stringify(value, null, 2)));
  });
  details.append(summary, body);
  item.append(details);
  return item;
}

function renderTrace(panel, rows, emptyMessage) {
  if (!rows.length) {
    panel.replaceChildren(element("p", "trace-empty", emptyMessage));
    return;
  }
  const list = element("ol", "trace-list");
  list.append(...rows);
  panel.replaceChildren(list);
}

function showToolTrace(calls) {
  const rows = calls.map((call, index) => {
    const sources = {
      search_billing_documentation: "MCP",
      prepare_bill_payment: "Ödeme hazırlığı",
    };
    const source = sources[call.name] ?? "Billing REST API";
    return traceRow(String(index + 1) + ". " + source, call.name, [
      ["Girdi", call.arguments], ["Sonuç", call.result],
    ], true);
  });
  renderTrace(toolTrace, rows, "Bu soru için tool çağrısı yapılmadı.");
}

function summarizeResult(result) {
  if (result.error) return result.error;
  if (result.status === "awaiting_confirmation") return "Ödeme onayı bekleniyor";
  if (result.internetGb !== undefined) {
    const charge = result.chargeBreakdown.find((line) => line.type === "internet");
    if (charge) return Number(result.internetGb) + " GB kullanım, $" + charge.amount + " internet ücreti";
  }
  if (result.total !== undefined) return "$" + result.total + " fatura tutarı";
  if (result.passages) {
    const sections = result.passages.map((passage) => "§" + passage.section);
    return sections.length ? "Rehber bölümleri " + sections.join(", ") : "Arama sonucu bulunamadı";
  }
  return "Tool sonucu";
}

function showDialogue(steps) {
  const rows = steps.map(({ kind, payload }, index) => {
    const number = String(index + 1) + ". ";
    if (kind === "request") {
      return traceRow(number + "Agent → LLM", "Soru ve " + payload.tools.length + " tool",
        [["Mesaj", payload]]);
    }
    if (kind === "tool_call") {
      return traceRow(number + "LLM → Agent", payload.name, [["Tool isteği", payload]], true);
    }
    if (kind === "tool_result") {
      return traceRow(number + "Agent → LLM", summarizeResult(payload.result), [["Tool sonucu", payload]]);
    }
    return traceRow(number + "LLM → Agent", "Son yanıt", [["Yanıt", payload]]);
  });
  renderTrace(dialogueTrace, rows, "Bu soru için Agent ↔ LLM akışı alınamadı.");
}

function setTraceMessage(message) {
  renderTrace(toolTrace, [], message);
  renderTrace(dialogueTrace, [], message);
}

traceViews.addEventListener("click", (event) => {
  const selected = event.target.closest("button");
  if (!selected) return;
  traceViews.querySelectorAll("button").forEach((button) => {
    const active = button === selected;
    button.setAttribute("aria-pressed", String(active));
    document.getElementById(button.getAttribute("aria-controls")).hidden = !active;
  });
});

function startSession(session) {
  token = session.token;
  const live = session.mode === "live";
  const isOperator = session.role === "operator";
  modeLabel.textContent = live ? "Canlı OpenAI" : "Yerel demo";
  modeInfo.textContent = live
    ? "Faturanı kendi cümlenle sor. Gönderdiğin sorular OpenAI API kullanır."
    : demoIntro;
  examples.replaceChildren(...session.examples.map((example) => {
    const button = element("button", "example");
    button.type = "button";
    button.append(element("span", "", example.source), document.createTextNode(example.question));
    button.addEventListener("click", () => void ask(example.question));
    return button;
  }));
  loginView.hidden = true;
  chatView.hidden = isOperator;
  operatorView.hidden = !isOperator;
  modeBadge.hidden = isOperator;
  logout.hidden = false;
  syncControls();
  (isOperator ? operatorKind : input).focus();
}

function endSession(message) {
  token = undefined;
  pending = false;
  input.value = "";
  messages.replaceChildren();
  examples.replaceChildren();
  setStatus("");
  setTraceMessage("Bir soru gönderdiğinde Agent akışı burada görünecek.");
  chatView.hidden = true;
  operatorView.hidden = true;
  operatorForm.reset();
  operatorFields.disabled = false;
  resetOperatorPreview();
  modeBadge.hidden = true;
  logout.hidden = true;
  loginView.hidden = false;
  loginStatus.textContent = message;
  loginStatus.dataset.error = String(Boolean(message));
  syncControls();
  loginUsername.focus();
}

function resetOperatorPreview() {
  operatorDraft = undefined;
  operatorPreview.hidden = true;
  operatorConfirm.disabled = false;
  operatorConfirm.textContent = "Onayla ve uygula";
  operatorStatus.textContent = "";
  operatorStatus.dataset.error = "false";
  usageFields.hidden = operatorKind.value !== "add_usage";
}

operatorForm.addEventListener("input", resetOperatorPreview);
operatorForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!token || operatorFields.disabled) return;
  const sessionToken = token;
  const fields = new FormData(operatorForm);
  const kind = fields.get("kind");
  const billing = {
    subscriberNo: fields.get("subscriberNo").trim(),
    year: Number(fields.get("year")),
    month: Number(fields.get("month")),
  };
  if (!billing.subscriberNo) {
    operatorStatus.textContent = "Abone numarasını gir.";
    operatorStatus.dataset.error = "true";
    return;
  }
  if (kind === "add_usage") billing.usageType = fields.get("usageType");

  resetOperatorPreview();
  operatorFields.disabled = true;
  try {
    const reply = await postChat("/api/v1/operator/operations/prepare", { kind, billing }, sessionToken);
    if (token !== sessionToken) return;
    if (reply.status === 401) {
      endSession("Oturumun süresi doldu. Tekrar giriş yap.");
      return;
    }
    if (!reply.ok) throw new Error("Operation could not be prepared");

    const draft = await reply.json();
    if (token !== sessionToken) return;
    operatorDraft = draft;
    const target = draft.operation.billing;
    const date = new Date(0);
    date.setUTCFullYear(target.year, target.month - 1, 1);
    const action = draft.operation.kind === "calculate_bill"
      ? "Fatura hesaplanacak"
      : target.usageType === "Phone" ? "10 dakika telefon kullanımı eklenecek" : "1 MB internet kullanımı eklenecek";
    operatorSummary.textContent = action + ". Abone " + target.subscriberNo + ", " + billingMonth.format(date) + ".";
    operatorResult.textContent = "Onay 5 dakika geçerli.";
    operatorResult.dataset.error = "false";
    operatorPreview.hidden = false;
    operatorConfirm.focus();
  } catch {
    if (token !== sessionToken) return;
    operatorStatus.textContent = "İşlem hazırlanamadı. Bilgileri kontrol edip tekrar dene.";
    operatorStatus.dataset.error = "true";
  } finally {
    if (token === sessionToken) operatorFields.disabled = false;
  }
});

operatorConfirm.addEventListener("click", async () => {
  if (!token || !operatorDraft || operatorConfirm.disabled) return;
  const sessionToken = token;
  const draft = operatorDraft;
  operatorConfirm.disabled = true;
  operatorFields.disabled = true;
  operatorResult.textContent = "İşlem uygulanıyor…";

  try {
    const reply = await postChat(
      "/api/v1/operator/operations/confirm", { confirmation_id: draft.confirmation_id }, sessionToken,
    );
    if (token !== sessionToken) return;
    if (reply.status === 401) {
      endSession("Oturumun süresi doldu. Tekrar giriş yap.");
      return;
    }
    if (reply.status === 404) {
      const error = await reply.json();
      if (token !== sessionToken) return;
      operatorResult.dataset.error = "true";
      operatorResult.textContent = error.detail === "Subscriber not found"
        ? "Bu abone numarası bulunamadı." : "Onay süresi doldu veya işlem bulunamadı.";
      return;
    }
    if (!reply.ok) throw new Error("Operation result unavailable");
    operatorConfirm.textContent = "Onaylandı";
    operatorResult.textContent = draft.operation.kind === "add_usage" ? "Kullanım kaydedildi." : "Fatura hesaplandı ve kaydedildi.";
  } catch {
    if (token !== sessionToken) return;
    operatorResult.dataset.error = "true";
    operatorResult.textContent = "İşlemin sonucu doğrulanamadı.";
  } finally {
    if (token === sessionToken) operatorFields.disabled = false;
  }
});

function postChat(path, payload, sessionToken) {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + sessionToken },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
}

async function ask(question) {
  if (!question || pending || !token) return;
  const sessionToken = token;
  pending = true;
  syncControls();
  input.value = "";
  addMessage(question, true);
  setStatus("Soru işleniyor…");
  setTraceMessage("Agent yanıtı bekleniyor…");

  try {
    const reply = await postChat("/api/v1/chat", { question }, sessionToken);
    if (token !== sessionToken) return;
    if (reply.status === 401) {
      endSession("Oturumun süresi doldu. Tekrar giriş yap.");
      return;
    }
    if (!reply.ok) {
      const error = await reply.json().catch(() => null);
      const detail = error?.detail;
      if (typeof detail === "string" && detail.startsWith("OpenAI API")) {
        throw new Error(detail);
      }
      throw new Error("Chat yanıt veremedi. Yerel servisi kontrol edip tekrar dene.");
    }
    const result = await reply.json();
    if (token !== sessionToken) return;
    const message = addMessage(result.answer);
    if (result.pending_payment) showPaymentApproval(message, result.pending_payment);
    showToolTrace(result.tool_trace);
    showDialogue(result.dialogue ?? []);
    setStatus("");
  } catch (error) {
    if (token !== sessionToken) return;
    setStatus(error.message, true);
    setTraceMessage("Agent akışı alınamadı.");
    input.value = question;
  } finally {
    if (token === sessionToken) {
      pending = false;
      syncControls();
    }
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  void ask(input.value.trim());
});

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (loginButton.disabled) return;
  loginButton.disabled = true;
  loginStatus.textContent = "Bilgiler kontrol ediliyor…";
  loginStatus.dataset.error = "false";

  try {
    const body = JSON.stringify({
      username: loginUsername.value.trim(),
      password: loginPassword.value,
    });
    loginPassword.value = "";
    const reply = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      cache: "no-store",
    });
    if (reply.status === 401) {
      loginStatus.textContent = "Kullanıcı adı veya şifre hatalı.";
      loginStatus.dataset.error = "true";
      loginPassword.focus();
      return;
    }
    if (!reply.ok) throw new Error("Login unavailable");
    const session = await reply.json();
    loginStatus.textContent = "";
    startSession(session);
  } catch {
    loginStatus.textContent = "Demo oturumu açılamadı. Chat sunucusunu kontrol et.";
    loginStatus.dataset.error = "true";
  } finally {
    loginButton.disabled = false;
  }
});

logout.addEventListener("click", () => endSession(""));
