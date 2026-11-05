document.addEventListener('DOMContentLoaded', () => {
    const toggleButton = document.getElementById('toggle');
    const userToggle = document.getElementById('user-toggle');
    const userDropdown = document.getElementById('user-dropdown');

    if (!userToggle || !userDropdown) return;

    function abrirDropdown() {
        userDropdown.classList.add('show');
        userToggle.classList.add('active');
    }

    function fecharDropdown() {
        userDropdown.classList.remove('show');
        userToggle.classList.remove('active');
    }

    // Minimizar a sidebar move o dropdown de lugar, então ele é fechado antes
    toggleButton.addEventListener('click', fecharDropdown);

    userToggle.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();

        if (userDropdown.classList.contains('show')) {
            fecharDropdown();
        } else {
            abrirDropdown();
        }
    });

    userDropdown.addEventListener('click', (event) => {
        if (event.target.closest('button[type="button"]')) fecharDropdown();
    });

    // Clicar fora fecha o dropdown aberto
    document.addEventListener('click', (event) => {
        if (!userToggle.contains(event.target) && !userDropdown.contains(event.target)) {
            fecharDropdown();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') fecharDropdown();
    });
});

// Listas dos cards: mostram só os itens que cabem inteiros na altura que o
// card tem. Os que não cabem ficam ocultos e, nas listas com data-more, viram
// um "e mais N" logo abaixo. Quem preenche a lista avisa por ajustarLista, e a
// mudança de altura do card chega pelo ResizeObserver do corpo do card (a
// lista em si encolhe até os itens, e não cresce sozinha quando o card cresce).
function cortarLista(lista) {
    const itens = [...lista.children];
    itens.forEach((item) => { item.hidden = false; });

    // Sem altura definida (antes do mosaico) não há o que cortar
    const limite = lista.clientHeight;
    if (!limite || lista.scrollHeight <= limite + 1) return 0;

    let ocultos = 0;
    for (const item of itens) {
        if (ocultos || item.offsetTop + item.offsetHeight > limite + 1) {
            item.hidden = true;
            ocultos += 1;
        }
    }
    return ocultos;
}

function ajustarLista(lista) {
    let ocultos = cortarLista(lista);

    if ('more' in lista.dataset) {
        let mais = lista.nextElementSibling;
        if (!mais || !mais.classList.contains('preview-more')) {
            mais = document.createElement('p');
            mais.className = 'preview-more';
            const link = document.createElement('a');
            const cabecalho = lista.closest('.service-card')?.querySelector('.service-card-header');
            link.href = cabecalho ? cabecalho.getAttribute('href') : '#';
            mais.appendChild(link);
            lista.after(mais);
        }
        // O "e mais N" ocupa uma linha: com ele à mostra cabe um item a menos
        mais.hidden = ocultos === 0;
        if (ocultos) ocultos = cortarLista(lista);
        mais.firstElementChild.textContent = `e mais ${ocultos}`;
        mais.hidden = ocultos === 0;
    }

    lista.dispatchEvent(new CustomEvent('lista:ajustada', { detail: { ocultos } }));
    return ocultos;
}

const observadorListas = new ResizeObserver((entradas) => {
    entradas.forEach((entrada) => {
        entrada.target.querySelectorAll('.preview-list[data-fit]').forEach(ajustarLista);
    });
});

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.service-card-body').forEach((corpo) => observadorListas.observe(corpo));
});

