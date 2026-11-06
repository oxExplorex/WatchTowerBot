"use strict";

const token = location.hash.slice(1);
history.replaceState(null, "", location.pathname);
const $ = id => document.getElementById(id);
let chats = [], selected = null, before = null, generation = 0;
const animations = new Set();

function disposeDetachedAnimations() {
    for (const entry of animations) {
        if (!entry.container.isConnected) {
            entry.player.destroy();
            animations.delete(entry);
        }
    }
}

function avatarNode(identity, name) {
    const fallback = node("span", "avatar", Array.from(name || "?").slice(0, 2).join("").toLocaleUpperCase());
    if (!identity) return fallback;
    const image = node("img", "avatar");
    image.alt = name || "Аватар";
    image.loading = "lazy";
    image.src = "/api/avatar/" + encodeURIComponent(identity) + "?token=" + encodeURIComponent(token);
    image.addEventListener("error", () => image.replaceWith(fallback), {once: true});
    return image;
}

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

async function showSticker(container, media) {
    const requestGeneration = generation;
    try {
        const value = await api("/api/sticker/" + encodeURIComponent(media.id));
        if (requestGeneration !== generation || !container.isConnected) return;
        if (value.format === "tgs") {
            const player = lottie.loadAnimation({container, renderer: "canvas", loop: true,
                autoplay: true, animationData: value.animation});
            animations.add({container, player});
        } else {
            const player = node(value.format === "video" ? "video" : "img", "sticker");
            if (value.format === "video") {
                player.autoplay = player.loop = player.muted = player.playsInline = true;
            } else player.alt = "Стикер";
            player.src = mediaURL(media.id);
            container.append(player);
        }
    } catch (error) {
        if (container.isConnected) container.append(node("small", "unavailable", "Не удалось показать стикер"));
    }
}

function appendMedia(box, media) {
    if (!media.available) {
        box.append(node("div", "unavailable", "Вложение не было скачано: " + media.name));
        return;
    }
    let player;
    const kind = media.preview === undefined ? media.kind : media.preview;
    if (kind === "sticker") {
        const container = node("div", "sticker");
        box.append(container);
        showSticker(container, media);
    } else if (kind === "photo") {
        player = node("img", "media");
        player.loading = "lazy";
        player.alt = "Фото из архива";
    } else if (["video", "video_note", "animation", "audio", "voice"].includes(kind)) {
        player = node(["video", "video_note", "animation"].includes(kind) ? "video" : "audio", "media");
        player.controls = true;
        player.preload = "none";
        player.playsInline = true;
        if (kind === "video_note") player.classList.add("round-video");
        if (kind === "animation") {
            player.autoplay = player.loop = player.muted = true;
        }
    }
    if (player) {
        player.src = mediaURL(media.id);
        player.addEventListener("error", () => {
            player.replaceWith(node("small", "unavailable", "Браузер не смог открыть вложение. Можно скачать оригинал ниже."));
        }, {once: true});
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
    if (message.sender) {
        const sender = node("div", "sender");
        if (message.avatar) sender.append(avatarNode(message.avatar, message.sender));
        sender.append(node("span", "", message.sender));
        box.append(sender);
    }
    if (message.text || !(message.media || []).length) box.append(node("div", "body", message.text || "Без текста"));
    if (versions) {
        const label = message.kind === "new" ? "Исходное сообщение" :
            message.kind === "snapshot" ? "Снимок из истории Telegram" : "Редакция сообщения";
        box.prepend(node("div", "version-label", label));
    }
    for (const media of message.media || []) appendMedia(box, media);
    const meta = node("div", "meta");
    if (message.deleted) meta.append(node("span", "badge", "Удалено"));
    if (message.missing) meta.append(node("span", "badge", "Недоступно при проверке"));
    if (versions) {
        meta.append(node("span", "", (message.kind === "edit" || message.edited ? "Изменено: " : "Отправлено: ") + stamp(message.time)));
        if (message.observed_at) meta.append(node("span", "", "Сохранено ботом: " + stamp(message.observed_at)));
    } else {
        meta.append(node("span", "", "Отправлено: " + stamp(message.time)));
        if (message.edited) meta.append(node("span", "", "Изменено: " + stamp(message.edited_at)));
    }
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
        const content = [];
        if (rows.length) {
            content.push(node("p", "", "Сообщение отправлено: " + stamp(rows[0].sent_at)));
            if (!rows[0].original_seen && rows[0].edited) content.push(node("p", "unavailable",
                "Бот впервые получил уже отредактированное сообщение. Исходный текст не сохранён."));
            content.push(node("small", "", "Даты показаны в часовом поясе этого компьютера."));
        }
        $("versions").replaceChildren(...content, ...rows.map(row => bubble(row, true)));
        disposeDetachedAnimations();
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
        button.append(avatarNode(chat.avatar, chat.name));
        const copy = node("span", "chat-copy");
        copy.append(node("span", "chat-name", chat.name),
            node("small", "", chat.id + " · " + chat.count + " сообщений"),
            node("small", "", "Аккаунт " + chat.account));
        if (chat.last_message_at) copy.append(node("small", "", stamp(chat.last_message_at)));
        button.append(copy);
        button.addEventListener("click", () => openChat(chat));
        return button;
    }));
}

async function loadMessages(older = false) {
    const requestGeneration = generation, key = selected;
    const previousButton = $("older");
    try {
        const result = await api((window.messageQuery ? window.messageQuery(key) : "/api/messages?chat=" + encodeURIComponent(key))
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
        let lastDay = null;
        for (const message of result.messages) {
            const day = message.time ? new Date(message.time * 1000).toLocaleDateString() : "Дата неизвестна";
            if (day !== lastDay) {
                const separator = node("div", "day-separator", day);
                separator.dataset.day = day;
                fragment.append(separator);
                lastDay = day;
            }
            fragment.append(bubble(message));
        }
        if (older && area.querySelector(".day-separator")?.dataset.day === lastDay)
            area.querySelector(".day-separator").remove();
        if (older) area.prepend(fragment);
        else area.replaceChildren(fragment);
        disposeDetachedAnimations();
        before = result.before;
        if (window.searchResult) window.searchResult(result);
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
    disposeDetachedAnimations();
    renderChats();
    await loadMessages();
    if (selected === chat.key && window.refreshInspector) window.refreshInspector(chat);
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
    disposeDetachedAnimations();
    $("history").close();
    $("viewer").hidden = true;
    $("unlock").hidden = false;
    $("search").value = "";
    $("secret").focus();
});

$("search").addEventListener("input", renderChats);
$("close-history").addEventListener("click", () => $("history").close());
$("history").addEventListener("close", () => {
    $("versions").replaceChildren();
    disposeDetachedAnimations();
});
if (!token) {
    $("error").textContent = "Откройте ссылку из окна просмотрщика или запустите его заново.";
    $("open").disabled = true;
}
