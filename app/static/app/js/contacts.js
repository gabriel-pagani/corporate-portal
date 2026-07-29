const CONTATOS_POR_PAGINA = 8;

let listaContatos = [];
let contatosFiltrados = [];
let paginaAtual = 1;

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

function criarCelula(texto) {
    const celula = document.createElement('td');
    celula.textContent = texto;
    return celula;
}

// Célula da máquina, com botão para copiar o valor
function criarCelulaMaquina(maquina) {
    const celula = document.createElement('td');
    const wrapper = document.createElement('div');
    wrapper.classList.add('machine-cell');

    const valor = document.createElement('span');
    valor.textContent = maquina;

    const botao = document.createElement('button');
    botao.classList.add('copy-button');
    botao.title = 'Copiar número da máquina';
    botao.innerHTML = '<i class="fas fa-copy"></i>';
    botao.addEventListener('click', () => copiarTexto(maquina));

    wrapper.append(valor, botao);
    celula.appendChild(wrapper);
    return celula;
}

function carregarContatos() {
    const corpoTabela = document.querySelector('#lista-contatos tbody');
    const inicio = (paginaAtual - 1) * CONTATOS_POR_PAGINA;
    const contatosPagina = contatosFiltrados.slice(inicio, inicio + CONTATOS_POR_PAGINA);

    corpoTabela.innerHTML = '';

    contatosPagina.forEach((contato) => {
        const linha = document.createElement('tr');
        linha.append(
            criarCelula(contato.name),
            criarCelula(contato.number),
            criarCelula(contato.sector)
        );
        if (isStaff) linha.appendChild(criarCelulaMaquina(contato.machine));
        corpoTabela.appendChild(linha);
    });

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
    const entrada = document.getElementById('search-input').value.toLowerCase().trim();
    const buscaInversa = entrada.startsWith('-');
    const termo = removerAcentos(buscaInversa ? entrada.slice(1).trim() : entrada);

    contatosFiltrados = listaContatos.filter((contato) => {
        const contemTermo = [contato.name, contato.number, contato.sector, contato.machine]
            .some((campo) => removerAcentos(campo.toLowerCase()).includes(termo));

        return buscaInversa ? !contemTermo : contemTermo;
    });

    paginaAtual = 1;
    carregarContatos();
}

function copiarTexto(texto) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(texto).catch((err) => {
            console.error('Erro ao copiar: ', err);
        });
    }
}

document.addEventListener('DOMContentLoaded', () => {
    listaContatos = JSON.parse(document.getElementById('contacts-data').textContent);
    contatosFiltrados = [...listaContatos];
    carregarContatos();
});
