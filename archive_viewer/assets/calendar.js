"use strict";
let calendarDays = [], calendarMonths = [], calendarMonth = 0;

function renderCalendar() {
    const month = calendarMonths[calendarMonth];
    $("date-month").value = month;
    $("previous-month").disabled = calendarMonth <= 0;
    $("next-month").disabled = calendarMonth >= calendarMonths.length - 1;
    const [year, number] = month.split("-").map(Number);
    const available = new Map(calendarDays.map(day => [day.day, day]));
    const cells = [];
    for(let i=0; i<(new Date(year, number-1, 1).getDay()+6)%7; i++) cells.push(node("span", ""));
    for(let day=1; day<=new Date(year, number, 0).getDate(); day++) {
        const identity = month + "-" + String(day).padStart(2,"0");
        const entry = available.get(identity), button = node("button", "calendar-day", day);
        button.disabled = !entry;
        button.title = entry ? entry.count + " сообщений" : "Нет сохранённых сообщений";
        if(entry) button.addEventListener("click", async()=>{
            $("date-dialog").close();
            window.resetChatSearch();
            generation++; before = after = null;
            await loadMessages("date", entry.start);
        });
        cells.push(button);
    }
    $("calendar-days").replaceChildren(...cells);
}

$("chat-date").addEventListener("click", async()=>{
    const chat = currentChat(); if(!chat) return;
    const requestGeneration = generation;
    $("calendar-days").replaceChildren();
    $("date-month").replaceChildren();
    $("calendar-note").textContent = "Читаем сохранённые даты…";
    $("previous-month").disabled = $("next-month").disabled = true;
    $("date-dialog").showModal();
    try {
        const offset = -new Date().getTimezoneOffset();
        const result = await api("/api/calendar?" + new URLSearchParams({chat:chat.key, offset}));
        if(requestGeneration !== generation || !$("date-dialog").open) return;
        calendarDays = result.days;
        calendarMonths = [...new Set(calendarDays.map(day => day.day.slice(0,7)))];
        if(!calendarMonths.length) {
            $("calendar-note").textContent = "В этом чате нет сообщений с известной датой.";
            return;
        }
        for(const month of calendarMonths) {
            const [year, number] = month.split("-").map(Number), option = node("option", "",
                new Date(year,number-1,1).toLocaleDateString(undefined,{year:"numeric",month:"long"}));
            option.value = month;
            $("date-month").append(option);
        }
        calendarMonth = calendarMonths.length-1;
        const absolute = Math.abs(offset), zone = "UTC"+(offset>=0?"+":"−")
            +String(Math.floor(absolute/60)).padStart(2,"0")+":"+String(absolute%60).padStart(2,"0");
        $("calendar-note").textContent = "Выберите день — откроется первое сохранённое сообщение. Даты: " + zone + ".";
        renderCalendar();
    } catch(error) { $("calendar-note").textContent = error.message; }
});
$("date-month").addEventListener("change",()=>{calendarMonth=calendarMonths.indexOf($("date-month").value);renderCalendar();});
$("previous-month").addEventListener("click",()=>{calendarMonth--;renderCalendar();});
$("next-month").addEventListener("click",()=>{calendarMonth++;renderCalendar();});
$("close-date").addEventListener("click",()=>$("date-dialog").close());
$("date-dialog").addEventListener("close",()=>{calendarDays=[];calendarMonths=[];$("calendar-days").replaceChildren();$("date-month").replaceChildren();});
$("lock").addEventListener("click",()=>$("date-dialog").close());
