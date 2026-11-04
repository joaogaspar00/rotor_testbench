// JavaScript da página Dashboard (templates/dashboard.html): pede o estado ao servidor e envia as ordens

// Pergunta o estado ao servidor e mostra-o na tabela. Corre a cada 500 ms.
// (É também o sinal de vida da página: se parar 2 s com o banco UNLOCKED, o servidor manda STOP.)
async function refresh() {
    try {
        const r = await fetch("/status");
        const s = await r.json();
        if (!r.ok) { show(s.detail, false); return; }
        const b = s.bench;
        document.getElementById("bench").textContent = [b.state, b.reason, ...b.problems].filter(x => x).join(" ");
        document.getElementById("esc").textContent = s.esc;
        document.getElementById("mode").textContent = s.mode;
        document.getElementById("motor").textContent = s.motor + " %";
        document.getElementById("battery").textContent = s.battery.state + "  " + s.battery.voltage.toFixed(2) + " V";
        document.getElementById("pot").textContent = s.pot;
    } catch (e) {
        show("no answer from the server", false);
    }
}

// Envia uma ordem (POST) e mostra a resposta na caixa: verde se correu bem, vermelho se não
async function post(url, body) {
    const name = url.slice(1).toUpperCase();                    // "/unlock" -> "UNLOCK"
    try {
        const r = await fetch(url, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(body || {}),
        });
        const answer = await r.json();
        if (r.ok) show(name + ": " + Object.values(answer).join(" "), true);   // p. ex. "UNLOCK: UNLOCKING"
        else      show(name + ": " + answer.detail, false);
    } catch (e) {
        show(name + ": no answer from the server", false);
    }
    refresh();
}

// Mostra uma mensagem na caixa nano-answer. ok = true (verde), false (vermelho) ou null (stand-by, azul)
function show(text, ok) {
    const box = document.getElementById("nano-answer");
    box.textContent = text;
    box.className = ok === null ? "standby" : (ok ? "ok" : "error");
}

show("Stand-by", null);                 // ao abrir a página: ainda não há respostas

refresh();
setInterval(refresh, 500);
