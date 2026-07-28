document.addEventListener('DOMContentLoaded', () => {
    const sidebar = document.getElementById('sidebar');
    const toggleButton = document.getElementById('toggle');
    const logoImg = document.getElementById('logo-img');

    function atualizarLogo() {
        const colapsada = sidebar.classList.contains('collapsed');
        logoImg.src = colapsada ? logoImg.dataset.iconLogo : logoImg.dataset.fullLogo;
    }

    // Restaura o estado da sidebar salvo na última visita
    if (localStorage.getItem('sidebar-collapsed') === 'true') {
        sidebar.classList.add('collapsed');
    }
    atualizarLogo();

    toggleButton.addEventListener('click', () => {
        sidebar.classList.toggle('collapsed');
        atualizarLogo();
        localStorage.setItem('sidebar-collapsed', sidebar.classList.contains('collapsed'));
    });
});
