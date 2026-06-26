/**
 * Live Poll App — Presenter Control Page
 *
 * Fetches all polls (visible and hidden) from the authenticated presenter endpoint,
 * renders toggle buttons for visibility control, and connects to WebSocket for
 * real-time state sync with other presenter instances.
 */

(function () {
    "use strict";

    // --- Configuration ---
    // Resolve backend from ?backend= query param (same logic as participant page)
    var BACKEND_KEYS = ["ec2", "ecs", "lambda"];
    var params = new URLSearchParams(window.location.search);
    var backendParam = params.get("backend");
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
    const accessDenied = document.getElementById("access-denied");

    // --- State ---
    let currentPolls = [];
    let ws = null;
    let reconnectAttempts = 0;
    const MAX_RECONNECT_ATTEMPTS = 3;
    const RECONNECT_DELAY = 2000;

    // --- Auth ---
    const key = params.get("key");

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

    /**
     * Derive WebSocket URL from the API URL.
     * http://... -> ws://...
     * https://... -> wss://...
     */
    function getWsUrl() {
        var wsUrl = API_URL.replace(/^http/, "ws");
        return wsUrl + "/ws";
    }

    // --- API ---

    /**
     * Fetch all polls from the presenter endpoint (includes hidden polls).
     */
    async function fetchPresenterPolls() {
        const response = await fetch(API_URL + "/presenter/polls?key=" + encodeURIComponent(key));
        if (response.status === 403) {
            throw new Error("ACCESS_DENIED");
        }
        if (!response.ok) {
            throw new Error("Failed to fetch polls");
        }
        return response.json();
    }

    /**
     * Toggle a poll's visibility via PATCH.
     */
    async function patchVisibility(pollId, newVisibility) {
        const response = await fetch(API_URL + "/polls/" + pollId + "/visibility?key=" + encodeURIComponent(key), {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ visibility: newVisibility }),
        });
        if (!response.ok) {
            throw new Error("Failed to update visibility");
        }
        return response.json();
    }

    // --- Rendering ---

    /**
     * Render a single poll row with toggle button.
     */
    function renderPollRow(poll) {
        const row = document.createElement("div");
        row.className = "presenter-poll-row";
        row.dataset.pollId = poll.poll_id;

        // Poll info
        const info = document.createElement("div");
        info.className = "presenter-poll-info";

        const question = document.createElement("span");
        question.className = "presenter-poll-question";
        question.textContent = poll.question;
        info.appendChild(question);

        const status = document.createElement("span");
        status.className = "presenter-poll-status";
        status.textContent = poll.visible ? "Visible" : "Hidden";
        status.classList.add(poll.visible ? "status-visible" : "status-hidden");
        info.appendChild(status);

        const votes = document.createElement("span");
        votes.className = "presenter-poll-votes";
        votes.textContent = poll.total_votes ? poll.total_votes + " vote" + (poll.total_votes !== 1 ? "s" : "") : "No votes yet";
        info.appendChild(votes);

        row.appendChild(info);

        // Toggle button
        const toggleBtn = document.createElement("button");
        toggleBtn.type = "button";
        toggleBtn.className = "presenter-toggle-btn";
        toggleBtn.classList.add(poll.visible ? "toggle-hide" : "toggle-show");
        toggleBtn.textContent = poll.visible ? "Hide" : "Show";
        toggleBtn.setAttribute("aria-label", (poll.visible ? "Hide" : "Show") + " poll: " + poll.question);

        toggleBtn.addEventListener("click", function () {
            handleToggle(poll.poll_id, poll.visible ? "hidden" : "visible", row);
        });

        row.appendChild(toggleBtn);

        // Inline error placeholder
        const errorSlot = document.createElement("p");
        errorSlot.className = "presenter-row-error hidden";
        row.appendChild(errorSlot);

        return row;
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
            pollsContainer.appendChild(renderPollRow(poll));
        });
    }

    /**
     * Update a single poll row's vote count display.
     */
    function updateVoteCount(pollId, totalVotes) {
        var row = pollsContainer.querySelector('[data-poll-id="' + pollId + '"]');
        if (!row) return;
        var votesEl = row.querySelector(".presenter-poll-votes");
        if (votesEl) {
            votesEl.textContent = totalVotes ? totalVotes + " vote" + (totalVotes !== 1 ? "s" : "") : "No votes yet";
        }
    }

    /**
     * Update a single poll row's UI to reflect new visibility state.
     */
    function updatePollRowState(pollId, visible) {
        var row = pollsContainer.querySelector('[data-poll-id="' + pollId + '"]');
        if (!row) return;

        // Update status text
        var status = row.querySelector(".presenter-poll-status");
        if (status) {
            status.textContent = visible ? "Visible" : "Hidden";
            status.classList.remove("status-visible", "status-hidden");
            status.classList.add(visible ? "status-visible" : "status-hidden");
        }

        // Update toggle button
        var btn = row.querySelector(".presenter-toggle-btn");
        if (btn) {
            btn.textContent = visible ? "Hide" : "Show";
            btn.classList.remove("toggle-hide", "toggle-show");
            btn.classList.add(visible ? "toggle-hide" : "toggle-show");
            var question = row.querySelector(".presenter-poll-question");
            var qText = question ? question.textContent : "";
            btn.setAttribute("aria-label", (visible ? "Hide" : "Show") + " poll: " + qText);
        }

        // Update in-memory state
        var poll = currentPolls.find(function (p) { return p.poll_id === pollId; });
        if (poll) {
            poll.visible = visible;
        }
    }

    // --- Toggle Handler ---

    /**
     * Handle a toggle button click.
     */
    async function handleToggle(pollId, newVisibility, row) {
        var btn = row.querySelector(".presenter-toggle-btn");
        var errorSlot = row.querySelector(".presenter-row-error");

        // Disable button during request
        btn.disabled = true;
        errorSlot.classList.add("hidden");
        errorSlot.textContent = "";

        try {
            await patchVisibility(pollId, newVisibility);

            // Success — update UI
            var isNowVisible = newVisibility === "visible";
            updatePollRowState(pollId, isNowVisible);
        } catch (err) {
            // Failure — show inline error, don't change toggle state
            errorSlot.textContent = "Failed to update visibility. Please try again.";
            errorSlot.classList.remove("hidden");
        } finally {
            btn.disabled = false;
        }
    }

    // --- WebSocket ---

    /**
     * Connect to WebSocket for real-time visibility sync.
     */
    function connectWebSocket() {
        var wsUrl = getWsUrl();

        try {
            ws = new WebSocket(wsUrl);
        } catch (e) {
            return;
        }

        ws.onopen = function () {
            reconnectAttempts = 0;
        };

        ws.onmessage = function (event) {
            try {
                var data = JSON.parse(event.data);

                if (data.event === "visibility_change" && data.poll) {
                    updatePollRowState(data.poll.poll_id, data.poll.visible);
                }

                if (data.event === "vote_update" && data.poll) {
                    var poll = currentPolls.find(function (p) { return p.poll_id === data.poll.poll_id; });
                    if (poll) {
                        poll.options = data.poll.options;
                        poll.total_votes = data.poll.total_votes;
                    }
                    updateVoteCount(data.poll.poll_id, data.poll.total_votes);
                }
            } catch (e) {
                // Ignore malformed messages
            }
        };

        ws.onclose = function () {
            attemptReconnect();
        };

        ws.onerror = function () {
            // onclose will fire after onerror
        };
    }

    /**
     * Attempt to reconnect to WebSocket with retry logic.
     */
    function attemptReconnect() {
        if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            // Fall back to polling
            startPolling();
            return;
        }

        reconnectAttempts++;
        setTimeout(function () {
            connectWebSocket();
        }, RECONNECT_DELAY);
    }

    /**
     * Fall back to polling GET /presenter/polls every 5 seconds.
     */
    function startPolling() {
        setInterval(async function () {
            try {
                var polls = await fetchPresenterPolls();
                // Update UI for any polls whose state changed
                polls.forEach(function (poll) {
                    var existing = currentPolls.find(function (p) { return p.poll_id === poll.poll_id; });
                    if (existing && existing.visible !== poll.visible) {
                        updatePollRowState(poll.poll_id, poll.visible);
                    }
                });
                currentPolls = polls;
            } catch (e) {
                // Silently fail — will retry on next interval
            }
        }, 5000);
    }

    // --- Initialisation ---

    /**
     * Load polls and start WebSocket connection.
     */
    async function init() {
        hideError();

        // Check for key
        if (!key) {
            accessDenied.classList.remove("hidden");
            pollsContainer.classList.add("hidden");
            return;
        }

        try {
            var polls = await fetchPresenterPolls();
            renderPolls(polls);
            connectWebSocket();
        } catch (err) {
            if (err.message === "ACCESS_DENIED") {
                accessDenied.classList.remove("hidden");
                pollsContainer.classList.add("hidden");
            } else {
                showError("Unable to load polls — please try again later.");
                emptyState.classList.add("hidden");
            }
        }
    }

    // Start
    init();
})();
