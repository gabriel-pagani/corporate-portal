// A configuração da tela vem em data-attributes: com o CSP ligado, o navegador
// recusa <script> inline, que é onde essas constantes moravam.
const {
    csrfToken: CSRF_TOKEN,
    apiUrl: NOTIFICATIONS_API_URL,
    readAllUrl: READ_ALL_API_URL,
} = document.getElementById('content').dataset;

const INTERVALO_ATUALIZACAO = 60000;
const ICONES = {
    I: 'fa-circle-info',
    A: 'fa-triangle-exclamation',
    U: 'fa-circle-exclamation',
};

let notificacoes = [];
let enviando = false;
// Muda a cada marcação para descartar atualizações que saíram antes dela
let versao = 0;

function escaparHtml(texto) {
    return String(texto ?? '').replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

// Remove acentos para tornar a pesquisa mais tolerante
function removerAcentos(texto) {
    return texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

async function requisitar(url, metodo = 'GET') {
    let resposta;
    try {
        resposta = await fetch(url, {
            method: metodo,
            headers: { 'X-CSRFToken': CSRF_TOKEN, 'Accept': 'application/json' },
        });
    } catch (erro) {
        throw new Error('Não foi possível se comunicar com o servidor.');
    }

    const dados = await resposta.json().catch(() => ({}));
    if (!resposta.ok) {
        throw new Error(dados.detail || `Erro inesperado (${resposta.status}).`);
    }
    return dados;
}

function mostrarErro(mensagem) {
    document.getElementById('alert-error-text').textContent = mensagem;
    document.getElementById('alert-error').hidden = !mensagem;
}

function notificacoesFiltradas() {
    const termo = removerAcentos(document.getElementById('search-input').value.toLowerCase().trim());
    const somenteNaoLidas = document.getElementById('only-unread').checked;

    return notificacoes.filter((notificacao) => {
        if (somenteNaoLidas && notificacao.is_read) return false;
        if (!termo) return true;
        return [notificacao.title, notificacao.message]
            .some((campo) => removerAcentos(campo.toLowerCase()).includes(termo));
    });
}

function cartao(notificacao) {
    const lida = notificacao.is_read;
    return `
        <article class="post level-${notificacao.level}${lida ? ' read' : ''}">
            <i class="fas ${ICONES[notificacao.level] || ICONES.I} post-icon" title="${escaparHtml(notificacao.level_display)}"></i>
            <div class="post-body">
                <div class="post-header">
                    <h3 class="post-title">${escaparHtml(notificacao.title)}</h3>
                    ${lida ? '' : '<span class="badge unread">Nova</span>'}
                </div>
                <p class="post-message">${escaparHtml(notificacao.message)}</p>
                <div class="post-footer">
                    <span><i class="far fa-clock"></i> ${escaparHtml(notificacao.start_at)} &middot; ${escaparHtml(notificacao.level_display)}</span>
                    ${lida ? '' : `<button type="button" class="button small" data-action="ler" data-id="${notificacao.id}"><i class="fas fa-check"></i> Marcar como lida</button>`}
                </div>
            </div>
        </article>`;
}

function renderizar() {
    const lista = notificacoesFiltradas();
    document.getElementById('board').innerHTML = lista.map(cartao).join('');

    const vazio = document.getElementById('empty-message');
    vazio.hidden = lista.length > 0;
    vazio.textContent = notificacoes.length ? 'Nenhuma notificação encontrada.' : 'Nenhuma notificação no mural.';

    const naoLidas = notificacoes.filter((notificacao) => !notificacao.is_read).length;
    const contador = document.getElementById('unread-count');
    contador.hidden = naoLidas === 0;
    contador.textContent = naoLidas === 1 ? '1 nova' : `${naoLidas} novas`;
    document.getElementById('read-all').disabled = naoLidas === 0;
}

async function marcarComoLida(id) {
    if (enviando) return;
    enviando = true;
    try {
        await requisitar(`${NOTIFICATIONS_API_URL}${id}/read/`, 'POST');
        versao++;
        const notificacao = notificacoes.find((n) => n.id === id);
        if (notificacao) notificacao.is_read = true;
        mostrarErro('');
        renderizar();
    } catch (erro) {
        mostrarErro(erro.message);
    } finally {
        enviando = false;
    }
}

async function marcarTodasComoLidas() {
    if (enviando) return;
    enviando = true;
    try {
        await requisitar(READ_ALL_API_URL, 'POST');
        versao++;
        notificacoes.forEach((notificacao) => { notificacao.is_read = true; });
        mostrarErro('');
        renderizar();
    } catch (erro) {
        mostrarErro(erro.message);
    } finally {
        enviando = false;
    }
}

async function atualizarMural() {
    if (enviando || document.visibilityState !== 'visible') return;
    const versaoInicial = versao;
    try {
        const dados = await requisitar(`${NOTIFICATIONS_API_URL}?all=1`);
        if (enviando || versao !== versaoInicial) return;
        notificacoes = dados.notifications;
        mostrarErro('');
        renderizar();
    } catch (erro) {
        mostrarErro(erro.message);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    notificacoes = JSON.parse(document.getElementById('notifications-data').textContent);
    renderizar();

    document.getElementById('search-input').addEventListener('input', renderizar);
    document.getElementById('only-unread').addEventListener('change', renderizar);
    document.getElementById('read-all').addEventListener('click', marcarTodasComoLidas);
    document.getElementById('board').addEventListener('click', (event) => {
        const botao = event.target.closest('[data-action="ler"]');
        if (botao) marcarComoLida(Number(botao.dataset.id));
    });

    setInterval(atualizarMural, INTERVALO_ATUALIZACAO);
    document.addEventListener('visibilitychange', atualizarMural);
});