// Card da lista de contatos: a busca filtra ali mesmo, mostra quantos couberem
// no card, e o Enter abre a lista completa
document.addEventListener('DOMContentLoaded', () => {
    const campo = document.getElementById('home-contact-search');
    const resultados = document.getElementById('home-contact-results');
    const dica = document.getElementById('home-contact-hint');
    const dados = document.getElementById('home-contacts');
    if (!campo || !resultados || !dica || !dados) return;

    // Mais do que isso não cabe nem no card mais alto
    const LIMITE = 40;
    const contatos = JSON.parse(dados.textContent);
    const dicaInicial = dica.textContent;
    let encontrados = 0;

    function normalizar(texto) {
        return texto.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').trim();
    }

    const indice = contatos.map((contato) => ({
        contato,
        texto: normalizar([contato.name, contato.number, contato.sector].join(' ')),
    }));

    function linkDaLista(busca) {
        const url = new URL(resultados.dataset.contactsUrl, window.location.origin);
        url.searchParams.set('q', busca);
        return url.pathname + url.search;
    }

    function criarItem(contato) {
        const item = document.createElement('li');
        const link = document.createElement('a');
        link.href = linkDaLista(contato.name);
        link.title = 'Ver na lista de contatos';

        const icone = document.createElement('i');
        icone.className = 'fas fa-user item-icon';
        icone.setAttribute('aria-hidden', 'true');

        const texto = document.createElement('span');
        texto.className = 'item-text';
        const nome = document.createElement('strong');
        nome.textContent = contato.name;
        const setor = document.createElement('small');
        setor.textContent = contato.sector || 'Sem setor';
        texto.append(nome, setor);

        const numero = document.createElement('span');
        numero.className = 'item-aside contact-number';
        numero.textContent = contato.number || '-';

        link.append(icone, texto, numero);
        item.appendChild(link);
        return item;
    }

    function atualizarDica(ocultos) {
        if (!normalizar(campo.value)) {
            dica.textContent = dicaInicial;
        } else if (!encontrados) {
            dica.textContent = 'Nenhum contato encontrado.';
        } else {
            const fora = ocultos + Math.max(0, encontrados - LIMITE);
            dica.textContent = fora
                ? `Mais ${fora} fora do card. Enter abre a lista completa.`
                : 'Enter abre na lista de contatos.';
        }
    }

    function filtrar() {
        const termo = normalizar(campo.value);
        const lista = termo ? indice.filter((entrada) => entrada.texto.includes(termo)) : [];
        encontrados = lista.length;
        resultados.replaceChildren(...lista.slice(0, LIMITE).map(({ contato }) => criarItem(contato)));
        ajustarLista(resultados);
    }

    resultados.addEventListener('lista:ajustada', ({ detail }) => atualizarDica(detail.ocultos));
    campo.addEventListener('input', filtrar);
});

// Card do mural: acompanha as notificações que o alerta global já consulta,
// e só busca a lista de novo quando alguma foi lida ou chegou
document.addEventListener('DOMContentLoaded', () => {
    const lista = document.getElementById('home-notifications');
    const resumo = document.getElementById('home-unread-summary');
    const contador = document.getElementById('home-unread-count');
    const rotulo = document.getElementById('home-unread-label');
    if (!lista || !resumo || !contador || !rotulo) return;

    const ICONES = {
        I: 'fa-circle-info',
        A: 'fa-triangle-exclamation',
        U: 'fa-circle-exclamation',
    };
    const limite = Number(lista.dataset.limit) || 10;
    let buscando = false;

    function atualizarResumo(quantidade) {
        contador.textContent = quantidade;
        rotulo.textContent = quantidade === 1 ? 'não lida' : 'não lidas';
        resumo.classList.toggle('attention', quantidade > 0);
    }

    function criarItem(notificacao) {
        const item = document.createElement('li');
        item.className = `notification-item level-${notificacao.level}${notificacao.is_read ? '' : ' unread'}`;
        item.dataset.id = notificacao.id;

        const link = document.createElement('a');
        link.href = lista.dataset.boardUrl;
        link.title = notificacao.level_display + (notificacao.is_read ? '' : ' · não lida');

        const icone = document.createElement('i');
        icone.className = `fas ${ICONES[notificacao.level] || ICONES.I} item-icon`;
        icone.setAttribute('aria-hidden', 'true');

        const texto = document.createElement('span');
        texto.className = 'item-text';
        const titulo = document.createElement('strong');
        titulo.textContent = notificacao.title;
        const mensagem = document.createElement('small');
        mensagem.textContent = notificacao.message;
        texto.append(titulo, mensagem);

        const data = document.createElement('time');
        data.className = 'item-aside';
        data.textContent = notificacao.start_at;

        link.append(icone, texto, data);
        item.appendChild(link);
        return item;
    }

    async function recarregar() {
        if (buscando) return;
        buscando = true;
        try {
            const resposta = await fetch(lista.dataset.apiUrl, { headers: { 'Accept': 'application/json' } });
            if (!resposta.ok) return;
            const { notifications } = await resposta.json();
            const itens = notifications.slice(0, limite).map(criarItem);
            if (!itens.length) {
                const vazio = document.createElement('li');
                vazio.className = 'preview-empty';
                vazio.textContent = 'Nenhuma notificação no mural.';
                itens.push(vazio);
            }
            lista.replaceChildren(...itens);
            ajustarLista(lista);
        } catch (erro) {
            // Sem rede o card fica como estava; a próxima rodada tenta de novo
        } finally {
            buscando = false;
        }
    }

    // A primeira consulta do alerta chega logo depois da página, que já veio
    // atualizada do servidor: ela só marca o ponto de partida
    let assinatura = null;

    document.addEventListener('notifications:updated', ({ detail }) => {
        const naoLidas = detail.unreadIds;
        atualizarResumo(naoLidas.size);

        const atual = [...naoLidas].sort((a, b) => a - b).join(',');
        if (assinatura !== null && atual !== assinatura) recarregar();
        assinatura = atual;
    });
});

