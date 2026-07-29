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
