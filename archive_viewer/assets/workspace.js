"use strict";
let inspectorChat = null, inspectorData = null;
let filterMedia = false, filterApplied = {q:"", start:"", end:"", global:false};
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
        const button = node("button", ""); button.title = item.name;
        if (item.available && (item.preview === "photo" || item.kind === "photo")) {
            const image = node("img", ""); image.src = mediaURL(item.id); image.loading = "lazy"; image.alt = item.name;
            button.append(image);
        } else button.append(node("small", "", (item.available ? "▦ " : "◌ ") + item.name));
        button.addEventListener("click", () => { const area = node("section", ""); appendMedia(area,item); showWorkspace(item.name,[area]); });
        grid.append(button);
    }
    return grid;
}
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
            ["Редакции",data.revisions],["Изменены",data.edited],["Удалены",data.deleted]]),node("h3","","Пересечения архива")];
        parts.push(node("p","",data.shared.length ? "Этот участник встречается ещё в " + data.shared.length + " сохранённых переписках." : "Других переписок с этим участником не найдено."));
        parts.push(node("small","","Это пересечения сохранённых участников, не список друзей Telegram."));
        parts.push(node("h3","","Ссылки и частые слова"));
        const words=node("div","keyword-list");
        for(const [word,count] of data.keywords){const b=node("button","",word+" · "+count);b.addEventListener("click",()=>{ $("filter-query").value=word;applyFilters(); });words.append(b);}
        parts.push(words);
        for(const url of data.links.slice(0,5)){const link=node("a","",url);link.href=url;link.target="_blank";link.rel="noreferrer noopener";parts.push(link);}
        parts.push(node("small","","Слова, ссылки и превью: последние " + data.sample_messages + " сообщений."),node("h3","","Медиа и файлы · " + data.media_total),mediaGallery(data.gallery.slice(-12).reverse()));
        $("inspector-content").replaceChildren(...parts);
    } catch(error) { $("inspector-content").replaceChildren(node("p","unavailable",error.message)); }
};
window.messageQuery = key => {
    if(!filterMedia && !filterApplied.q && !filterApplied.start && !filterApplied.end && !filterApplied.global) return "/api/messages?chat="+encodeURIComponent(key);
    const params=new URLSearchParams({chat:filterApplied.global?"":key,q:filterApplied.q,start:filterApplied.start,end:filterApplied.end,media:filterMedia?"1":"0"});
    return "/api/search?"+params;
};
window.searchResult = result => { $("result-status").textContent = result.total === undefined ? "" : "Найдено: " + result.total + (filterApplied.global ? " · весь архив" : " · этот чат"); };
async function applyFilters() {
    filterApplied={q:$("filter-query").value.trim(),start:$("filter-start").value,end:$("filter-end").value,global:$("filter-global").checked};
    if(selected){generation++;before=null;await loadMessages();if(currentChat())window.refreshInspector(currentChat());}
}
for(const id of ["date-filter","keyword-filter","chat-search"]){$(id).addEventListener("click",()=>{
    const show = $("filters").hidden || id === "chat-search";
    $("filters").hidden=!show; $("date-filter").setAttribute("aria-expanded",String(show));$("keyword-filter").setAttribute("aria-expanded",String(show));
    if(show) $(id==="date-filter"?"filter-start":"filter-query").focus();
});}
$("media-filter").addEventListener("click",()=>{filterMedia=!filterMedia;$("media-filter").setAttribute("aria-pressed",String(filterMedia));applyFilters();});
$("apply-filters").addEventListener("click",applyFilters);
$("filter-query").addEventListener("keydown",event=>{if(event.key==="Enter")applyFilters();});
$("clear-filters").addEventListener("click",()=>{ for(const id of ["filter-query","filter-start","filter-end"])$(id).value=""; $("filter-global").checked=false;filterMedia=false;$("media-filter").setAttribute("aria-pressed","false");applyFilters();});
$("toggle-inspector").addEventListener("click",()=>inspectorVisible($("viewer").classList.contains("inspector-hidden")));
$("close-inspector").addEventListener("click",()=>inspectorVisible(false));

