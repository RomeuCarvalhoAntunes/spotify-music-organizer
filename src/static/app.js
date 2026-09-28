const state = { genres: [], review: [], progress: null, automaticJob: null };

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
      <div class="review-actions">
        <a class="button button-secondary" href="${escapeHtml(track.spotify_url)}" target="_blank" rel="noopener">Ouvir</a>
        <button class="button button-secondary choose-track" data-id="${escapeHtml(track.spotify_id)}">Classificar</button>
      </div>
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

function renderLocalPlaylists(playlists) {
  $("#local-playlist-count").textContent = playlists.length;
  const list = $("#local-playlist-list");
  if (!playlists.length) {
    list.innerHTML = '<p class="muted">Nenhuma playlist local gerada.</p>';
    return;
  }
  list.innerHTML = playlists.map((playlist) => `
    <article class="local-playlist-card">
      <div class="panel-heading"><strong>${escapeHtml(playlist.name)}</strong><span class="count-badge">${playlist.track_count} faixas</span></div>
      <ol>${playlist.tracks.slice(0, 5).map((track) => `<li><a href="${escapeHtml(track.spotify_url)}" target="_blank" rel="noopener">${escapeHtml(track.name)}</a><small>${escapeHtml(track.artists.map((artist) => artist.name).join(", "))}</small></li>`).join("")}</ol>
      ${playlist.track_count > 5 ? `<small class="muted">+ ${playlist.track_count - 5} faixas nesta playlist local</small>` : ""}
    </article>
  `).join("");
}

async function loadLocalPlaylists() {
  const data = await api("/local-playlists");
  renderLocalPlaylists(data.items);
}

async function watchOperation(operationId, button, title, onCompleted) {
  const response = await api("/operations/" + operationId);
  const percent = response.total ? Math.round(response.processed / response.total * 100) : 0;
  $("#operation-panel").hidden = false;
  $("#operation-title").textContent = title;
  $("#operation-percent").textContent = percent + "%";
  $("#operation-progress-fill").style.width = percent + "%";
  $("#operation-phase").textContent = response.phase + (response.current_item ? " · " + response.current_item : "");
  showMessage(title + ": " + response.phase);
  if (response.status === "queued" || response.status === "running") {
    window.setTimeout(() => watchOperation(operationId, button, title, onCompleted), 700);
    return;
  }
  button.disabled = false;
  $("#operation-panel").hidden = true;
  if (response.status === "error") {
    showMessage(response.error || "A operação falhou.", true);
    return;
  }
  await onCompleted(response.result || {});
}

function renderSpotifyRules(data) {
  $("#spotify-rule-count").textContent = data.genre_playlist_count + " de " + data.total_playlists;
  const list = $("#spotify-rule-list");
  const mapped = data.playlists.filter((playlist) => playlist.genre);
  const ignored = data.playlists.filter((playlist) => !playlist.genre);
  list.innerHTML = '<div class="rule-summary"><strong>' + mapped.length + ' playlists de gênero</strong><span>' + ignored.length + ' playlists ignoradas por serem contexto/origem/artista</span></div><div class="spotify-rule-grid">' + data.playlists.map((playlist) => '<article class="spotify-rule-card"><div><strong>' + escapeHtml(playlist.name) + '</strong><span>' + playlist.track_count + ' faixas</span></div><small>' + escapeHtml(playlist.rule) + '</small></article>').join("") + '</div>';
}

async function loadSpotifyRules() {
  const data = await api("/spotify/classification-rules");
  renderSpotifyRules(data);
  return data;
}

async function loadProgress() {
  const progress = await api("/classifications/progress");
  const percentage = progress.library_count ? Math.round(progress.classified_count / progress.library_count * 100) : 0;
  $("#progress-label").textContent = percentage + "%";
  $("#progress-bar-fill").style.width = percentage + "%";
  $("#library-total").textContent = progress.library_count;
  $("#automatic-total").textContent = progress.automatically_classified_count;
  $("#manual-total").textContent = progress.manually_classified_count;
  $("#pending-total").textContent = progress.needs_manual_count;
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
    await loadProgress();
    await loadLocalPlaylists();
    setDot("#review-dot", state.review.length === 0);
  } catch (error) {
    showMessage(error.message, true);
  }
}

