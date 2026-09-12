const $ = (id) => document.getElementById(id);

const CPU_ALERT_THRESHOLD = 80;
const MEMORY_ALERT_THRESHOLD = 90;
const DISK_ALERT_THRESHOLD = 90;
const BROWSER_NOTIFICATION_INTERVAL_MS = 0;
const DASHBOARD_REFRESH_INTERVAL_MS = 1000;
const SUPPORTING_DATA_REFRESH_INTERVAL_MS = 5000;

let soundEnabled = false;
let alertActive = false;
let audioContext = null;
let lastSoundAt = 0;
let lastEmailAlertAt = 0;
let lastBrowserAlertAt = 0;
let activeAlertTypes = new Set();
let cpuBrowserNotificationActive = false;
let refreshInFlight = false;
let supportingRefreshInFlight = false;
let inAppNotificationTimer = null;
let monitoringLogs = [];

function clampPercent(value) {
    return Math.max(0, Math.min(100, Number(value) || 0));
}

function setBar(id, value) {
    $(id).style.width = `${clampPercent(value)}%`;
}

function getAudioContext() {
    if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }

    return audioContext;
}

function playAlertSound() {
    if (!soundEnabled) return;

    const now = Date.now();
    if (now - lastSoundAt < 10000) return;
    lastSoundAt = now;

    const context = getAudioContext();
    const oscillator = context.createOscillator();
    const gain = context.createGain();

    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(880, context.currentTime);
    oscillator.frequency.setValueAtTime(660, context.currentTime + 0.18);

    gain.gain.setValueAtTime(0.0001, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.22, context.currentTime + 0.03);
    gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.42);

    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.45);
}

function browserNotificationsSupported() {
    return "Notification" in window;
}

function updateBrowserNotificationButton() {
    const button = $("browserNotificationToggle");
    if (!button) return;

    if (!browserNotificationsSupported()) {
        button.textContent = "Chrome Notify Unsupported";
        button.disabled = true;
        return;
    }

    if (Notification.permission === "granted") {
        button.textContent = "Chrome Notify On";
    } else if (Notification.permission === "denied") {
        button.textContent = "Chrome Notify Blocked";
    } else {
        button.textContent = "Enable Chrome Notify";
    }
}

function showInAppNotification(title, body) {
    const notification = $("inAppNotification");
    const titleElement = $("inAppNotificationTitle");
    const messageElement = $("inAppNotificationMessage");

    if (!notification || !titleElement || !messageElement) return;

    titleElement.textContent = title;
    messageElement.textContent = body;
    notification.classList.add("is-visible");

    if (inAppNotificationTimer) {
        clearTimeout(inAppNotificationTimer);
    }

    inAppNotificationTimer = setTimeout(() => {
        notification.classList.remove("is-visible");
    }, 6000);
}

function showBrowserNotification(title, body, options = {}) {
    const status = $("notificationStatus");
    const respectCooldown = options.respectCooldown ?? true;

    if (!browserNotificationsSupported() || Notification.permission !== "granted") {
        if (status) {
            status.textContent = "Chrome notification needs permission first.";
        }
        return false;
    }

    const now = Date.now();
    if (respectCooldown) {
        if (
            BROWSER_NOTIFICATION_INTERVAL_MS > 0
            && now - lastBrowserAlertAt < BROWSER_NOTIFICATION_INTERVAL_MS
        ) {
            return false;
        }
        lastBrowserAlertAt = now;
    }

    const notification = new Notification(title, {
        body,
        icon: "/favicon.ico",
        requireInteraction: false,
    });

    notification.onclick = () => {
        window.focus();
        notification.close();
    };

    if (status) {
        status.textContent = `Chrome notification requested: ${body}`;
    }

    return true;
}

async function requestBrowserNotificationPermission() {
    const status = $("notificationStatus");

    if (!browserNotificationsSupported()) {
        if (status) {
            status.textContent = "Chrome notifications are not supported in this browser.";
        }
        updateBrowserNotificationButton();
        return;
    }

    const permission = await Notification.requestPermission();
    updateBrowserNotificationButton();

    if (permission === "granted") {
        cpuBrowserNotificationActive = false;
        showBrowserNotification(
            "CPU Monitor notifications enabled",
            "Chrome will show CPU alerts immediately when CPU reaches 80%.",
            { respectCooldown: false }
        );
    } else if (status) {
        status.textContent = "Chrome notification permission was not allowed.";
    }
}

