// A configuração da tela vem em data-attributes: com o CSP ligado, o navegador
// recusa <script> inline, que é onde essas constantes moravam.
const {
    csrfToken: CSRF_TOKEN,
    apiUrl: TONERS_API_URL,
} = document.getElementById('content').dataset;

const INTERVALO_ATUALIZACAO = 15000;
const TONERS_POR_PAGINA = 7;

let listaToners = [];
let paginaAtual = 1;
let permissoes = {};
let locais = [];
let editandoId = null;
let movimentandoId = null;
let historicoId = null;
let historico = null;
let enviando = false;

function escaparHtml(texto) {
    return String(texto ?? '').replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

// Remove acentos para tornar a pesquisa mais tolerante
function removerAcentos(texto) {
    return texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

function urlToner(id) {
    return `${TONERS_API_URL}${id}/`;
}

async function requisitar(url, metodo = 'GET', corpo = null) {
    const opcoes = {
        method: metodo,
        headers: { 'X-CSRFToken': CSRF_TOKEN, 'Accept': 'application/json' },
    };
    if (corpo !== null) {
        opcoes.headers['Content-Type'] = 'application/json';
        opcoes.body = JSON.stringify(corpo);
    }

    let resposta;
    try {
        resposta = await fetch(url, opcoes);
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

function substituirToner(toner) {
    const indice = listaToners.findIndex((t) => t.id === toner.id);
    if (indice === -1) {
        listaToners.push(toner);
    } else {
        listaToners[indice] = toner;
    }
}

function ordenarToners(toners) {
    return [...toners].sort((a, b) => {
        const porLocal = a.location.localeCompare(b.location, 'pt-BR', { sensitivity: 'base' });
        return porLocal || a.name.localeCompare(b.name, 'pt-BR', { sensitivity: 'base' });
    });
}

// Prefixar a busca com "-" inverte o filtro, igual à lista de contatos
function tonersFiltrados() {
    const entrada = document.getElementById('search-input').value.toLowerCase().trim();
    const somenteBaixos = document.getElementById('only-low').checked;
    const buscaInversa = entrada.startsWith('-');
    const termo = removerAcentos(buscaInversa ? entrada.slice(1).trim() : entrada);

    return ordenarToners(listaToners).filter((toner) => {
        if (somenteBaixos && !toner.is_low) return false;
        if (!termo) return true;

        const contemTermo = [toner.name, toner.location, toner.observations]
            .some((campo) => removerAcentos(campo.toLowerCase()).includes(termo));
        return buscaInversa ? !contemTermo : contemTermo;
    });
}

function renderizarAlerta() {
    const baixos = ordenarToners(listaToners.filter((toner) => toner.is_low));
    document.getElementById('alert-low').hidden = baixos.length === 0;
    document.getElementById('alert-low-list').innerHTML = baixos.map((toner) =>
        `<li>${escaparHtml(toner.name)}${toner.location ? ' - ' + escaparHtml(toner.location) : ''}</li>`
    ).join('');
}

// Os locais são cadastrados apenas pelo portal de administração
function opcoesDeLocal(idSelecionado) {
    return [
        `<option value=""${idSelecionado ? '' : ' selected'}>Sem local</option>`,
        ...locais.map((local) => `
            <option value="${local.id}"${local.id === idSelecionado ? ' selected' : ''}>${escaparHtml(local.name)}</option>`),
    ].join('');
}

function badgeStatus(toner) {
    return toner.is_low
        ? '<span class="badge low">Comprar</span>'
        : '<span class="badge ok">OK</span>';
}

function linhaVisualizacao(toner) {
    const acoes = [
        permissoes.move && `<button class="button" data-action="movimentar" data-id="${toner.id}" title="Registrar entrada ou saída"><i class="fas fa-right-left"></i></button>`,
        `<button class="button" data-action="historico" data-id="${toner.id}" title="Ver histórico"><i class="fas fa-clock-rotate-left"></i></button>`,
        permissoes.change && `<button class="button" data-action="editar" data-id="${toner.id}" title="Editar"><i class="fas fa-pen"></i></button>`,
        permissoes.delete && `<button class="button danger" data-action="excluir" data-id="${toner.id}" title="Excluir"><i class="fas fa-trash"></i></button>`,
    ].filter(Boolean).join('');

    return `
        <tr class="${toner.is_low ? 'low' : ''}">
            <td>${escaparHtml(toner.name)}</td>
            <td>${escaparHtml(toner.location || '-')}</td>
            <td class="muted">${escaparHtml(toner.observations || '-')}</td>
            <td><span class="quantity-value">${toner.quantity}</span></td>
            <td>${toner.minimum_quantity}</td>
            <td>${badgeStatus(toner)}</td>
            <td><div class="row-actions">${acoes}</div></td>
        </tr>`;
}

function linhaEdicao(toner) {
    return `
        <tr class="${toner.is_low ? 'low' : ''}">
            <td>${toner.can_rename
                ? `<input class="edit-input" id="edit-name" type="text" maxlength="100" value="${escaparHtml(toner.name)}">`
                : `<span title="O nome não muda mais porque o toner já tem movimentação">${escaparHtml(toner.name)}</span>`}</td>
            <td><select class="edit-input" id="edit-location">${opcoesDeLocal(toner.location_id)}</select></td>
            <td><input class="edit-input" id="edit-observations" type="text" maxlength="255" value="${escaparHtml(toner.observations)}"></td>
            <td><span class="quantity-value" title="A quantidade muda apenas por entradas e saídas">${toner.quantity}</span></td>
            <td><input class="edit-input small" id="edit-minimum" type="number" min="0" value="${toner.minimum_quantity}"></td>
            <td>${badgeStatus(toner)}</td>
            <td>
                <div class="row-actions">
                    <button class="button" data-action="salvar" data-id="${toner.id}" title="Salvar"><i class="fas fa-check"></i></button>
                    <button class="button" data-action="cancelar" data-id="${toner.id}" title="Cancelar"><i class="fas fa-xmark"></i></button>
                </div>
            </td>
        </tr>`;
}

function linhaMovimentacao(toner) {
    return `
        <tr class="detail-row">
            <td colspan="7">
                <div class="inline-form">
                    <div class="field">
                        <label for="move-type">Tipo</label>
                        <select id="move-type">
                            <option value="S">Saída (retirar)</option>
                            <option value="E">Entrada (repor)</option>
                        </select>
                    </div>
                    <div class="field">
                        <label for="move-quantity">Quantidade</label>
                        <input id="move-quantity" type="number" min="1" value="1" style="width: 90px;">
                    </div>
                    <div class="field grow">
                        <label for="move-reason">Motivo (opcional)</label>
                        <input id="move-reason" type="text" maxlength="255" placeholder="Ex: troca na recepção, retirado por João">
                    </div>
                    <button class="button primary" data-action="confirmar-movimentacao" data-id="${toner.id}">Confirmar</button>
                    <button class="button" data-action="cancelar" data-id="${toner.id}">Cancelar</button>
                </div>
                <div class="error-text" id="move-error" hidden></div>
            </td>
        </tr>`;
}

function linhaHistorico(toner) {
    let conteudo;
    if (historico === null) {
        conteudo = '<div class="muted">Carregando...</div>';
    } else if (historico.length === 0) {
        conteudo = '<div class="muted">Nenhuma movimentação registrada ainda.</div>';
    } else {
        conteudo = `
            <table>
                <thead>
                    <tr><th>Data</th><th>Tipo</th><th>Qtd</th><th>Motivo</th><th>Usuário</th></tr>
                </thead>
                <tbody>
                    ${historico.map((mov) => `
                        <tr>
                            <td>${new Date(mov.created_at).toLocaleString('pt-BR')}</td>
                            <td><span class="movement-tag ${mov.type}">${escaparHtml(mov.type_display)}</span></td>
                            <td>${mov.quantity}</td>
                            <td>${escaparHtml(mov.reason || '-')}</td>
                            <td>${escaparHtml(mov.user || '-')}</td>
                        </tr>`).join('')}
                </tbody>
            </table>`;
    }

    return `
        <tr class="detail-row">
            <td colspan="7">
                <div class="history">
                    ${conteudo}
                    <button class="button small" data-action="fechar-historico" data-id="${toner.id}">Fechar histórico</button>
                </div>
            </td>
        </tr>`;
}

function renderizar() {
    renderizarAlerta();

    const toners = tonersFiltrados();
    const totalPaginas = Math.ceil(toners.length / TONERS_POR_PAGINA);
    paginaAtual = Math.min(paginaAtual, Math.max(1, totalPaginas));
    const inicio = (paginaAtual - 1) * TONERS_POR_PAGINA;
    const tonersPagina = toners.slice(inicio, inicio + TONERS_POR_PAGINA);
    const corpoTabela = document.querySelector('#toners-table tbody');
    const vazio = document.getElementById('empty-message');

    corpoTabela.innerHTML = tonersPagina.map((toner) => {
        let linhas = toner.id === editandoId ? linhaEdicao(toner) : linhaVisualizacao(toner);
        if (toner.id === movimentandoId) linhas += linhaMovimentacao(toner);
        if (toner.id === historicoId) linhas += linhaHistorico(toner);
        return linhas;
    }).join('');

    vazio.hidden = toners.length > 0;
    vazio.textContent = listaToners.length === 0
        ? 'Nenhum toner cadastrado ainda.'
        : 'Nenhum toner encontrado com os filtros atuais.';
    renderizarPaginacao(totalPaginas);
}

function criarBotaoPagina(rotulo, pagina, ativo = false) {
    const botao = document.createElement('button');
    botao.type = 'button';
    botao.textContent = rotulo;
    botao.classList.add('pagination-button');
    if (ativo) {
        botao.classList.add('active');
        botao.setAttribute('aria-current', 'page');
    }
    botao.addEventListener('click', () => {
        paginaAtual = pagina;
        editandoId = null;
        movimentandoId = null;
        historicoId = null;
        renderizar();
    });
    return botao;
}

function criarReticencias() {
    const reticencias = document.createElement('span');
    reticencias.textContent = '...';
    reticencias.classList.add('pagination-ellipsis');
    return reticencias;
}

function renderizarPaginacao(totalPaginas) {
    const container = document.getElementById('pagination');
    container.innerHTML = '';
    if (totalPaginas <= 1) return;

    const isMobile = window.innerWidth <= 480;
    const maxVisiveis = isMobile ? 3 : 7;
    let inicio = Math.max(1, paginaAtual - Math.floor(maxVisiveis / 2));
    const fim = Math.min(totalPaginas, inicio + maxVisiveis - 1);
    inicio = Math.max(1, fim - maxVisiveis + 1);

    if (paginaAtual > 1) {
        container.appendChild(criarBotaoPagina(isMobile ? '‹' : '‹ Anterior', paginaAtual - 1));
    }
    if (inicio > 1) {
        container.appendChild(criarBotaoPagina('1', 1));
        if (inicio > 2) container.appendChild(criarReticencias());
    }
    for (let pagina = inicio; pagina <= fim; pagina++) {
        container.appendChild(criarBotaoPagina(pagina, pagina, pagina === paginaAtual));
    }
    if (fim < totalPaginas) {
        if (fim < totalPaginas - 1) container.appendChild(criarReticencias());
        container.appendChild(criarBotaoPagina(totalPaginas, totalPaginas));
    }
    if (paginaAtual < totalPaginas) {
        container.appendChild(criarBotaoPagina(isMobile ? '›' : 'Próximo ›', paginaAtual + 1));
    }
}

async function carregarHistorico(id) {
    historico = null;
    renderizar();
    try {
        const dados = await requisitar(`${urlToner(id)}movements/`);
        if (historicoId === id) historico = dados.movements;
    } catch (erro) {
        historicoId = null;
        mostrarErro(erro.message);
    }
    renderizar();
}

async function movimentar(id, tipo, quantidade, motivo = '') {
    const dados = await requisitar(`${urlToner(id)}movements/`, 'POST', {
        type: tipo, quantity: quantidade, reason: motivo,
    });
    substituirToner(dados.toner);
    if (historicoId === id && historico) historico.unshift(dados.movement);
}

async function executarAcao(acao, id) {
    const toner = listaToners.find((t) => t.id === id);
    if (!toner) return;

    switch (acao) {
        case 'movimentar':
            movimentandoId = id;
            editandoId = null;
            historicoId = null;
            renderizar();
            document.getElementById('move-quantity').focus();
            return;
        case 'confirmar-movimentacao': {
            const campoQuantidade = document.getElementById('move-quantity');
            const quantidade = parseInt(campoQuantidade.value, 10);
            const erroMovimentacao = document.getElementById('move-error');
            if (isNaN(quantidade) || quantidade <= 0) {
                erroMovimentacao.textContent = 'Informe uma quantidade válida.';
                erroMovimentacao.hidden = false;
                return;
            }
            try {
                await movimentar(
                    id,
                    document.getElementById('move-type').value,
                    quantidade,
                    document.getElementById('move-reason').value.trim(),
                );
            } catch (erro) {
                // O erro fica junto ao formulário para o usuário corrigir sem perder o que digitou
                erroMovimentacao.textContent = erro.message;
                erroMovimentacao.hidden = false;
                return;
            }
            movimentandoId = null;
            break;
        }
        case 'historico':
            historicoId = id;
            movimentandoId = null;
            editandoId = null;
            await carregarHistorico(id);
            return;
        case 'fechar-historico':
            historicoId = null;
            break;
        case 'editar':
            editandoId = id;
            movimentandoId = null;
            historicoId = null;
            renderizar();
            document.getElementById(toner.can_rename ? 'edit-name' : 'edit-location').focus();
            return;
        case 'cancelar':
            editandoId = null;
            movimentandoId = null;
            break;
        case 'salvar': {
            const campoNome = document.getElementById('edit-name');
            if (campoNome && !campoNome.value.trim()) {
                campoNome.classList.add('invalid');
                campoNome.focus();
                return;
            }
            const dados = await requisitar(urlToner(id), 'POST', {
                ...(campoNome ? { name: campoNome.value.trim() } : {}),
                location: document.getElementById('edit-location').value,
                observations: document.getElementById('edit-observations').value.trim(),
                minimum_quantity: document.getElementById('edit-minimum').value,
            });
            substituirToner(dados.toner);
            editandoId = null;
            break;
        }
        case 'excluir':
            if (!confirm(`Excluir o toner "${toner.name}" e todo o seu histórico?`)) return;
            await requisitar(urlToner(id), 'DELETE');
            listaToners = listaToners.filter((t) => t.id !== id);
            if (historicoId === id) historicoId = null;
            break;
    }

    renderizar();
}

async function aoClicarNaTabela(evento) {
    const botao = evento.target.closest('button[data-action]');
    if (!botao || enviando) return;

    enviando = true;
    botao.disabled = true;
    try {
        mostrarErro('');
        await executarAcao(botao.dataset.action, Number(botao.dataset.id));
    } catch (erro) {
        mostrarErro(erro.message);
        renderizar();
    } finally {
        enviando = false;
        botao.disabled = false;
    }
}

async function aoAdicionar(evento) {
    evento.preventDefault();
    const formulario = evento.currentTarget;
    const botao = formulario.querySelector('button[type="submit"]');
    const dadosFormulario = Object.fromEntries(new FormData(formulario));
    Object.keys(dadosFormulario).forEach((campo) => {
        dadosFormulario[campo] = dadosFormulario[campo].trim();
    });

    botao.disabled = true;
    try {
        mostrarErro('');
        const dados = await requisitar(TONERS_API_URL, 'POST', dadosFormulario);
        substituirToner(dados.toner);
        formulario.reset();
        const indice = tonersFiltrados().findIndex((toner) => toner.id === dados.toner.id);
        if (indice >= 0) paginaAtual = Math.floor(indice / TONERS_POR_PAGINA) + 1;
        document.getElementById('add-name').focus();
        renderizar();
    } catch (erro) {
        mostrarErro(erro.message);
    } finally {
        botao.disabled = false;
    }
}

// Mantém a tela em dia com alterações feitas por outras pessoas
async function atualizarLista() {
    if (enviando || editandoId !== null || movimentandoId !== null || document.hidden) return;
    try {
        const dados = await requisitar(TONERS_API_URL);
        listaToners = dados.toners;
        renderizar();
    } catch (erro) {
        // Falhas pontuais são ignoradas; a próxima atualização tenta de novo
    }
}

function linhasExportacao() {
    return tonersFiltrados().map((toner) => [
        toner.name,
        toner.location || '-',
        toner.observations || '-',
        toner.quantity,
        toner.minimum_quantity,
        toner.is_low ? 'Comprar' : 'OK',
    ]);
}

const CABECALHO_EXPORTACAO = ['Toner', 'Local', 'Observação', 'Quantidade', 'Mínimo', 'Status'];

function dataArquivo() {
    return new Date().toISOString().slice(0, 10);
}

function exportarExcel() {
    const planilha = XLSX.utils.aoa_to_sheet([CABECALHO_EXPORTACAO, ...linhasExportacao()]);
    planilha['!cols'] = [{ wch: 18 }, { wch: 22 }, { wch: 28 }, { wch: 12 }, { wch: 10 }, { wch: 10 }];
    const pasta = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(pasta, planilha, 'Estoque de Toners');
    XLSX.writeFile(pasta, `estoque-toners-${dataArquivo()}.xlsx`);
}

function exportarPdf() {
    const { jsPDF } = window.jspdf;
    const documento = new jsPDF();

    documento.setFontSize(14);
    documento.text('Controle de Estoque de Toners', 14, 16);
    documento.setFontSize(9);
    documento.setTextColor(120);
    documento.text('Gerado em ' + new Date().toLocaleDateString('pt-BR'), 14, 22);

    documento.autoTable({
        startY: 28,
        head: [CABECALHO_EXPORTACAO],
        body: linhasExportacao().map((linha) => linha.map(String)),
        styles: { fontSize: 9 },
        headStyles: { fillColor: [51, 51, 51] },
        didParseCell(celula) {
            if (celula.section === 'body' && celula.row.raw[5] === 'Comprar') {
                celula.cell.styles.fillColor = [252, 235, 235];
                celula.cell.styles.textColor = [163, 45, 45];
            }
        },
    });

    documento.save(`estoque-toners-${dataArquivo()}.pdf`);
}

document.addEventListener('DOMContentLoaded', () => {
    listaToners = JSON.parse(document.getElementById('toners-data').textContent);
    permissoes = JSON.parse(document.getElementById('permissions-data').textContent);
    locais = JSON.parse(document.getElementById('locations-data').textContent);

    document.querySelector('#toners-table tbody').addEventListener('click', aoClicarNaTabela);
    const aoAlterarFiltro = () => {
        paginaAtual = 1;
        editandoId = null;
        movimentandoId = null;
        historicoId = null;
        renderizar();
    };
    document.getElementById('search-input').addEventListener('input', aoAlterarFiltro);
    document.getElementById('only-low').addEventListener('change', aoAlterarFiltro);
    document.getElementById('export-excel').addEventListener('click', exportarExcel);
    document.getElementById('export-pdf').addEventListener('click', exportarPdf);

    const formularioAdicionar = document.getElementById('add-form');
    if (formularioAdicionar) formularioAdicionar.addEventListener('submit', aoAdicionar);

    // Enter confirma a edição ou a movimentação aberta
    document.querySelector('#toners-table tbody').addEventListener('keydown', (evento) => {
        if (evento.key !== 'Enter' || evento.target.tagName !== 'INPUT') return;
        const acao = editandoId !== null ? 'salvar' : 'confirmar-movimentacao';
        const botao = document.querySelector(`button[data-action="${acao}"]`);
        if (botao) botao.click();
    });

    renderizar();
    setInterval(atualizarLista, INTERVALO_ATUALIZACAO);
});
