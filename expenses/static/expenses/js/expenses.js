// A configuração da tela vem em data-attributes: com o CSP ligado, o navegador
// recusa <script> inline, que é onde essas constantes morariam.
const URLS = document.getElementById('content').dataset;

const permissoes = lerJson('permissions-data');
const LIMITES_DE_FOTO = lerJson('photo-limits-data');

const RASCUNHO = 'D';
const ENVIADA = 'E';
const CORRECAO = 'C';
const APROVADA = 'A';
// Depois de aprovada ou rejeitada, a despesa já não sai da lista
const EXCLUIVEIS = [RASCUNHO, ENVIADA, CORRECAO];
// Rejeitada e reembolsada: as que vêm aos poucos na lista do funcionário
const ENCERRADAS_MINHAS = ['R', 'P'];

let minhas = lerJson('my-expenses-data');
// As abas da lista do funcionário, uma por status. As encerradas vêm aos poucos,
// então a contagem delas vem do servidor; as outras estão todas na lista.
const ABAS_MINHAS = [RASCUNHO, CORRECAO, ENVIADA, APROVADA, 'P', 'R'];
let contagensMinhas = lerJson('my-counts-data');
// Começa na primeira aba com despesa, quando a lista é desenhada pela primeira vez
let filtroMinhas = null;
// A despesa aberta no formulário do funcionário, e as fotos que esperam a leitura
let emEdicao = null;
let fotosEscolhidas = [];
// O guia é um lançamento de teste: a pessoa toca nos botões e mexe nos campos de
// verdade, mas nada vai ao servidor (requisitar responde sozinho) e a despesa é
// sempre a de exemplo, com a nota de exemplo do app, o que quer que ela digite.
// Tudo acontece numa lista vazia no lugar das despesas dela, que voltam intactas.
let emGuia = false;
const ID_DO_EXEMPLO = -1;
const ITENS_DO_EXEMPLO = [
    ['CAFE TORRADO 500G', '1', '18.90'],
    ['AGUA MINERAL 1,5L', '2', '7.00'],
    ['PAO DE FORMA', '1', '9.50'],
];

function despesaDeExemplo(status) {
    const itens = ITENS_DO_EXEMPLO.map(([description, quantity, amount]) => ({ description, quantity, amount }));
    const total = itens.reduce((soma, item) => soma + (Number(item.amount) || 0), 0).toFixed(2);
    return {
        id: ID_DO_EXEMPLO,
        status,
        status_display: status === ENVIADA ? 'Enviada' : 'Rascunho',
        is_own: true,
        merchant: 'LOJA DE EXEMPLO LTDA',
        cnpj: '11222333000181',
        issue_date: '2026-11-10',
        total,
        reimbursable_total: total,
        cost_center: null,
        created_at: '',
        note: '',
        photos: [{ id: 0, url: URLS.examplePhotoUrl }],
        items: itens.map((item, indice) => ({
            id: indice + 1, description: item.description, quantity: String(item.quantity),
            amount: String(item.amount), unreadable: false, ignored: false,
        })),
        events: [],
    };
}

// Os cartões que o usuário abriu continuam abertos quando a lista é redesenhada
const abertas = new Set();

