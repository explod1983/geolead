(function () {
  const EXT_LOG_PREFIX = "[GeoLead Bridge]";

  function log(...args) {
    console.log(EXT_LOG_PREFIX, ...args);
  }

  function importFromStorage() {
    chrome.storage.local.get("geoguessrLastGame", (result) => {
      const data = result.geoguessrLastGame;
      if (!data) {
        alert(
          "GeoLead Bridge: No recent GeoGuessr game found.\nFinish a game on geoguessr.com first."
        );
        return;
      }

      log("Imported GeoGuessr data:", data);

      // Dispatch event to page so your app can consume it
      window.dispatchEvent(
        new CustomEvent("geolead:geoguessr-import", {
          detail: data
        })
      );
    });
  }

  function createFloatingButton() {
    // If you prefer to hook into your own button instead, you can skip this
    // and just call importFromStorage() from a listener on your button.
    const existing = document.getElementById("geolead-import-btn");
    if (existing) return;

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
      fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      borderRadius: "999px",
      border: "none",
      boxShadow: "0 2px 6px rgba(0,0,0,0.3)",
      cursor: "pointer",
      background: "#10b981", // Tailwind emerald-500-ish
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
