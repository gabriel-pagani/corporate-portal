// Remove acentos para tornar a pesquisa mais tolerante
function removerAcentos(texto) {
    return texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

// Troca o indicador de carregamento pelo iframe assim que o dashboard termina de carregar
document.addEventListener('DOMContentLoaded', () => {
    const frame = document.getElementById('dashboard-frame');
    const loader = document.getElementById('dashboard-loader');

    if (!frame || !loader) return;

    frame.addEventListener('load', () => {
        loader.style.display = 'none';
        frame.style.display = 'block';
    });
});

function getCsrfToken() {
    return document.cookie.split('; ').find((linha) => linha.startsWith('csrftoken='))?.split('=')[1];
}

document.addEventListener('DOMContentLoaded', () => {
    const sidebar = document.getElementById('sidebar');
    const menuList = document.querySelector('.menu-list');

    if (!menuList) return;

    function fecharSubmenus() {
        menuList.querySelectorAll('.sector-header.active').forEach((header) => header.classList.remove('active'));
        menuList.querySelectorAll('.submenu.show').forEach((submenu) => {
            submenu.classList.remove('show');
            submenu.style.maxHeight = '';
            submenu.style.top = '';
        });
        menuList.querySelectorAll('.submenu.active').forEach((submenu) => submenu.classList.remove('active'));
    }

    // Ao minimizar/expandir a sidebar os submenus trocam entre dropdown e acordeão
    document.getElementById('toggle').addEventListener('click', () => {
        // Roda antes do sidebar.js alternar a classe, por isso o estado ainda é o anterior
        const colapsada = sidebar.classList.contains('collapsed');

        if (colapsada) {
            menuList.querySelectorAll('.submenu.show').forEach((submenu) => {
                submenu.classList.replace('show', 'active');
                submenu.style.maxHeight = '';
                submenu.style.top = '';
            });
        } else {
            fecharSubmenus();
        }
    });

    // Abre o setor como dropdown flutuante quando a sidebar está minimizada
    function abrirDropdown(sectorHeader, submenu) {
        const jaAberto = submenu.classList.contains('show');
        fecharSubmenus();

        if (jaAberto) return;

        sectorHeader.classList.add('active');
        submenu.classList.add('show');
        submenu.style.maxHeight = `${window.innerHeight * 0.8}px`;

        // Reposiciona para cima caso o dropdown ultrapasse o rodapé da tela
        const rect = submenu.getBoundingClientRect();
        if (rect.bottom > window.innerHeight) {
            const excedente = rect.bottom - window.innerHeight + 20;
            const topoAtual = parseInt(window.getComputedStyle(submenu).top) || 0;
            submenu.style.top = `${topoAtual - excedente}px`;
        }
    }

    menuList.addEventListener('click', (event) => {
        const pinIcon = event.target.closest('.pin-icon');
        const dashboardLink = event.target.closest('.dashboard-link');
        const sectorHeader = event.target.closest('.sector-header');

        if (pinIcon) {
            event.preventDefault();
            event.stopPropagation();
            alternarFavorito(pinIcon);
            return;
        }

        // Os links navegam normalmente; só marcamos o destino para dar retorno imediato ao clique
        if (dashboardLink) {
            menuList.querySelectorAll('.dashboard-link.active').forEach((link) => link.classList.remove('active'));
            dashboardLink.classList.add('active');
            return;
        }

        if (sectorHeader) {
            const submenu = sectorHeader.nextElementSibling;
            if (!submenu?.classList.contains('submenu')) return;

            if (sidebar.classList.contains('collapsed')) {
                abrirDropdown(sectorHeader, submenu);
            } else {
                sectorHeader.classList.toggle('active');
                submenu.classList.toggle('active');
            }
        }
    });

    // Clicar fora fecha os dropdowns abertos
    document.addEventListener('click', (event) => {
        if (sidebar.classList.contains('collapsed') && !event.target.closest('.menu-list')) {
            fecharSubmenus();
        }
    });

    // Deixa aberto o setor do dashboard que está sendo exibido
    const linkAtivo = menuList.querySelector('.dashboard-link.active');
    if (linkAtivo && !sidebar.classList.contains('collapsed')) {
        const submenu = linkAtivo.closest('.submenu');
        submenu.classList.add('active');
        submenu.previousElementSibling.classList.add('active');
    }
});

document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('search-input');
    const clearButton = document.querySelector('.clear-search');
    const semResultados = document.querySelector('.no-results');
    const menuList = document.querySelector('.menu-list');
    let setoresExpandidos = [];

    if (!menuList) return;

    function filtrar() {
        const termo = removerAcentos(searchInput.value.toLowerCase().trim());
        clearButton.style.display = termo ? 'block' : 'none';

        // Guarda quais setores estavam abertos para restaurar ao limpar a pesquisa
        if (termo && !setoresExpandidos.length) {
            setoresExpandidos = Array.from(menuList.querySelectorAll('.sector-header'))
                .map((header) => header.classList.contains('active'));
        }

        menuList.querySelectorAll('li[data-id]').forEach((item) => {
            const titulo = removerAcentos(item.querySelector('.text').textContent.toLowerCase());
            item.style.display = titulo.includes(termo) ? '' : 'none';
        });

        let algumResultado = false;
        menuList.querySelectorAll('.menu-item').forEach((secao, indice) => {
            const header = secao.querySelector('.sector-header');
            const submenu = secao.querySelector('.submenu');
            const temResultado = Array.from(secao.querySelectorAll('li[data-id]'))
                .some((item) => item.style.display !== 'none');

            if (temResultado) algumResultado = true;
            secao.style.display = temResultado ? '' : 'none';

            const expandir = termo ? temResultado : setoresExpandidos[indice];
            header.classList.toggle('active', !!expandir);
            submenu.classList.toggle('active', !!expandir);
        });

        semResultados.classList.toggle('visible', !!termo && !algumResultado);

        if (!termo) setoresExpandidos = [];
    }

    searchInput.addEventListener('input', filtrar);

    searchInput.addEventListener('keydown', (event) => {
        // Esc limpa a pesquisa; Enter abre o primeiro resultado
        if (event.key === 'Escape') {
            searchInput.value = '';
            filtrar();
            return;
        }

        if (event.key === 'Enter') {
            const primeiro = Array.from(menuList.querySelectorAll('li[data-id]'))
                .find((item) => item.style.display !== 'none');
            primeiro?.querySelector('.dashboard-link').click();
        }
    });

    clearButton.addEventListener('click', () => {
        searchInput.value = '';
        filtrar();
        searchInput.focus();
    });

    // Restaura a pesquisa após a navegação, já que a página recarrega a cada dashboard
    const termoSalvo = sessionStorage.getItem('dashboards-busca');
    if (termoSalvo) {
        searchInput.value = termoSalvo;
        filtrar();
    }

    window.addEventListener('beforeunload', () => {
        sessionStorage.setItem('dashboards-busca', searchInput.value);
    });
});

