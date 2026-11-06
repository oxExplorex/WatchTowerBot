"use strict";
let inspectorChat = null, inspectorData = null;
let filterQuery = "";
let updatePoll = null;

function showWorkspace(title, children) {
    $("workspace-title").textContent = title;
    $("workspace-content").replaceChildren(...children);
    disposeDetachedAnimations();
    $("workspace-dialog").showModal();
}
function currentChat() { return chats.find(chat => chat.key === selected); }
function requireChat() { const chat = currentChat(); if (!chat) toast("Сначала выберите чат"); return chat; }
function inspectorVisible(visible) {
    $("viewer").classList.toggle("inspector-hidden", !visible);
    $("toggle-inspector").setAttribute("aria-expanded", String(visible));
}
function factList(pairs) {
    const list = node("dl", "facts");
    for (const [name,value] of pairs) list.append(node("dt","",name),node("dd","",value));
    return list;
}
function mediaGallery(items) {
    const grid = node("div", "gallery");
    for (const item of items) {
        const button = node("button", "gallery-tile"); button.title = item.name;
        const kind = item.preview || item.kind;
        if(item.available && kind === "photo") {
            const image=node("img", "");image.src=mediaURL(item.id);image.loading="lazy";image.alt=item.name;
            button.append(image);
        } else if(item.available && ["video","video_note","animation"].includes(kind)) {
            const video=node("video","gallery-video"),badge=node("span","duration-badge",durationLabel(item.duration));
            video.muted=video.playsInline=true;
            if(kind==="video_note")video.classList.add("round-video");
            video.addEventListener("error",()=>{video.replaceWith(node("small","",item.name));},{once:true});
            button.append(video,badge);prepareVideoPreview(video,item,badge);
        } else if(item.available && kind === "sticker") {
            const sticker=node("div","gallery-sticker");button.append(sticker);showSticker(sticker,item);
        } else button.append(node("small", "", (item.available ? "" : "Не скачано · ") + item.name));
        button.addEventListener("click", () => openMedia(item));grid.append(button);
    }
    return grid;
}
function linkCards(items) {
    const list=node("div","link-list");let day=null;
    for(const item of items) {
        const date=item.time?new Date(item.time*1000).toLocaleDateString():"Дата неизвестна";
        if(date!==day){list.append(node("h4","link-day",date));day=date;}
        const card=node("a","link-card"),copy=node("span","link-copy");
        card.href=item.url;card.target="_blank";card.rel="noreferrer noopener";
        const initial=node("span","link-avatar",Array.from(item.domain.replace(/^www\./,""))[0]?.toUpperCase()||"↗");
        copy.append(node("strong","",item.domain),node("span","link-excerpt",item.text),node("span","link-url",item.url));
        card.append(initial,copy);list.append(card);
    }
    if(!items.length)list.append(node("p","","В последних сохранённых сообщениях ссылок нет."));
    return list;
}
async function openAvatarHistory() {
    const chat=requireChat();if(!chat)return;
    const content=node("section","avatar-timeline");showWorkspace("История аватарок · "+chat.name,[content]);
    const requestGeneration=generation;
    try {
        const entries=await api("/api/avatars?chat="+encodeURIComponent(chat.key));
        if(requestGeneration!==generation||!content.isConnected)return;
        if(!entries.length)content.append(node("p","","В этот дамп аватарки ещё не попали."));
        for(const item of entries) {
            const row=node("article","avatar-history-row"),copy=node("div","");
            if(item.available){
                const photo=node("a","avatar-history-photo");photo.href="/api/avatar/"+encodeURIComponent(item.id)+"?token="+encodeURIComponent(token);
                photo.target="_blank";photo.rel="noreferrer noopener";
                const image=node("img","");image.src=photo.href;image.alt="Сохранённая аватарка";image.loading="lazy";photo.append(image);row.append(photo);
            }
            copy.append(node("strong","",item.status==="absent"?"Аватарка не видна":item.current?"Текущая аватарка":"Предыдущая аватарка"));
            if(item.first_seen_at)copy.append(node("small","","Замечена: "+stamp(item.first_seen_at)));
            if(item.ended_at)copy.append(node("small","","Сменена или скрыта: "+stamp(item.ended_at)));
            if(!item.available&&item.status!=="absent")copy.append(node("small","unavailable","Фотография не успела скачаться."));
            row.append(copy);content.append(row);
        }
        content.append(node("p","sample-note","Даты — время наблюдения ботом. Изменения между проверками могли остаться незамеченными."));
    } catch(error) {if(content.isConnected)content.append(node("p","unavailable",error.message));}
}
$("chat-avatars").addEventListener("click",openAvatarHistory);
window.refreshInspector = async chat => {
    inspectorChat = chat; inspectorData = null;
    $("inspector-content").replaceChildren(node("p", "", "Собираю сведения…"));
    const requestGeneration = generation;
    try {
        const data = await api("/api/inspect?chat=" + encodeURIComponent(chat.key));
        if (requestGeneration !== generation || selected !== chat.key) return;
        inspectorData = data;
        const profile = node("div", "inspector-profile"), name = node("div", "");
        name.append(node("strong","",chat.name),node("small","","Telegram · ID " + chat.id));
        profile.append(avatarNode(chat.avatar,chat.name),name);
        const parts = [profile,node("h3","","Данные"), factList([["Аккаунт",chat.account],["Сообщения",data.messages],
            ["Сохранённые версии",data.revisions],["Изменены",data.edited],["Удалены",data.deleted]])];
        const avatars=node("button","avatar-history-button","Аватарки · история");avatars.addEventListener("click",openAvatarHistory);parts.push(avatars);
        parts.push(node("h3","","Пересечения архива"));
        parts.push(node("p","",data.shared.length ? "Этот участник встречается ещё в " + data.shared.length + " сохранённых переписках." : "Других переписок с этим участником не найдено."));
        parts.push(node("small","","Это пересечения сохранённых участников, не список друзей Telegram."));
        const details=node("details","link-details"),summary=node("summary","","Ссылки и частые слова");
        const words=node("div","keyword-list");
        for(const [word,count] of data.keywords){const button=node("button","",word+" · "+count);button.addEventListener("click",()=>{$("filter-query").value=word;applyFilters();});words.append(button);}
        details.append(summary,words,linkCards(data.links),node("small","sample-note","Слова и ссылки: последние " + data.sample_messages + " сообщений."));parts.push(details);
        parts.push(node("h3","","Медиа и файлы · " + data.media_total),mediaGallery(data.gallery.slice(-12).reverse()));
        $("inspector-content").replaceChildren(...parts);
    } catch(error) {
        if(requestGeneration === generation && selected === chat.key)
            $("inspector-content").replaceChildren(node("p","unavailable",error.message));
    }
};
window.messageQuery = key => filterQuery
    ? "/api/search?" + new URLSearchParams({chat:key, q:filterQuery})
    : "/api/messages?chat=" + encodeURIComponent(key);
