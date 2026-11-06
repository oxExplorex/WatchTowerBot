"use strict";

const token = location.hash.slice(1);
history.replaceState(null, "", location.pathname);
const $ = id => document.getElementById(id);
let chats = [], selected = null, before = null, generation = 0;

async function api(path, body) {
    const response = await fetch(path, {
        method: body === undefined ? "GET" : "POST",
        headers: {"X-Viewer-Token": token, "Content-Type": "application/json"},
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: "no-store",
    });
    const value = await response.json();
    if (!response.ok) throw Error(value.error || "Ошибка чтения");
    return value;
}

function toast(error) {
    $("toast").textContent = error.message || String(error);
    $("toast").hidden = false;
    setTimeout(() => $("toast").hidden = true, 5000);
}

function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    // Archive content is text, never executable markup.
    if (text !== undefined) element.textContent = String(text);
    return element;
}

function mediaURL(id, download = false) {
    return "/api/media/" + encodeURIComponent(id) + "?token=" + encodeURIComponent(token)
        + (download ? "&download=1" : "");
}

function stamp(value) {
    return value ? new Date(value * 1000).toLocaleString() : "Дата неизвестна";
}

function appendMedia(box, media) {
    if (!media.available) {
        box.append(node("div", "unavailable", "Вложение не было скачано: " + media.name));
        return;
    }
    let player;
    if (media.kind === "photo") {
        player = node("img", "media");
        player.loading = "lazy";
        player.alt = "Фото из архива";
    } else if (["video", "video_note", "audio", "voice"].includes(media.kind)) {
        player = node(["video", "video_note"].includes(media.kind) ? "video" : "audio", "media");
        player.controls = true;
        player.preload = "none";
    }
    if (player) {
        player.src = mediaURL(media.id);
        box.append(player);
    }
    const link = node("a", "attachment", "Скачать · " + media.name);
    link.href = mediaURL(media.id, true);
    link.download = media.name;
    box.append(link);
}

function bubble(message, versions = false) {
    const box = node("article", "bubble" + (message.outgoing ? " outgoing" : "")
        + (message.deleted ? " deleted" : ""));
    if (message.sender) box.append(node("div", "sender", message.sender));
    box.append(node("div", "body", message.text || "Без текста"));
    for (const media of message.media || []) appendMedia(box, media);
    const meta = node("div", "meta");
    if (message.deleted) meta.append(node("span", "badge", "Удалено"));
    if (message.missing) meta.append(node("span", "badge", "Недоступно при проверке"));
    if (message.edited) meta.append(node("span", "", "Изменено"));
    meta.append(node("span", "", stamp(message.time)));
    if (!versions && message.versions) {
        const button = node("button", "", "⋯");
        button.title = "История сообщения · версий: " + message.versions;
        button.addEventListener("click", () => showVersions(message.id));
        meta.append(button);
        box.addEventListener("contextmenu", event => {
            event.preventDefault();
            showVersions(message.id);
        });
    }
    box.append(meta);
    return box;
}

async function showVersions(id) {
    const requestGeneration = generation;
    try {
        const rows = await api("/api/versions?id=" + encodeURIComponent(id));
        if (requestGeneration !== generation) return;
        $("versions").replaceChildren(...rows.map(row => bubble(row, true)));
        $("history").showModal();
    } catch (error) {
        toast(error);
    }
}

function renderChats() {
    const term = $("search").value.toLocaleLowerCase();
    const matching = chats.filter(chat => [chat.name, chat.id, chat.account].join(" ")
        .toLocaleLowerCase().includes(term));
    $("chats").replaceChildren(...matching.map(chat => {
        const button = node("button", "chat" + (selected === chat.key ? " active" : ""));
        button.append(node("span", "avatar", chat.name.slice(0, 2).toLocaleUpperCase()));
        const copy = node("span", "chat-copy");
        copy.append(node("span", "chat-name", chat.name),
            node("small", "", chat.id + " · " + chat.count + " сообщений"),
            node("small", "", "Аккаунт " + chat.account));
        button.append(copy);
        button.addEventListener("click", () => openChat(chat));
        return button;
    }));
}

async function loadMessages(older = false) {
    const requestGeneration = generation, key = selected;
    const previousButton = $("older");
    try {
        const result = await api("/api/messages?chat=" + encodeURIComponent(key)
            + (older && before !== null ? "&before=" + before : ""));
        if (requestGeneration !== generation || key !== selected) return;
        const area = $("messages"), height = area.scrollHeight;
        if (previousButton) previousButton.remove();
        const fragment = document.createDocumentFragment();
        if (result.before !== null) {
            const button = node("button", "", "Показать более ранние сообщения");
            button.id = "older";
            button.addEventListener("click", () => {
                button.disabled = true;
                loadMessages(true);
            });
            fragment.append(button);
        }
        for (const message of result.messages) fragment.append(bubble(message));
        if (older) area.prepend(fragment);
        else area.replaceChildren(fragment);
        before = result.before;
        area.scrollTop = older ? area.scrollHeight - height : area.scrollHeight;
    } catch (error) {
        if (previousButton) previousButton.disabled = false;
        toast(error);
    }
}

async function openChat(chat) {
    generation++;
    selected = chat.key;
    before = null;
    $("chat-title").textContent = chat.name;
    $("chat-info").textContent = "ID " + chat.id + " · аккаунт " + chat.account
        + " · " + chat.count + " сообщений";
    $("messages").replaceChildren(node("div", "empty", "Загрузка сообщений…"));
    renderChats();
    await loadMessages();
}

$("unlock-form").addEventListener("submit", async event => {
    event.preventDefault();
    $("error").textContent = "";
    $("open").disabled = true;
    $("open").textContent = "Открываю архив…";
    let secret = $("secret").value;
    $("secret").value = "";
    try {
        await api("/api/unlock", {secret});
        secret = "";
        chats = await api("/api/chats");
        $("count").textContent = chats.length;
        $("unlock").hidden = true;
        $("viewer").hidden = false;
        renderChats();
        if (chats.length) await openChat(chats[0]);
        else $("messages").textContent = "В архиве нет сохранённых сообщений";
    } catch (error) {
        $("error").textContent = error.message;
    } finally {
        secret = "";
        $("open").disabled = false;
        $("open").textContent = "Открыть архив →";
    }
});

$("lock").addEventListener("click", async () => {
    generation++; // Discard in-flight plaintext responses, including the version dialog.
    try {
        await api("/api/lock", {});
    } catch (error) {
        toast(error);
        return;
    }
    chats = [];
    selected = null;
    for (const id of ["messages", "chats", "versions", "chat-title", "chat-info"]) $(id).replaceChildren();
    $("history").close();
    $("viewer").hidden = true;
    $("unlock").hidden = false;
    $("search").value = "";
    $("secret").focus();
});

$("search").addEventListener("input", renderChats);
$("close-history").addEventListener("click", () => $("history").close());
if (!token) {
    $("error").textContent = "Откройте ссылку из окна просмотрщика или запустите его заново.";
    $("open").disabled = true;
}