function escaparHtml(texto) {
    return String(texto ?? '').replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

function lerJson(id) {
    return JSON.parse(document.getElementById(id).textContent);
}

function urlCom(modelo, id) {
    return modelo.replace('/0/', `/${id}/`);
}

// No guia, o que iria ao servidor ganha a resposta de exemplo: as fotos viram o
// rascunho lido, o envio vira a despesa enviada, e o resto (a exclusão) dá certo
async function simularNoGuia(metodo, corpo) {
    if (corpo instanceof FormData) {
        // A leitura de verdade leva alguns segundos: o guia mostra a espera também
        await new Promise((pronto) => setTimeout(pronto, 1500));
        return { expense: despesaDeExemplo(RASCUNHO), read: true };
    }
    return metodo === 'POST' ? { expense: despesaDeExemplo(ENVIADA) } : {};
}

async function requisitar(url, metodo = 'GET', corpo = null) {
    if (emGuia) return simularNoGuia(metodo, corpo);
    const opcoes = {
        method: metodo,
        headers: { 'X-CSRFToken': URLS.csrfToken, 'Accept': 'application/json' },
    };
    if (corpo instanceof FormData) {
        opcoes.body = corpo;
    } else if (corpo !== null) {
        opcoes.headers['Content-Type'] = 'application/json';
        opcoes.body = JSON.stringify(corpo);
    }

    let resposta;
    try {
        resposta = await fetch(url, opcoes);
    } catch (erro) {
        throw new Error('Não foi possível se comunicar com o servidor. Confira a sua conexão.');
    }

    // O nginx recusa o envio grande antes de ele chegar ao portal, e responde com HTML
    if (resposta.status === 413) {
        throw recusa('As fotos passam do limite de envio. Tire a foto com menos resolução e tente de novo.', true);
    }
    const dados = await resposta.json().catch(() => ({}));
    if (!resposta.ok) {
        // O 400 é a regra que a pessoa resolve sozinha (tipo repetido, nota já enviada,
        // centro de custo faltando): vira aviso. O resto é falha de verdade.
        throw recusa(dados.detail || `Erro inesperado (${resposta.status}).`, resposta.status === 400);
    }
    return dados;
}

function recusa(mensagem, aviso) {
    const erro = new Error(mensagem);
    erro.aviso = aviso;
    return erro;
}

// Aviso (amarelo) é o que a pessoa corrige; erro (vermelho) é o que deu errado e não depende dela
function mostrarErro(mensagem, aviso = false) {
    const alerta = document.getElementById('alert-error');
    document.getElementById('alert-error-text').textContent = mensagem;
    alerta.classList.toggle('warning', aviso);
    document.getElementById('alert-error-icon').className = `fas ${aviso ? 'fa-triangle-exclamation' : 'fa-circle-xmark'}`;
    alerta.hidden = !mensagem;
    if (mensagem) alerta.scrollIntoView({ block: 'nearest' });
}

function mostrarSucesso(mensagem) {
    const aviso = document.getElementById('success-message');
    aviso.textContent = mensagem;
    aviso.hidden = !mensagem;
}

function moeda(valor) {
    return Number(valor || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function dataBr(iso) {
    const [ano, mes, dia] = iso.split('-');
    return `${dia}/${mes}/${ano}`;
}

// Trava o botão durante o envio e leva o erro para o alerta da página
async function executar(botao, acao) {
    if (botao.disabled) return;
    botao.disabled = true;
    mostrarErro('');
    mostrarSucesso('');
    try {
        await acao();
    } catch (erro) {
        mostrarErro(erro.message, erro.aviso);
    } finally {
        botao.disabled = false;
    }
}


// Abas

const abas = [...document.querySelectorAll('#tabs .tab')];

function abrirAba(nome) {
    abas.forEach((aba) => aba.classList.toggle('active', aba.dataset.tab === nome));
    document.querySelectorAll('.tab-panel').forEach((painel) => { painel.hidden = painel.id !== `tab-${nome}`; });
    history.replaceState(null, '', `#${nome}`);
}

abas.forEach((aba) => aba.addEventListener('click', () => abrirAba(aba.dataset.tab)));
// Com uma aba só não há o que escolher
document.getElementById('tabs').hidden = abas.length < 2;
if (abas.length) {
    const pedida = location.hash.slice(1);
    abrirAba(abas.some((aba) => aba.dataset.tab === pedida) ? pedida : abas[0].dataset.tab);
}


// O editor de itens, usado pelo funcionário e pelo aprovador. O total mostrado
// aqui é só uma prévia: o que vale é o que o servidor soma.

function htmlMarcaDeItem(item) {
    if (!item.ignored) return '';
    return '<span class="badge low">Não reembolsável</span>';
}

function htmlLinhaDeItem(item, aprovador) {
    const marca = aprovador
        ? `<label class="item-flag"><input type="checkbox" class="item-ignored"${item.ignored ? ' checked' : ''}> Fora do reembolso${item.unreadable ? ' (ilegível)' : ''}</label>`
        : `<span class="item-flag">${htmlMarcaDeItem(item)}</span>`;
    return `
        <div class="item-row${item.ignored ? ' out' : ''}" data-item-id="${item.id ?? ''}">
            <label class="item-field description"><span>Descrição</span>
                <input type="text" class="item-description" maxlength="200" value="${escaparHtml(item.description)}" required>
            </label>
            <label class="item-field quantity"><span>Qtd.</span>
                <input type="number" class="item-quantity" inputmode="decimal" min="0.001" step="any" value="${escaparHtml(item.quantity)}">
            </label>
            <label class="item-field amount"><span>Valor (R$)</span>
                <input type="number" class="item-amount" inputmode="decimal" min="0" step="0.01" value="${escaparHtml(item.amount)}" required>
            </label>
            ${marca}
            <button type="button" class="item-remove" title="Remover o item" aria-label="Remover o item"><i class="fas fa-trash" aria-hidden="true"></i></button>
        </div>`;
}

function lerItens(lista) {
    return [...lista.querySelectorAll('.item-row')].map((linha) => ({
        id: linha.dataset.itemId ? Number(linha.dataset.itemId) : null,
        description: linha.querySelector('.item-description').value.trim(),
        quantity: linha.querySelector('.item-quantity').value || '1',
        amount: linha.querySelector('.item-amount').value,
        ignored: linha.querySelector('.item-ignored')?.checked ?? false,
    }));
}

function atualizarTotais(lista) {
    const itens = lerItens(lista);
    const somar = (filtro) => moeda(itens.filter(filtro).reduce((total, item) => total + (Number(item.amount) || 0), 0));
    document.querySelectorAll(`[data-items-total="${lista.id}"]`).forEach((alvo) => { alvo.textContent = somar(() => true); });
    document.querySelectorAll(`[data-items-reimbursable="${lista.id}"]`).forEach((alvo) => { alvo.textContent = somar((item) => !item.ignored); });

    // Sem nada a reembolsar não há o que aprovar: o servidor também recusa
    if (lista.id === 'review-items') {
        const semValor = !itens.some((item) => !item.ignored && Number(item.amount) > 0);
        document.querySelector('[data-review="approve"]').disabled = semValor;
        document.getElementById('review-nothing').hidden = !semValor;
    }
}

function adicionarItem(lista, focar = true) {
    const vazio = { description: '', quantity: '1', amount: '', ignored: false };
    lista.insertAdjacentHTML('beforeend', htmlLinhaDeItem(vazio, lista.dataset.approver === '1'));
    if (focar) lista.lastElementChild.querySelector('.item-description').focus();
}

function preencherItens(lista, itens, aprovador) {
    lista.dataset.approver = aprovador ? '1' : '';
    lista.innerHTML = itens.map((item) => htmlLinhaDeItem(item, aprovador)).join('');
    // Na despesa preenchida à mão a primeira linha já espera o funcionário
    if (!itens.length) adicionarItem(lista, false);
    atualizarTotais(lista);
}

document.addEventListener('click', (evento) => {
    const adicionar = evento.target.closest('[data-add-item]');
    if (adicionar) adicionarItem(document.getElementById(adicionar.dataset.addItem));

    const remover = evento.target.closest('.item-remove');
    if (remover) {
        const lista = remover.closest('.items');
        remover.closest('.item-row').remove();
        atualizarTotais(lista);
    }
});

document.addEventListener('input', (evento) => {
    const linha = evento.target.closest('.item-row');
    if (!linha) return;
    if (evento.target.classList.contains('item-ignored')) {
        linha.classList.toggle('out', evento.target.checked);
    } else if (evento.target.classList.contains('item-description') && !linha.querySelector('.item-ignored')) {
        // A marca era da descrição antiga: o servidor compara a nova no envio
        linha.querySelector('.item-flag').innerHTML = '';
        linha.classList.remove('out');
    }
    atualizarTotais(linha.closest('.items'));
});


// O cartão de uma despesa, nas listas

function htmlItens(despesa) {
    return `<ul class="item-list">${despesa.items.map((item) => `
        <li class="${item.ignored ? 'out' : ''}">
            <span>${escaparHtml(item.description)}</span>
            <span class="item-amount-text">${moeda(item.amount)}</span>
            <small>Qtd. ${escaparHtml(item.quantity.replace('.', ','))} ${htmlMarcaDeItem(item)}</small>
        </li>`).join('')}</ul>`;
}

function htmlFotos(despesa) {
    return `<div class="photo-grid">${despesa.photos.map((foto, indice) => `
        <a class="photo" href="${foto.url}" target="_blank" rel="noopener" title="Abrir a foto ${indice + 1} em tamanho real">
            <img src="${foto.url}" alt="Foto ${indice + 1} do recibo" loading="lazy">
        </a>`).join('')}</div>`;
}

function htmlHistorico(despesa) {
    if (!despesa.events.length) return '';
    return `<details class="more"><summary>Histórico</summary><ul class="history">${despesa.events.map((evento) => `
        <li>
            <strong>${escaparHtml(evento.status_display)}</strong> · ${escaparHtml(evento.created_at)}${evento.user ? ` · ${escaparHtml(evento.user)}` : ''}
            ${evento.note ? `<span class="history-note">${escaparHtml(evento.note)}</span>` : ''}
        </li>`).join('')}</ul></details>`;
}

function htmlStatus(despesa) {
    return `<span class="badge status-${despesa.status}">${escaparHtml(despesa.status_display)}</span>`;
}

function htmlDataDaNota(despesa) {
    return despesa.issue_date ? `<span>Nota de ${dataBr(despesa.issue_date)}</span>` : '';
}

// Com `direto`, o cartão não abre: o clique leva à análise da despesa. Com `seta`,
// uma seta convida quem lança a despesa a abrir o cartão e ver os itens
function htmlCartao(despesa, {
    titulo = null, meta = null, topo = '', corpo = '', gerencia = false, direto = false, seta = false,
} = {}) {
    const aberta = abertas.has(despesa.id);
    const resumo = `
                <span class="expense-title">${escaparHtml(titulo ?? (despesa.merchant || 'Estabelecimento não informado'))}</span>
                <span class="expense-value">${moeda(despesa.reimbursable_total)}${direto ? ' <i class="fas fa-chevron-right" aria-hidden="true"></i>' : ''}${seta ? ' <i class="fas fa-chevron-right expand-icon" aria-hidden="true"></i>' : ''}</span>
                <span class="expense-meta">${meta ?? htmlStatus(despesa) + htmlDataDaNota(despesa)}</span>`;
    if (direto) {
        return `
        <article class="expense-card" data-expense-id="${despesa.id}">
            <button type="button" class="expense-summary" data-open-review>${resumo}</button>
        </article>`;
    }
    return `
        <article class="expense-card" data-expense-id="${despesa.id}">
            <button type="button" class="expense-summary" aria-expanded="${aberta}">${resumo}</button>
            <div class="expense-detail"${aberta ? '' : ' hidden'}>
                ${topo}
                ${despesa.note ? `<div class="notice"><span><strong>Observação do aprovador:</strong> <span class="history-note">${escaparHtml(despesa.note)}</span></span></div>` : ''}
                ${gerencia ? `
                <p class="totals">A reembolsar: <strong>${moeda(despesa.reimbursable_total)}</strong> · Total da nota: ${moeda(despesa.total)}</p>
                <p class="muted">Centro de custo: ${despesa.cost_center ? escaparHtml(despesa.cost_center.label) : 'não informado'} · Criada em ${escaparHtml(despesa.created_at)}</p>` : ''}
                <h3>Itens</h3>
                ${htmlItens(despesa)}
                <h3>Fotos</h3>
                ${htmlFotos(despesa)}
                ${gerencia ? htmlHistorico(despesa) : ''}
                ${corpo}
            </div>
        </article>`;
}

// Abre e fecha o cartão; devolve a despesa do cartão clicado para as ações dele
function despesaDoClique(evento, despesas) {
    const cartao = evento.target.closest('.expense-card');
    if (!cartao) return null;
    const id = Number(cartao.dataset.expenseId);

    const resumo = evento.target.closest('.expense-summary');
    const detalhe = cartao.querySelector('.expense-detail');
    if (resumo && detalhe) {
        detalhe.hidden = !detalhe.hidden;
        resumo.setAttribute('aria-expanded', String(!detalhe.hidden));
        if (detalhe.hidden) abertas.delete(id);
        else abertas.add(id);
    }
    return despesas.find((despesa) => despesa.id === id);
}


// Minhas despesas

const editor = document.getElementById('expense-editor');
const formulario = document.getElementById('expense-form');
const itensDoFormulario = document.getElementById('expense-items');

function contarMinhas(status) {
    return ENCERRADAS_MINHAS.includes(status)
        ? contagensMinhas[status] || 0
        : minhas.filter((despesa) => despesa.status === status).length;
}

function renderizarMinhas() {
    const temDespesa = ABAS_MINHAS.some((status) => contarMinhas(status) > 0);
    if (filtroMinhas === null) filtroMinhas = ABAS_MINHAS.find((status) => contarMinhas(status) > 0) || ENVIADA;
    // Quem ainda não enviou nada não precisa de abas, só do botão de nova despesa
    document.getElementById('my-filters').hidden = !temDespesa;
    document.querySelectorAll('#my-filters .filter').forEach((botao) => {
        const ativo = botao.dataset.filter === filtroMinhas;
        botao.classList.toggle('active', ativo);
        botao.setAttribute('aria-pressed', String(ativo));
        botao.querySelector('.count').textContent = contarMinhas(botao.dataset.filter);
    });

    const visiveis = minhas.filter((despesa) => despesa.status === filtroMinhas);
    document.getElementById('my-expenses').innerHTML = visiveis.map((despesa) => {
        let acao = '';
        if (despesa.status === RASCUNHO) acao = 'Continuar o envio';
        if (despesa.status === CORRECAO) acao = 'Corrigir e reenviar';
        const botoes = [
            EXCLUIVEIS.includes(despesa.status) ? '<button type="button" class="button danger" data-delete>Excluir</button>' : '',
            acao ? `<button type="button" class="button primary" data-edit>${acao}</button>` : '',
        ].join('');
        return htmlCartao(despesa, { corpo: botoes && `<div class="editor-actions">${botoes}</div>`, seta: true });
    }).join('');
    const vazio = document.getElementById('my-empty');
    vazio.textContent = temDespesa ? 'Nenhuma despesa nesta situação.' : 'Você ainda não enviou nenhuma despesa.';
    vazio.hidden = visiveis.length > 0;
    document.getElementById('my-more').hidden = !(
        ENCERRADAS_MINHAS.includes(filtroMinhas) && visiveis.length < contarMinhas(filtroMinhas)
    );
}

function guardarMinha(despesa) {
    // O rascunho novo toma o lugar do anterior, como no servidor
    minhas = [despesa, ...minhas.filter((outra) => (
        outra.id !== despesa.id && !(despesa.status === RASCUNHO && outra.status === RASCUNHO)
    ))];
}

// passo: 'fotos', 'formulario' ou null para voltar à lista
function mostrarEditor(passo) {
    document.getElementById('my-list').hidden = passo !== null;
    // Com uma despesa aberta, os botões do cabeçalho recomeçariam e perderiam o que está sendo feito
    document.getElementById('header-actions').hidden = passo !== null;
    editor.hidden = passo === null;
    document.getElementById('step-photos').hidden = passo !== 'fotos';
    formulario.hidden = passo !== 'formulario';
    // Cada troca de tela começa do topo, com o cabeçalho e a logo à vista
    window.scrollTo(0, 0);
}

function fecharEditor() {
    emEdicao = null;
    mostrarEditor(null);
    renderizarMinhas();
}

function renderizarFotosEscolhidas() {
    const grade = document.getElementById('photo-previews');
    grade.querySelectorAll('img').forEach((imagem) => URL.revokeObjectURL(imagem.src));
    grade.innerHTML = fotosEscolhidas.map((foto, indice) => `
        <div class="photo">
            <img src="${URL.createObjectURL(foto)}" alt="Foto ${indice + 1} escolhida">
            <button type="button" class="photo-remove" data-remove-photo="${indice}" title="Remover a foto" aria-label="Remover a foto ${indice + 1}">
                <i class="fas fa-xmark" aria-hidden="true"></i>
            </button>
        </div>`).join('');
    const cheio = fotosEscolhidas.length >= LIMITES_DE_FOTO.max_photos;
    document.getElementById('camera-button').hidden = cheio;
    document.getElementById('gallery-button').hidden = cheio;
    document.getElementById('read-photos').disabled = !fotosEscolhidas.length || reduzindo;
}

// Com uma despesa, as fotos novas trocam as dela; sem, começam uma despesa
function abrirFotos(despesa = null) {
    emEdicao = despesa;
    fotosEscolhidas = [];
    renderizarFotosEscolhidas();
    mostrarEditor('fotos');
}

// O servidor guarda a foto com o lado maior em 2000 px. Reduzir aqui, antes
// do envio, troca os 4 a 12 MB da câmera por uns 500 KB: no 4G da obra é a
// diferença entre segundos e minutos esperando.
const LADO_MAXIMO = 2000;
// Sem enviar enquanto as fotos ainda estão sendo reduzidas
let reduzindo = false;

async function reduzirFoto(arquivo) {
    try {
        // O from-image endireita a foto que o celular gravou deitada, pelo EXIF
        const imagem = await createImageBitmap(arquivo, { imageOrientation: 'from-image' });
        const escala = Math.min(1, LADO_MAXIMO / Math.max(imagem.width, imagem.height));
        const tela = document.createElement('canvas');
        tela.width = Math.round(imagem.width * escala);
        tela.height = Math.round(imagem.height * escala);
        tela.getContext('2d').drawImage(imagem, 0, 0, tela.width, tela.height);
        imagem.close();
        const reduzida = await new Promise((pronto) => tela.toBlob(pronto, 'image/jpeg', 0.85));
        // A redução só vale se diminuiu: a foto pequena vai como está
        return reduzida && reduzida.size < arquivo.size ? new File([reduzida], 'foto.jpg', { type: 'image/jpeg' }) : arquivo;
    } catch (erro) {
        // Navegador sem suporte ou imagem que ele não abre: vai o original, e o servidor reduz ou recusa
        return arquivo;
    }
}

async function escolherFotos(evento) {
    mostrarErro('');
    const arquivos = [...evento.target.files];
    // Limpo, o campo aceita a mesma foto de novo se ela for removida
    evento.target.value = '';
    reduzindo = true;
    renderizarFotosEscolhidas();
    for (const original of arquivos) {
        if (fotosEscolhidas.length >= LIMITES_DE_FOTO.max_photos) {
            mostrarErro(`São no máximo ${LIMITES_DE_FOTO.max_photos} fotos por despesa.`, true);
            break;
        }
        const arquivo = await reduzirFoto(original);
        if (arquivo.size > LIMITES_DE_FOTO.max_size) {
            mostrarErro(`A foto passa de ${LIMITES_DE_FOTO.max_size / 1024 / 1024} MB.`, true);
            continue;
        }
        fotosEscolhidas.push(arquivo);
        renderizarFotosEscolhidas();
    }
    reduzindo = false;
    renderizarFotosEscolhidas();
}

function abrirFormulario(despesa, leituraFalhou = false) {
    emEdicao = despesa;
    formulario.merchant.value = despesa.merchant;
    formulario.cnpj.value = despesa.cnpj;
    formulario.issue_date.value = despesa.issue_date || '';
    document.getElementById('reading-failed').hidden = !leituraFalhou;

    const correcao = document.getElementById('correction-note');
    correcao.hidden = !(despesa.status === CORRECAO && despesa.note);
    correcao.innerHTML = `<span><strong>O aprovador pediu uma correção:</strong> <span class="history-note">${escaparHtml(despesa.note)}</span></span>`;

    document.getElementById('form-photos').innerHTML = htmlFotos(despesa);
    preencherItens(itensDoFormulario, despesa.items, false);
    document.getElementById('discard-draft').hidden = despesa.status !== RASCUNHO;
    mostrarEditor('formulario');
}

// Quem aprova, paga ou configura não lança despesa: a aba dele nem vem na página
if (permissoes.submit) {
    document.getElementById('new-expense').addEventListener('click', () => abrirFotos());
    document.getElementById('camera-input').addEventListener('change', escolherFotos);
    document.getElementById('gallery-input').addEventListener('change', escolherFotos);

    // No guia, a câmera e a galeria não abrem: a foto é a nota de exemplo
    document.querySelector('.photo-actions').addEventListener('click', async (evento) => {
        if (!emGuia || !evento.target.closest('label')) return;
        evento.preventDefault();
        const resposta = await fetch(URLS.examplePhotoUrl);
        fotosEscolhidas = [new File([await resposta.blob()], 'nota-exemplo.jpg', { type: 'image/jpeg' })];
        renderizarFotosEscolhidas();
    });

    document.getElementById('photo-previews').addEventListener('click', (evento) => {
        const botao = evento.target.closest('[data-remove-photo]');
        if (!botao) return;
        fotosEscolhidas.splice(Number(botao.dataset.removePhoto), 1);
        renderizarFotosEscolhidas();
    });

    document.getElementById('cancel-photos').addEventListener('click', () => {
        // Quem só ia trocar as fotos volta para o formulário com as que já tinha
        if (emEdicao) abrirFormulario(emEdicao);
        else fecharEditor();
    });

    document.getElementById('read-photos').addEventListener('click', (evento) => {
        const estado = document.getElementById('reading-state');
        executar(evento.currentTarget, async () => {
            const corpo = new FormData();
            fotosEscolhidas.forEach((foto) => corpo.append('photos', foto));
            estado.hidden = false;
            try {
                const url = emEdicao ? urlCom(URLS.photosUrl, emEdicao.id) : URLS.expensesUrl;
                const dados = await requisitar(url, 'POST', corpo);
                guardarMinha(dados.expense);
                abrirFormulario(dados.expense, !dados.read);
            } finally {
                estado.hidden = true;
            }
        });
    });

    document.getElementById('change-photos').addEventListener('click', () => abrirFotos(emEdicao));
    document.getElementById('cancel-form').addEventListener('click', fecharEditor);

    document.getElementById('discard-draft').addEventListener('click', async (evento) => {
        const botao = evento.currentTarget;
        if (!await confirmar({
            titulo: 'Descartar esta despesa?', texto: 'As fotos serão apagadas.', botao: 'Descartar', perigo: true,
        })) return;
        executar(botao, async () => {
            await requisitar(urlCom(URLS.expenseUrl, emEdicao.id), 'DELETE');
            minhas = minhas.filter((despesa) => despesa.id !== emEdicao.id);
            fecharEditor();
        });
    });

    formulario.addEventListener('submit', (evento) => {
        evento.preventDefault();
        executar(formulario.querySelector('[type="submit"]'), async () => {
            const dados = await requisitar(urlCom(URLS.expenseUrl, emEdicao.id), 'POST', {
                merchant: formulario.merchant.value,
                cnpj: formulario.cnpj.value,
                issue_date: formulario.issue_date.value || null,
                items: lerItens(itensDoFormulario),
            });
            guardarMinha(dados.expense);
            // A despesa acabou de ir para Enviadas: é lá que ele espera vê-la
            filtroMinhas = dados.expense.status;
            fecharEditor();
            mostrarSucesso('Despesa enviada para aprovação.');
        });
    });

    document.getElementById('my-filters').addEventListener('click', (evento) => {
        const botao = evento.target.closest('.filter');
        if (!botao) return;
        filtroMinhas = botao.dataset.filter;
        renderizarMinhas();
    });

    // As encerradas mais antigas vêm aos poucos, pela aba de cada status
    document.getElementById('my-more').addEventListener('click', (evento) => {
        executar(evento.currentTarget, async () => {
            const carregadas = minhas.filter((despesa) => despesa.status === filtroMinhas).length;
            const dados = await requisitar(`${URLS.myClosedUrl}?status=${filtroMinhas}&offset=${carregadas}`);
            const ids = new Set(minhas.map((despesa) => despesa.id));
            minhas = [...minhas, ...dados.expenses.filter((despesa) => !ids.has(despesa.id))];
            renderizarMinhas();
        });
    });

    document.getElementById('my-expenses').addEventListener('click', async (evento) => {
        const despesa = despesaDoClique(evento, minhas);
        if (!despesa) return;
        if (evento.target.closest('[data-edit]')) abrirFormulario(despesa);

        const excluir = evento.target.closest('[data-delete]');
        if (excluir && await confirmar({
            titulo: 'Excluir esta despesa?', texto: 'Ela e as fotos serão apagadas.', botao: 'Excluir', perigo: true,
        })) {
            executar(excluir, async () => {
                await requisitar(urlCom(URLS.expenseUrl, despesa.id), 'DELETE');
                minhas = minhas.filter((outra) => outra.id !== despesa.id);
                renderizarMinhas();
                mostrarSucesso('Despesa excluída.');
            });
        }
    });

    // A lista se atualiza sozinha quando o aprovador decide, gastando o mínimo: a
    // tela só pergunta se há despesa esperando outra pessoa (aprovação ou
    // pagamento), uma vez por minuto, nunca com a aba em segundo plano, e
    // pergunta só a versão; a lista nova vem apenas quando algo mudou.
    const INTERVALO_DE_ATUALIZACAO = 60000;
    const ESPERANDO_OUTRA_PESSOA = [ENVIADA, APROVADA];
    let minhaVersao = URLS.myVersion;

    const atualizarMinhas = async () => {
        // Enquanto o funcionário mexe numa despesa, ou faz o guia com a de exemplo, a lista fica como está
        if (document.hidden || !editor.hidden || emGuia) return;
        if (!minhas.some((despesa) => ESPERANDO_OUTRA_PESSOA.includes(despesa.status))) return;
        let dados;
        try {
            dados = await requisitar(`${URLS.myUrl}?version=${encodeURIComponent(minhaVersao)}`);
        } catch (erro) {
            // Sem rede agora: a próxima volta tenta de novo, sem alarmar ninguém
            return;
        }
        if (!dados.changed || !editor.hidden) return;
        minhaVersao = dados.version;
        // As encerradas mais antigas que ele já tinha carregado continuam na lista
        const novas = new Set(dados.expenses.map((despesa) => despesa.id));
        const antigas = minhas.filter((despesa) => ENCERRADAS_MINHAS.includes(despesa.status) && !novas.has(despesa.id));
        minhas = [...dados.expenses, ...antigas];
        contagensMinhas = dados.counts;
        renderizarMinhas();
    };

    // O guia de como usar: abre sozinho na primeira visita e, a qualquer hora, pelo botão de ajuda.
    // A pessoa faz o lançamento de teste ela mesma, do envio à exclusão.
    const CARTAO_DO_EXEMPLO = `#my-expenses .expense-card[data-expense-id="${ID_DO_EXEMPLO}"]`;
    const exemplo = () => minhas.find((despesa) => despesa.id === ID_DO_EXEMPLO);

    const PASSOS_DO_GUIA = [
        { titulo: 'Bem-vindo às Despesas', texto: 'Vamos fazer um lançamento de teste. Nada é enviado de verdade.' },
        {
            alvo: '#new-expense', titulo: 'Nova despesa', texto: 'Toque em Nova despesa.',
            espera: () => !editor.hidden,
        },
        {
            alvo: '.photo-actions', titulo: 'Foto da nota',
            texto: 'Toque em Tirar foto para fotografar a nota inteira, ou em Galeria para escolher uma foto.',
            espera: () => fotosEscolhidas.length > 0,
        },
        {
            alvo: '#read-photos', titulo: 'Continuar', texto: 'Toque em Continuar. O sistema lê a nota.',
            espera: () => !formulario.hidden,
        },
        {
            alvo: '#expense-form .expense-header', titulo: 'Dados da nota',
            texto: 'O sistema preencheu os dados da nota. Confira o estabelecimento, o CNPJ e a data.',
            area: '#expense-form .expense-header',
        },
        {
            alvo: '#expense-items', titulo: 'Itens da nota',
            texto: 'Confira os itens, as quantidades e os valores. Se algo estiver errado, toque no campo e corrija.',
            area: '#expense-items, [data-add-item="expense-items"]',
        },
        {
            alvo: '#expense-form [type="submit"]', titulo: 'Enviar', texto: 'Com tudo certo, toque em Enviar.',
            espera: () => exemplo()?.status === ENVIADA,
        },
        {
            alvo: '#my-filters', titulo: 'Situação da despesa',
            texto: 'A despesa está em Enviadas, esperando a aprovação. Aqui você acompanha cada uma: '
                + 'aprovada, reembolsada ou rejeitada. Se o aprovador pedir correção, ela aparece em Correções Necessárias.',
        },
        {
            alvo: `${CARTAO_DO_EXEMPLO} .expense-summary`, titulo: 'Abrir a despesa',
            texto: 'Toque na despesa para ver os itens e as fotos.',
            espera: () => abertas.has(ID_DO_EXEMPLO),
        },
        {
            alvo: `${CARTAO_DO_EXEMPLO} [data-delete]`, titulo: 'Excluir',
            texto: 'Enquanto a despesa não for aprovada nem rejeitada, você pode excluí-la. Toque em Excluir e confirme.',
            espera: () => !exemplo(),
        },
        { alvo: '#help-tour', titulo: 'Pronto!', texto: 'Para ver este guia de novo, toque neste botão.' },
    ];

    const abrirGuia = () => {
        // As despesas reais saem da tela durante o guia e voltam no fim, como estavam
        const real = { minhas, contagens: contagensMinhas, filtro: filtroMinhas };
        emGuia = true;
        minhas = [];
        contagensMinhas = {};
        filtroMinhas = null;
        mostrarSucesso('');
        renderizarMinhas();
        iniciarTour(PASSOS_DO_GUIA, {
            aoTerminar: () => {
                emGuia = false;
                abertas.delete(ID_DO_EXEMPLO);
                fotosEscolhidas = [];
                ({ minhas, contagens: contagensMinhas, filtro: filtroMinhas } = real);
                mostrarSucesso('');
                fecharEditor();
            },
        });
    };
    document.getElementById('help-tour').addEventListener('click', abrirGuia);

    setInterval(atualizarMinhas, INTERVALO_DE_ATUALIZACAO);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) atualizarMinhas();
    });

    renderizarMinhas();
    // Fica marcado como visto já ao abrir: fechar a página no meio não faz o guia voltar sempre.
    // Se a marcação falhar, o guia só abre de novo na próxima visita: não vale um erro na tela.
    if (URLS.showGuide) {
        abrirGuia();
        requisitar(URLS.guideUrl, 'POST').catch(() => {});
    }
}