async function sendAlertNotification(alertTypes) {
    const status = $("notificationStatus");
    const now = Date.now();
    if (now - lastEmailAlertAt < 60000) return;
    lastEmailAlertAt = now;

    try {
        const res = await fetch("/api/notify-alert", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ alert_types: alertTypes }),
        });
        const data = await res.json();

        if (status) {
            if (data.status === "sent") {
                status.textContent = "Gmail notification sent to your account email.";
            } else if (data.status === "skipped") {
                status.textContent = "Gmail notification skipped because cooldown is active.";
            } else {
                status.textContent = data.error || "Gmail notification was not sent.";
            }
        }
    } catch (error) {
        console.error("Failed to request Gmail notification.", error);
        if (status) {
            status.textContent = "Gmail notification request failed.";
        }
    }
}

async function sendTestNotification() {
    const status = $("notificationStatus");
    if (status) {
        status.textContent = "Sending test Gmail notification...";
    }

    try {
        const res = await fetch("/api/test-notification", {
            method: "POST",
        });
        const data = await res.json();

        if (status) {
            status.textContent = data.status === "sent"
                ? "Test Gmail sent to your account email."
                : data.error || "Test Gmail was not sent.";
        }
    } catch (error) {
        console.error("Failed to send test Gmail notification.", error);
        if (status) {
            status.textContent = "Test Gmail request failed.";
        }
    }
}

function updateAlertState(data) {
    const alertPanel = $("alertPanel");
    const statusText = $("statusText");
    const alertTitle = $("alertTitle");
    const alertMessage = $("alertMessage");

    if (!alertPanel || !statusText || !alertTitle || !alertMessage) {
        return;
    }

    const cpuPercent = Number(data.cpu_percent);
    const memoryPercent = Number(data.memory_percent);
    const alerts = [];
    const alertTypes = [];

    if (cpuPercent >= CPU_ALERT_THRESHOLD) {
        alerts.push(`CPU is high at ${cpuPercent.toFixed(1)}%`);
        alertTypes.push("CPU");
    }

    if (memoryPercent >= MEMORY_ALERT_THRESHOLD) {
        alerts.push(`Memory is high at ${memoryPercent.toFixed(1)}%`);
        alertTypes.push("Memory");
    }

    if (Number(data.disk_percent) >= DISK_ALERT_THRESHOLD) {
        alerts.push(`Disk is high at ${Number(data.disk_percent).toFixed(1)}%`);
        alertTypes.push("Disk");
    }

    const hasAlert = alerts.length > 0;
    const newAlertTypes = alertTypes.filter((alertType) => !activeAlertTypes.has(alertType));
    alertPanel.classList.toggle("is-alert", hasAlert);
    statusText.textContent = hasAlert ? "Alert" : "Live";

    if (hasAlert) {
        alertTitle.textContent = "High system load detected";
        alertMessage.textContent = alerts.join(" - ");

        if (cpuPercent >= CPU_ALERT_THRESHOLD && !cpuBrowserNotificationActive) {
            const message = `CPU Usage: ${cpuPercent.toFixed(1)}%`;
            showInAppNotification("CPU Usage Alert", message);
            cpuBrowserNotificationActive = showBrowserNotification(
                "CPU Usage Alert",
                message
            );
        }

        if (!alertActive || newAlertTypes.length) {
            playAlertSound();
            sendAlertNotification(newAlertTypes.length ? newAlertTypes : alertTypes);
        }
    } else {
        alertTitle.textContent = "System load normal";
        alertMessage.textContent =
            `Sound alerts trigger when CPU reaches ${CPU_ALERT_THRESHOLD}%, memory reaches ${MEMORY_ALERT_THRESHOLD}%, or disk reaches ${DISK_ALERT_THRESHOLD}%.`;
    }

    alertActive = hasAlert;
    activeAlertTypes = new Set(alertTypes);

    if (cpuPercent < CPU_ALERT_THRESHOLD) {
        cpuBrowserNotificationActive = false;
    }
}

