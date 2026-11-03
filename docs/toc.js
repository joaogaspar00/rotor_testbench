// Índice automático: uma ligação por cada <h2> e <h3> que tenha id (os <h3> ficam recuados)
const toc = document.getElementById("toc");
for (const h of document.querySelectorAll("h2[id], h3[id]")) {
    const li = document.createElement("li");
    if (h.tagName === "H3") li.className = "sub";
    li.innerHTML = `<a href="#${h.id}">${h.textContent}</a>`;
    toc.appendChild(li);
}