$("#import-button").addEventListener("click", async () => {
  const button = $("#import-button");
  button.disabled = true;
  try {
    const operation = await api("/imports", { method: "POST" });
    await watchOperation(operation.operation_id, button, "Importação", async (result) => {
      showMessage("Importação concluída: " + result.playlist_count + " playlists e " + result.playlist_track_count + " relações.");
      await loadStatus();
    });
  } catch (error) {
    button.disabled = false;
    showMessage(error.message, true);
  }
});

$("#generate-playlists-button").addEventListener("click", async () => {
  const button = $("#generate-playlists-button");
  button.disabled = true;
  try {
    const operation = await api("/local-playlists", { method: "POST" });
    await watchOperation(operation.operation_id, button, "Playlists locais", async (result) => {
      showMessage(result.playlist_count + " playlists locais geradas com " + result.track_count + " faixas.");
      await loadLocalPlaylists();
    });
  } catch (error) {
    button.disabled = false;
    showMessage(error.message, true);
  }
});

async function watchAutomaticJob(jobId, button) {
  const response = await api("/classifications/automatic/" + jobId);
  state.automaticJob = response;
  const percent = response.total ? Math.round(response.processed / response.total * 100) : 0;
  showMessage("Classificando: " + percent + "% · " + response.phase + (response.current_track ? " · " + response.current_track : ""));
  $("#auto-button").textContent = "Classificar lote de 300 (" + percent + "%)";
  $("#operation-panel").hidden = false;
  $("#operation-title").textContent = "Classificação automática";
  $("#operation-percent").textContent = percent + "%";
  $("#operation-progress-fill").style.width = percent + "%";
  $("#operation-phase").textContent = response.phase + (response.current_track ? " · " + response.current_track : "");
  if (response.status === "queued" || response.status === "running") {
    window.setTimeout(() => watchAutomaticJob(jobId, button), 700);
    return;
  }
  button.disabled = false;
  $("#auto-button").textContent = "Classificar lote de 300";
  $("#operation-panel").hidden = true;
  if (response.status === "error") {
    showMessage(response.error || "A classificação falhou.", true);
    return;
  }
  showMessage(response.matched + " faixa(s) classificadas no lote. " + response.no_match + " precisam de revisão.");
  await loadStatus();
}

$("#auto-button").addEventListener("click", async () => {
  const button = $("#auto-button");
  button.disabled = true;
  try {
    const result = await api("/classifications/automatic?limit=300", { method: "POST" });
    showMessage("Preparando classificação pelas playlists do Spotify...");
    await watchAutomaticJob(result.job_id, button);
  } catch (error) {
    button.disabled = false;
    button.textContent = "Classificar lote de 300";
    showMessage(error.message, true);
  }
});

$("#spotify-rules-button").addEventListener("click", async () => {
  const button = $("#spotify-rules-button");
  button.disabled = true;
  showMessage("Lendo playlists do Spotify e inferindo as regras...");
  try {
    const data = await loadSpotifyRules();
    showMessage(data.genre_playlist_count + " playlists de gênero identificadas; " + data.ignored_playlist_count + " ignoradas.");
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
});

$("#reset-button").addEventListener("click", async () => {
  if (!window.confirm("Zerar todas as classificações, regras e playlists locais? A biblioteca importada será preservada.")) return;
  const button = $("#reset-button");
  button.disabled = true;
  try {
    const operation = await api("/classifications/reset", { method: "POST" });
    await watchOperation(operation.operation_id, button, "Reset local", async (result) => {
      showMessage("Reset concluído: " + result.automatic_classifications + " automáticas e " + result.manual_classifications + " manuais removidas.");
      await loadStatus();
      await loadLocalPlaylists();
    });
  } catch (error) {
    button.disabled = false;
    showMessage(error.message, true);
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
