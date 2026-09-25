document.addEventListener('DOMContentLoaded', () => {
    const container = document.getElementById('notifications');
    if (!container) return;

    const contadorNaoLidas = document.getElementById('notification-unread-badge');

    const INTERVALO_ATUALIZACAO = 60000;
    const ICONES = {
        I: 'fa-circle-info',
        A: 'fa-triangle-exclamation',
        U: 'fa-circle-exclamation',
    };
    const exibidas = new Map();

    function atualizarContador(quantidade) {
        if (!contadorNaoLidas) return;
        contadorNaoLidas.hidden = quantidade === 0;
        contadorNaoLidas.textContent = quantidade > 99 ? '99+' : quantidade;
        contadorNaoLidas.setAttribute(
            'aria-label',
            `${quantidade} notifica\u00e7\u00e3${quantidade === 1 ? 'o n\u00e3o lida' : '\u00f5es n\u00e3o lidas'}`,
        );
    }

    async function requisitar(url, metodo = 'GET') {
        const resposta = await fetch(url, {
            method: metodo,
            headers: { 'X-CSRFToken': container.dataset.csrfToken, 'Accept': 'application/json' },
        });
        if (!resposta.ok) throw new Error(`Erro inesperado (${resposta.status}).`);
        return resposta.json();
    }

    function remover(id) {
        const elemento = exibidas.get(id);
        if (!elemento) return;
        exibidas.delete(id);
        atualizarContador(exibidas.size);
        elemento.classList.add('leaving');
        elemento.addEventListener('animationend', () => elemento.remove(), { once: true });
    }

    async function marcarComoLida(id) {
        remover(id);
        try {
            await requisitar(`${container.dataset.apiUrl}${id}/read/`, 'POST');
        } catch (erro) {
            // Se falhar, a notificação volta na próxima atualização
        }
    }

    function criar(notificacao) {
        const elemento = document.createElement('div');
        elemento.className = `notification level-${notificacao.level}`;
        elemento.setAttribute('role', notificacao.level === 'U' ? 'alert' : 'status');

        const icone = document.createElement('i');
        icone.className = `fas ${ICONES[notificacao.level] || ICONES.I} notification-icon`;
        icone.title = notificacao.level_display;

        const corpo = document.createElement('div');
        corpo.className = 'notification-body';

        const titulo = document.createElement('div');
        titulo.className = 'notification-title';
        titulo.textContent = notificacao.title;

        const mensagem = document.createElement('div');
        mensagem.className = 'notification-message';
        mensagem.textContent = notificacao.message;

        const data = document.createElement('div');
        data.className = 'notification-date';
        data.textContent = `${notificacao.start_at} · `;

        const linkMural = document.createElement('a');
        linkMural.href = container.dataset.boardUrl;
        linkMural.textContent = 'Ver mural';
        data.appendChild(linkMural);

        const fechar = document.createElement('button');
        fechar.type = 'button';
        fechar.className = 'notification-close';
        fechar.title = 'Marcar como lida';
        fechar.innerHTML = '<i class="fas fa-xmark"></i>';
        fechar.addEventListener('click', () => marcarComoLida(notificacao.id));

        corpo.append(titulo, mensagem, data);
        elemento.append(icone, corpo, fechar);
        return elemento;
    }

    async function atualizar() {
        let dados;
        try {
            dados = await requisitar(container.dataset.apiUrl);
        } catch (erro) {
            return;
        }

        const ids = new Set(dados.notifications.map((n) => n.id));
        atualizarContador(ids.size);

        // Some da tela o que foi lido em outra aba ou desativado no admin
        for (const id of [...exibidas.keys()]) {
            if (!ids.has(id)) remover(id);
        }

        for (const notificacao of dados.notifications) {
            if (exibidas.has(notificacao.id)) continue;
            const elemento = criar(notificacao);
            exibidas.set(notificacao.id, elemento);
            container.appendChild(elemento);
        }
    }

    atualizar();
    setInterval(() => {
        if (document.visibilityState === 'visible') atualizar();
    }, INTERVALO_ATUALIZACAO);
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') atualizar();
    });
});