function setMonitoringPausedState() {
    const alertPanel = $("alertPanel");
    const statusText = $("statusText");
    const alertTitle = $("alertTitle");
    const alertMessage = $("alertMessage");

    if (alertPanel) {
        alertPanel.classList.remove("is-alert");
    }

    if (statusText) {
        statusText.textContent = "Stopped";
    }

    if (alertTitle) {
        alertTitle.textContent = "Monitoring paused";
    }

    if (alertMessage) {
        alertMessage.textContent = "Click Start to resume live CPU monitoring and alerts.";
    }

    alertActive = false;
    activeAlertTypes = new Set();
    cpuBrowserNotificationActive = false;
}

function updateMonitoringControls(isRunning) {
    const startButton = $("startMonitoringButton");
    const stopButton = $("stopMonitoringButton");
    const controlStatus = $("monitoringControlStatus");
    const statusText = $("statusText");

    if (startButton) {
        startButton.disabled = isRunning;
    }

    if (stopButton) {
        stopButton.disabled = !isRunning;
    }

    if (controlStatus) {
        controlStatus.textContent = isRunning
            ? "Monitoring is running. Metrics are being collected and saved."
            : "Monitoring is stopped. Latest saved metrics remain visible.";
    }

    if (statusText && !isRunning) {
        statusText.textContent = "Stopped";
    }
}

function renderCores(values) {
    const grid = $("coresGrid");
    grid.innerHTML = "";

    values.forEach((value, index) => {
        const card = document.createElement("div");
        card.className = "core-card";

        const top = document.createElement("div");
        top.className = "core-top";

        const label = document.createElement("span");
        label.textContent = `Core ${index + 1}`;

        const number = document.createElement("strong");
        number.textContent = `${Number(value).toFixed(1)}%`;

        const bar = document.createElement("div");
        bar.className = "bar";

        const fill = document.createElement("div");
        fill.className = "bar-fill";
        fill.style.width = `${clampPercent(value)}%`;

        top.append(label, number);
        bar.appendChild(fill);
        card.append(top, bar);
        grid.appendChild(card);
    });
}

function renderProcesses(processes) {
    const table = $("processTable");
    table.innerHTML = "";

    if (!processes.length) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 4;
        cell.textContent = "No process data available.";
        row.appendChild(cell);
        table.appendChild(row);
        return;
    }

    processes.forEach((process) => {
        const row = document.createElement("tr");
        const pid = document.createElement("td");
        const name = document.createElement("td");
        const cpu = document.createElement("td");
        const memory = document.createElement("td");

        pid.textContent = process.pid;
        name.textContent = process.name;
        cpu.textContent = `${Number(process.cpu_percent).toFixed(1)}%`;
        memory.textContent = `${Number(process.memory_percent).toFixed(1)}%`;

        row.append(pid, name, cpu, memory);
        table.appendChild(row);
    });
}

function renderApplicationActivity(items) {
    const table = $("applicationActivityTable");
    table.innerHTML = "";

    if (!items.length) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 5;
        cell.textContent = "No application activity recorded yet.";
        row.appendChild(cell);
        table.appendChild(row);
        return;
    }

    items.forEach((item) => {
        const row = document.createElement("tr");
        const processName = document.createElement("td");
        const instances = document.createElement("td");
        const firstSeen = document.createElement("td");
        const lastSeen = document.createElement("td");
        const samples = document.createElement("td");
        const firstSeenDate = new Date(item.first_seen);
        const lastSeenDate = new Date(item.last_seen);

        processName.textContent = item.process_name;
        instances.textContent = item.instance_count;
        firstSeen.textContent = firstSeenDate.toLocaleTimeString();
        lastSeen.textContent = lastSeenDate.toLocaleTimeString();
        samples.textContent = item.sample_count;

        row.append(processName, instances, firstSeen, lastSeen, samples);
        table.appendChild(row);
    });
}