async function inspected() {
    const chat=requireChat(); if(!chat)return null;
    if(!inspectorData || inspectorChat?.key!==chat.key) await window.refreshInspector(chat);
    return inspectorData;
}
$("chat-analytics").addEventListener("click",async()=>{ const data=await inspected();if(!data)return;
    const grid=node("div","metric-grid");
    for(const [label,value] of [["Сообщений",data.messages],["Редакций",data.revisions],["Изменены",data.edited],["Удалены",data.deleted],["Недоступны",data.missing],["Вложений",data.media_total]]){const tile=node("div","metric");tile.append(node("strong","",value),node("small","",label));grid.append(tile);}
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
$("chat-audit").addEventListener("click",async()=>{const data=await inspected();if(data)showWorkspace("Проверка записей",[factList([["Нет исходного текста редакций",data.original_missing],["Недоступны при проверке",data.missing],["Вложений ещё нет в бекапе",data.missing_media],["Неизвестна дата отправки",data.unknown_date]]),node("p","","Это замечания о полноте сохранённых данных. Недоступность сообщения сама по себе не доказывает удаление.")]);});
$("chat-graph").addEventListener("click",async()=>{const data=await inspected();if(!data)return;
    const ns="http://www.w3.org/2000/svg",svg=document.createElementNS(ns,"svg");svg.setAttribute("viewBox","0 0 600 300");svg.classList.add("graph");
    const ids=[...new Set(data.graph.flatMap(edge=>[edge.source,edge.target]))];
    const points=new Map(ids.map((id,index)=>[id,{x:300+180*Math.cos(index*2*Math.PI/ids.length),y:150+90*Math.sin(index*2*Math.PI/ids.length)}]));
    for(const edge of data.graph){const a=points.get(edge.source),b=points.get(edge.target);const line=document.createElementNS(ns,"line");for(const [key,value]of Object.entries({x1:a.x,y1:a.y,x2:b.x,y2:b.y}))line.setAttribute(key,value);svg.append(line);const text=document.createElementNS(ns,"text");text.setAttribute("x",(a.x+b.x)/2);text.setAttribute("y",(a.y+b.y)/2-5);text.textContent=edge.count;svg.append(text);}
    for(const [id,p]of points){const circle=document.createElementNS(ns,"circle");circle.setAttribute("cx",p.x);circle.setAttribute("cy",p.y);circle.setAttribute("r",24);const text=document.createElementNS(ns,"text");text.setAttribute("x",p.x);text.setAttribute("y",p.y+43);text.setAttribute("text-anchor","middle");text.textContent=id;svg.append(circle,text);}
    showWorkspace("Связи по сохранённым сообщениям",[svg,node("p","","Линии связывают отправителя и получателя личных сообщений. Числа — количество сохранённых сообщений, не социальные связи вне архива.")]);
});
function exportDialog(all=false){const chat=all?null:requireChat();if(!all&&!chat)return;
    const choices=node("div","export-options");for(const format of ["json","html"]){const link=node("a","",format.toUpperCase());link.href="/api/export?"+new URLSearchParams({chat:chat?.key||"",format,token});link.download="watchtower-export."+format;choices.append(link);}
    showWorkspace(all?"Экспорт всех переписок":"Экспорт ветки",[node("p","unavailable","Экспорт содержит расшифрованный текст и версии сообщений. Храните его отдельно от публичных файлов. Вложения остаются в исходном зашифрованном бекапе."),choices]);
}
$("export-all").addEventListener("click",()=>exportDialog(true));$("export-chat").addEventListener("click",()=>exportDialog());
$("close-workspace").addEventListener("click",()=>$("workspace-dialog").close());
$("workspace-dialog").addEventListener("close",()=>{$("workspace-content").replaceChildren();disposeDetachedAnimations();});
$("lock").addEventListener("click",()=>{inspectorData=inspectorChat=null;$("inspector-content").replaceChildren();$("workspace-dialog").close();$("result-status").textContent="";for(const id of ["filter-query","filter-start","filter-end"])$(id).value="";$("filter-global").checked=false;filterApplied={q:"",start:"",end:"",global:false};filterMedia=false;$("media-filter").setAttribute("aria-pressed","false");});

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
