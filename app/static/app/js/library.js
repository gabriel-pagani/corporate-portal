// A configuração da tela vem em data-attributes e json_script: com o CSP
// ligado, o navegador recusa <script> inline.
const {
    csrfToken: CSRF_TOKEN,
    foldersUrl: PASTAS_API_URL,
    documentsUrl: DOCUMENTOS_API_URL,
} = document.getElementById('library').dataset;

function lerJson(id) {
    return JSON.parse(document.getElementById(id).textContent);
}

let pastas = lerJson('library-folders');
let documentos = lerJson('library-documents');
const permissoes = lerJson('library-permissions');
const destinatarios = lerJson('library-recipients');
const TAMANHO_MAXIMO = lerJson('library-max-file-size');

// Quantos documentos cada card de pasta lista antes do "e mais N"
const DOCUMENTOS_POR_PASTA = 5;

let pastaAtual = null;
let editandoPastaId = null;
let editandoDocumentoId = null;
let enviando = false;

function escaparHtml(texto) {
    return String(texto ?? '').replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

// Remove acentos para tornar a pesquisa mais tolerante
function removerAcentos(texto) {
    return texto.normalize('NFD').replace(/[̀-ͯ]/g, '');
}

function comparar(a, b) {
    return a.localeCompare(b, 'pt-BR', { sensitivity: 'base', numeric: true });
}

function formatarTamanho(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    const unidades = ['KB', 'MB', 'GB'];
    let valor = bytes / 1024;
    let indice = 0;
    while (valor >= 1024 && indice < unidades.length - 1) {
        valor /= 1024;
        indice += 1;
    }
    return `${valor.toLocaleString('pt-BR', { maximumFractionDigits: valor < 10 ? 1 : 0 })} ${unidades[indice]}`;
}

function plural(quantidade, singular, pluralTexto) {
    return `${quantidade} ${quantidade === 1 ? singular : pluralTexto}`;
}

async function requisitar(url, metodo = 'GET', corpo = null) {
    const opcoes = {
        method: metodo,
        headers: { 'X-CSRFToken': CSRF_TOKEN, 'Accept': 'application/json' },
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
        throw new Error('Não foi possível se comunicar com o servidor.');
    }

    // O nginx recusa o upload grande antes do django, com uma página HTML
    if (resposta.status === 413) {
        throw new Error('O arquivo passa de 20 MB.');
    }
    const dados = await resposta.json().catch(() => ({}));
    if (!resposta.ok) {
        throw new Error(dados.detail || `Erro inesperado (${resposta.status}).`);
    }
    return dados;
}

function mostrarMensagem(texto, erro = false) {
    const aviso = document.getElementById('library-message');
    aviso.textContent = texto;
    aviso.classList.toggle('error', erro);
    aviso.hidden = !texto;
}

function ordenarPastas() {
    pastas.sort((a, b) => comparar(a.name, b.name));
}

function documentosDaPasta(pastaId) {
    return documentos
        .filter((documento) => documento.folder_id === pastaId)
        .sort((a, b) => comparar(a.title, b.title));
}

function pastaPorId(id) {
    return pastas.find((pasta) => pasta.id === id) || null;
}

function termoDeBusca() {
    return removerAcentos(document.getElementById('search-input').value.toLowerCase().trim());
}

function correspondeABusca(documento, termo) {
    return [documento.title, documento.description, documento.file_name, documento.folder]
        .some((campo) => removerAcentos(String(campo || '').toLowerCase()).includes(termo));
}

// ---- Navegação ----

function lerPastaDaUrl() {
    const id = Number(new URLSearchParams(window.location.search).get('folder'));
    return pastaPorId(id) ? id : null;
}

function abrirPasta(id, { historico = true } = {}) {
    pastaAtual = id;
    if (historico) {
        const url = new URL(window.location.href);
        if (id === null) {
            url.searchParams.delete('folder');
        } else {
            url.searchParams.set('folder', id);
        }
        window.history.pushState({ folder: id }, '', url);
    }
    mostrarMensagem('');
    renderizar();
    document.getElementById('library').scrollTop = 0;
}

window.addEventListener('popstate', () => {
    pastaAtual = lerPastaDaUrl();
    renderizar();
});

// ---- Renderização ----

function renderizarSidebar() {
    const lista = document.getElementById('folder-list');
    const itens = [
        `<li>
            <button type="button" class="folder-link${pastaAtual === null ? ' active' : ''}" data-folder="" title="Todas as pastas">
                <i class="fas fa-book" aria-hidden="true"></i>
                <span class="text">Todas as pastas</span>
                <span class="folder-count">${documentos.length}</span>
            </button>
        </li>`,
        ...pastas.map((pasta) => `
        <li>
            <button type="button" class="folder-link${pasta.id === pastaAtual ? ' active' : ''}" data-folder="${pasta.id}" title="${escaparHtml(pasta.name)}">
                <i class="fas ${pasta.id === pastaAtual ? 'fa-folder-open' : 'fa-folder'}" aria-hidden="true"></i>
                <span class="text">${escaparHtml(pasta.name)}</span>
                <span class="folder-count">${documentosDaPasta(pasta.id).length}</span>
            </button>
        </li>`),
    ];
    lista.innerHTML = itens.join('');
}

function renderizarCaminho(termo) {
    const caminho = document.getElementById('library-breadcrumb');
    const raiz = '<i class="fas fa-book" aria-hidden="true"></i>';

    if (termo) {
        caminho.innerHTML = `${raiz} <strong>Resultados da pesquisa</strong>`;
        return;
    }
    if (pastaAtual === null) {
        caminho.innerHTML = `${raiz} <strong>Biblioteca</strong>`;
        return;
    }
    caminho.innerHTML = `
        ${raiz}
        <button type="button" data-folder="">Biblioteca</button>
        <i class="fas fa-chevron-right separator" aria-hidden="true"></i>
        <strong>${escaparHtml(pastaPorId(pastaAtual).name)}</strong>`;
}

function cardPasta(pasta, indice) {
    const lista = documentosDaPasta(pasta.id);
    const visiveis = lista.slice(0, DOCUMENTOS_POR_PASTA);
    const restantes = lista.length - visiveis.length;

    const corpo = lista.length
        ? visiveis.map((documento) => `
            <a href="${documento.download_url}" title="Baixar ${escaparHtml(documento.title)}">
                <i class="fas ${documento.icon} item-icon" aria-hidden="true"></i>
                <span class="item-text">${escaparHtml(documento.title)}</span>
                <i class="fas fa-download" aria-hidden="true"></i>
            </a>`).join('')
        : '<p class="folder-card-empty">Pasta vazia.</p>';

    return `
        <article class="folder-card" style="animation-delay: ${Math.min(indice, 12) * 0.03}s">
            <button type="button" class="folder-card-header" data-folder="${pasta.id}" title="Abrir a pasta ${escaparHtml(pasta.name)}">
                <span class="folder-card-icon"><i class="fas fa-folder" aria-hidden="true"></i></span>
                <span class="folder-card-heading">
                    <strong>${escaparHtml(pasta.name)}</strong>
                    <small>${plural(lista.length, 'documento', 'documentos')}</small>
                </span>
                <i class="fas fa-arrow-right folder-card-open" aria-hidden="true"></i>
            </button>
            <div class="folder-card-body">
                ${corpo}
                ${restantes > 0 ? `<button type="button" class="folder-card-more" data-folder="${pasta.id}">e mais ${restantes}</button>` : ''}
            </div>
        </article>`;
}

function textoDestinatarios(documento) {
    return documento.recipients.length ? documento.recipients.join(', ') : 'Todos';
}

function cardDocumento(documento, indice, mostrarPasta) {
    const extensao = documento.extension ? documento.extension.toUpperCase() : 'Arquivo';
    const detalhes = [];
    if (mostrarPasta) {
        detalhes.push(`<span><i class="fas fa-folder" aria-hidden="true"></i>${escaparHtml(documento.folder)}</span>`);
    }
    if (documento.author) {
        detalhes.push(`<span><i class="fas fa-user" aria-hidden="true"></i>${escaparHtml(documento.author)}</span>`);
    }
    if (documento.recipients) {
        detalhes.push(`<span title="Quem recebe este documento"><i class="fas fa-users" aria-hidden="true"></i>${escaparHtml(textoDestinatarios(documento))}</span>`);
        detalhes.push(`<span><i class="fas fa-download" aria-hidden="true"></i>${plural(documento.downloads, 'download', 'downloads')}</span>`);
    }

    const acoes = [
        `<a class="library-button primary" href="${documento.download_url}" title="Baixar ${escaparHtml(documento.file_name)}">
            <i class="fas fa-download" aria-hidden="true"></i> Baixar
        </a>`,
        permissoes.change_document && `<button type="button" class="library-button icon" data-action="editar" data-id="${documento.id}" title="Editar"><i class="fas fa-pen" aria-hidden="true"></i></button>`,
        permissoes.delete_document && `<button type="button" class="library-button icon danger" data-action="excluir" data-id="${documento.id}" title="Excluir"><i class="fas fa-trash" aria-hidden="true"></i></button>`,
    ].filter(Boolean).join('');

    return `
        <article class="document-card" data-id="${documento.id}" style="animation-delay: ${Math.min(indice, 12) * 0.03}s">
            <div class="document-card-top">
                <span class="document-icon ${documento.icon}-bg"><i class="fas ${documento.icon}" aria-hidden="true"></i></span>
                <div class="document-heading">
                    <h3>${escaparHtml(documento.title)}</h3>
                    <p class="document-meta">${escaparHtml(extensao)} · ${formatarTamanho(documento.size)} · Atualizado em ${documento.updated_at}</p>
                </div>
            </div>
            ${documento.description ? `<p class="document-description">${escaparHtml(documento.description)}</p>` : ''}
            ${detalhes.length ? `<div class="document-details">${detalhes.join('')}</div>` : ''}
            <div class="document-actions">${acoes}</div>
        </article>`;
}

function mostrarVazio(texto) {
    document.getElementById('library-empty-text').textContent = texto;
    document.getElementById('library-empty').hidden = !texto;
}

function renderizarConteudo(termo) {
    const grade = document.getElementById('library-grid');

    if (termo) {
        const encontrados = documentos
            .filter((documento) => correspondeABusca(documento, termo))
            .sort((a, b) => comparar(a.title, b.title) || comparar(a.folder, b.folder));
        grade.innerHTML = encontrados.map((documento, indice) => cardDocumento(documento, indice, true)).join('');
        mostrarVazio(encontrados.length ? '' : 'Nenhum documento encontrado.');
        return;
    }

    if (pastaAtual === null) {
        grade.innerHTML = pastas.map(cardPasta).join('');
        if (pastas.length) {
            mostrarVazio('');
        } else if (permissoes.add_folder) {
            mostrarVazio('Nenhuma pasta criada ainda. Use "Nova pasta", na barra lateral, para começar.');
        } else {
            mostrarVazio('Nenhum documento foi liberado para você ainda.');
        }
        return;
    }

    const lista = documentosDaPasta(pastaAtual);
    grade.innerHTML = lista.map((documento, indice) => cardDocumento(documento, indice, false)).join('');
    mostrarVazio(lista.length ? '' : 'Esta pasta ainda não tem documentos.');
}

function renderizarAcoes(termo) {
    const naPasta = pastaAtual !== null && !termo;
    const renomear = document.getElementById('rename-folder');
    const excluir = document.getElementById('delete-folder');
    if (renomear) renomear.hidden = !naPasta;
    if (excluir) excluir.hidden = !naPasta;

    // Sem pasta não há onde guardar o documento
    const novoDocumento = document.getElementById('open-document-modal');
    if (novoDocumento) {
        novoDocumento.disabled = !pastas.length;
        novoDocumento.title = pastas.length ? 'Enviar um documento' : 'Crie uma pasta antes de enviar documentos';
    }
}

function renderizar() {
    if (pastaAtual !== null && !pastaPorId(pastaAtual)) pastaAtual = null;
    const termo = termoDeBusca();
    renderizarSidebar();
    renderizarCaminho(termo);
    renderizarConteudo(termo);
    renderizarAcoes(termo);
}

// ---- Pastas ----

function abrirModalPasta(pasta = null) {
    const modal = document.getElementById('folder-modal');
    editandoPastaId = pasta ? pasta.id : null;
    document.getElementById('folder-modal-title').textContent = pasta ? 'Renomear pasta' : 'Nova pasta';
    document.getElementById('folder-submit').textContent = pasta ? 'Salvar' : 'Criar';
    document.getElementById('folder-name').value = pasta ? pasta.name : '';
    document.getElementById('folder-error').hidden = true;
    modal.showModal();
    document.getElementById('folder-name').focus();
}

async function aoSalvarPasta(evento) {
    evento.preventDefault();
    if (enviando) return;

    const erro = document.getElementById('folder-error');
    const botao = document.getElementById('folder-submit');
    const nome = document.getElementById('folder-name').value.trim();
    const url = editandoPastaId === null ? PASTAS_API_URL : `${PASTAS_API_URL}${editandoPastaId}/`;

    enviando = true;
    botao.disabled = true;
    erro.hidden = true;
    try {
        const { folder } = await requisitar(url, 'POST', { name: nome });
        const indice = pastas.findIndex((pasta) => pasta.id === folder.id);
        if (indice === -1) {
            pastas.push(folder);
        } else {
            pastas[indice] = folder;
            // O nome da pasta também aparece nos documentos dela
            documentos.forEach((documento) => {
                if (documento.folder_id === folder.id) documento.folder = folder.name;
            });
        }
        ordenarPastas();
        document.getElementById('folder-modal').close();
        // A pasta nova já abre, pronta para receber documentos
        if (indice === -1) {
            abrirPasta(folder.id);
            mostrarMensagem(`Pasta "${folder.name}" criada.`);
        } else {
            renderizar();
            mostrarMensagem('Pasta renomeada.');
        }
    } catch (falha) {
        erro.textContent = falha.message;
        erro.hidden = false;
    } finally {
        enviando = false;
        botao.disabled = false;
    }
}

async function excluirPasta() {
    const pasta = pastaPorId(pastaAtual);
    if (!pasta || !confirm(`Excluir a pasta "${pasta.name}"?`)) return;

    try {
        await requisitar(`${PASTAS_API_URL}${pasta.id}/`, 'DELETE');
        pastas = pastas.filter((item) => item.id !== pasta.id);
        abrirPasta(null);
        mostrarMensagem(`Pasta "${pasta.name}" excluída.`);
    } catch (falha) {
        mostrarMensagem(falha.message, true);
    }
}

// ---- Documentos ----

function montarSeletor(tipo, opcoes, selecionados) {
    const seletor = document.querySelector(`.recipient-picker[data-picker="${tipo}"]`);
    const lista = seletor.querySelector('[data-picker-options]');
    const marcados = new Set(selecionados);

    lista.innerHTML = opcoes.length
        ? opcoes.map((opcao) => `
            <li data-name="${escaparHtml(removerAcentos(opcao.name.toLowerCase()))}">
                <label>
                    <input type="checkbox" name="${tipo}" value="${opcao.id}"${marcados.has(opcao.id) ? ' checked' : ''}>
                    ${escaparHtml(opcao.name)}
                </label>
            </li>`).join('')
        : `<li class="empty">Nenhum ${tipo === 'users' ? 'usuário' : 'grupo'} cadastrado.</li>`;
    seletor.querySelector('.recipient-search').value = '';
}

function filtrarSeletor(seletor) {
    const termo = removerAcentos(seletor.querySelector('.recipient-search').value.toLowerCase().trim());
    seletor.querySelectorAll('[data-picker-options] li[data-name]').forEach((item) => {
        item.hidden = !item.dataset.name.includes(termo);
    });
}

function nomesMarcados(tipo) {
    return [...document.querySelectorAll(`.recipient-picker[data-picker="${tipo}"] input:checked`)]
        .map((caixa) => caixa.parentElement.textContent.trim());
}

function atualizarResumoDestinatarios() {
    const usuarios = nomesMarcados('users');
    const grupos = nomesMarcados('groups');
    document.querySelector('.recipient-picker[data-picker="users"] [data-picker-count]').textContent =
        usuarios.length ? plural(usuarios.length, 'selecionado', 'selecionados') : '';
    document.querySelector('.recipient-picker[data-picker="groups"] [data-picker-count]').textContent =
        grupos.length ? plural(grupos.length, 'selecionado', 'selecionados') : '';

    const resumo = document.getElementById('recipients-summary');
    if (!usuarios.length && !grupos.length) {
        resumo.innerHTML = '<strong>Liberado para:</strong> todos os usuários.';
        return;
    }
    const partes = [];
    if (usuarios.length) partes.push(plural(usuarios.length, 'usuário', 'usuários'));
    if (grupos.length) partes.push(plural(grupos.length, 'grupo', 'grupos'));
    resumo.innerHTML = `<strong>Liberado para:</strong> ${partes.join(' e ')} — ${escaparHtml([...usuarios, ...grupos].join(', '))}.`;
}

function abrirModalDocumento(documento = null) {
    const modal = document.getElementById('document-modal');
    editandoDocumentoId = documento ? documento.id : null;

    document.getElementById('document-modal-title').textContent = documento ? 'Editar documento' : 'Novo documento';
    document.getElementById('document-submit').textContent = documento ? 'Salvar' : 'Enviar';
    document.getElementById('document-title').value = documento ? documento.title : '';
    document.getElementById('document-description').value = documento ? documento.description : '';

    const pastaEscolhida = documento ? documento.folder_id : pastaAtual;
    document.getElementById('document-folder').innerHTML = [
        `<option value=""${pastaEscolhida ? '' : ' selected'} disabled>Selecione uma pasta</option>`,
        ...pastas.map((pasta) => `<option value="${pasta.id}"${pasta.id === pastaEscolhida ? ' selected' : ''}>${escaparHtml(pasta.name)}</option>`),
    ].join('');

    const arquivo = document.getElementById('document-file');
    arquivo.value = '';
    arquivo.required = !documento;
    document.getElementById('document-file-label').textContent = documento
        ? 'Substituir o arquivo (opcional, até 20 MB)'
        : 'Arquivo (até 20 MB)';
    const atual = document.getElementById('document-file-current');
    atual.hidden = !documento;
    atual.textContent = documento ? `Arquivo atual: ${documento.file_name} (${formatarTamanho(documento.size)})` : '';

    montarSeletor('users', destinatarios.users, documento ? documento.user_ids : []);
    montarSeletor('groups', destinatarios.groups, documento ? documento.group_ids : []);
    atualizarResumoDestinatarios();

    document.getElementById('document-error').hidden = true;
    modal.showModal();
    document.getElementById('document-title').focus();
}

async function aoSalvarDocumento(evento) {
    evento.preventDefault();
    if (enviando) return;

    const formulario = evento.target;
    const erro = document.getElementById('document-error');
    const botao = document.getElementById('document-submit');
    const arquivo = document.getElementById('document-file').files[0];

    if (arquivo && arquivo.size > TAMANHO_MAXIMO) {
        erro.textContent = 'O arquivo passa de 20 MB.';
        erro.hidden = false;
        return;
    }

    // O FormData leva título, pasta, descrição, arquivo e as caixas marcadas;
    // sem arquivo novo na edição, o campo vazio não vai
    const dados = new FormData(formulario);
    if (!arquivo) dados.delete('file');

    const url = editandoDocumentoId === null ? DOCUMENTOS_API_URL : `${DOCUMENTOS_API_URL}${editandoDocumentoId}/`;

    enviando = true;
    botao.disabled = true;
    botao.textContent = arquivo ? 'Enviando...' : 'Salvando...';
    erro.hidden = true;
    try {
        const { document: salvo } = await requisitar(url, 'POST', dados);
        const indice = documentos.findIndex((documento) => documento.id === salvo.id);
        if (indice === -1) {
            documentos.push(salvo);
        } else {
            documentos[indice] = salvo;
        }
        document.getElementById('document-modal').close();
        // Mostra o documento onde ele ficou, mesmo que tenha mudado de pasta
        document.getElementById('search-input').value = '';
        abrirPasta(salvo.folder_id, { historico: salvo.folder_id !== pastaAtual });
        mostrarMensagem(indice === -1 ? `Documento "${salvo.title}" enviado.` : 'Documento atualizado.');
        destacarDocumento(salvo.id);
    } catch (falha) {
        erro.textContent = falha.message;
        erro.hidden = false;
    } finally {
        enviando = false;
        botao.disabled = false;
        botao.textContent = editandoDocumentoId === null ? 'Enviar' : 'Salvar';
    }
}

function destacarDocumento(id) {
    const card = document.querySelector(`.document-card[data-id="${id}"]`);
    if (!card) return;
    card.classList.add('highlight');
    card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    setTimeout(() => card.classList.remove('highlight'), 2500);
}

async function excluirDocumento(id) {
    const documento = documentos.find((item) => item.id === id);
    if (!documento || !confirm(`Excluir o documento "${documento.title}"?`)) return;

    try {
        await requisitar(`${DOCUMENTOS_API_URL}${id}/`, 'DELETE');
        documentos = documentos.filter((item) => item.id !== id);
        renderizar();
        mostrarMensagem(`Documento "${documento.title}" excluído.`);
    } catch (falha) {
        mostrarMensagem(falha.message, true);
    }
}

// ---- Eventos ----

document.addEventListener('DOMContentLoaded', () => {
    ordenarPastas();
    pastaAtual = lerPastaDaUrl();
    window.history.replaceState({ folder: pastaAtual }, '');

    // Qualquer elemento com data-folder abre a pasta: a sidebar, o caminho e os cards
    document.body.addEventListener('click', (evento) => {
        const alvo = evento.target.closest('[data-folder]');
        if (!alvo) return;
        const pesquisa = document.getElementById('search-input');
        pesquisa.value = '';
        abrirPasta(alvo.dataset.folder ? Number(alvo.dataset.folder) : null);
    });

    const pesquisa = document.getElementById('search-input');
    pesquisa.addEventListener('input', renderizar);
    pesquisa.addEventListener('keydown', (evento) => {
        if (evento.key === 'Escape') {
            pesquisa.value = '';
            renderizar();
        }
    });

    document.getElementById('library-grid').addEventListener('click', (evento) => {
        const botao = evento.target.closest('button[data-action]');
        if (!botao) return;
        const id = Number(botao.dataset.id);
        if (botao.dataset.action === 'editar') {
            abrirModalDocumento(documentos.find((documento) => documento.id === id));
        } else if (botao.dataset.action === 'excluir') {
            excluirDocumento(id);
        }
    });

    document.querySelectorAll('dialog.form-modal').forEach((modal) => {
        modal.querySelectorAll('[data-close-modal]').forEach((botao) => {
            botao.addEventListener('click', () => modal.close());
        });
    });

    const formularioPasta = document.getElementById('folder-form');
    if (formularioPasta) {
        formularioPasta.addEventListener('submit', aoSalvarPasta);
        document.getElementById('open-folder-modal')?.addEventListener('click', () => abrirModalPasta());
        document.getElementById('rename-folder')?.addEventListener('click', () => abrirModalPasta(pastaPorId(pastaAtual)));
    }
    document.getElementById('delete-folder')?.addEventListener('click', excluirPasta);

    const formularioDocumento = document.getElementById('document-form');
    if (formularioDocumento) {
        formularioDocumento.addEventListener('submit', aoSalvarDocumento);
        document.getElementById('open-document-modal')?.addEventListener('click', () => abrirModalDocumento());
        formularioDocumento.querySelectorAll('.recipient-picker').forEach((seletor) => {
            const busca = seletor.querySelector('.recipient-search');
            busca.addEventListener('input', () => filtrarSeletor(seletor));
            // Enter na pesquisa não deve enviar o formulário
            busca.addEventListener('keydown', (evento) => {
                if (evento.key === 'Enter') evento.preventDefault();
            });
        });
        formularioDocumento.addEventListener('change', (evento) => {
            if (evento.target.matches('.recipient-options input')) atualizarResumoDestinatarios();
        });
    }

    renderizar();
});