function renderMonitoringLogs() {
    const table = $("monitoringLogsTable");
    if (!table) return;

    const search = ($("monitoringLogSearch")?.value || "").trim().toLowerCase();
    table.innerHTML = "";

    const filteredLogs = monitoringLogs.filter((item) => {
        if (!search) return true;

        const date = new Date(item.recorded_at);
        const haystack = [
            date.toLocaleString(),
            Number(item.cpu_percent).toFixed(1),
            Number(item.memory_percent).toFixed(1),
            Number(item.disk_percent).toFixed(1),
            String(item.process_count),
        ].join(" ").toLowerCase();

        return haystack.includes(search);
    });

    if (!filteredLogs.length) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 6;
        cell.textContent = "No monitoring logs match the selected filter.";
        row.appendChild(cell);
        table.appendChild(row);
        return;
    }

    filteredLogs.forEach((item) => {
        const row = document.createElement("tr");
        const time = document.createElement("td");
        const cpu = document.createElement("td");
        const memory = document.createElement("td");
        const disk = document.createElement("td");
        const processes = document.createElement("td");
        const network = document.createElement("td");
        const date = new Date(item.recorded_at);

        time.textContent = date.toLocaleString();
        cpu.textContent = `${Number(item.cpu_percent).toFixed(1)}%`;
        memory.textContent = `${Number(item.memory_percent).toFixed(1)}%`;
        disk.textContent = `${Number(item.disk_percent).toFixed(1)}%`;
        processes.textContent = item.process_count;
        network.textContent =
            `${Number(item.net_download_kbps).toFixed(1)} down / ${Number(item.net_upload_kbps).toFixed(1)} up KB/s`;

        row.append(time, cpu, memory, disk, processes, network);
        table.appendChild(row);
    });
}

