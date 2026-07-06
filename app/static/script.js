document.addEventListener("DOMContentLoaded", () => {
    const scheduleDateInput = document.getElementById("schedule-date");
    const refreshBtn = document.getElementById("refresh-btn");
    const scheduleBody = document.getElementById("schedule-body");
    const chatFeed = document.getElementById("chat-feed");
    const chatForm = document.getElementById("chat-form");
    const chatInput = document.getElementById("chat-input");
    const simPhone = document.getElementById("sim-phone");
    const simName = document.getElementById("sim-name");
    const modelBadge = document.getElementById("model-badge");
    const syncBadge = document.getElementById("sync-badge");
    const quickChips = document.querySelectorAll(".chip");

    // Initialize default date to today
    const today = new Date().toISOString().split("T")[0];
    scheduleDateInput.value = today;

    // Fetch config & schedule on load
    loadSystemConfig();
    fetchSchedule(today);

    // Event listeners
    scheduleDateInput.addEventListener("change", (e) => fetchSchedule(e.target.value));
    refreshBtn.addEventListener("click", () => fetchSchedule(scheduleDateInput.value));

    quickChips.forEach(chip => {
        chip.addEventListener("click", () => {
            chatInput.value = chip.getAttribute("data-text");
            chatForm.dispatchEvent(new Event("submit", { cancelable: true }));
        });
    });

    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = chatInput.value.trim();
        if (!text) return;

        // Clear input and display user message
        chatInput.value = "";
        appendMessage("user", text);

        // Display typing indicator
        const typingId = appendTypingIndicator();

        try {
            const response = await fetch("/webhook/simulator", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    sender_phone: simPhone.value.trim() || "+15550192",
                    sender_name: simName.value.trim() || "Alex Customer",
                    message_text: text
                })
            });

            const data = await response.json();
            removeMessage(typingId);

            if (data.status === "success") {
                appendMessage("assistant", data.reply);
                // Refresh schedule table automatically to reflect new/cancelled bookings!
                fetchSchedule(scheduleDateInput.value);
            } else {
                appendMessage("assistant", "⚠️ Error: Gagal mendapatkan respons dari server.");
            }
        } catch (err) {
            console.error("Chat error:", err);
            removeMessage(typingId);
            appendMessage("assistant", "⚠️ Kesalahan Jaringan: Pastikan server FastAPI sedang berjalan.");
        }
    });

    async function loadSystemConfig() {
        try {
            const res = await fetch("/api/config");
            const conf = await res.json();
            
            if (conf.llm_model) {
                const modelShort = conf.llm_model.split("/").pop();
                modelBadge.textContent = `OpenRouter: ${modelShort}`;
            }
            if (conf.google_calendar_synced) {
                syncBadge.textContent = "🟢 Google Calendar Aktif";
                syncBadge.style.color = "#34d399";
                syncBadge.style.borderColor = "#34d399";
            } else {
                syncBadge.textContent = "🟡 Mode Database SQL Lokal";
            }
        } catch (err) {
            console.warn("Could not load backend config:", err);
        }
    }

    async function fetchSchedule(dateStr) {
        scheduleBody.innerHTML = `<tr><td colspan="3" class="loading-state">Memuat ketersediaan lapangan untuk tanggal ${dateStr}...</td></tr>`;
        try {
            const res = await fetch(`/api/schedule?date=${dateStr}`);
            const data = await res.json();
            renderScheduleTable(data.slots);
        } catch (err) {
            console.error("Schedule fetch error:", err);
            scheduleBody.innerHTML = `<tr><td colspan="3" style="color: #ef4444; padding: 20px;">Gagal memuat jadwal. Pastikan server FastAPI sedang berjalan.</td></tr>`;
        }
    }

    function renderScheduleTable(slots) {
        if (!slots || slots.length === 0) {
            scheduleBody.innerHTML = `<tr><td colspan="3" style="padding: 20px;">Tidak ada slot operasional untuk tanggal ini.</td></tr>`;
            return;
        }

        scheduleBody.innerHTML = "";
        slots.forEach(slot => {
            const tr = document.createElement("tr");

            // Time column
            const tdTime = document.createElement("td");
            tdTime.className = "time-cell";
            tdTime.textContent = slot.time;
            tr.appendChild(tdTime);

            // Court 1 column
            const tdC1 = document.createElement("td");
            tdC1.className = `slot-cell ${slot.court_1_status.toLowerCase()}`;
            if (slot.court_1_status === "Available") {
                tdC1.innerHTML = `<span>🟢 Tersedia (Rp400.000/jam)</span>`;
            } else {
                const phoneStr1 = slot.court_1_phone ? ` (${slot.court_1_phone})` : '';
                tdC1.innerHTML = `<span>🔴 Terpesan</span> <span class="booking-badge">${slot.court_1_customer || 'Terisi'}${phoneStr1}</span>`;
            }
            tr.appendChild(tdC1);

            // Court 2 column
            const tdC2 = document.createElement("td");
            tdC2.className = `slot-cell ${slot.court_2_status.toLowerCase()}`;
            if (slot.court_2_status === "Available") {
                tdC2.innerHTML = `<span>🟢 Tersedia (Rp400.000/jam)</span>`;
            } else {
                const phoneStr2 = slot.court_2_phone ? ` (${slot.court_2_phone})` : '';
                tdC2.innerHTML = `<span>🔴 Terpesan</span> <span class="booking-badge">${slot.court_2_customer || 'Terisi'}${phoneStr2}</span>`;
            }
            tr.appendChild(tdC2);

            scheduleBody.appendChild(tr);
        });
    }

    function appendMessage(role, text) {
        const msgDiv = document.createElement("div");
        msgDiv.className = `message ${role}`;
        
        const bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.textContent = text;
        
        const timeSpan = document.createElement("span");
        timeSpan.className = "time";
        timeSpan.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        msgDiv.appendChild(bubble);
        msgDiv.appendChild(timeSpan);
        chatFeed.appendChild(msgDiv);
        
        chatFeed.scrollTop = chatFeed.scrollHeight;
        return msgDiv.id = `msg-${Date.now()}`;
    }

    function appendTypingIndicator() {
        const id = `typing-${Date.now()}`;
        const msgDiv = document.createElement("div");
        msgDiv.className = "message assistant";
        msgDiv.id = id;
        
        const bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.style.fontStyle = "italic";
        bubble.style.color = "#9ca3af";
        bubble.textContent = "🤖 Resepsionis AI sedang memeriksa jadwal & mengetik...";
        
        msgDiv.appendChild(bubble);
        chatFeed.appendChild(msgDiv);
        chatFeed.scrollTop = chatFeed.scrollHeight;
        return id;
    }

    function removeMessage(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }
});
