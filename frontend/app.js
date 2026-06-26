/**
 * Live Poll App — Participant Frontend
 *
 * Fetches visible polls from the backend, renders vote buttons,
 * handles vote submission, displays horizontal bar chart results,
 * and connects via WebSocket for real-time vote and visibility updates
 * with automatic reconnection and fallback polling.
 */

(function () {
    "use strict";

    // --- Configuration ---
    // Resolve the backend from the ?backend= query parameter
    var BACKEND_KEYS = ["ec2", "ecs", "lambda"];
    var backendParam = new URLSearchParams(window.location.search).get("backend");
    var activeBackendKey = null;
    var API_URL;

    if (backendParam === "random") {
        activeBackendKey = BACKEND_KEYS[Math.floor(Math.random() * BACKEND_KEYS.length)];
    } else if (backendParam && BACKEND_KEYS.indexOf(backendParam) !== -1) {
        activeBackendKey = backendParam;
    }

    if (activeBackendKey && window.BACKENDS && window.BACKENDS[activeBackendKey]) {
        API_URL = window.BACKENDS[activeBackendKey].url.replace(/\/+$/, "");
    } else {
        API_URL = (window.API_URL || "http://localhost:8000").replace(/\/+$/, "");
    }

    // --- DOM References ---
    const pollsContainer = document.getElementById("polls-container");
    const emptyState = document.getElementById("empty-state");
    const errorBanner = document.getElementById("error-banner");

    // --- Backend Badge ---
    // Show a coloured indicator of which backend the user is connected to
    (function showBackendBadge() {
        var badge = document.getElementById("backend-badge");
        if (!badge || !activeBackendKey || !window.BACKENDS) return;
        var info = window.BACKENDS[activeBackendKey];
        if (!info) return;
        badge.textContent = info.label;
        badge.style.backgroundColor = info.color;
        badge.classList.remove("hidden");
    })();

    // --- State ---
    // Keeps the latest poll data in memory for re-rendering on updates
    let currentPolls = [];

    // --- Helpers ---

    /**
     * Show the global error banner.
     */
    function showError(message) {
        errorBanner.textContent = message;
        errorBanner.classList.remove("hidden");
    }

    /**
     * Hide the global error banner.
     */
    function hideError() {
        errorBanner.textContent = "";
        errorBanner.classList.add("hidden");
    }

    // --- API ---

    /**
     * Fetch visible polls from the backend.
     */
    async function fetchPolls() {
        const response = await fetch(API_URL + "/polls");
        if (!response.ok) {
            throw new Error("Failed to fetch polls");
        }
        return response.json();
    }

    /**
     * Submit a vote to the backend.
     */
    async function submitVote(pollId, optionId) {
        const response = await fetch(API_URL + "/polls/" + pollId + "/votes", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ option_id: optionId }),
        });
        if (!response.ok) {
            throw new Error("Vote failed");
        }
        return response.json();
    }

    // --- Rendering ---

    /**
     * Render a single poll card with vote buttons and live results.
     */
    function renderPollCard(poll) {
        const card = document.createElement("article");
        card.className = "poll-card";
        card.dataset.pollId = poll.poll_id;

        // Question
        const question = document.createElement("h2");
        question.className = "poll-question";
        question.textContent = poll.question;
        card.appendChild(question);

        // Always show vote buttons
        card.appendChild(renderOptions(poll));

        // Always show results below
        card.appendChild(renderResults(poll));

        return card;
    }

    /**
     * Render vote option buttons for a poll.
     */
    function renderOptions(poll) {
        const optionsDiv = document.createElement("div");
        optionsDiv.className = "poll-options";

        poll.options.forEach(function (option) {
            const btn = document.createElement("button");
            btn.className = "option-btn";
            btn.type = "button";
            btn.textContent = option.label;
            btn.setAttribute("aria-label", "Vote for " + option.label);
            btn.dataset.optionId = option.option_id;

            btn.addEventListener("click", function () {
                handleVote(poll.poll_id, option.option_id, optionsDiv);
            });

            optionsDiv.appendChild(btn);
        });

        return optionsDiv;
    }

    /**
     * Render horizontal bar chart results for a poll.
     */
    function renderResults(poll) {
        const resultsDiv = document.createElement("div");
        resultsDiv.className = "poll-results";

        const totalVotes = poll.total_votes || 0;

        poll.options.forEach(function (option) {
            const row = document.createElement("div");
            row.className = "result-row";

            // Label
            const label = document.createElement("span");
            label.className = "result-label";
            label.textContent = option.label;
            label.title = option.label;
            row.appendChild(label);

            // Bar container
            const barContainer = document.createElement("div");
            barContainer.className = "result-bar-container";
            barContainer.setAttribute("role", "progressbar");
            const pct = totalVotes > 0 ? Math.round((option.vote_count / totalVotes) * 100) : 0;
            barContainer.setAttribute("aria-valuenow", String(pct));
            barContainer.setAttribute("aria-valuemin", "0");
            barContainer.setAttribute("aria-valuemax", "100");
            barContainer.setAttribute("aria-label", option.label + " — " + pct + "%");

            const bar = document.createElement("div");
            bar.className = "result-bar";
            bar.style.width = pct + "%";
            barContainer.appendChild(bar);
            row.appendChild(barContainer);

            // Stats
            const stats = document.createElement("span");
            stats.className = "result-stats";
            stats.textContent = option.vote_count + " (" + pct + "%)";
            row.appendChild(stats);

            resultsDiv.appendChild(row);
        });

        return resultsDiv;
    }

    /**
     * Render all polls into the container.
     */
    function renderPolls(polls) {
        currentPolls = polls;
        pollsContainer.innerHTML = "";

        if (!polls || polls.length === 0) {
            emptyState.classList.remove("hidden");
            return;
        }

        emptyState.classList.add("hidden");

        polls.forEach(function (poll) {
            pollsContainer.appendChild(renderPollCard(poll));
        });
    }

    // --- Vote Handler ---

    /**
     * Handle a vote button click. Allows unlimited voting.
     */
    async function handleVote(pollId, optionId, optionsContainer) {
        // Disable all buttons while the request is in flight
        var buttons = optionsContainer.querySelectorAll(".option-btn");
        buttons.forEach(function (btn) {
            btn.disabled = true;
        });

        // Remove any previous inline error
        var existingError = optionsContainer.parentElement.querySelector(".vote-error");
        if (existingError) {
            existingError.remove();
        }

        try {
            await submitVote(pollId, optionId);

            // Re-fetch polls to get updated counts
            try {
                var updatedPolls = await fetchPolls();
                renderPolls(updatedPolls);
            } catch (_) {
                // If re-fetch fails, just re-enable buttons
                buttons.forEach(function (btn) { btn.disabled = false; });
            }
        } catch (err) {
            buttons.forEach(function (btn) {
                btn.disabled = false;
            });

            var errorMsg = document.createElement("p");
            errorMsg.className = "vote-error";
            errorMsg.textContent = "Your vote could not be recorded — please try again.";
            optionsContainer.parentElement.appendChild(errorMsg);
        }
    }

    // --- Initialisation ---

    /**
     * Load polls on page start.
     */
    async function init() {
        hideError();

        try {
            var polls = await fetchPolls();
            renderPolls(polls);
        } catch (err) {
            showError("Unable to load polls — please try again later.");
            emptyState.classList.add("hidden");
        }
    }

    // --- Public API for WebSocket updates ---
    window.LivePoll = {
        renderPolls: renderPolls,
        getCurrentPolls: function () { return currentPolls; },
        fetchAndRender: init,
    };

    // --- WebSocket Real-Time Updates ---

    /**
     * Get WebSocket URL. Uses explicit ws property from BACKENDS config if available,
     * otherwise falls back to window.WS_URL, otherwise derives from API_URL + /ws.
     */
    function getWebSocketUrl() {
        if (activeBackendKey && window.BACKENDS && window.BACKENDS[activeBackendKey] && window.BACKENDS[activeBackendKey].ws) {
            return window.BACKENDS[activeBackendKey].ws;
        }
        if (window.WS_URL) {
            return window.WS_URL;
        }
        var wsUrl = API_URL.replace(/^http:\/\//, "ws://").replace(/^https:\/\//, "wss://");
        return wsUrl + "/ws";
    }

    var ws = null;
    var reconnectAttempts = 0;
    var maxReconnectAttempts = 3;
    var reconnectDelay = 2000; // 2 seconds
    var reconnectTimer = null;
    var pollingInterval = null;

    /**
     * Stop the fallback polling interval if it's running.
     */
    function stopPolling() {
        if (pollingInterval !== null) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
    }

    /**
     * Start fallback polling: GET /polls every 5 seconds.
     */
    function startFallbackPolling() {
        stopPolling();
        pollingInterval = setInterval(function () {
            fetchPolls()
                .then(function (polls) {
                    renderPolls(polls);
                })
                .catch(function () {
                    // Silently ignore polling errors
                });
        }, 5000);
    }

    /**
     * Handle an incoming WebSocket message.
     */
    function handleWebSocketMessage(event) {
        var data;
        try {
            data = JSON.parse(event.data);
        } catch (e) {
            return; // Ignore malformed messages
        }

        if (data.event === "vote_update" && data.poll) {
            handleVoteUpdate(data.poll);
        } else if (data.event === "visibility_change" && data.poll) {
            handleVisibilityChange(data.poll);
        }
    }

    /**
     * Handle a vote_update event: update the affected poll's data and re-render its card.
     */
    function handleVoteUpdate(updatedPoll) {
        var index = -1;
        for (var i = 0; i < currentPolls.length; i++) {
            if (currentPolls[i].poll_id === updatedPoll.poll_id) {
                index = i;
                break;
            }
        }

        if (index === -1) {
            // Poll not currently displayed (maybe not voted on yet or hidden) — ignore
            return;
        }

        // Update in-memory state
        currentPolls[index] = updatedPoll;

        // Re-render just that card
        var existingCard = pollsContainer.querySelector('[data-poll-id="' + updatedPoll.poll_id + '"]');
        if (existingCard) {
            var newCard = renderPollCard(updatedPoll);
            pollsContainer.replaceChild(newCard, existingCard);
        }
    }

    /**
     * Handle a visibility_change event: add or remove poll from display.
     */
    function handleVisibilityChange(poll) {
        if (poll.visible) {
            // Add poll if not already displayed
            var exists = false;
            for (var i = 0; i < currentPolls.length; i++) {
                if (currentPolls[i].poll_id === poll.poll_id) {
                    exists = true;
                    // Update in place in case data changed
                    currentPolls[i] = poll;
                    break;
                }
            }
            if (!exists) {
                currentPolls.push(poll);
            }
            renderPolls(currentPolls);
        } else {
            // Remove poll from display
            var filtered = [];
            for (var i = 0; i < currentPolls.length; i++) {
                if (currentPolls[i].poll_id !== poll.poll_id) {
                    filtered.push(currentPolls[i]);
                }
            }
            renderPolls(filtered);
        }
    }

    /**
     * Attempt to reconnect the WebSocket.
     * After 3 failed attempts, fall back to polling.
     */
    function attemptReconnect() {
        if (reconnectAttempts >= maxReconnectAttempts) {
            // All retries exhausted — fall back to polling
            startFallbackPolling();
            return;
        }

        reconnectAttempts++;
        reconnectTimer = setTimeout(function () {
            connectWebSocket();
        }, reconnectDelay);
    }

    /**
     * Connect to the WebSocket endpoint.
     */
    function connectWebSocket() {
        var wsUrl = getWebSocketUrl();

        try {
            ws = new WebSocket(wsUrl);
        } catch (e) {
            attemptReconnect();
            return;
        }

        ws.onopen = function () {
            // Connection successful — reset reconnect state and stop any polling
            reconnectAttempts = 0;
            stopPolling();
            if (reconnectTimer !== null) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
        };

        ws.onmessage = handleWebSocketMessage;

        ws.onclose = function () {
            ws = null;
            attemptReconnect();
        };

        ws.onerror = function () {
            // Close will fire after error, triggering reconnection
            if (ws) {
                ws.close();
            }
        };
    }

    // Expose WebSocket control on LivePoll for testing/debugging
    window.LivePoll.connectWebSocket = connectWebSocket;
    window.LivePoll.stopPolling = stopPolling;

    // Start the app
    init();

    // Connect WebSocket after initial load (falls back to polling if WS fails)
    connectWebSocket();
})();
