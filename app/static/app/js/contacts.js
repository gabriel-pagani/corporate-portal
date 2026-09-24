// A configuração da tela vem em data-attributes: com o CSP ligado, o navegador
// recusa <script> inline, que é onde essas constantes moravam.
const isStaff = document.getElementById('content').dataset.isStaff === '1';
const canEdit = document.getElementById('content').dataset.canEdit === '1';
const canDelete = document.getElementById('content').dataset.canDelete === '1';
const csrfToken = document.getElementById('content').dataset.csrfToken;
const updateUrlTemplate = document.getElementById('content').dataset.updateUrl;

const CONTATOS_POR_PAGINA = 6;

let listaContatos = [];
let contatosFiltrados = [];
let paginaAtual = 1;
let setores = [];
let usuarios = [];
let editandoId = null;
let salvando = false;

function mostrarErro(mensagem) {
    document.getElementById('alert-error-text').textContent = mensagem;
    document.getElementById('alert-error').hidden = !mensagem;
}

function mostrarSucesso(mensagem) {
    const aviso = document.getElementById('success-message');
    aviso.textContent = mensagem;
    aviso.hidden = !mensagem;
}

function campoEdicao(valor, campo) {
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'edit-input';
    input.dataset.field = campo;
    input.maxLength = 100;
    input.value = valor || '';
    input.setAttribute('aria-label', campo === 'number' ? 'Número' : campo === 'machine' ? 'Máquina' : 'Nome');
    return input;
}

function selecaoSetor(selecionado) {
    const select = document.createElement('select');
    select.className = 'edit-input';
    select.dataset.field = 'sector';
    select.setAttribute('aria-label', 'Setor');
    const vazio = new Option('Sem setor', '');
    select.add(vazio);
    setores.forEach((setor) => select.add(new Option(setor.name, String(setor.id))));
    select.value = selecionado == null ? '' : String(selecionado);
    return select;
}

function editorNome(contato) {
    const campos = document.createElement('div');
    campos.className = 'contact-name-edit';

    const usuario = document.createElement('select');
    usuario.className = 'edit-input';
    usuario.dataset.field = 'user';
    usuario.setAttribute('aria-label', 'Usuário vinculado');
    usuario.add(new Option('Sem usuário', ''));
    usuarios.forEach((item) => usuario.add(new Option(item.name, String(item.id))));
    usuario.value = contato.user_id == null ? '' : String(contato.user_id);

    const nome = campoEdicao(contato.custom_name, 'name');
    nome.placeholder = 'Nome sem vínculo';
    nome.title = 'Com usuário vinculado, o nome exibido vem do usuário.';
    campos.append(usuario, nome);
    return campos;
}

function celulaCom(conteudo) {
    const celula = document.createElement('td');
    if (typeof conteudo === 'string') celula.textContent = conteudo;
    else celula.appendChild(conteudo);
    return celula;
}

function botaoAcao(acao, id, icone, titulo, perigo = false) {
    const botao = document.createElement('button');
    botao.type = 'button';
    botao.className = perigo ? 'button small danger' : 'button small';
    botao.dataset.action = acao;
    botao.dataset.id = id;
    botao.title = titulo;
    botao.setAttribute('aria-label', titulo);
    botao.innerHTML = '<i class="fas ' + icone + '"></i>';
    return botao;
}

function linhaContato(contato) {
    const linha = document.createElement('tr');
    linha.dataset.contactId = contato.id;
    const emEdicao = editandoId === contato.id;

    linha.appendChild(celulaCom(emEdicao ? editorNome(contato) : contato.name));
    linha.appendChild(celulaCom(emEdicao
        ? campoEdicao(contato.number, 'number') : contato.number || '-'));
    linha.appendChild(celulaCom(emEdicao
        ? selecaoSetor(contato.sector_id) : contato.sector || '-'));

    if (isStaff) linha.appendChild(celulaCom(emEdicao
        ? campoEdicao(contato.machine, 'machine') : contato.machine || '-'));

    if (canEdit || canDelete || isStaff) {
        const acoes = document.createElement('div');
        acoes.className = 'row-actions';
        if (emEdicao) {
            acoes.append(
                botaoAcao('salvar', contato.id, 'fa-check', 'Salvar'),
                botaoAcao('cancelar', contato.id, 'fa-xmark', 'Cancelar'),
            );
        } else {
            if (isStaff && contato.machine) {
                acoes.appendChild(botaoAcao('copiar', contato.id, 'fa-copy', 'Copiar número da máquina'));
            }
            if (canEdit) acoes.appendChild(botaoAcao('editar', contato.id, 'fa-pen', 'Editar contato'));
            if (canDelete) acoes.appendChild(botaoAcao('excluir', contato.id, 'fa-trash', 'Excluir contato', true));
        }
        linha.appendChild(celulaCom(acoes));
    }
    return linha;
}

