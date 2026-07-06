const ROLE = document.body.dataset.role;

// ---------- Onglets ----------
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "users") loadUsers();
    if (btn.dataset.tab === "admin-settings") loadAdminSettings();
    if (btn.dataset.tab === "training") loadNextTraining();
    if (btn.dataset.tab === "logs") loadLogHistory();
  });
});

// ---------- Statut de la base ----------
async function refreshStatus() {
  try {
    const r = await fetch("/api/status");
    if (r.status === 401) { window.location.href = "/login"; return; }
    const d = await r.json();
    document.getElementById("status").textContent = `${d.songs} morceaux · ${d.hashes} hash`;
  } catch (e) {
    document.getElementById("status").textContent = "serveur indisponible";
  }
}
refreshStatus();

// ---------- Enregistrement micro ----------
const recordBtn = document.getElementById("recordBtn");
const recordStatus = document.getElementById("recordStatus");
const resultsDiv = document.getElementById("results");

let mediaRecorder = null;
let chunks = [];
const RECORD_SECONDS = 10;

recordBtn.addEventListener("click", async () => {
  if (mediaRecorder && mediaRecorder.state === "recording") return;

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    chunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = e => chunks.push(e.data);
    mediaRecorder.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" });
      sendClip(blob);
    };

    mediaRecorder.start();
    recordBtn.classList.add("recording");
    recordBtn.textContent = "⏺ Enregistrement en cours...";

    let remaining = RECORD_SECONDS;
    recordStatus.textContent = `${remaining}s restantes`;
    const interval = setInterval(() => {
      remaining -= 1;
      recordStatus.textContent = `${remaining}s restantes`;
      if (remaining <= 0) {
        clearInterval(interval);
        if (mediaRecorder.state === "recording") mediaRecorder.stop();
        recordBtn.classList.remove("recording");
        recordBtn.textContent = "🎤 Enregistrer (10s)";
      }
    }, 1000);
  } catch (e) {
    recordStatus.textContent = "Impossible d'accéder au micro : " + e.message;
  }
});

async function sendClip(blob) {
  recordStatus.textContent = "Analyse en cours...";
  resultsDiv.innerHTML = "";

  const form = new FormData();
  form.append("audio", blob, "clip.webm");

  try {
    const r = await fetch("/api/identify", { method: "POST", body: form });
    const data = await r.json();
    if (data.error) {
      recordStatus.textContent = "Erreur : " + data.error;
      return;
    }
    recordStatus.textContent = data.results.length
      ? `${data.results.length} résultat(s)`
      : "Aucun match trouvé.";
    renderResults(data.results, resultsDiv, async (payload) => {
      await postConfirm(payload);
    });
  } catch (e) {
    recordStatus.textContent = "Erreur réseau : " + e.message;
  }
}

// ---------- Rendu générique des résultats (réutilisé par Identifier + Entraînement) ----------
function renderResults(results, container, onConfirm) {
  container.innerHTML = "";
  if (!results.length) {
    const card = document.createElement("div");
    card.className = "result-card";
    card.innerHTML = `
      <div class="result-title">Aucun match trouvé</div>
      <div class="result-actions">
        <button class="wrong-btn">Indiquer le bon morceau quand même</button>
      </div>
      <div class="correction-box"></div>`;
    container.appendChild(card);
    wireCard(card, null, onConfirm);
    return;
  }
  results.forEach((res, i) => {
    const card = document.createElement("div");
    card.className = "result-card";
    card.innerHTML = `
      <div class="result-title">${i + 1}. ${res.title}</div>
      <div class="result-meta">confiance = ${res.confidence} · début estimé = ${res.offset_sec}s</div>
      <div class="result-actions">
        <button class="confirm">✓ C'est le bon</button>
        <button class="wrong-btn">✗ Ce n'est pas ça</button>
      </div>
      <div class="correction-box"></div>
    `;
    container.appendChild(card);
    wireCard(card, res, onConfirm);
  });
}

