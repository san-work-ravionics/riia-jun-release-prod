const API = window.RITA_API_BASE || "";

async function loadUserTraffic() {
    const token = sessionStorage.getItem("auth_token") || "";

    try {
        const headers = token ? { "Authorization": `Bearer ${token}` } : {};
        const res = await fetch(`${API}/api/v1/experience/users/traffic`, { headers });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        const s = data.summary;
        document.getElementById("ut-total-users").textContent = s.total_users ?? "—";
        document.getElementById("ut-active-today").textContent = s.active_today ?? "—";
        document.getElementById("ut-active-week").textContent = s.active_this_week ?? "—";
        document.getElementById("ut-active-month").textContent = s.active_this_month ?? "—";
        document.getElementById("ut-total-logins").textContent = s.total_logins_all_time ?? "—";

        renderChart(data.daily);
        renderTable(data.daily);
    } catch (e) {
        ["ut-total-users","ut-active-today","ut-active-week","ut-active-month","ut-total-logins"]
            .forEach(id => { document.getElementById(id).textContent = "—"; });
        const tbody = document.getElementById("ut-daily-tbody");
        if (tbody) tbody.innerHTML = `<tr><td colspan="4">Failed to load data</td></tr>`;
    }
}

function renderChart(daily) {
    const labels = daily.map(r => r.date).reverse();
    const values = daily.map(r => r.total_logins).reverse();
    const ctx = document.getElementById("ut-logins-chart").getContext("2d");
    new Chart(ctx, {
        type: "bar",
        data: {
            labels,
            datasets: [{ label: "Logins", data: values, backgroundColor: "rgba(99,102,241,0.7)" }]
        },
        options: {
            responsive: true,
            scales: {
                x: { ticks: { maxTicksLimit: 6 } },
                y: { beginAtZero: true }
            }
        }
    });
}

function renderTable(daily) {
    const tbody = document.getElementById("ut-daily-tbody");
    tbody.innerHTML = daily.map(r =>
        `<tr><td>${r.date}</td><td>${r.unique_users}</td><td>${r.total_logins}</td><td>${r.new_registrations}</td></tr>`
    ).join("");
}

document.addEventListener("DOMContentLoaded", loadUserTraffic);
