// geoguessr_content.js
(function () {
  const EXT_LOG_PREFIX = "[GeoLead Bridge]";

  function log(...args) {
    console.log(EXT_LOG_PREFIX, ...args);
  }

  // ---------- Helpers to read __NEXT_DATA__ ----------

  function getNextData() {
    const script = document.getElementById("__NEXT_DATA__");
    if (!script) {
      log("__NEXT_DATA__ script not found.");
      return null;
    }

    try {
      const raw = script.textContent || script.innerText || "{}";
      const data = JSON.parse(raw);
      return data;
    } catch (e) {
      console.warn(EXT_LOG_PREFIX, "Failed to parse __NEXT_DATA__", e);
      return null;
    }
  }

  function extractFromNextData() {
    const data = getNextData();
    if (!data) return null;

    const props = data.props || {};
    const pageProps = props.pageProps || {};
    const accountProps = props.accountProps || {};
    const account = accountProps.account || {};
    const userRaw = account.user || {};

    const user = {
      id: userRaw.userId || userRaw.id || null,
      nick: userRaw.nick || null,
      email: account.email || null,
      countryCode: userRaw.countryCode || null
    };

    // Support both classic games and the free daily quiz
    const classicGame =
      pageProps.game || (pageProps.data && pageProps.data.game) || null;
    const quizGame = pageProps.quizGame || null;

    if (quizGame) {
      return {
        type: "daily-quiz",
        dailyQuizId: pageProps.dailyQuizId || null,
        game: quizGame,
        user
      };
    }

    if (classicGame) {
      return {
        type: "classic",
        game: classicGame,
        user
      };
    }

    log("No game object found in __NEXT_DATA__ (no quizGame or game).");
    return null;
  }

  // ---------- Build summaries ----------

  // Classic (normal) game – in case you play other modes later
  function buildClassicSummary(game, user) {
    const map = game.map || game.challenge?.map || {};
    const mapImage =
      map.coverUrl || map.thumbnailUrl || map.imageUrl || null;

    const players = game.players || (game.player ? [game.player] : []);
    const myPlayer = players[0] || null;

    const totalScore =
      myPlayer?.totalScore?.amount ??
      myPlayer?.totalScore ??
      myPlayer?.score ??
      null;

    const rounds = game.rounds || [];
    const currentRoundNumber =
      game.currentRoundNumber || game.round || rounds.length;

    const roundsSummary = rounds.slice(0, currentRoundNumber).map((rnd, i) => {
      const guesses = rnd.guesses || [];
      const guess = guesses[0] || rnd.guess || null;

      const distance =
        guess?.distanceInMeters ??
        guess?.distance ??
        rnd.distanceInMeters ??
        null;

      const score =
        guess?.roundScoreInPoints ??
        guess?.scoreInPoints ??
        rnd.roundScoreInPoints ??
        null;

      return {
        round: i + 1,
        distance_m: distance,
        distance_km:
          typeof distance === "number" ? distance / 1000 : null,
        score,
        correct: { lat: rnd.lat, lng: rnd.lng },
        guess: guess
          ? { lat: guess.lat, lng: guess.lng }
          : null
      };
    });

    return {
      source: "geoguessr",
      mode: "classic",
      token: game.token || null,
      user,
      map: {
        id: map.id || null,
        name: map.name || null,
        slug: map.slug || null,
        image: mapImage
      },
      total_score: totalScore,
      rounds: roundsSummary
    };
  }

  // Daily free game / quiz mode (/free/start)
  function buildDailyQuizSummary(quizGame, user, dailyQuizId) {
    const guesses = quizGame.guesses || [];
    const rounds = quizGame.rounds || [];

    const guessByRound = {};
    for (const g of guesses) {
      if (g && g.roundNumber != null) {
        guessByRound[g.roundNumber] = g;
      }
    }

    const roundsSummary = rounds.map((r, idx) => {
      const roundNumber = r.roundNumber ?? idx + 1;
      const guess = guessByRound[roundNumber] || null;

      const pano =
        r.question?.panoramaQuestionPayload?.panorama || {};
      const correctLat = pano.lat;
      const correctLng = pano.lng;

      const distance =
        typeof guess?.distance === "number" ? guess.distance : null;
      const score =
        typeof guess?.score === "number" ? guess.score : null;

      return {
        round: roundNumber,
        distance_m: distance,
        distance_km:
          typeof distance === "number" ? distance / 1000 : null,
        score,
        correct: { lat: correctLat, lng: correctLng },
        guess: guess
          ? { lat: guess.lat, lng: guess.lng }
          : null
      };
    });

    return {
      source: "geoguessr",
      mode: "daily-quiz",
      dailyQuizId: dailyQuizId || null,
      quizId: quizGame.quizId || null,
      user,
      total_score: quizGame.totalScore ?? null,
      max_score: quizGame.maxScore ?? null,
      total_rounds: quizGame.totalRounds ?? rounds.length ?? null,
      rounds: roundsSummary
    };
  }

  function buildSummaryFromNextData() {
    const extracted = extractFromNextData();
    if (!extracted) return null;

    const { type, game, user, dailyQuizId } = extracted;

    if (type === "daily-quiz") {
      return buildDailyQuizSummary(game, user, dailyQuizId);
    }

    if (type === "classic") {
      return buildClassicSummary(game, user);
    }

    return null;
  }

  function storeSummary() {
    const summary = buildSummaryFromNextData();
    if (!summary) {
      return;
    }

    chrome.storage.local.set({ geoguessrLastGame: summary }, () => {
      if (chrome.runtime.lastError) {
        console.warn(
          EXT_LOG_PREFIX,
          "Failed to store game summary:",
          chrome.runtime.lastError
        );
      } else {
        log("Stored latest game summary from __NEXT_DATA__:", summary);
      }
    });
  }

  // ---------- Watch for SPA updates (Next.js) ----------

  function setupObserver() {
    const script = document.getElementById("__NEXT_DATA__");
    if (!script) {
      log("__NEXT_DATA__ not found, cannot observe.");
      return;
    }

    let lastSignature = null;

    const update = () => {
      const data = getNextData();
      if (!data) return;

      // Create a small "signature" to avoid repeated writes
      const props = data.props || {};
      const pageProps = props.pageProps || {};
      const quizGame = pageProps.quizGame || {};
      const classicGame =
        pageProps.game || (pageProps.data && pageProps.data.game) || {};

      const sig =
        (quizGame.quizId || "") +
        "|" +
        (quizGame.currentRound || "") +
        "|" +
        (classicGame.token || "") +
        "|" +
        (classicGame.currentRoundNumber || "");

      if (sig && sig === lastSignature) {
        return; // no change
      }
      lastSignature = sig;

      storeSummary();
    };

    // Initial run
    update();

    const observer = new MutationObserver(() => {
      update();
    });

    observer.observe(script, {
      characterData: true,
      childList: true,
      subtree: true
    });

    log("MutationObserver set on __NEXT_DATA__.");
  }

  if (
    document.readyState === "complete" ||
    document.readyState === "interactive"
  ) {
    setupObserver();
  } else {
    window.addEventListener("DOMContentLoaded", setupObserver, {
      once: true
    });
  }
})();
