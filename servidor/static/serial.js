// JavaScript da página Serial (templates/serial.html): mostra o que é enviado e recebido do Nano

let serialAfter = 0;                    // número da última linha já mostrada

async function refreshSerial() {
    const all = document.getElementById("show-quiet").checked;
    try {
        const r = await fetch(`/serial-log?after=${serialAfter}&all=${all}`);
        const data = await r.json();
        const box = document.getElementById("serial");
        if (data.reset) box.textContent = "";                    // o Nano foi religado
        const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 5;
        for (const l of data.lines) {
            const span = document.createElement("span");
            span.className = l.dir === "TX" ? "tx" : l.text.startsWith("EVT") ? "evt" : l.text.startsWith("ERROR") ? "err" : "rx";
            span.textContent = `${l.time}  ${l.dir === "TX" ? "→" : "←"}  ${l.text}\n`;
            box.appendChild(span);
        }
        while (box.childNodes.length > 500) box.removeChild(box.firstChild);   // não deixar crescer para sempre
        if (atBottom) box.scrollTop = box.scrollHeight;          // segue as linhas novas (se estava em baixo)
        serialAfter = data.last;
    } catch (e) { /* sem servidor: tenta outra vez daqui a 500 ms */ }
}

// Ao ligar/desligar "show background": limpa e volta a pedir tudo desde o início
function resetSerial() {
    serialAfter = 0;
    document.getElementById("serial").textContent = "";
    refreshSerial();
}

refreshSerial();
setInterval(refreshSerial, 500);