window.searchResult = result => {
    $("result-status").textContent = result.total === undefined ? "" : "Найдено в этом диалоге: " + result.total;
};
window.resetChatSearch = () => {
    filterQuery = "";
    $("filter-query").value = "";
    $("chat-filters").hidden = true;
    $("result-status").textContent = "";
};
async function applyFilters() {
    if(!selected) return;
    filterQuery = $("filter-query").value.trim();
    generation++; before = after = null;
    await loadMessages();
}
$("chat-search").addEventListener("click",()=>{
    if(!requireChat()) return;
    $("chat-filters").hidden = !$("chat-filters").hidden;
    if(!$("chat-filters").hidden) $("filter-query").focus();
});
$("apply-filters").addEventListener("click",applyFilters);
$("filter-query").addEventListener("keydown",event=>{if(event.key==="Enter")applyFilters();});
$("clear-filters").addEventListener("click",()=>{ $("filter-query").value=""; applyFilters(); });
$("toggle-inspector").addEventListener("click",()=>inspectorVisible($("viewer").classList.contains("inspector-hidden")));
$("close-inspector").addEventListener("click",()=>inspectorVisible(false));

async function inspected() {
    const chat=requireChat(); if(!chat)return null;
    if(!inspectorData || inspectorChat?.key!==chat.key) await window.refreshInspector(chat);
    return inspectorData;
}
$("chat-analytics").addEventListener("click",async()=>{ const data=await inspected();if(!data)return;
    const grid=node("div","metric-grid");
    for(const [label,value] of [["Сообщений",data.messages],["Сохранённых версий",data.revisions],["Изменены",data.edited],["Удалены",data.deleted],["Недоступны",data.missing],["Вложений",data.media_total]]){const tile=node("div","metric");tile.append(node("strong","",value),node("small","",label));grid.append(tile);}
    showWorkspace("Аналитика сохранённого чата",[grid,node("p","","Показатели относятся к архиву. Они не измеряют онлайн-статус или полноту истории Telegram.")]);
});
$("chat-gallery").addEventListener("click",async()=>{
    const chat=requireChat();if(!chat)return;
    const content=node("section","");
    showWorkspace("Медиагалерея",[content]);
    const requestGeneration=generation;
    async function more(before=null){
        try{const data=await api("/api/gallery?chat="+encodeURIComponent(chat.key)+(before!==null?"&before="+before:""));
            if(!content.isConnected||requestGeneration!==generation)return;
            content.querySelector(".load-more")?.remove();content.append(mediaGallery(data.items));
            if(data.before!==null){const button=node("button","load-more","Показать ещё");button.addEventListener("click",()=>{button.disabled=true;more(data.before);});content.append(button);}
            if(!content.childElementCount)content.append(node("p","","Сохранённых вложений нет"));
        }catch(error){toast(error);}
    }
    more();
});
$("chat-people").addEventListener("click",async()=>{const data=await inspected();if(data)showWorkspace("Сохранённые участники",data.participants.map(person=>node("div","participant",person.name+" · ID "+person.id+" · сообщений: "+person.count)));});
$("close-workspace").addEventListener("click",()=>$("workspace-dialog").close());
$("workspace-dialog").addEventListener("close",()=>{$("workspace-content").replaceChildren();disposeDetachedAnimations();});
$("lock").addEventListener("click",()=>{inspectorData=inspectorChat=null;$("inspector-content").replaceChildren();$("workspace-dialog").close();window.resetChatSearch();});