// Aprovações

// Os avisos que só quem aprova ou paga recebe. Na despesa do próprio usuário
// o servidor não os manda, e as listas ficam vazias.
function htmlAvisoDeCentro(despesa) {
    // Só na despesa de outra pessoa ainda em andamento: na encerrada não há o que preencher
    if (despesa.is_own || despesa.cost_center || ![ENVIADA, CORRECAO].includes(despesa.status)) return '';
    return `
        <div class="notice"><i class="fas fa-building" aria-hidden="true"></i>
            <span>O cadastro de ${escaparHtml(despesa.user)} não tem centro de custo. Escolha um para aprovar.</span>
        </div>`;
}

// Os motivos de conferência só servem enquanto a despesa espera a aprovação
function htmlAvisos(despesa) {
    const motivos = despesa.status === ENVIADA ? despesa.verification_reasons || [] : [];
    const verificacao = motivos.length ? `
        <div class="notice"><i class="fas fa-magnifying-glass" aria-hidden="true"></i>
            <span><strong>Alertas:</strong>
                <ul class="reasons">${motivos.map((motivo) => `<li>${escaparHtml(motivo)}</li>`).join('')}</ul>
            </span>
        </div>` : '';
    return verificacao;
}

function htmlMarcasDeAviso(despesa) {
    return (!despesa.is_own && !despesa.cost_center && despesa.status === ENVIADA ? '<span class="badge requested">Sem centro de custo</span>' : '')
        + (despesa.status === ENVIADA && despesa.verification_reasons?.length ? '<span class="badge requested">Com alerta</span>' : '');
}

