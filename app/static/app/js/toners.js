const INTERVALO_ATUALIZACAO = 15000;

let listaToners = [];
let permissoes = {};
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

function renderizarLocais() {
    const locais = [...new Set(listaToners.map((toner) => toner.location).filter(Boolean))]
        .sort((a, b) => a.localeCompare(b, 'pt-BR'));
    document.getElementById('locations').innerHTML = locais
        .map((local) => `<option value="${escaparHtml(local)}"></option>`).join('');
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
            <td><input class="edit-input" id="edit-name" type="text" maxlength="100" value="${escaparHtml(toner.name)}"></td>
            <td><input class="edit-input" id="edit-location" type="text" maxlength="100" list="locations" value="${escaparHtml(toner.location)}"></td>
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
    renderizarLocais();

    const toners = tonersFiltrados();
    const corpoTabela = document.querySelector('#toners-table tbody');
    const vazio = document.getElementById('empty-message');

    corpoTabela.innerHTML = toners.map((toner) => {
        let linhas = toner.id === editandoId ? linhaEdicao(toner) : linhaVisualizacao(toner);
        if (toner.id === movimentandoId) linhas += linhaMovimentacao(toner);
        if (toner.id === historicoId) linhas += linhaHistorico(toner);
        return linhas;
    }).join('');

    vazio.hidden = toners.length > 0;
    vazio.textContent = listaToners.length === 0
        ? 'Nenhum toner cadastrado ainda.'
        : 'Nenhum toner encontrado com os filtros atuais.';
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
            document.getElementById('edit-name').focus();
            return;
        case 'cancelar':
            editandoId = null;
            movimentandoId = null;
            break;
        case 'salvar': {
            const campoNome = document.getElementById('edit-name');
            if (!campoNome.value.trim()) {
                campoNome.classList.add('invalid');
                campoNome.focus();
                return;
            }
            const dados = await requisitar(urlToner(id), 'POST', {
                name: campoNome.value.trim(),
                location: document.getElementById('edit-location').value.trim(),
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
    XLSX.utils.book_append_sheet(pasta, planilha, 'Estoque de Toner');
    XLSX.writeFile(pasta, `estoque-toner-${dataArquivo()}.xlsx`);
}

function exportarPdf() {
    const { jsPDF } = window.jspdf;
    const documento = new jsPDF();

    documento.setFontSize(14);
    documento.text('Controle de Estoque de Toner', 14, 16);
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

    documento.save(`estoque-toner-${dataArquivo()}.pdf`);
}

document.addEventListener('DOMContentLoaded', () => {
    listaToners = JSON.parse(document.getElementById('toners-data').textContent);
    permissoes = JSON.parse(document.getElementById('permissions-data').textContent);

    document.querySelector('#toners-table tbody').addEventListener('click', aoClicarNaTabela);
    document.getElementById('search-input').addEventListener('input', renderizar);
    document.getElementById('only-low').addEventListener('change', renderizar);
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
