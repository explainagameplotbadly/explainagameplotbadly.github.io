(function () {
  "use strict";

  const STORAGE_KEYS = {
    current: "eagpb_current_streak",
    highest: "eagpb_highest_streak",
    previous: "eagpb_previous_streak",
    seen: "eagpb_seen_ids",
  };
  const DAILY_STORAGE_KEY = "eagpb_daily_attempts";

  let questions = [];
  let autocompletePool = [];
  let queue = [];
  let currentQuestion = null;
  let hintsRevealed = 0;
  let answered = false;
  let supabaseClient = null;
  let mainAutocomplete = null;

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
    dailyCards: document.getElementById("daily-cards"),
    dailyShareBtn: document.getElementById("daily-share-btn"),
  };

  function normalize(str) {
    return (str || "")
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  // Most questions have one right answer, but some (e.g. a guess that only
  // named a Pokemon generation, not which paired version) have several
  // equally-valid ones - question.accepted_answers holds all of them when
  // that applies, falling back to just question.answer when it's absent.
  function isCorrectGuess(rawGuess, question) {
    const accepted =
      Array.isArray(question.accepted_answers) && question.accepted_answers.length
        ? question.accepted_answers
        : [question.answer];
    const normalizedGuess = normalize(rawGuess);
    return accepted.some((a) => normalize(a) === normalizedGuess);
  }

  // ===== Reusable autocomplete (main game input + any number of daily cards) =====

  function createAutocomplete(inputEl, listEl) {
    let activeIndex = -1;

    function hide() {
      listEl.hidden = true;
      listEl.innerHTML = "";
      activeIndex = -1;
    }

    function render(value) {
      const query = normalize(value);
      if (!query) {
        hide();
        return;
      }
      const matches = autocompletePool.filter((title) => normalize(title).includes(query)).slice(0, 8);
      if (matches.length === 0) {
        hide();
        return;
      }
      listEl.innerHTML = "";
      matches.forEach((title) => {
        const li = document.createElement("li");
        li.textContent = title;
        li.addEventListener("mousedown", (e) => {
          e.preventDefault();
          inputEl.value = title;
          hide();
        });
        listEl.appendChild(li);
      });
      activeIndex = -1;
      listEl.hidden = false;
    }

    function moveActive(delta) {
      const items = Array.from(listEl.children);
      if (items.length === 0) return;
      if (activeIndex >= 0) items[activeIndex].classList.remove("active");
      activeIndex = (activeIndex + delta + items.length) % items.length;
      items[activeIndex].classList.add("active");
      inputEl.value = items[activeIndex].textContent;
    }

    inputEl.addEventListener("input", () => render(inputEl.value));
    inputEl.addEventListener("blur", () => setTimeout(hide, 100));
    inputEl.addEventListener("keydown", (e) => {
      if (listEl.hidden) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        moveActive(1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        moveActive(-1);
      } else if (e.key === "Escape") {
        hide();
      }
    });

    return { hide };
  }

  // ===== Streaks (main game) =====

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

  function buildQueue(avoidId) {
    const seen = JSON.parse(localStorage.getItem(STORAGE_KEYS.seen) || "[]");
    let unseen = questions.filter((q) => !seen.includes(q.id));
    if (unseen.length === 0) {
      // Full pool just got exhausted - reset for a new cycle. The just-answered
      // question (avoidId) is back in the mix now, so without the swap below it
      // could immediately repeat if the shuffle happens to put it last (next to
      // be served) - no question should repeat until every other one has shown.
      localStorage.setItem(STORAGE_KEYS.seen, "[]");
      unseen = questions.slice();
    }
    // Fisher-Yates shuffle
    for (let i = unseen.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [unseen[i], unseen[j]] = [unseen[j], unseen[i]];
    }
    // queue.pop() serves from the end of this array - keep the just-answered
    // question out of that spot so it can't be served back-to-back.
    const lastIdx = unseen.length - 1;
    if (lastIdx > 0 && unseen[lastIdx].id === avoidId) {
      [unseen[lastIdx], unseen[0]] = [unseen[0], unseen[lastIdx]];
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
    if (questions.length === 0) {
      el.prompt.textContent = "No questions available yet — check back soon!";
      el.guessForm.hidden = true;
      el.hintsSection.hidden = true;
      return;
    }
    if (queue.length === 0) buildQueue(currentQuestion ? currentQuestion.id : null);
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
    if (mainAutocomplete) mainAutocomplete.hide();

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

  async function renderGlobalStatInto(questionId, targetEl) {
    if (!supabaseClient) {
      targetEl.textContent = "Community stats unavailable.";
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
        targetEl.textContent = "Be the first to answer this one!";
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
      targetEl.textContent = `${pct}% of ${total} player${total === 1 ? "" : "s"} got this right.`;
    } catch (err) {
      console.warn("Failed to load stats:", err);
      targetEl.textContent = "Community stats unavailable.";
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

    el.globalStat.textContent = "Loading community stats…";
    renderGlobalStatInto(currentQuestion.id, el.globalStat);
    el.nextBtn.hidden = false;
    el.giveUpBtn.disabled = true;
    el.guessInput.disabled = true;
    if (mainAutocomplete) mainAutocomplete.hide();
  }

  function handleGuess(rawGuess) {
    if (answered || !currentQuestion) return;
    answered = true;
    const correct = isCorrectGuess(rawGuess, currentQuestion);

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

  // ===== Daily Challenge =====
  // "Gaming day" runs 1am-to-1am Pacific time, not midnight-to-midnight - see
  // getDailyPeriodKey(). The 3 questions are picked deterministically from a
  // hash of (period key + question id), so every visitor worldwide computes the
  // exact same 3 independently, with no server/cron needed for the rotation
  // itself. An answer is only ever revealed once its period key no longer
  // matches the CURRENT period key - i.e. once the next rotation has happened -
  // which naturally implements the "reveal after 24h" requirement without
  // needing to track exact reveal timestamps.

  function getLaParts(date) {
    const fmt = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      hour12: false,
    });
    const parts = {};
    fmt.formatToParts(date).forEach((p) => {
      if (p.type !== "literal") parts[p.type] = p.value;
    });
    return parts;
  }

  function getDailyPeriodKey(date) {
    date = date || new Date();
    const p = getLaParts(date);
    let hour = parseInt(p.hour, 10);
    if (hour === 24) hour = 0; // some environments report midnight as "24"
    const periodDate = new Date(
      Date.UTC(parseInt(p.year, 10), parseInt(p.month, 10) - 1, parseInt(p.day, 10))
    );
    if (hour < 1) {
      periodDate.setUTCDate(periodDate.getUTCDate() - 1);
    }
    return periodDate.toISOString().slice(0, 10);
  }

  function dailyHash(str) {
    // FNV-1a - fast, deterministic, good-enough distribution for this.
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }

  function pickDailyQuestions(periodKey) {
    if (questions.length === 0) return [];
    const count = Math.min(3, questions.length);
    const scored = questions.map((q) => ({ q, score: dailyHash(periodKey + "|" + q.id) }));
    scored.sort((a, b) => a.score - b.score);
    return scored.slice(0, count).map((s) => s.q);
  }

  function getDailyAttempts() {
    try {
      return JSON.parse(localStorage.getItem(DAILY_STORAGE_KEY) || "{}");
    } catch (e) {
      return {};
    }
  }

  function saveDailyAttempt(periodKey, questionId, attempt) {
    const all = getDailyAttempts();
    if (!all[periodKey]) all[periodKey] = {};
    all[periodKey][questionId] = attempt;
    localStorage.setItem(DAILY_STORAGE_KEY, JSON.stringify(all));
  }

  function dailyQuestionStatId(periodKey, questionId) {
    return `daily-${periodKey}-${questionId}`;
  }

  function handleDailyGuess(question, periodKey, rawGuess) {
    if (!rawGuess.trim()) return;
    const correct = isCorrectGuess(rawGuess, question);
    saveDailyAttempt(periodKey, question.id, {
      correct,
      guess: rawGuess,
      answeredAt: new Date().toISOString(),
    });
    submitStatToSupabase(dailyQuestionStatId(periodKey, question.id), correct);
    renderDailySection();
  }

  function buildDailyCard(question, index, periodKey, isCurrentPeriod, attempt) {
    const card = document.createElement("div");
    card.className = "daily-card";

    const header = document.createElement("div");
    header.className = "daily-card-header";
    const label = document.createElement("span");
    label.className = "daily-card-label";
    label.textContent = `Question ${index + 1} of 3`;
    header.appendChild(label);
    if (attempt) {
      const status = document.createElement("span");
      status.className = "daily-card-status " + (attempt.correct ? "correct" : "incorrect");
      status.textContent = attempt.correct ? "Correct" : "Missed";
      header.appendChild(status);
    }
    card.appendChild(header);

    const promptEl = document.createElement("p");
    promptEl.className = "daily-card-prompt";
    promptEl.textContent = question.prompt;
    card.appendChild(promptEl);

    if (isCurrentPeriod && !attempt) {
      const form = document.createElement("form");
      form.className = "daily-guess-form";
      form.setAttribute("autocomplete", "off");

      const wrap = document.createElement("div");
      wrap.className = "autocomplete-wrap";
      const input = document.createElement("input");
      input.type = "text";
      input.placeholder = "Type a game title…";
      input.setAttribute("autocomplete", "off");
      input.setAttribute("aria-label", `Your guess for question ${index + 1}`);
      const list = document.createElement("ul");
      list.className = "autocomplete-list";
      list.hidden = true;
      wrap.appendChild(input);
      wrap.appendChild(list);

      const submitBtn = document.createElement("button");
      submitBtn.type = "submit";
      submitBtn.className = "btn btn-primary";
      submitBtn.textContent = "Guess";

      form.appendChild(wrap);
      form.appendChild(submitBtn);
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        handleDailyGuess(question, periodKey, input.value);
      });
      card.appendChild(form);

      createAutocomplete(input, list);
    } else if (!isCurrentPeriod) {
      // A past period's attempt - the period has ended, so fully reveal.
      const revealWrap = document.createElement("div");
      revealWrap.className = "daily-card-revealed";
      if (question.cover_art_url) {
        const img = document.createElement("img");
        img.src = question.cover_art_url;
        img.alt = question.answer + " cover art";
        revealWrap.appendChild(img);
      }
      const details = document.createElement("div");
      const answerNameEl = document.createElement("p");
      answerNameEl.className = "answer-name";
      answerNameEl.textContent = question.answer;
      details.appendChild(answerNameEl);

      const statEl = document.createElement("p");
      statEl.className = "global-stat";
      statEl.textContent = "Loading community stats…";
      details.appendChild(statEl);
      renderGlobalStatInto(dailyQuestionStatId(periodKey, question.id), statEl);

      if (question.permalink) {
        const link = document.createElement("a");
        link.className = "permalink-link";
        link.href = question.permalink;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = "View original post on Reddit";
        details.appendChild(link);
      }
      revealWrap.appendChild(details);
      card.appendChild(revealWrap);
    } else {
      // Current period, already attempted: acknowledge it, but the answer
      // stays hidden until the next rotation.
      const locked = document.createElement("p");
      locked.className = "daily-card-locked";
      locked.textContent =
        `You guessed "${attempt.guess}" — ${attempt.correct ? "correct!" : "not quite."} ` +
        "The answer reveals after today's period ends at 1am PST.";
      card.appendChild(locked);
    }

    return card;
  }

  function updateDailyShareButton(periodKey, dailyQuestions, attempts) {
    const todaysAttempts = attempts[periodKey] || {};
    const allAnswered = dailyQuestions.length > 0 && dailyQuestions.every((q) => todaysAttempts[q.id]);
    if (!allAnswered) {
      el.dailyShareBtn.hidden = true;
      return;
    }
    el.dailyShareBtn.hidden = false;
    el.dailyShareBtn.onclick = () => {
      const emojis = dailyQuestions.map((q) => (todaysAttempts[q.id].correct ? "✅" : "❌")).join("");
      const correctCount = dailyQuestions.filter((q) => todaysAttempts[q.id].correct).length;
      const url = window.location.origin + window.location.pathname;
      const text =
        `Explain a Game Plot Badly — Daily Challenge (${periodKey})\n` +
        `${emojis} ${correctCount}/${dailyQuestions.length}\n` +
        `Play today's 3: ${url}`;
      navigator.clipboard
        .writeText(text)
        .then(() => {
          el.dailyShareBtn.textContent = "Copied!";
          setTimeout(() => {
            el.dailyShareBtn.textContent = "Copy results to share";
          }, 2000);
        })
        .catch(() => {
          el.dailyShareBtn.textContent = "Couldn't copy — try manually";
        });
    };
  }

  function getPreviousPeriodKey(periodKey) {
    const d = new Date(periodKey + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() - 1);
    return d.toISOString().slice(0, 10);
  }

  function renderDailySection() {
    if (!el.dailyCards || questions.length === 0) return;
    const periodKey = getDailyPeriodKey();
    const attempts = getDailyAttempts();
    const dailyQuestions = pickDailyQuestions(periodKey);

    el.dailyCards.innerHTML = "";

    dailyQuestions.forEach((q, i) => {
      const attempt = (attempts[periodKey] || {})[q.id];
      el.dailyCards.appendChild(buildDailyCard(q, i, periodKey, true, attempt));
    });

    // Yesterday's set is deterministic from its period key alone (same hash
    // everyone else's browser computes), so its answers are shown to every
    // visitor - not just whoever's browser happens to have a local attempt
    // recorded for it - underneath today's questions.
    const previousPeriodKey = getPreviousPeriodKey(periodKey);
    const previousAttempts = attempts[previousPeriodKey] || {};
    const previousHeading = document.createElement("h3");
    previousHeading.className = "daily-subheading";
    previousHeading.textContent = "Yesterday's Answers";
    el.dailyCards.appendChild(previousHeading);

    pickDailyQuestions(previousPeriodKey).forEach((q, i) => {
      const attempt = previousAttempts[q.id];
      el.dailyCards.appendChild(buildDailyCard(q, i, previousPeriodKey, false, attempt));
    });

    updateDailyShareButton(periodKey, dailyQuestions, attempts);
  }

  // ===== Wiring =====

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

    mainAutocomplete = createAutocomplete(el.guessInput, el.autocompleteList);
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
    renderDailySection();
  }

  init();
})();