function htmlLeitura(leitura) {
    if (!leitura) return '<p class="muted">A leitura automática falhou: tudo nesta despesa foi digitado pelo funcionário.</p>';
    return `
        <p class="muted">
            ${escaparHtml(leitura.merchant || 'Estabelecimento não lido')} · CNPJ ${escaparHtml(leitura.cnpj || 'não lido')}
            · ${leitura.date ? dataBr(leitura.date) : 'data não lida'}
            · Total lido: <strong>${leitura.total === null ? 'não lido' : moeda(leitura.total)}</strong>
        </p>
        <ul class="item-list">${leitura.items.map((item) => `
            <li>
                <span>${escaparHtml(item.description || '(sem descrição)')}</span>
                <span>${moeda(item.amount)}</span>
                <small>Qtd. ${escaparHtml(String(Number(item.quantity)).replace('.', ','))} ${item.legible ? '' : '<span class="badge low">Ilegível</span>'}</small>
            </li>`).join('')}</ul>`;
}

if (permissoes.approve || permissoes.reimburse) {
    // As pendentes vêm todas na página e são filtradas aqui. As encerradas
    // crescem sem parar: o servidor filtra e devolve uma página por vez.
    let fila = lerJson('review-expenses-data');
    let encerradas = { lista: [], total: 0, temMais: false };
    let filtro = permissoes.approve ? ENVIADA : APROVADA;
    let emAnalise = null;
    const ENCERRADAS = 'X';
    const PENDENTES = [ENVIADA, APROVADA, CORRECAO];

    const FILTROS = {
        E: (despesa) => despesa.status === ENVIADA,
        A: (despesa) => despesa.status === APROVADA,
        C: (despesa) => despesa.status === CORRECAO,
    };

    // A busca ignora acento e maiúscula: "joao" acha "João"
    const semAcento = (texto) => texto.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();
    const campoBusca = document.getElementById('review-search');
    const campoCentro = document.getElementById('review-cost-center-filter');
    const campoConferencia = document.getElementById('review-needs-check');
    const SEM_CENTRO = campoCentro.querySelector('option:last-child').value;

    const passaNaBusca = (despesa) => {
        const termos = semAcento(campoBusca.value).split(/\s+/).filter(Boolean);
        const texto = semAcento(`${despesa.user || ''} ${despesa.user_search || ''}`);
        const centro = campoCentro.value;
        return termos.every((termo) => texto.includes(termo))
            && (!centro || (centro === SEM_CENTRO ? !despesa.cost_center : String(despesa.cost_center?.id) === centro))
            && (!campoConferencia.checked || Boolean(despesa.verification_reasons?.length));
    };

    const paraAnalisar = (despesa) => despesa.status === ENVIADA && permissoes.approve && !despesa.is_own;

    const htmlAcoes = (despesa) => {
        if (despesa.status === ENVIADA && permissoes.approve) {
            return '<p class="muted">Você não pode aprovar a própria despesa.</p>';
        }
        if (despesa.status === APROVADA && permissoes.reimburse) {
            return '<div class="editor-actions"><button type="button" class="button primary" data-reimburse>Marcar como reembolsada</button></div>';
        }
        return '';
    };

    const renderizarFila = () => {
        const buscadas = fila.filter(passaNaBusca);
        document.querySelectorAll('#review-filters .filter').forEach((botao) => {
            const ativo = botao.dataset.filter === filtro;
            botao.classList.toggle('active', ativo);
            botao.setAttribute('aria-pressed', String(ativo));
            botao.querySelector('.count').textContent = botao.dataset.filter === ENCERRADAS
                ? encerradas.total : buscadas.filter(FILTROS[botao.dataset.filter]).length;
        });
        const visiveis = filtro === ENCERRADAS ? encerradas.lista : buscadas.filter(FILTROS[filtro]);
        document.getElementById('review-more').hidden = filtro !== ENCERRADAS || !encerradas.temMais;
        document.getElementById('review-expenses').innerHTML = visiveis.map((despesa) => htmlCartao(despesa, {
            titulo: despesa.user,
            // Só em Encerradas o status varia dentro da lista
            meta: (filtro === ENCERRADAS ? htmlStatus(despesa) : '')
                + `<span>${escaparHtml(despesa.merchant || 'Estabelecimento não informado')}</span>`
                + htmlDataDaNota(despesa) + htmlMarcasDeAviso(despesa),
            topo: htmlAvisoDeCentro(despesa) + htmlAvisos(despesa),
            corpo: htmlAcoes(despesa),
            gerencia: true,
            direto: paraAnalisar(despesa),
        })).join('');
        document.getElementById('review-empty').hidden = visiveis.length > 0;
    };

    // Só a resposta da última busca vale: a digitação dispara várias
    let ultimaBusca = 0;
    const carregarEncerradas = async (mais = false) => {
        const busca = ++ultimaBusca;
        const parametros = new URLSearchParams({
            q: campoBusca.value.trim(),
            cost_center: campoCentro.value,
            needs_check: campoConferencia.checked ? '1' : '',
            offset: mais ? encerradas.lista.length : 0,
        });
        try {
            const dados = await requisitar(`${URLS.closedUrl}?${parametros}`);
            if (busca !== ultimaBusca) return;
            encerradas = {
                lista: mais ? [...encerradas.lista, ...dados.expenses] : dados.expenses,
                total: dados.count,
                temMais: dados.has_more,
            };
            renderizarFila();
        } catch (erro) {
            mostrarErro(erro.message, erro.aviso);
        }
    };

    let esperaDaBusca = null;
    const filtrar = () => {
        renderizarFila();
        clearTimeout(esperaDaBusca);
        esperaDaBusca = setTimeout(() => carregarEncerradas(), 300);
    };

    const guardarNaFila = (despesa) => {
        // A que foi encerrada sai das pendentes e passa a vir da busca
        if (PENDENTES.includes(despesa.status)) {
            fila = fila.map((outra) => (outra.id === despesa.id ? despesa : outra));
        } else {
            fila = fila.filter((outra) => outra.id !== despesa.id);
            carregarEncerradas();
        }
        // A despesa do próprio usuário também está na outra aba
        if (despesa.is_own && permissoes.submit) {
            minhas = minhas.map((outra) => (outra.id === despesa.id ? despesa : outra));
            renderizarMinhas();
        }
    };

    const mostrarAnalise = (aberta) => {
        document.getElementById('review-list').hidden = aberta;
        document.getElementById('review-panel').hidden = !aberta;
    };

    const fecharAnalise = () => {
        emAnalise = null;
        mostrarAnalise(false);
        renderizarFila();
    };

    const NOTAS = {
        reject: { pergunta: 'Por que a despesa foi rejeitada?', confirmar: 'Rejeitar a despesa' },
        correction: { pergunta: 'O que o funcionário precisa corrigir?', confirmar: 'Pedir a correção' },
    };
    // A ação que espera a observação, ou null enquanto os três botões estão à mostra
    let acaoComNota = null;

    const pedirNota = (acao) => {
        acaoComNota = acao;
        document.getElementById('review-decision').hidden = acao !== null;
        document.getElementById('review-note-step').hidden = acao === null;
        if (!acao) return;
        document.getElementById('review-note-label').textContent = NOTAS[acao].pergunta;
        const confirmar = document.getElementById('review-note-confirm');
        confirmar.textContent = NOTAS[acao].confirmar;
        confirmar.classList.toggle('danger', acao === 'reject');
        confirmar.classList.toggle('primary', acao !== 'reject');
        document.getElementById('review-note').focus();
    };

    const abrirAnalise = (despesa) => {
        emAnalise = despesa;
        const formularioDeAnalise = document.getElementById('review-form');
        formularioDeAnalise.reset();
        pedirNota(null);
        document.getElementById('review-title').textContent = despesa.user;
        document.getElementById('review-summary').textContent = [
            despesa.merchant || 'Estabelecimento não informado',
            `CNPJ ${despesa.cnpj || 'não informado'}`,
            despesa.issue_date ? `Nota de ${dataBr(despesa.issue_date)}` : 'Data da nota não informada',
        ].join(' · ');
        document.getElementById('review-alerts').innerHTML = htmlAvisos(despesa);
        document.getElementById('review-cost-center-alert').innerHTML = htmlAvisoDeCentro(despesa);
        // As fotos ficam ao lado dos itens, grandes: é nelas que o aprovador confere cada valor
        document.getElementById('review-photos').innerHTML = despesa.photos.map((foto, indice) => `
            <a href="${foto.url}" target="_blank" rel="noopener" title="Abrir a foto ${indice + 1} em tamanho real">
                <img src="${foto.url}" alt="Foto ${indice + 1} do recibo">
            </a>`).join('');
        preencherItens(document.getElementById('review-items'), despesa.items, true);
        document.getElementById('review-reading').open = false;
        document.getElementById('review-reading-content').innerHTML = htmlLeitura(despesa.reading);

        // O centro de custo inativo que já era da despesa continua escolhido
        const centros = document.getElementById('review-cost-center');
        centros.querySelector('[data-inactive]')?.remove();
        const centro = despesa.cost_center;
        if (centro && !centros.querySelector(`option[value="${centro.id}"]`)) {
            centros.insertAdjacentHTML('beforeend', `<option value="${centro.id}" data-inactive>${escaparHtml(centro.label)} (inativo)</option>`);
        }
        centros.value = centro ? centro.id : '';

        document.getElementById('review-check').hidden = !despesa.verification_reasons.length;
        document.getElementById('review-history').innerHTML = htmlHistorico(despesa);
        mostrarAnalise(true);
        document.getElementById('review-panel').scrollIntoView({ block: 'start' });
    };

    campoBusca.addEventListener('input', filtrar);
    campoCentro.addEventListener('change', filtrar);
    campoConferencia.addEventListener('change', filtrar);
    document.getElementById('review-more').addEventListener('click', (evento) => {
        executar(evento.currentTarget, () => carregarEncerradas(true));
    });

    document.getElementById('review-filters').addEventListener('click', (evento) => {
        const botao = evento.target.closest('.filter');
        if (!botao) return;
        filtro = botao.dataset.filter;
        renderizarFila();
    });

    document.getElementById('review-expenses').addEventListener('click', async (evento) => {
        const despesa = despesaDoClique(evento, [...fila, ...encerradas.lista]);
        if (!despesa) return;
        if (evento.target.closest('[data-open-review]')) abrirAnalise(despesa);

        const pagar = evento.target.closest('[data-reimburse]');
        if (pagar && await confirmar({
            titulo: 'Marcar como reembolsada?',
            texto: `Despesa de ${despesa.user}, no valor de ${moeda(despesa.reimbursable_total)}.`,
            botao: 'Marcar como reembolsada',
        })) {
            executar(pagar, async () => {
                const dados = await requisitar(urlCom(URLS.reimburseUrl, despesa.id), 'POST');
                guardarNaFila(dados.expense);
                renderizarFila();
                mostrarSucesso('Despesa marcada como reembolsada.');
            });
        }
    });

    if (permissoes.approve) {
        const MENSAGENS = {
            approve: 'Despesa aprovada.',
            reject: 'Despesa rejeitada.',
            correction: 'Correção solicitada ao funcionário.',
        };

        document.getElementById('close-review').addEventListener('click', fecharAnalise);

        const decidir = (botao, acao) => {
            const formularioDeAnalise = document.getElementById('review-form');
            executar(botao, async () => {
                const dados = await requisitar(urlCom(URLS.reviewUrl, emAnalise.id), 'POST', {
                    action: acao,
                    note: acao === 'approve' ? '' : formularioDeAnalise.note.value,
                    photo_checked: formularioDeAnalise.photo_checked.checked,
                    cost_center: formularioDeAnalise.cost_center.value || null,
                    items: lerItens(document.getElementById('review-items')),
                });
                guardarNaFila(dados.expense);
                fecharAnalise();
                mostrarSucesso(MENSAGENS[acao]);
            });
        };

        document.getElementById('review-form').addEventListener('click', (evento) => {
            const comNota = evento.target.closest('[data-ask-note]');
            if (comNota) pedirNota(comNota.dataset.askNote);

            const aprovar = evento.target.closest('[data-review]');
            if (aprovar) decidir(aprovar, aprovar.dataset.review);
        });
        document.getElementById('review-note-cancel').addEventListener('click', () => pedirNota(null));
        document.getElementById('review-note-confirm').addEventListener('click', (evento) => decidir(evento.currentTarget, acaoComNota));
    }

    renderizarFila();
    carregarEncerradas();
}