async function renderApplication(){
    try{const info=await api("/api/application");for(const label of document.querySelectorAll(".app-version"))label.textContent="v"+info.version+(info.build&&info.build!=="source"?" · "+info.build:"");
        const labels={source:"Запуск из исходников",unchecked:"Обновления ещё не проверены",checking:"Проверяю обновления…",current:"Установлена актуальная сборка",available:"Доступно обновление "+(info.latest||""),installing:"Скачиваю и устанавливаю…",error:"Не удалось обновить: "+(info.error||"нет соединения")};
        $("update-status").textContent=labels[info.state]||info.state;
        $("install-update").hidden=!info.available;$("install-update").disabled=info.state==="installing";$("check-update").disabled=["source","checking","installing"].includes(info.state);
        if(info.state==="unchecked"){await api("/api/update/check",{});updatePoll=setTimeout(renderApplication,1500);}
        if(["checking","installing"].includes(info.state))updatePoll=setTimeout(renderApplication,1500);
    }catch(error){$("update-status").textContent="Приложение перезапускается или недоступно";}
}
$("check-update").addEventListener("click",async()=>{try{await api("/api/update/check",{});await renderApplication();}catch(error){toast(error);}});
$("install-update").addEventListener("click",async()=>{if(!confirm("Архив будет заблокирован, программа обновится и перезапустится. Продолжить?"))return;
    $("lock").click();try{await api("/api/update/install",{});await renderApplication();}catch(error){toast(error);}
});
renderApplication();
if(matchMedia("(max-width:900px)").matches)inspectorVisible(false);
