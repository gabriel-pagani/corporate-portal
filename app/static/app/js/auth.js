document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.querySelector('.toggle-password');
    if (!toggle) return;

    toggle.addEventListener('click', () => {
        const targetId = toggle.dataset.target;
        const input = document.getElementById(targetId);
        if (!input) return;

        const isPassword = input.type === 'password';
        input.type = isPassword ? 'text' : 'password';
        toggle.classList.toggle('fa-eye');
        toggle.classList.toggle('fa-eye-slash');
    });
});