// Configurações

function renderizarConfiguracoes(dados) {
    document.getElementById('words').innerHTML = dados.words.map((palavra) => `
        <li class="chip">
            ${escaparHtml(palavra.word)}
            <button type="button" data-remove-word="${palavra.id}" title="Remover ${escaparHtml(palavra.word)}" aria-label="Remover ${escaparHtml(palavra.word)}">
                <i class="fas fa-xmark" aria-hidden="true"></i>
            </button>
        </li>`).join('');
    document.getElementById('words-empty').hidden = dados.words.length > 0;
}

if (permissoes.settings) {
    renderizarConfiguracoes(lerJson('settings-data'));

    document.getElementById('word-form').addEventListener('submit', (evento) => {
        evento.preventDefault();
        const formulario = evento.target;
        executar(formulario.querySelector('[type="submit"]'), async () => {
            renderizarConfiguracoes(await requisitar(URLS.wordsUrl, 'POST', { word: formulario.word.value }));
            formulario.reset();
        });
    });

    document.getElementById('words').addEventListener('click', (evento) => {
        const botao = evento.target.closest('[data-remove-word]');
        if (!botao) return;
        executar(botao, async () => {
            renderizarConfiguracoes(await requisitar(urlCom(URLS.wordUrl, botao.dataset.removeWord), 'DELETE'));
        });
    });
}