function makePolyline(values) {
    if (!values.length) return "";

    const width = 1000;
    const height = 300;
    const maxIndex = Math.max(1, values.length - 1);

    return values
        .map((value, index) => {
            const x = (index / maxIndex) * width;
            const y = height - (clampPercent(value) / 100) * height;
            return `${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(" ");
}

async function loadSystemInfo() {
    const res = await fetch("/api/system");
    if (!res.ok) return;

    const data = await res.json();
    $("hostname").textContent = data.hostname;
    $("processor").textContent = data.processor;
    $("cores").textContent = `${data.physical_cores ?? "?"} physical / ${data.logical_cores ?? "?"} logical`;
    $("platform").textContent = data.platform;
}

async function loadLatest() {
    const res = await fetch("/api/latest");

    if (res.status === 404) {
        $("lastUpdated").textContent = "Collecting first sample...";
        return;
    }

    if (!res.ok) {
        throw new Error("Failed to load latest metrics.");
    }

    const data = await res.json();

    $("cpuUsage").textContent = Number(data.cpu_percent).toFixed(1);
    $("cpuFreq").textContent =
        data.cpu_frequency_mhz == null ? "--" : Number(data.cpu_frequency_mhz).toFixed(0);
    $("memoryUsage").textContent = Number(data.memory_percent).toFixed(1);
    $("processCount").textContent = data.process_count;
    $("diskUsage").textContent = Number(data.disk_percent).toFixed(1);
    $("diskFree").textContent = Number(data.disk_free_gb).toFixed(1);
    $("diskTotal").textContent = Number(data.disk_total_gb).toFixed(1);
    $("downloadSpeed").textContent = Number(data.net_download_kbps).toFixed(1);
    $("uploadSpeed").textContent = Number(data.net_upload_kbps).toFixed(1);
    $("totalReceived").textContent = Number(data.net_recv_mb).toFixed(1);
    $("totalSent").textContent = Number(data.net_sent_mb).toFixed(1);

    setBar("cpuBar", data.cpu_percent);
    setBar("memoryBar", data.memory_percent);
    setBar("diskBar", data.disk_percent);
    renderCores(data.per_core || []);

    if (data.monitoring_enabled === false) {
        setMonitoringPausedState();
        updateMonitoringControls(false);
    } else {
        updateMonitoringControls(true);
        updateAlertState(data);
    }

    const date = new Date(data.recorded_at);
    $("lastUpdated").textContent = `Last updated: ${date.toLocaleTimeString()}`;
}

async function loadMonitoringStatus() {
    const res = await fetch("/api/monitoring/status");
    if (!res.ok) return;

    const data = await res.json();
    updateMonitoringControls(Boolean(data.running));
}

async function loadHistory() {
    const res = await fetch("/api/history");
    if (!res.ok) {
        throw new Error("Failed to load history.");
    }

    const data = await res.json();

    $("cpuLine").setAttribute(
        "points",
        makePolyline(data.map((item) => item.cpu_percent))
    );

    $("memoryLine").setAttribute(
        "points",
        makePolyline(data.map((item) => item.memory_percent))
    );

    $("diskLine").setAttribute(
        "points",
        makePolyline(data.map((item) => item.disk_percent))
    );
}

async function loadProcesses() {
    const res = await fetch("/api/processes");
    if (!res.ok) {
        throw new Error("Failed to load process data.");
    }

    renderProcesses(await res.json());
}

async function loadMonitoringLogs() {
    const filter = $("monitoringLogFilter")?.value || "all";
    const res = await fetch(`/api/monitoring-logs?filter=${encodeURIComponent(filter)}`);

    if (!res.ok) {
        throw new Error("Failed to load monitoring logs.");
    }

    monitoringLogs = await res.json();
    renderMonitoringLogs();
}

async function loadApplicationActivity() {
    const res = await fetch("/api/application-activity");
    if (!res.ok) {
        throw new Error("Failed to load application activity.");
    }

    renderApplicationActivity(await res.json());
}

async function refresh() {
    if (refreshInFlight) return;
    refreshInFlight = true;

    try {
        await loadLatest();
    } catch (error) {
        console.error(error);
        $("lastUpdated").textContent = "Connection error";
    } finally {
        refreshInFlight = false;
    }
}

async function refreshSupportingData() {
    if (supportingRefreshInFlight) return;
    supportingRefreshInFlight = true;

    try {
        await Promise.all([
            loadHistory(),
            loadProcesses(),
            loadMonitoringLogs(),
            loadApplicationActivity(),
        ]);
    } catch (error) {
        console.error(error);
    } finally {
        supportingRefreshInFlight = false;
    }
}

async function setMonitoringRunning(shouldRun) {
    const endpoint = shouldRun ? "/api/monitoring/start" : "/api/monitoring/stop";
    const res = await fetch(endpoint, { method: "POST" });

    if (!res.ok) {
        throw new Error("Failed to update monitoring status.");
    }

    const data = await res.json();
    updateMonitoringControls(Boolean(data.running));

    if (data.running) {
        await refresh();
    } else {
        setMonitoringPausedState();
    }

    await refreshSupportingData();
}

loadSystemInfo().catch(console.error);
loadMonitoringStatus().catch(console.error);
updateBrowserNotificationButton();
const soundToggle = $("soundToggle");
if (soundToggle) {
    soundToggle.addEventListener("click", async () => {
        soundEnabled = !soundEnabled;
        soundToggle.textContent = soundEnabled ? "Sound On" : "Enable Sound";

        if (soundEnabled) {
            await getAudioContext().resume();
            playAlertSound();
        }
    });
}
const testEmailButton = $("testEmailButton");
if (testEmailButton) {
    testEmailButton.addEventListener("click", sendTestNotification);
}
const browserNotificationToggle = $("browserNotificationToggle");
if (browserNotificationToggle) {
    browserNotificationToggle.addEventListener("click", requestBrowserNotificationPermission);
}
const startMonitoringButton = $("startMonitoringButton");
if (startMonitoringButton) {
    startMonitoringButton.addEventListener("click", () => {
        setMonitoringRunning(true).catch(console.error);
    });
}
const stopMonitoringButton = $("stopMonitoringButton");
if (stopMonitoringButton) {
    stopMonitoringButton.addEventListener("click", () => {
        setMonitoringRunning(false).catch(console.error);
    });
}
const monitoringLogFilter = $("monitoringLogFilter");
if (monitoringLogFilter) {
    monitoringLogFilter.addEventListener("change", () => {
        loadMonitoringLogs().catch(console.error);
    });
}
const monitoringLogSearch = $("monitoringLogSearch");
if (monitoringLogSearch) {
    monitoringLogSearch.addEventListener("input", renderMonitoringLogs);
}
refresh();
refreshSupportingData();
setInterval(refresh, DASHBOARD_REFRESH_INTERVAL_MS);
setInterval(refreshSupportingData, SUPPORTING_DATA_REFRESH_INTERVAL_MS);