function alternarFavorito(pinIcon) {
    const dashboardId = pinIcon.dataset.id;

    // A URL vem do template com um id de exemplo, trocado pelo id real do dashboard
    const url = document.querySelector('.menu-list').dataset.favoriteUrl.replace('12345', dashboardId);

    // Bloqueia novos cliques enquanto a requisição não responde
    pinIcon.classList.add('pending');

    fetch(url, {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCsrfToken(),
            'Content-Type': 'application/json',
        },
    })
        .then((resposta) => resposta.json())
        .then((dados) => {
            if (dados.status !== 'success') return;

            document.querySelectorAll(`.pin-icon[data-id="${dashboardId}"]`).forEach((icone) => {
                icone.classList.toggle('favorited', dados.is_favorite);
                icone.title = dados.is_favorite ? 'Desafixar dos favoritos' : 'Fixar nos favoritos';
            });

            atualizarFavoritos(dashboardId, dados.is_favorite);
        })
        .catch((erro) => console.error('Erro ao favoritar: ', erro))
        .finally(() => {
            document.querySelector(`.pin-icon[data-id="${dashboardId}"]`)?.classList.remove('pending');
        });
}

// Move o item entre a seção "Favoritos" e o seu setor de origem, sem precisar recarregar a página
function atualizarFavoritos(dashboardId, favoritado) {
    const sidebar = document.getElementById('sidebar');
    const menuList = document.querySelector('.menu-list');
    const item = menuList.querySelector(`li[data-id="${dashboardId}"]`);
    if (!item) return;

    const secaoOrigemNome = item.dataset.sector;

    if (favoritado) {
        let favoritos = menuList.querySelector('.submenu[data-sector="Favoritos"]');

        if (!favoritos) {
            const secao = document.createElement('li');
            secao.className = 'menu-item';
            secao.innerHTML = `
                <div class="sector-header active" title="Favoritos">
                    <i class="fas fa-star"></i>
                    <span class="text">Favoritos</span>
                    <i class="fas fa-chevron-right toggle-icon"></i>
                </div>
                <ul class="submenu active" data-sector="Favoritos"></ul>
            `;
            menuList.prepend(secao);
            favoritos = secao.querySelector('.submenu');
        } else if (!sidebar.classList.contains('collapsed')) {
            favoritos.classList.add('active');
            favoritos.previousElementSibling.classList.add('active');
        }

        const secaoOrigem = item.closest('.menu-item');
        favoritos.appendChild(item);
        if (!secaoOrigem.querySelector('li[data-id]')) {
            secaoOrigem.remove();
        }
        return;
    }

    let destino = menuList.querySelector(`.submenu[data-sector="${secaoOrigemNome}"]`);
    if (!destino) {
        const secao = document.createElement('li');
        secao.className = 'menu-item';
        secao.innerHTML = `
            <div class="sector-header active" title="${secaoOrigemNome}">
                <i class="fas fa-box-archive"></i>
                <span class="text">${secaoOrigemNome}</span>
                <i class="fas fa-chevron-right toggle-icon"></i>
            </div>
            <ul class="submenu active" data-sector="${secaoOrigemNome}"></ul>
        `;
        menuList.appendChild(secao);
        destino = secao.querySelector('.submenu');
    } else if (!sidebar.classList.contains('collapsed')) {
        destino.classList.add('active');
        destino.previousElementSibling.classList.add('active');
    }

    const secaoFavoritos = item.closest('.menu-item');
    destino.appendChild(item);
    if (!secaoFavoritos.querySelector('li[data-id]')) {
        secaoFavoritos.remove();
    }
}
