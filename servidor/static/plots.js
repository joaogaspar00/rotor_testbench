let timer = null;      // null = o despertador está desligado

let ultimo = 0;

const ctx = document.getElementById('graph');



const data = {
  datasets: [{
    label: 'thrust',
    data: [],
    fill: false,
    pointRadius: 0,
    borderColor: 'rgb(75, 192, 192)',
    tension: 0.1
  },
  {
    label: 'throtle',
    data: [],
    fill: false,
    pointRadius: 0,
    borderColor: 'rgb(255, 99, 132)',
    tension: 0.1
  }]
};



const chart = new Chart(ctx, {
    type: 'line',
    data: data,
    options: {
        scales: {
        y: {
            beginAtZero: true
        },
        x: { type: 'linear' }
        },
        animation: false
    }
});


async function addPoint() {

    const r = await fetch("/thrust?after=" + ultimo);
    const resposta = await r.json();
    if (!resposta.recording) stopPlot();       // ← aqui

    for (const p of resposta.points) {
        // push no thrust:    x = p.t, y = p.gf
        // push no throttle:  x = p.t, y = p.throttle
        // ultimo = p.n
    }

    const pontos_thurst = chart.data.datasets[0].data;
    const pontos_throtle = chart.data.datasets[1].data;

    for (const p of resposta.points) {
        pontos_thurst.push({ x: p.t, y: p.gf });
        pontos_throtle.push({ x: p.t, y: p.throttle });
        ultimo = p.n;
    }

    if (pontos_thurst.length === 0) return;                   // ainda não chegou nada
    const agora = pontos_thurst[pontos_thurst.length - 1].x;  // o t do último ponto


    while (pontos_thurst[0].x < agora - 30) {
        pontos_thurst.shift();
        pontos_throtle.shift();
    }

    chart.options.scales.x.min = Math.max(0, agora - 30);
    chart.options.scales.x.max = Math.max(30, agora);

    
    chart.update("none");

}

function startPlot() {
    if (timer !== null) return;      // já está a correr: não cria outro

    chart.data.datasets[0].data.length = 0;
    chart.data.datasets[1].data.length = 0;

    ultimo = 0;

    post("/thrust/start");          
    timer = setInterval(addPoint, 200);
}

function stopPlot() {
    clearInterval(timer);
    timer = null;
    post("/thrust/stop");
}