// Mosaico e personalização dos cards. Os cards ficam em colunas com o mesmo
// espaço entre todos, cada um com a altura que o usuário escolheu (ou a padrão
// do serviço). Como a posição de cada card é um transform, reorganizar ou
// redimensionar é só recalcular, e o CSS anima o resto.
document.addEventListener('DOMContentLoaded', () => {
    const grade = document.getElementById('quick-access');
    const barra = document.getElementById('quick-access-toolbar');
    if (!grade || !barra) return;

    const botaoPersonalizar = document.getElementById('quick-access-customize');
    const botaoConcluir = document.getElementById('quick-access-finish');
    const botaoRestaurar = document.getElementById('quick-access-reset');
    const dica = document.getElementById('quick-access-hint');
    const vazio = document.getElementById('quick-access-empty');
    const rolagem = grade.closest('.main-content') || document.scrollingElement;
    const textoDica = dica.textContent;

    const ESPACO = 20;
    const COLUNA_MINIMA = 340;
    const ALTURA_MINIMA = Number(grade.dataset.minHeight) || 180;
    const ALTURA_MAXIMA = Number(grade.dataset.maxHeight) || 900;
    const PASSO_TECLADO = 20;
    const DURACAO = 420;
    const reduzMovimento = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let ordem = [...grade.querySelectorAll('.service-card')];
    let posicoes = new Map();
    let editando = false;
    let arrasto = null;
    let redimensionamento = null;
    let lugar = null;
    let quadro = null;

    // Só as alturas que o usuário mudou vão para o servidor; o resto segue a
    // padrão do serviço, que pode mudar numa versão futura
    const alturas = new Map();
    ordem.forEach((card) => {
        if (card.dataset.height !== card.dataset.defaultHeight) {
            alturas.set(card.dataset.service, Number(card.dataset.height));
        }
    });

    const oculto = (card) => card.classList.contains('is-hidden');
    const visiveis = () => ordem.filter((card) => editando || !oculto(card));
    const transform = (p) => `translate3d(${p.x}px, ${p.y}px, 0)`;
    const limitar = (valor, minimo, maximo) => Math.max(minimo, Math.min(maximo, valor));
    const alturaDe = (card) => alturas.get(card.dataset.service) ?? Number(card.dataset.defaultHeight);

    function calcular() {
        const cards = visiveis();
        const largura = grade.clientWidth;
        let colunas = Math.max(1, Math.floor((largura + ESPACO) / (COLUNA_MINIMA + ESPACO)));
        colunas = Math.min(colunas, Math.max(cards.length, 1));
        const larguraColuna = (largura - ESPACO * (colunas - 1)) / colunas;

        for (const card of ordem) card.style.width = `${larguraColuna}px`;

        // Cada card vai para a coluna mais curta, na ordem escolhida
        const pilhas = Array.from({ length: colunas }, (_, indice) => ({
            x: indice * (larguraColuna + ESPACO),
            altura: 0,
        }));
        const resultado = new Map();
        for (const card of cards) {
            const pilha = pilhas.reduce((menor, atual) => (atual.altura < menor.altura ? atual : menor));
            const h = alturaDe(card);
            resultado.set(card, { x: pilha.x, y: pilha.altura, w: larguraColuna, h });
            pilha.altura += h + ESPACO;
        }

        const total = Math.max(0, ...pilhas.map((pilha) => pilha.altura - ESPACO));
        return { resultado, total };
    }

    function posicionarLugar(p) {
        if (!lugar || !p) return;
        lugar.style.width = `${p.w}px`;
        lugar.style.height = `${p.h}px`;
        lugar.style.transform = transform(p);
    }

    function aplicar() {
        const { resultado, total } = calcular();
        posicoes = resultado;
        grade.style.height = `${total}px`;

        for (const [card, p] of resultado) {
            card.style.height = `${p.h}px`;
            if (arrasto && arrasto.ativo && card === arrasto.card) {
                posicionarLugar(p);
                continue;
            }
            if (!card.dataset.placed) {
                // O card que aparece pela primeira vez já nasce no lugar, sem deslizar do canto
                card.dataset.placed = '1';
                card.style.transition = 'none';
                card.style.transform = transform(p);
                card.getBoundingClientRect();
                card.style.transition = '';
            } else {
                card.style.transform = transform(p);
            }
        }

        vazio.hidden = editando || resultado.size > 0;
    }

    let agendado = false;
    function agendar() {
        if (agendado) return;
        agendado = true;
        requestAnimationFrame(() => {
            agendado = false;
            aplicar();
        });
    }

    grade.classList.add('masonry');
    aplicar();
    requestAnimationFrame(() => requestAnimationFrame(() => grade.classList.add('animated')));

    let larguraAtual = grade.clientWidth;
    new ResizeObserver(() => {
        if (grade.clientWidth === larguraAtual) return;
        larguraAtual = grade.clientWidth;
        agendar();
    }).observe(grade);

    // Ordem do DOM igual à da tela, para o Tab seguir os cards. Mover um nó
    // interrompe a transição dele, então só acontece com tudo parado.
    function sincronizarDom() {
        if (arrasto || redimensionamento) return;
        const focado = document.activeElement;
        ordem.forEach((card) => grade.appendChild(card));
        if (focado && grade.contains(focado)) focado.focus({ preventScroll: true });
    }

    let temporizadorDom = null;
    function sincronizarDepois() {
        clearTimeout(temporizadorDom);
        temporizadorDom = setTimeout(sincronizarDom, DURACAO + 40);
    }

    // Salvar
    let temporizador = null;

    function mostrarAviso(texto, erro = false) {
        barra.hidden = false;
        dica.hidden = false;
        dica.textContent = texto;
        dica.classList.toggle('error', erro);
    }

    async function requisitar(metodo, corpo) {
        const resposta = await fetch(barra.dataset.layoutUrl, {
            method: metodo,
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': barra.dataset.csrfToken,
            },
            body: corpo ? JSON.stringify(corpo) : undefined,
            keepalive: true,
        });
        if (!resposta.ok) throw new Error(`Erro inesperado (${resposta.status}).`);
        return resposta.json();
    }

    async function enviar() {
        temporizador = null;
        try {
            await requisitar('POST', {
                order: ordem.map((card) => card.dataset.service),
                hidden: ordem.filter(oculto).map((card) => card.dataset.service),
                sizes: Object.fromEntries(alturas),
            });
            if (dica.classList.contains('error')) mostrarAviso(textoDica);
            if (!editando) barra.hidden = true;
        } catch (erro) {
            mostrarAviso('Não foi possível salvar a organização dos cards. Tente novamente.', true);
        }
    }

    function salvar() {
        clearTimeout(temporizador);
        temporizador = setTimeout(enviar, 400);
    }

    function salvarAgora() {
        if (temporizador === null) return;
        clearTimeout(temporizador);
        enviar();
    }

    // Modo de personalizar
    function definirOculto(card, valor) {
        card.classList.toggle('is-hidden', valor);
        const botao = card.querySelector('.card-visibility');
        const titulo = card.querySelector('.service-card-heading strong').textContent;
        botao.setAttribute('aria-pressed', String(!valor));
        botao.title = `${valor ? 'Exibir' : 'Ocultar'} o card ${titulo}`;
        botao.querySelector('i').className = `fas ${valor ? 'fa-eye-slash' : 'fa-eye'}`;
    }

    function entrarEdicao() {
        editando = true;
        grade.classList.add('editing');
        ordem.forEach((card) => { card.tabIndex = 0; });
        botaoPersonalizar.hidden = true;
        botaoConcluir.hidden = false;
        botaoRestaurar.hidden = false;
        mostrarAviso(textoDica);
        aplicar();
    }

    function sairEdicao() {
        editando = false;
        grade.classList.remove('editing');
        ordem.forEach((card) => card.removeAttribute('tabindex'));
        botaoPersonalizar.hidden = false;
        botaoConcluir.hidden = true;
        botaoRestaurar.hidden = true;
        // A barra só fica fora da edição para mostrar um erro ao salvar
        if (!dica.classList.contains('error')) barra.hidden = true;
        salvarAgora();
        aplicar();
    }

    botaoPersonalizar.addEventListener('click', entrarEdicao);
    botaoConcluir.addEventListener('click', sairEdicao);

    // Esc conclui a personalização, como o botão Concluir. Fica na captura para
    // ver o menu do usuário antes de ele fechar: com o menu aberto, Esc só o fecha.
    // No meio de um arrasto ou de um ajuste de altura, espera soltar
    document.addEventListener('keydown', (evento) => {
        if (evento.key !== 'Escape' || !editando || arrasto || redimensionamento) return;
        if (document.getElementById('user-dropdown')?.classList.contains('show')) return;
        evento.preventDefault();
        sairEdicao();
    }, true);

    botaoRestaurar.addEventListener('click', async () => {
        clearTimeout(temporizador);
        temporizador = null;
        try {
            const { order } = await requisitar('DELETE');
            const porChave = new Map(ordem.map((card) => [card.dataset.service, card]));
            const restaurada = order.map((chave) => porChave.get(chave)).filter(Boolean);
            ordem = restaurada.concat(ordem.filter((card) => !restaurada.includes(card)));
            ordem.forEach((card) => definirOculto(card, false));
            alturas.clear();
            mostrarAviso(textoDica);
            aplicar();
            sincronizarDepois();
        } catch (erro) {
            mostrarAviso('Não foi possível restaurar os cards. Tente novamente.', true);
        }
    });

    grade.addEventListener('click', (evento) => {
        const botao = evento.target.closest('.card-visibility');
        if (!botao || !editando) return;
        const card = botao.closest('.service-card');
        definirOculto(card, !oculto(card));
        salvar();
    });

    function mudarAltura(card, altura) {
        const nova = Math.round(limitar(altura, ALTURA_MINIMA, ALTURA_MAXIMA));
        if (nova === alturaDe(card)) return false;
        alturas.set(card.dataset.service, nova);
        aplicar();
        return true;
    }

    // Pelo teclado: com o card focado, as setas o levam para trás ou para a
    // frente, e com Shift aumentam ou diminuem a altura
    grade.addEventListener('keydown', (evento) => {
        if (!editando || arrasto || redimensionamento) return;
        const card = evento.target.closest('.service-card');
        if (!card || evento.target !== card) return;

        if (evento.shiftKey && (evento.key === 'ArrowUp' || evento.key === 'ArrowDown')) {
            evento.preventDefault();
            const passo = evento.key === 'ArrowDown' ? PASSO_TECLADO : -PASSO_TECLADO;
            if (mudarAltura(card, alturaDe(card) + passo)) salvar();
            return;
        }

        const passo = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 }[evento.key];
        if (!passo) return;
        evento.preventDefault();
        const de = ordem.indexOf(card);
        const para = limitar(de + passo, 0, ordem.length - 1);
        if (de === para) return;
        ordem.splice(de, 1);
        ordem.splice(para, 0, card);
        aplicar();
        sincronizarDepois();
        salvar();
    });

    function rolarAutomatico(y) {
        const area = rolagem.getBoundingClientRect();
        const margem = 80;
        if (y < area.top + margem) {
            rolagem.scrollTop -= Math.ceil((area.top + margem - y) / 5);
        } else if (y > area.bottom - margem) {
            rolagem.scrollTop += Math.ceil((y - (area.bottom - margem)) / 5);
        }
    }

    // Redimensionar: a borda de baixo segue o ponteiro, e o que está abaixo
    // do card e nas outras colunas se acomoda com a animação de sempre
    function quadroDoRedimensionamento() {
        if (!redimensionamento) return;
        const { card, ponteiroY, inicioY, inicioAltura } = redimensionamento;
        rolarAutomatico(ponteiroY);
        // A rolagem conta: puxar até a borda da tela e deixar rolar também estica o card
        mudarAltura(card, inicioAltura + (ponteiroY + rolagem.scrollTop) - inicioY);
        quadro = requestAnimationFrame(quadroDoRedimensionamento);
    }

    function iniciarRedimensionamento(evento, card) {
        evento.preventDefault();
        redimensionamento = {
            card,
            id: evento.pointerId,
            ponteiroY: evento.clientY,
            inicioY: evento.clientY + rolagem.scrollTop,
            inicioAltura: alturaDe(card),
        };
        card.classList.add('resizing');
        document.body.classList.add('card-resizing');
        card.setPointerCapture(evento.pointerId);
        quadro = requestAnimationFrame(quadroDoRedimensionamento);
    }

    function encerrarRedimensionamento(evento) {
        const { card, inicioAltura } = redimensionamento;
        if (card.hasPointerCapture(evento.pointerId)) card.releasePointerCapture(evento.pointerId);
        cancelAnimationFrame(quadro);
        redimensionamento = null;
        card.classList.remove('resizing');
        document.body.classList.remove('card-resizing');
        if (alturaDe(card) !== inicioAltura) salvar();
    }

    // Arrastar
    function reordenar(px, py, agora) {
        let alvo = null;
        for (const [card, p] of posicoes) {
            if (card === arrasto.card) continue;
            if (px >= p.x && px <= p.x + p.w && py >= p.y && py <= p.y + p.h) {
                alvo = card;
                break;
            }
        }

        // Depois de uma troca, o card trocado só conta de novo quando o ponteiro
        // sair dele: sem isso os dois ficariam trocando de lugar sem parar
        if (alvo !== arrasto.ignorar) arrasto.ignorar = null;
        if (alvo !== arrasto.alvo) {
            arrasto.alvo = alvo;
            arrasto.desde = agora;
        }
        if (!alvo || alvo === arrasto.ignorar || agora - arrasto.desde < 80) return;

        const de = ordem.indexOf(arrasto.card);
        const para = ordem.indexOf(alvo);
        ordem.splice(de, 1);
        ordem.splice(para, 0, arrasto.card);
        arrasto.ignorar = alvo;
        aplicar();
    }

    function quadroDoArrasto(agora) {
        if (!arrasto || !arrasto.ativo) return;
        const { card } = arrasto;
        rolarAutomatico(arrasto.ponteiro.y);

        const caixa = grade.getBoundingClientRect();
        const alvoX = arrasto.ponteiro.x - caixa.left - arrasto.pega.x;
        const alvoY = arrasto.ponteiro.y - caixa.top - arrasto.pega.y;

        // O card segue a mão com um leve atraso e inclina conforme a velocidade
        const suavidade = reduzMovimento ? 1 : 0.38;
        const antes = arrasto.atual.x;
        arrasto.atual.x += (alvoX - arrasto.atual.x) * suavidade;
        arrasto.atual.y += (alvoY - arrasto.atual.y) * suavidade;
        const inclinacao = reduzMovimento ? 0 : limitar((arrasto.atual.x - antes) * 0.3, -5, 5);
        arrasto.inclinacao += (inclinacao - arrasto.inclinacao) * 0.18;
        arrasto.escala += ((reduzMovimento ? 1 : 1.035) - arrasto.escala) * 0.25;

        card.style.transform = transform(arrasto.atual);
        card.style.rotate = `${arrasto.inclinacao.toFixed(2)}deg`;
        card.style.scale = arrasto.escala.toFixed(4);

        reordenar(arrasto.ponteiro.x - caixa.left, arrasto.ponteiro.y - caixa.top, agora);
        quadro = requestAnimationFrame(quadroDoArrasto);
    }

    function iniciarArrasto() {
        arrasto.ativo = true;
        lugar = document.createElement('div');
        lugar.className = 'card-placeholder';
        grade.appendChild(lugar);
        posicionarLugar(posicoes.get(arrasto.card));
        arrasto.card.classList.add('dragging');
        document.body.classList.add('card-dragging');
        quadro = requestAnimationFrame(quadroDoArrasto);
    }

    grade.addEventListener('pointerdown', (evento) => {
        if (!editando || arrasto || redimensionamento || evento.button !== 0) return;
        const card = evento.target.closest('.service-card');
        if (!card || evento.target.closest('.card-visibility')) return;
        const p = posicoes.get(card);
        if (!p) return;

        if (evento.target.closest('.card-resize-handle')) {
            iniciarRedimensionamento(evento, card);
            return;
        }

        evento.preventDefault();
        card.focus({ preventScroll: true });
        const caixa = grade.getBoundingClientRect();
        arrasto = {
            card,
            id: evento.pointerId,
            ativo: false,
            inicio: { x: evento.clientX, y: evento.clientY },
            ponteiro: { x: evento.clientX, y: evento.clientY },
            pega: { x: evento.clientX - caixa.left - p.x, y: evento.clientY - caixa.top - p.y },
            atual: { x: p.x, y: p.y },
            inclinacao: 0,
            escala: 1,
            alvo: null,
            desde: 0,
            ignorar: null,
        };
        card.setPointerCapture(evento.pointerId);
    });

    grade.addEventListener('pointermove', (evento) => {
        if (redimensionamento && evento.pointerId === redimensionamento.id) {
            redimensionamento.ponteiroY = evento.clientY;
            return;
        }
        if (!arrasto || evento.pointerId !== arrasto.id) return;
        arrasto.ponteiro = { x: evento.clientX, y: evento.clientY };
        const distancia = Math.hypot(evento.clientX - arrasto.inicio.x, evento.clientY - arrasto.inicio.y);
        if (!arrasto.ativo && distancia > 4) iniciarArrasto();
    });

    function soltar(evento) {
        if (redimensionamento && evento.pointerId === redimensionamento.id) {
            encerrarRedimensionamento(evento);
            return;
        }
        if (!arrasto || evento.pointerId !== arrasto.id) return;
        const { card, ativo } = arrasto;
        if (card.hasPointerCapture(evento.pointerId)) card.releasePointerCapture(evento.pointerId);
        cancelAnimationFrame(quadro);
        arrasto = null;
        if (!ativo) return;

        // Sem a classe de arrasto a transição volta, e o card desliza da mão até o lugar
        card.classList.remove('dragging');
        card.classList.add('dropping');
        document.body.classList.remove('card-dragging');
        const p = posicoes.get(card);
        if (p) card.style.transform = transform(p);
        card.style.rotate = '';
        card.style.scale = '';
        lugar.remove();
        lugar = null;

        setTimeout(() => card.classList.remove('dropping'), DURACAO);
        sincronizarDepois();
        salvar();
    }

    grade.addEventListener('pointerup', soltar);
    grade.addEventListener('pointercancel', soltar);

    window.addEventListener('pagehide', salvarAgora);
});
