// A confirmação das ações do portal, no lugar do confirm() do navegador. A
// janela é criada na primeira vez que é usada: nenhuma página precisa de HTML
// próprio para ela.
//
//   if (!await confirmar({ titulo: 'Excluir o contato?', botao: 'Excluir', perigo: true })) return;
//
// Devolve true se a pessoa confirmou; Cancelar, Esc ou um clique fora contam como não.

function janelaDeConfirmacao() {
    let janela = document.getElementById('confirm-dialog');
    if (janela) return janela;

    janela = document.createElement('dialog');
    janela.id = 'confirm-dialog';
    janela.className = 'confirm-modal';
    janela.setAttribute('aria-labelledby', 'confirm-title');
    janela.setAttribute('aria-describedby', 'confirm-text');
    janela.innerHTML = `
        <h2 id="confirm-title"></h2>
        <p id="confirm-text"></p>
        <div class="confirm-actions">
            <button type="button" class="confirm-button" id="confirm-cancel">Cancelar</button>
            <button type="button" class="confirm-button" id="confirm-ok"></button>
        </div>`;
    document.body.appendChild(janela);
    return janela;
}

function confirmar({ titulo, texto = '', botao = 'Confirmar', perigo = false }) {
    const janela = janelaDeConfirmacao();
    const confirmarBotao = document.getElementById('confirm-ok');
    const cancelarBotao = document.getElementById('confirm-cancel');
    document.getElementById('confirm-title').textContent = titulo;
    const descricao = document.getElementById('confirm-text');
    descricao.textContent = texto;
    descricao.hidden = !texto;
    confirmarBotao.textContent = botao;
    confirmarBotao.classList.toggle('danger', perigo);

    return new Promise((resolver) => {
        const fechar = (resposta) => {
            janela.removeEventListener('close', aoFechar);
            janela.close();
            resolver(resposta);
        };
        // O close chega um instante depois de a janela fechar: o atrasado de uma
        // confirmação anterior não pode fechar esta, que já está aberta
        const aoFechar = () => { if (!janela.open) fechar(false); };
        confirmarBotao.onclick = () => fechar(true);
        cancelarBotao.onclick = () => fechar(false);
        // O clique no fundo escuro cai no próprio dialog, fora da caixa
        janela.onclick = (evento) => { if (evento.target === janela) fechar(false); };
        janela.addEventListener('close', aoFechar);
        janela.showModal();
        // O foco começa no Cancelar: um Enter sem querer não confirma nada
        cancelarBotao.focus();
    });
}
