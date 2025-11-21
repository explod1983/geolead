// geolead_content.js
(function () {
  const EXT_LOG_PREFIX = "[GeoLead Bridge]";

  function log(...args) {
    console.log(EXT_LOG_PREFIX, ...args);
  }

  // ---- Helpers to get context from the GeoLead page ----

  function getBoardSlug() {
    // Works for /board/{slug}, /board/{slug}/today, /board/{slug}/submit, etc.
    const m = window.location.pathname.match(/^\/board\/([^/]+)/);
    if (!m) return null;
    try {
      return decodeURIComponent(m[1]);
    } catch {
      return m[1];
    }
  }

  function getPlayerNameFromNavbar() {
    // <a href="/me" class="nav-link"> My stats · {{ me.name }}</a>
    const link = document.querySelector('a[href="/me"]');
    if (!link) return null;
    const txt = (link.textContent || "").trim();
    // split on the · separator
    const parts = txt.split("·");
    if (parts.length < 2) return null;
    return parts[1].trim();
  }

  function buildImportPayload(summary, playerName, boardSlug) {
    // summary is what we stored from GeoGuessr (__NEXT_DATA__)
    const roundsSource = Array.isArray(summary.rounds)
      ? summary.rounds
      : [];

    const rounds = roundsSource.map((r) => {
      const score = typeof r.score === "number" ? r.score : 0;
      const dist =
        typeof r.distance_m === "number" ? r.distance_m : null;

      const guess = r.guess || {};
      const correct = r.correct || {};

      return {
        score,
        distance_m: dist,
        guess_lat:
          typeof guess.lat === "number" ? guess.lat : null,
        guess_lng:
          typeof guess.lng === "number" ? guess.lng : null,
        target_lat:
          typeof correct.lat === "number" ? correct.lat : null,
        target_lng:
          typeof correct.lng === "number" ? correct.lng : null
      };
    });

    const totalScore =
      typeof summary.total_score === "number"
        ? summary.total_score
        : rounds.reduce((acc, r) => acc + (r.score || 0), 0);

    const totalDistance =
      typeof summary.total_distance_m === "number"
        ? summary.total_distance_m
        : rounds.reduce(
            (acc, r) => acc + (r.distance_m || 0),
            0
          );

    const gameId =
      summary.dailyQuizId ||
      summary.quizId ||
      summary.token ||
      null;

    return {
      player_name: playerName,
      board_slug: boardSlug,
      total_score: totalScore,
      total_distance_m: totalDistance,
      game_id: gameId,
      rounds
    };
  }

  async function sendImport(summary) {
    const boardSlug = getBoardSlug();
    if (!boardSlug) {
      alert(
        "GeoLead Bridge:\nOpen a specific board URL like /board/your-board before importing."
      );
      return;
    }

    const playerName = getPlayerNameFromNavbar();
    if (!playerName) {
      alert(
        "GeoLead Bridge:\nCould not detect your player name. Make sure you are logged in on GeoLead."
      );
      return;
    }

    const payload = buildImportPayload(summary, playerName, boardSlug);
    log("Sending payload to GeoLead backend:", payload);

    const url = window.location.origin + "/api/geoguessr/import";

    try {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        credentials: "include" // keep session cookies if needed
      });

      if (!resp.ok) {
        const text = await resp.text();
        console.error(
          EXT_LOG_PREFIX,
          "Backend error:",
          resp.status,
          text
        );
        alert(
          "GeoLead Bridge:\nImport failed, backend returned " +
            resp.status +
            ". See console for details."
        );
        return;
      }

      const data = await resp.json();
      log("Import success:", data);

      alert(
        "GeoLead Bridge:\nImported game successfully!\n" +
          "Total score: " +
          (data.total_score ?? "n/a") +
          "\nTotal distance: " +
          (data.total_distance_m != null
            ? (data.total_distance_m / 1000).toFixed(1) + " km"
            : "n/a")
      );

      // Optional: jump straight to today's round for this board
      const todayUrl =
        window.location.origin +
        "/board/" +
        encodeURIComponent(boardSlug) +
        "/today";
      window.location.href = todayUrl;
    } catch (e) {
      console.error(EXT_LOG_PREFIX, "Request failed:", e);
      alert(
        "GeoLead Bridge:\nCould not reach GeoLead backend.\n" +
          "Check that it is running (localhost:8000) or the production site is up."
      );
    }
  }

  function importFromStorage() {
    chrome.storage.local.get("geoguessrLastGame", (result) => {
      const data = result.geoguessrLastGame;
      if (!data) {
        alert(
          "GeoLead Bridge:\nNo recent GeoGuessr game found.\nFinish a game on geoguessr.com first."
        );
        return;
      }

      log("Loaded GeoGuessr data from storage:", data);
      void sendImport(data);
    });
  }

  // ---- Floating button on GeoLead ----

  function createFloatingButton() {
    if (document.getElementById("geolead-import-btn")) return;

    const btn = document.createElement("button");
    btn.id = "geolead-import-btn";
    btn.textContent = "Import GeoGuessr";

    Object.assign(btn.style, {
      position: "fixed",
      bottom: "16px",
      right: "16px",
      zIndex: "2147483647",
      padding: "10px 16px",
      fontSize: "14px",
      fontFamily:
        "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      borderRadius: "999px",
      border: "none",
      boxShadow: "0 2px 6px rgba(0,0,0,0.3)",
      cursor: "pointer",
      background: "#10b981",
      color: "#fff"
    });

    btn.addEventListener("mouseenter", () => {
      btn.style.filter = "brightness(1.1)";
    });
    btn.addEventListener("mouseleave", () => {
      btn.style.filter = "none";
    });

    btn.addEventListener("click", importFromStorage);

    document.body.appendChild(btn);
    log("Floating Import GeoGuessr button injected.");
  }

  if (
    document.readyState === "complete" ||
    document.readyState === "interactive"
  ) {
    createFloatingButton();
  } else {
    window.addEventListener("DOMContentLoaded", createFloatingButton, {
      once: true
    });
  }
})();
