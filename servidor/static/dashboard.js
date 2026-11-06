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

        if (s.air === null) {
            // Se o sensor de ar não estiver presente, mostra "no sensor" em vez de valores
            document.getElementById("air-density").textContent = "no sensor";
            document.getElementById("air-temperature").textContent = "no sensor";
            document.getElementById("air-pressure").textContent = "no sensor";
        } else {
            document.getElementById("air-density").textContent = s.air.density.toFixed(4) + " kg/m³";
            document.getElementById("air-temperature").textContent = s.air.temperature.toFixed(1) + " °C";
            document.getElementById("air-pressure").textContent = s.air.pressure.toFixed(1) + " hPa";
        }

        document.getElementById("thrust-offset").textContent = s.thrust_offset === null ? "no sensor" : s.thrust_offset;


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

// ----- Portas: o menu com as portas USB, e o CONNECT à que estiver escolhida -----

// Pede a lista das portas ao servidor e enche o menu. A que está ligada fica escolhida e marcada com ●
async function loadPorts() {
    const select = document.getElementById("port");
    if (document.activeElement === select) return;              // está a escolher: não mexer no menu aberto
    try {
        const r = await fetch("/ports");
        const data = await r.json();
        const chosen = select.value;                            // para não perder a escolha ao atualizar
        select.innerHTML = "";
        for (const p of data.ports) {
            const option = document.createElement("option");
            option.value = p.port;
            // p. ex.: "/dev/ttyUSB0 - USB2.0-Serial [1A86:7523] ● connected"
            option.textContent = `${p.device} - ${p.description}${p.manufacturer ? " (" + p.manufacturer + ")" : ""} [${p.usb_id}]`
                               + (p.connected ? "  ● connected" : "");
            if (p.connected || p.port === chosen) option.selected = true;
            select.appendChild(option);
        }
        if (data.ports.length === 0) select.innerHTML = '<option value="">(no USB ports)</option>';
    } catch (e) {
        select.innerHTML = '<option value="">(no answer from the server)</option>';
    }
}

// Liga à porta escolhida no menu (sem nenhuma escolhida: a porta por omissão do servidor)
async function connectNano() {
    const port = document.getElementById("port").value;
    await post("/connect", port ? {port: port} : {});
    loadPorts();                                                // para o ● passar para a porta nova
}

loadPorts();
setInterval(loadPorts, 5000);                                   // apanha um USB ligado ou desligado

refresh();
setInterval(refresh, 500);