async function salvarContato(id) {
    if (salvando) return;
    const contato = listaContatos.find((item) => item.id === id);
    const linha = document.querySelector(`tr[data-contact-id="${id}"]`);
    if (!contato || !linha) return;

    const campo = (nome) => linha.querySelector(`[data-field="${nome}"]`);
    const dados = {
        user: campo('user').value,
        name: campo('name').value.trim(),
        number: campo('number').value.trim(),
        sector: campo('sector').value,
        machine: isStaff ? campo('machine').value.trim() : contato.machine,
    };
    salvando = true;
    try {
        mostrarSucesso('');
        const resposta = await fetch(updateUrlTemplate.replace('/0/', `/${id}/`), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify(dados),
        });
        const resultado = await resposta.json().catch(() => ({}));
        if (!resposta.ok) throw new Error(resultado.detail || `Erro ao salvar (${resposta.status}).`);
        const indice = listaContatos.findIndex((item) => item.id === id);
        listaContatos[indice] = resultado.contact;
        editandoId = null;
        mostrarErro('');
        mostrarSucesso('Contato atualizado com sucesso.');
        filtrarContatos();
    } catch (erro) {
        mostrarErro(erro.message);
    } finally {
        salvando = false;
    }
}

async function excluirContato(id) {
    const contato = listaContatos.find((item) => item.id === id);
    if (!contato || !confirm(`Excluir o contato de "${contato.name}"?`)) return;
    salvando = true;
    try {
        mostrarSucesso('');
        const resposta = await fetch(updateUrlTemplate.replace('/0/', `/${id}/`), {
            method: 'DELETE',
            headers: { 'X-CSRFToken': csrfToken, 'Accept': 'application/json' },
        });
        const resultado = await resposta.json().catch(() => ({}));
        if (!resposta.ok) throw new Error(resultado.detail || `Erro ao excluir (${resposta.status}).`);
        listaContatos = listaContatos.filter((item) => item.id !== id);
        if (editandoId === id) editandoId = null;
        mostrarErro('');
        mostrarSucesso('Contato excluído com sucesso.');
        filtrarContatos();
    } catch (erro) {
        mostrarErro(erro.message);
    } finally {
        salvando = false;
    }
}

function aoClicarNaTabela(evento) {
    const botao = evento.target.closest('button[data-action]');
    if (!botao || salvando) return;
    const id = Number(botao.dataset.id);
    if (botao.dataset.action === 'editar') {
        mostrarSucesso('');
        editandoId = id;
        mostrarErro('');
        carregarContatos();
        const linha = document.querySelector(`tr[data-contact-id="${id}"]`);
        linha.querySelector('[data-field="user"]').focus();
    } else if (botao.dataset.action === 'cancelar') {
        editandoId = null;
        mostrarErro('');
        carregarContatos();
    } else if (botao.dataset.action === 'salvar') {
        salvarContato(id);
    } else if (botao.dataset.action === 'excluir') {
        excluirContato(id);
    } else if (botao.dataset.action === 'copiar') {
        const contato = listaContatos.find((item) => item.id === id);
        if (contato) copiarTexto(contato.machine);
    }
}

