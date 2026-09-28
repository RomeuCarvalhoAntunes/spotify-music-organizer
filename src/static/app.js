const state = { genres: [], review: [] };

const $ = (selector) => document.querySelector(selector);

function showMessage(text, error = false) {
  const box = $("#message");
  box.textContent = text;
  box.className = error ? "message error" : "message";
  box.hidden = !text;
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Não foi possível concluir a operação.");
  return data;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}

function setDot(id, status) {
  const dot = $(id);
  dot.className = status ? "ok" : "error";
}

function renderReview() {
  $("#review-count").textContent = state.review.length + " pendentes";
  $("#review-status").textContent = state.review.length;
  const list = $("#review-list");
  if (!state.review.length) {
    list.innerHTML = '<p class="muted">Nenhuma faixa pendente de revisão.</p>';
    return;
  }
  list.innerHTML = state.review.map((track) => `
    <div class="review-item">
      <div><strong>${escapeHtml(track.name)}</strong><small>${escapeHtml(track.artists.map((artist) => artist.name).join(", "))} · ${escapeHtml(track.album_name || "Álbum desconhecido")}</small></div>
      <button class="button button-secondary choose-track" data-id="${escapeHtml(track.spotify_id)}">Classificar</button>
    </div>
  `).join("");
  document.querySelectorAll(".choose-track").forEach((button) => button.addEventListener("click", () => {
    $("#resource-type").value = "track";
    $("#spotify-id").value = button.dataset.id;
    $("#decision-form").scrollIntoView({ behavior: "smooth", block: "center" });
    $("#spotify-id").focus();
  }));
}

function renderGenres() {
  $("#genre-count").textContent = state.genres.length;
  $("#genre-options").innerHTML = state.genres.map((genre) => `
    <label class="genre-option"><input class="genre-checkbox" type="checkbox" value="${genre.id}"> ${escapeHtml(genre.name)}</label>
  `).join("");
  $("#genre-list").innerHTML = state.genres.map((genre) => `
    <article class="genre-card"><strong>${escapeHtml(genre.name)}</strong><p>${escapeHtml(genre.description)}</p></article>
  `).join("");
}

async function loadReview() {
  const data = await api("/classification/review?limit=100");
  state.review = data.items;
  renderReview();
}

async function loadGenres() {
  const data = await api("/genres?include_disabled=false");
  state.genres = data.items;
  renderGenres();
}

async function loadStatus() {
  try {
    await api("/health");
    $("#app-status").textContent = "online";
    setDot("#app-dot", true);
  } catch (error) {
    $("#app-status").textContent = "erro";
    setDot("#app-dot", false);
  }
  try {
    const account = await api("/me");
    $("#spotify-status").textContent = "conectado";
    $("#account-name").textContent = account.display_name || account.id || "Conta conectada";
    $("#account-detail").textContent = "Acesso de leitura autorizado.";
    setDot("#spotify-dot", true);
  } catch (error) {
    $("#spotify-status").textContent = "desconectado";
    setDot("#spotify-dot", false);
  }
  try {
    await loadReview();
    setDot("#review-dot", state.review.length === 0);
  } catch (error) {
    showMessage(error.message, true);
  }
}

$("#import-button").addEventListener("click", async () => {
  const button = $("#import-button");
  button.disabled = true;
  showMessage("Importando playlists e faixas...");
  try {
    const result = await api("/imports", { method: "POST" });
    showMessage(`Importação concluída: ${result.playlist_count} playlists e ${result.playlist_track_count} relações.`);
    await loadStatus();
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
});

$("#refresh-button").addEventListener("click", async () => {
  await Promise.all([loadStatus(), loadGenres()]);
  showMessage("Status atualizado.");
});

$("#decision-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const genreIds = [...document.querySelectorAll(".genre-checkbox:checked")].map((input) => Number(input.value));
  if (!genreIds.length) {
    showMessage("Selecione pelo menos um gênero.", true);
    return;
  }
  try {
    const result = await api("/classification/decisions", {
      method: "POST",
      body: JSON.stringify({ resource_type: $("#resource-type").value, spotify_id: $("#spotify-id").value.trim(), genre_ids: genreIds }),
    });
    showMessage(`Decisão salva: ${result.classification_count} classificação(ões) atualizada(s).`);
    document.querySelectorAll(".genre-checkbox").forEach((input) => { input.checked = false; });
    await loadStatus();
  } catch (error) {
    showMessage(error.message, true);
  }
});

Promise.all([loadGenres(), loadStatus()]);