function wireCard(card, predicted, onConfirm) {
  const confirmBtn = card.querySelector(".confirm");
  const wrongBtn = card.querySelector(".wrong-btn");
  const box = card.querySelector(".correction-box");

  if (confirmBtn) {
    confirmBtn.addEventListener("click", async () => {
      await onConfirm({
        predicted_song_id: predicted.song_id,
        predicted_title: predicted.title,
        confidence: predicted.confidence,
        correct_song_id: predicted.song_id,
        correct_title: predicted.title,
        was_correct: true,
      });
      card.parentElement.querySelectorAll(".result-actions").forEach(el => el.innerHTML = "");
      card.querySelector(".result-actions").innerHTML = "<em>Merci, enregistré ✔</em>";
    });
  }

  wrongBtn.addEventListener("click", () => {
    box.style.display = "block";
    box.innerHTML = `
      <input type="text" placeholder="Cherche le bon morceau par son titre..." class="search-input">
      <div class="correction-matches"></div>
    `;
    const input = box.querySelector(".search-input");
    const matchesDiv = box.querySelector(".correction-matches");
    let debounce;
    input.addEventListener("input", () => {
      clearTimeout(debounce);
      debounce = setTimeout(async () => {
        const q = input.value.trim();
        if (!q) { matchesDiv.innerHTML = ""; return; }
        const r = await fetch("/api/search_songs?q=" + encodeURIComponent(q));
        const d = await r.json();
        matchesDiv.innerHTML = "";
        d.matches.forEach(m => {
          const b = document.createElement("button");
          b.textContent = m.title;
          b.addEventListener("click", async () => {
            await onConfirm({
              predicted_song_id: predicted ? predicted.song_id : null,
              predicted_title: predicted ? predicted.title : null,
              confidence: predicted ? predicted.confidence : 0,
              correct_song_id: m.song_id,
              correct_title: m.title,
              was_correct: false,
            });
            box.innerHTML = "<em>Correction enregistrée ✔</em>";
          });
          matchesDiv.appendChild(b);
        });
      }, 250);
    });
  });
}

async function postConfirm(payload) {
  await fetch("/api/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query_label: "web-recording", ...payload }),
  });
}

// ---------- Mes réglages (tous les utilisateurs) ----------
const userSettingsForm = document.getElementById("userSettingsForm");

async function loadUserSettings() {
  const r = await fetch("/api/user/settings");
  const d = await r.json();
  document.getElementById("user_min_confidence").value = d.min_confidence;
}
loadUserSettings();

userSettingsForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const value = Number(document.getElementById("user_min_confidence").value);
  await fetch("/api/user/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ min_confidence: value }),
  });
  alert("Seuil sauvegardé.");
});

document.getElementById("userCalibrateBtn").addEventListener("click", async () => {
  const status = document.getElementById("userCalibrateStatus");
  status.textContent = "Calibration en cours...";
  const r = await fetch("/api/user/auto_calibrate", { method: "POST" });
  const d = await r.json();
  status.textContent = d.message || "Terminé.";
  if (d.ok) {
    document.getElementById("user_min_confidence").value = d.min_confidence;
  }
});

document.getElementById("changePasswordForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const status = document.getElementById("changePasswordStatus");
  const payload = {
    current_password: document.getElementById("current_password").value,
    new_password: document.getElementById("new_password_self").value,
  };
  const r = await fetch("/api/user/change_password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const d = await r.json();
  if (!d.ok) { status.textContent = "Erreur : " + d.error; return; }
  status.textContent = "Mot de passe changé.";
  document.getElementById("changePasswordForm").reset();
});

// =====================================================================
// Tout ce qui suit n'est chargé/actif que pour les administrateurs
// (les éléments HTML correspondants n'existent même pas pour un user simple)
// =====================================================================