// Remove acentos para tornar a pesquisa mais tolerante
function removerAcentos(texto) {
    return texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

function criarBotaoPagina(rotulo, pagina, ativo = false) {
    const botao = document.createElement('button');
    botao.textContent = rotulo;
    botao.classList.add('pagination-button');
    if (ativo) botao.classList.add('active');
    botao.addEventListener('click', () => {
        paginaAtual = pagina;
        carregarContatos();
    });
    return botao;
}

function carregarContatos() {
    const corpoTabela = document.querySelector('#lista-contatos tbody');
    const inicio = (paginaAtual - 1) * CONTATOS_POR_PAGINA;
    const contatosPagina = contatosFiltrados.slice(inicio, inicio + CONTATOS_POR_PAGINA);

    corpoTabela.innerHTML = '';

    contatosPagina.forEach((contato) => corpoTabela.appendChild(linhaContato(contato)));

    renderizarPaginacao();
}

function criarReticencias() {
    const reticencias = document.createElement('span');
    reticencias.textContent = '...';
    reticencias.classList.add('pagination-ellipsis');
    return reticencias;
}

function renderizarPaginacao() {
    const container = document.getElementById('pagination');
    const totalPaginas = Math.ceil(contatosFiltrados.length / CONTATOS_POR_PAGINA);

    container.innerHTML = '';
    if (totalPaginas <= 1) return;

    // Em telas pequenas mostramos uma janela menor de páginas
    const isMobile = window.innerWidth <= 480;
    const maxVisiveis = isMobile ? 3 : 7;

    let inicio = Math.max(1, paginaAtual - Math.floor(maxVisiveis / 2));
    let fim = Math.min(totalPaginas, inicio + maxVisiveis - 1);

    if (fim - inicio + 1 < maxVisiveis) {
        inicio = Math.max(1, fim - maxVisiveis + 1);
    }

    if (paginaAtual > 1) {
        container.appendChild(criarBotaoPagina(isMobile ? '‹' : '‹ Anterior', paginaAtual - 1));
    }

    if (inicio > 1) {
        container.appendChild(criarBotaoPagina('1', 1));
        if (inicio > 2) {
            container.appendChild(criarReticencias());
        }
    }

    for (let pagina = inicio; pagina <= fim; pagina++) {
        container.appendChild(criarBotaoPagina(pagina, pagina, pagina === paginaAtual));
    }

    if (fim < totalPaginas) {
        if (fim < totalPaginas - 1) {
            container.appendChild(criarReticencias());
        }
        container.appendChild(criarBotaoPagina(totalPaginas, totalPaginas));
    }

    if (paginaAtual < totalPaginas) {
        container.appendChild(criarBotaoPagina(isMobile ? '›' : 'Próximo ›', paginaAtual + 1));
    }
}

// Prefixar a busca com "-" inverte o filtro
function filtrarContatos() {
    const valorBruto = document.getElementById('search-input').value;
    const entrada = valorBruto.toLowerCase().trim();
    const buscaInversa = entrada.startsWith('-');
    const termo = removerAcentos(buscaInversa ? entrada.slice(1).trim() : entrada);

    contatosFiltrados = listaContatos.filter((contato) => {
        const contemTermo = [contato.name, contato.number, contato.sector, contato.machine]
            .some((campo) => removerAcentos(campo.toLowerCase()).includes(termo));

        return buscaInversa ? !contemTermo : contemTermo;
    });

    paginaAtual = 1;
    carregarContatos();
    atualizarUrlComBusca(valorBruto);
}

// Mantém a pesquisa sincronizada com a URL (parâmetro "q"), sem poluir o histórico
function atualizarUrlComBusca(valorBusca) {
    const url = new URL(window.location.href);
    if (valorBusca) {
        url.searchParams.set('q', valorBusca);
    } else {
        url.searchParams.delete('q');
    }
    window.history.replaceState({}, '', url);
}

function copiarTexto(texto) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(texto).catch((err) => {
            console.error('Erro ao copiar: ', err);
        });
    }
}

function exportarPdf() {
    if (!window.jspdf?.jsPDF) {
        mostrarErro('Não foi possível carregar o gerador de PDF.');
        return;
    }

    const { jsPDF } = window.jspdf;
    const documento = new jsPDF();
    if (typeof documento.autoTable !== 'function') {
        mostrarErro('Não foi possível carregar a tabela do PDF.');
        return;
    }

    const cabecalho = ['Nome', 'Número', 'Setor'];
    if (isStaff) cabecalho.push('Máquina');

    const linhas = contatosFiltrados.map((contato) => {
        const linha = [contato.name, contato.number || '-', contato.sector || '-'];
        if (isStaff) linha.push(contato.machine || '-');
        return linha.map(String);
    });

    mostrarErro('');
    documento.setFontSize(14);
    documento.text('Lista de Contatos', 14, 16);
    documento.setFontSize(9);
    documento.setTextColor(120);
    documento.text('Gerado em ' + new Date().toLocaleDateString('pt-BR'), 14, 22);
    documento.autoTable({
        startY: 28,
        head: [cabecalho],
        body: linhas,
        styles: { fontSize: 9 },
        headStyles: { fillColor: [51, 51, 51] },
    });
    documento.save(`lista-contatos-${new Date().toISOString().slice(0, 10)}.pdf`);
}

document.addEventListener('DOMContentLoaded', () => {
    listaContatos = JSON.parse(document.getElementById('contacts-data').textContent);
    setores = JSON.parse(document.getElementById('sectors-data').textContent);
    usuarios = JSON.parse(document.getElementById('users-data').textContent);

    document.getElementById('search-input').addEventListener('input', filtrarContatos);
    document.getElementById('export-pdf').addEventListener('click', exportarPdf);
    document.querySelector('#lista-contatos tbody').addEventListener('click', aoClicarNaTabela);

    const modal = document.getElementById('contact-modal');
    if (modal) {
        document.getElementById('open-contact-modal').addEventListener('click', () => {
            modal.showModal();
            modal.querySelector('input, select, textarea').focus();
        });
        modal.querySelectorAll('[data-close-modal]').forEach((botao) => {
            botao.addEventListener('click', () => modal.close());
        });
        if (modal.dataset.openOnLoad) modal.showModal();
    }

    const buscaSalva = new URLSearchParams(window.location.search).get('q');
    if (buscaSalva) {
        document.getElementById('search-input').value = buscaSalva;
        filtrarContatos();
        return;
    }

    contatosFiltrados = [...listaContatos];
    carregarContatos();
});
