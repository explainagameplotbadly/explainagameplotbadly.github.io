(function () {
  "use strict";

  const STORAGE_KEYS = {
    current: "eagpb_current_streak",
    highest: "eagpb_highest_streak",
    previous: "eagpb_previous_streak",
    seen: "eagpb_seen_ids",
  };

  let questions = [];
  let autocompletePool = [];
  let queue = [];
  let currentQuestion = null;
  let hintsRevealed = 0;
  let answered = false;
  let activeSuggestionIndex = -1;
  let supabaseClient = null;

  const el = {
    prompt: document.getElementById("prompt-text"),
    hintsSection: document.getElementById("hints-section"),
    hintsList: document.getElementById("hints-list"),
    revealHintBtn: document.getElementById("reveal-hint-btn"),
    guessForm: document.getElementById("guess-form"),
    guessInput: document.getElementById("guess-input"),
    autocompleteList: document.getElementById("autocomplete-list"),
    giveUpBtn: document.getElementById("give-up-btn"),
    feedback: document.getElementById("feedback"),
    revealSection: document.getElementById("reveal-section"),
    coverArt: document.getElementById("cover-art"),
    coverArtFallback: document.getElementById("cover-art-fallback"),
    answerName: document.getElementById("answer-name"),
    globalStat: document.getElementById("global-stat"),
    permalinkLink: document.getElementById("permalink-link"),
    nextBtn: document.getElementById("next-btn"),
    statCurrent: document.getElementById("stat-current"),
    statHighest: document.getElementById("stat-highest"),
    statPrevious: document.getElementById("stat-previous"),
    banner: document.getElementById("data-banner"),
    lastUpdated: document.getElementById("last-updated"),
  };

  function normalize(str) {
    return (str || "")
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function getStreaks() {
    return {
      current: parseInt(localStorage.getItem(STORAGE_KEYS.current) || "0", 10),
      highest: parseInt(localStorage.getItem(STORAGE_KEYS.highest) || "0", 10),
      previous: parseInt(localStorage.getItem(STORAGE_KEYS.previous) || "0", 10),
    };
  }

  function setStreaks(streaks) {
    localStorage.setItem(STORAGE_KEYS.current, String(streaks.current));
    localStorage.setItem(STORAGE_KEYS.highest, String(streaks.highest));
    localStorage.setItem(STORAGE_KEYS.previous, String(streaks.previous));
    renderStreaks();
  }

  function renderStreaks() {
    const s = getStreaks();
    el.statCurrent.textContent = s.current;
    el.statHighest.textContent = s.highest;
    el.statPrevious.textContent = s.previous;
  }

  function recordResult(correct) {
    const s = getStreaks();
    if (correct) {
      s.current += 1;
      s.highest = Math.max(s.highest, s.current);
    } else {
      s.previous = s.current;
      s.current = 0;
    }
    setStreaks(s);
  }

  function showBanner(message) {
    el.banner.textContent = message;
    el.banner.hidden = false;
  }

  async function loadData() {
    const [questionsRes, gamesRes] = await Promise.all([
      fetch("data/questions.json"),
      fetch("data/games.json"),
    ]);
    const questionsData = await questionsRes.json();
    const gamesData = await gamesRes.json();

    questions = questionsData.questions || [];
    if (questionsData.source === "sample-placeholder") {
      showBanner(
        "Showing sample placeholder questions — the Reddit scraper hasn't run yet. See README.md."
      );
    }
    if (el.lastUpdated) {
      el.lastUpdated.textContent = "Questions last updated: " + (questionsData.updated_at || "unknown");
    }

    const pool = new Set(gamesData.games || []);
    questions.forEach((q) => pool.add(q.answer));
    autocompletePool = Array.from(pool).sort((a, b) => a.localeCompare(b));
  }

  function buildQueue() {
    const seen = JSON.parse(localStorage.getItem(STORAGE_KEYS.seen) || "[]");
    let unseen = questions.filter((q) => !seen.includes(q.id));
    if (unseen.length === 0) {
      localStorage.setItem(STORAGE_KEYS.seen, "[]");
      unseen = questions.slice();
    }
    // Fisher-Yates shuffle
    for (let i = unseen.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [unseen[i], unseen[j]] = [unseen[j], unseen[i]];
    }
    queue = unseen;
  }

  function markSeen(id) {
    const seen = JSON.parse(localStorage.getItem(STORAGE_KEYS.seen) || "[]");
    if (!seen.includes(id)) {
      seen.push(id);
      localStorage.setItem(STORAGE_KEYS.seen, JSON.stringify(seen));
    }
  }

  function loadNextQuestion() {
    if (queue.length === 0) buildQueue();
    currentQuestion = queue.pop();
    hintsRevealed = 0;
    answered = false;

    el.prompt.textContent = currentQuestion.prompt;
    el.hintsList.innerHTML = "";
    el.feedback.textContent = "";
    el.feedback.className = "feedback";
    el.guessInput.value = "";
    el.guessInput.disabled = false;
    el.giveUpBtn.disabled = false;
    el.revealSection.hidden = true;
    el.nextBtn.hidden = true;
    hideAutocomplete();

    const hints = currentQuestion.hints || [];
    if (hints.length > 0) {
      el.hintsSection.hidden = false;
      el.revealHintBtn.hidden = false;
      el.revealHintBtn.textContent = `Reveal a hint (0/${hints.length})`;
      el.revealHintBtn.disabled = false;
    } else {
      el.hintsSection.hidden = true;
    }

    el.guessInput.focus();
  }

  function revealNextHint() {
    const hints = currentQuestion.hints || [];
    if (hintsRevealed >= hints.length) return;
    const li = document.createElement("li");
    li.textContent = hints[hintsRevealed];
    el.hintsList.appendChild(li);
    hintsRevealed += 1;
    if (hintsRevealed >= hints.length) {
      el.revealHintBtn.hidden = true;
    } else {
      el.revealHintBtn.textContent = `Reveal a hint (${hintsRevealed}/${hints.length})`;
    }
  }

  function hideAutocomplete() {
    el.autocompleteList.hidden = true;
    el.autocompleteList.innerHTML = "";
    activeSuggestionIndex = -1;
  }

  function renderAutocomplete(value) {
    const query = normalize(value);
    if (!query) {
      hideAutocomplete();
      return;
    }
    const matches = autocompletePool
      .filter((title) => normalize(title).includes(query))
      .slice(0, 8);

    if (matches.length === 0) {
      hideAutocomplete();
      return;
    }

    el.autocompleteList.innerHTML = "";
    matches.forEach((title) => {
      const li = document.createElement("li");
      li.textContent = title;
      li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        el.guessInput.value = title;
        hideAutocomplete();
      });
      el.autocompleteList.appendChild(li);
    });
    activeSuggestionIndex = -1;
    el.autocompleteList.hidden = false;
  }

  function moveSuggestionActive(delta) {
    const items = Array.from(el.autocompleteList.children);
    if (items.length === 0) return;
    items[activeSuggestionIndex]?.classList.remove("active");
    activeSuggestionIndex = (activeSuggestionIndex + delta + items.length) % items.length;
    items[activeSuggestionIndex].classList.add("active");
    el.guessInput.value = items[activeSuggestionIndex].textContent;
  }

  async function submitStatToSupabase(questionId, correct) {
    if (!supabaseClient) return;
    try {
      const { error } = await supabaseClient
        .from("answers")
        .insert({ question_id: questionId, is_correct: correct });
      if (error) console.warn("Failed to record stat:", error.message);
    } catch (err) {
      console.warn("Failed to record stat:", err);
    }
  }

  async function renderGlobalStat(questionId) {
    if (!supabaseClient) {
      el.globalStat.textContent = "Community stats unavailable.";
      return;
    }
    try {
      const totalRes = await supabaseClient
        .from("answers")
        .select("*", { count: "exact", head: true })
        .eq("question_id", questionId);
      if (totalRes.error || totalRes.count === null) {
        throw totalRes.error || new Error("count unavailable");
      }

      const total = totalRes.count;
      if (total === 0) {
        el.globalStat.textContent = "Be the first to answer this one!";
        return;
      }

      const correctRes = await supabaseClient
        .from("answers")
        .select("*", { count: "exact", head: true })
        .eq("question_id", questionId)
        .eq("is_correct", true);
      if (correctRes.error || correctRes.count === null) {
        throw correctRes.error || new Error("count unavailable");
      }

      const pct = Math.round((correctRes.count / total) * 100);
      el.globalStat.textContent = `${pct}% of ${total} player${total === 1 ? "" : "s"} got this right.`;
    } catch (err) {
      console.warn("Failed to load stats:", err);
      el.globalStat.textContent = "Community stats unavailable.";
    }
  }

  function showReveal(correct) {
    el.revealSection.hidden = false;
    el.answerName.textContent = currentQuestion.answer;
    el.permalinkLink.href = currentQuestion.permalink || "#";

    if (currentQuestion.cover_art_url) {
      el.coverArt.src = currentQuestion.cover_art_url;
      el.coverArt.alt = currentQuestion.answer + " cover art";
      el.coverArt.hidden = false;
      el.coverArtFallback.hidden = true;
    } else {
      el.coverArt.hidden = true;
      el.coverArtFallback.hidden = false;
    }

    renderGlobalStat(currentQuestion.id);
    el.nextBtn.hidden = false;
    el.giveUpBtn.disabled = true;
    el.guessInput.disabled = true;
    hideAutocomplete();
  }

  function handleGuess(rawGuess) {
    if (answered || !currentQuestion) return;
    answered = true;
    const correct = normalize(rawGuess) === normalize(currentQuestion.answer);

    el.feedback.textContent = correct ? "Correct!" : `Not quite.`;
    el.feedback.className = "feedback " + (correct ? "correct" : "incorrect");

    recordResult(correct);
    submitStatToSupabase(currentQuestion.id, correct);
    markSeen(currentQuestion.id);
    showReveal(correct);
  }

  function handleGiveUp() {
    if (answered || !currentQuestion) return;
    answered = true;
    el.feedback.textContent = "Answer revealed.";
    el.feedback.className = "feedback incorrect";
    recordResult(false);
    submitStatToSupabase(currentQuestion.id, false);
    markSeen(currentQuestion.id);
    showReveal(false);
  }

  function initSupabase() {
    if (window.supabase && window.APP_CONFIG && window.APP_CONFIG.SUPABASE_URL) {
      supabaseClient = window.supabase.createClient(
        window.APP_CONFIG.SUPABASE_URL,
        window.APP_CONFIG.SUPABASE_ANON_KEY
      );
    }
  }

  function bindEvents() {
    el.guessForm.addEventListener("submit", (e) => {
      e.preventDefault();
      handleGuess(el.guessInput.value);
    });

    el.giveUpBtn.addEventListener("click", handleGiveUp);
    el.revealHintBtn.addEventListener("click", revealNextHint);
    el.nextBtn.addEventListener("click", loadNextQuestion);

    el.guessInput.addEventListener("input", () => renderAutocomplete(el.guessInput.value));
    el.guessInput.addEventListener("blur", () => setTimeout(hideAutocomplete, 100));
    el.guessInput.addEventListener("keydown", (e) => {
      if (el.autocompleteList.hidden) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        moveSuggestionActive(1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        moveSuggestionActive(-1);
      } else if (e.key === "Escape") {
        hideAutocomplete();
      }
    });
  }

  async function init() {
    renderStreaks();
    bindEvents();
    // supabase-js/config.js load via earlier deferred <script> tags, which execute
    // before this one, but guard against readystate races just in case.
    if (document.readyState === "loading") {
      await new Promise((resolve) => document.addEventListener("DOMContentLoaded", resolve, { once: true }));
    }
    initSupabase();
    try {
      await loadData();
    } catch (err) {
      el.prompt.textContent = "Failed to load questions. Please refresh.";
      console.error(err);
      return;
    }
    buildQueue();
    loadNextQuestion();
  }

  init();
})();