if (ROLE === "admin") {

  // ---------- Comptes utilisateurs ----------
  async function loadUsers() {
    const r = await fetch("/api/admin/users");
    const d = await r.json();
    const div = document.getElementById("usersList");
    div.innerHTML = "";
    d.users.forEach(u => {
      const row = document.createElement("div");
      row.className = "user-row";
      row.innerHTML = `
        <span>${u.username} <em>(${u.role})</em></span>
        <span>
          <button class="small-btn reset-pwd" data-id="${u.id}" data-username="${u.username}">Réinitialiser mdp</button>
          <button class="small-btn delete-user" data-id="${u.id}">Supprimer</button>
        </span>
      `;
      div.appendChild(row);
    });
    div.querySelectorAll(".delete-user").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("Supprimer ce compte ?")) return;
        const r = await fetch("/api/admin/users/" + btn.dataset.id, { method: "DELETE" });
        const d = await r.json();
        if (!d.ok) { alert(d.error); return; }
        loadUsers();
      });
    });
    div.querySelectorAll(".reset-pwd").forEach(btn => {
      btn.addEventListener("click", async () => {
        const newPwd = prompt(`Nouveau mot de passe pour ${btn.dataset.username} :`);
        if (!newPwd) return;
        const r = await fetch(`/api/admin/users/${btn.dataset.id}/reset_password`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ new_password: newPwd }),
        });
        const d = await r.json();
        alert(d.ok ? "Mot de passe réinitialisé." : "Erreur : " + d.error);
      });
    });
  }
  window.loadUsers = loadUsers;

  document.getElementById("createUserForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const status = document.getElementById("createUserStatus");
    const payload = {
      username: document.getElementById("new_username").value.trim(),
      password: document.getElementById("new_password").value,
      role: document.getElementById("new_role").value,
    };
    const r = await fetch("/api/admin/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!d.ok) { status.textContent = "Erreur : " + d.error; return; }
    status.textContent = "Compte créé.";
    document.getElementById("createUserForm").reset();
    loadUsers();
  });

  // ---------- Réglages avancés (admin) ----------
  async function loadAdminSettings() {
    const r = await fetch("/api/admin/settings");
    const cfg = await r.json();
    document.getElementById("amp_min_db").value = cfg.amp_min_db;
    document.getElementById("neighborhood_t").value = cfg.neighborhood[1];
    document.getElementById("neighborhood_f").value = cfg.neighborhood[0];
    document.getElementById("fan_out").value = cfg.fan_out;
    document.getElementById("time_window").value = cfg.time_window;
  }
  window.loadAdminSettings = loadAdminSettings;

  document.getElementById("settingsForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const cfg = {
      amp_min_db: Number(document.getElementById("amp_min_db").value),
      neighborhood: [Number(document.getElementById("neighborhood_f").value), Number(document.getElementById("neighborhood_t").value)],
      fan_out: Number(document.getElementById("fan_out").value),
      time_window: Number(document.getElementById("time_window").value),
    };
    const r = await fetch("/api/admin/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    });
    const d = await r.json();
    alert(d.note || "Sauvegardé.");
  });

  document.getElementById("calibrateBtn").addEventListener("click", async () => {
    const status = document.getElementById("calibrateStatus");
    status.textContent = "Lancement...";
    const r = await fetch("/api/admin/calibrate", { method: "POST" });
    const d = await r.json();
    status.textContent = d.note || "Lancé, regarde l'onglet Logs.";
  });

  // ---------- Entraînement (admin) ----------
  async function loadNextTraining() {
    const statusDiv = document.getElementById("trainingStatus");
    const cardDiv = document.getElementById("trainingCard");
    statusDiv.textContent = "Chargement...";
    cardDiv.innerHTML = "";

    const st = await (await fetch("/api/admin/training/status")).json();
    statusDiv.textContent = `${st.reviewed}/${st.total} déjà revus (${st.remaining} restants)`;

    const r = await fetch("/api/admin/training/next");
    const d = await r.json();
    if (d.done) {
      cardDiv.innerHTML = "<p>Tous les échantillons de training/ ont été revus 🎉</p>";
      return;
    }
    if (d.error) {
      cardDiv.innerHTML = `<p>Erreur sur ${d.file} : ${d.error}</p>`;
      return;
    }

    const header = document.createElement("p");
    header.innerHTML = `<strong>Fichier :</strong> ${d.file}`;
    cardDiv.appendChild(header);

    const resultsContainer = document.createElement("div");
    resultsContainer.className = "results";
    cardDiv.appendChild(resultsContainer);

    renderResults(d.results, resultsContainer, async (payload) => {
      await fetch("/api/admin/training/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file: d.file, ...payload }),
      });
      setTimeout(loadNextTraining, 600);
    });
  }
  window.loadNextTraining = loadNextTraining;

  // ---------- Logs (admin) ----------
  const logsView = document.getElementById("logsView");

  function appendLog(entry) {
    const line = document.createElement("div");
    line.className = "log-line log-" + entry.level;
    line.textContent = `[${entry.time}] ${entry.level}: ${entry.message}`;
    logsView.appendChild(line);
    logsView.scrollTop = logsView.scrollHeight;
  }

  let logStreamStarted = false;
  async function loadLogHistory() {
    logsView.innerHTML = "";
    const r = await fetch("/api/admin/logs/history");
    const d = await r.json();
    d.logs.forEach(appendLog);
    if (!logStreamStarted) {
      logStreamStarted = true;
      const lastId = d.logs.length ? d.logs[d.logs.length - 1].id : 0;
      const es = new EventSource("/api/admin/logs/stream?since=" + lastId);
      es.onmessage = (e) => { if (e.data) appendLog(JSON.parse(e.data)); };
    }
  }
  window.loadLogHistory = loadLogHistory;

  document.getElementById("clearLogsBtn").addEventListener("click", () => {
    logsView.innerHTML = "";
  });
}
